"""T2-lite card and report-only diagnostic acceptance."""

import copy
import json
import runpy
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import NAMES, SCHEMAS, validate
from bicentennial.director.compiler.answer_contract import CONTRACT_SHA256
from bicentennial.packs import build, manifest
from bicentennial.report import t2lite_card as cards
from bicentennial.report.card import assemble, finalize
from bicentennial.report.t1_gate import check_baseline
from bicentennial.report.t2lite_diag import (
    citation_match,
    value_match,
    value_match_normalised,
)
from bicentennial.score.qa import _cited, score_qa

ROOT = Path(__file__).resolve().parents[2]
LEGACY_CARD_HASHES = {
    "T0/api": "529915dbd7770bd0f9dfcf5167064db2e2aea7dd04095f31ca545fa0de558899",
    "T0/hermes": "7ee7c41ac1d1771ef934103dc3177afabc5e587783a46921e06f9d98f833d171",
    "T1/api": "9cef1686c7e38dd86c361b441f8f292709658f882a07b68e9bbd8eb1b71c38e0",
    "T1/hermes": "9cef1686c7e38dd86c361b441f8f292709658f882a07b68e9bbd8eb1b71c38e0",
}


def schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_bytes())


def fixture(name):
    return json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"][name]


def inputs():
    old = fixture("card_ring0")
    pin_names = ("benchmark_commit", "generator_commit", "director_commit", "scorer_commit", "harness_hash")
    return dict(system="synthetic-system", pack_hash="a" * 64, seed_hash="b" * 64,
                pins={name: old["pins"][name] for name in pin_names},
                model="synthetic-model", effort="medium", served_identity="synthetic-identity",
                aa_prime=False, items=old["items"], counts=dict(assigned=len(old["items"])),
                answer_contract_sha256=CONTRACT_SHA256)


def test_complete_card_and_stable_fresh_canonical_bytes():
    args = inputs()
    before = copy.deepcopy(args)
    card = cards.build_t2lite_card(**args)
    assert cards.validate_t2lite_card(card) is None
    assert "card_t2lite" in NAMES
    assert validate("card_t2lite", card) is None
    assert "gate_verdict" not in card
    assert card["answer_contract_sha256"] == CONTRACT_SHA256
    assert card["tier"] == "T2-lite" and card["profile"] == "probe-live"
    assert card["live_roles"] == ["probe_main"] and card["aa_prime"] is False
    assert card["items"] == sorted(before["items"], key=lambda row: row["item_id"])
    reversed_args = {key: args[key] for key in reversed(args)}
    reversed_args["items"] = args["items"][::-1]
    assert canon(card) == canon(cards.build_t2lite_card(**reversed_args)) == canon(json.loads(canon(card)))
    card["items"][0]["item_id"] = "changed"
    card["pins"]["harness_hash"] = "c" * 64
    card["counts"]["assigned"] = 0
    assert args == before
    assert cards.build_t2lite_card(**dict(args, aa_prime=True))["aa_prime"] is True


@pytest.mark.parametrize("field", schema("card_t2lite")["required"])
def test_every_required_card_field(field):
    card = cards.build_t2lite_card(**inputs())
    del card[field]
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("bad", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", None, 1])
@pytest.mark.parametrize("field", ["answer_contract_sha256", "pack_hash", "seed_hash"])
def test_hashes_require_exact_lowercase_hex(field, bad):
    card = cards.build_t2lite_card(**inputs())
    card[field] = bad
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("roles", [[], ["write_turn"], ["probe_main", "write_turn"],
                                  ["probe_main", "probe_main"], "probe_main"])
def test_probe_live_roles_are_exact(roles):
    card = dict(cards.build_t2lite_card(**inputs()), live_roles=roles)
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("verdict", [None, "PASS", "FAIL"])
def test_gate_verdict_is_forbidden_by_schema_itself(verdict):
    card = dict(cards.build_t2lite_card(**inputs()), gate_verdict=verdict)
    # This must fail even without the local semantic check: kills a permissive schema.
    with pytest.raises(ValueError, match="gate_verdict"):
        validate("card_t2lite", card)
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)
    assert "gate_verdict" not in schema("card_t2lite")["properties"]


@pytest.mark.parametrize("field,bad", [("tier", "T1"), ("profile", "system-live"),
                                     ("aa_prime", 1), ("counts", {"assigned": -1}),
                                     ("counts", {"assigned": True}), ("extra", 0)])
def test_other_structural_refusals(field, bad):
    card = dict(cards.build_t2lite_card(**inputs()), **{field: bad})
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


def test_schema_copies_items_pins_and_inherited_labels():
    raw = (SCHEMAS / "card_t2lite.schema.json").read_bytes()
    assert canon(json.loads(raw)) == raw
    props, old = schema("card_t2lite")["properties"], schema("card_ring0")["properties"]
    # The project checker has no $ref support; copies must never drift.
    assert props["items"] == old["items"]
    assert props["pins"]["properties"] == {name: old["pins"]["properties"][name]
                                             for name in inputs()["pins"]}
    inherited = {k: v for k, v in old["labels"]["properties"].items() if k != "scripted_model"}
    extra = {
        "t2lite": {"enum": ["T2-lite: live probe answers; not predictive of the full tier; never certifies"]},
        "act_g2": {"enum": ["G2 actions not scored live"]},
        "entity_match": {"enum": ["entity answers match exactly"]},
    }
    assert props["labels"]["properties"] == inherited | extra
    assert set(props["labels"]["required"]) == set(inherited | extra)
    assert "scripted_model" not in cards.build_t2lite_card(**inputs())["labels"]


@pytest.mark.parametrize("label", schema("card_t2lite")["properties"]["labels"]["required"])
def test_every_label_is_required_and_fixed(label):
    card = cards.build_t2lite_card(**inputs())
    card["labels"][label] += "changed"
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)
    del card["labels"][label]
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("name", inputs()["pins"])
def test_every_pin_is_required_with_ring0_format(name):
    card = cards.build_t2lite_card(**inputs())
    card["pins"][name] = "bad"
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)
    del card["pins"][name]
    with pytest.raises(ValueError):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("field,bad,reason", [
    ("tier", "T0", "tier"), ("gate_verdict", None, "gate_verdict"),
    ("answer_contract_sha256", "X" * 64, "answer_contract_sha256"),
    ("live_roles", [], "live_roles"), ("labels", {}, "labels"),
])
def test_semantic_checks_live_in_report_module(field, bad, reason, monkeypatch):
    card = cards.build_t2lite_card(**inputs())
    monkeypatch.setattr(cards.run, "validate", lambda name, obj: None)
    card[field] = bad
    with pytest.raises(ValueError, match="^t2lite_card:" + reason + "$"):
        cards.validate_t2lite_card(card)


def test_t1_baseline_refuses_a_complete_t2lite_card():
    card = cards.build_t2lite_card(**inputs())
    cards.validate_t2lite_card(card)
    # Ring 0 structural validation refuses missing/extra fields before the eager verdict lookup.
    with pytest.raises(ValueError, match=r"\$: missing=.*gate_verdict.*extra="):
        check_baseline(canon(card), system=card["system"],
                       pins=dict(pack_hash=card["pack_hash"], seed_hash=card["seed_hash"]))


def test_legacy_card_byte_controls():
    inputs = runpy.run_path(str(Path(__file__).with_name("test_card_bytes.py")))["inputs"]
    hashes = {}
    for tier in ("T0", "T1"):
        for mode in ("api", "hermes"):
            args = inputs()
            args.update(tier=tier, mode=mode)
            if tier == "T0":
                args["controls"]["wiped_store"] = "not run at T0"
            hashes[tier + "/" + mode] = sha256(finalize(assemble(**args), "PASS")).hexdigest()
    assert hashes == LEGACY_CARD_HASHES


def envelope(kind="entity", value="Mira", citation=None):
    return dict(type=kind, value=value, confidence_milli=1000, citation=citation)


def test_value_match_ignores_wrong_citation_without_changing_score():
    gold = envelope()
    answer = envelope(citation=dict(quote="unrelated event", context_offset=0))
    item = dict(stage="remember", gold=dict(option_id="gold", never_observed=False),
                options=[dict(option_id="gold", envelope=gold)])
    before = copy.deepcopy((item, answer))
    scored = score_qa(item, answer, evidence_texts=["Mira stated it"])
    assert value_match(gold, answer) is True
    assert value_match(gold, envelope(value="Someone else")) is False
    assert citation_match(answer["citation"], ["Mira stated it"]) is False
    assert scored.score_milli == -1000 and scored.correct is False
    assert score_qa(item, answer, evidence_texts=["Mira stated it"]) == scored
    assert (item, answer) == before


@pytest.mark.parametrize("answer", [None, envelope("unknown", None)])
def test_missing_and_unknown_have_no_value_diagnostic(answer):
    assert value_match(envelope(), answer) is None
    assert value_match_normalised(envelope(), answer) is None


@pytest.mark.parametrize("kind,gold,answer,expected", [
    ("datetime", 100, 102, False), ("number", "1.00", 1, True),
    ("boolean", True, False, False), ("set", ["a", "b"], ["b", "a"], True),
    ("ordered_list", ["a", "b"], ["b", "a"], False), ("span", "A B", " a  b ", True),
])
def test_value_diagnostic_uses_typed_matchers(kind, gold, answer, expected):
    assert value_match(envelope(kind, gold), envelope(kind, answer)) is expected
    if kind == "datetime":
        assert value_match(envelope(kind, gold), envelope(kind, answer), tolerance_s=2) is True
    assert value_match(envelope(kind, gold), envelope("entity", "Mira")) is False


def test_entity_normalisation_is_separate_from_strict_matching():
    gold, answer = envelope(value="Mira Stone"), envelope(value="  MIRA\tSTONE \n")
    assert value_match(gold, answer) is False
    assert value_match_normalised(gold, answer) is True
    assert value_match_normalised(gold, envelope(value="Other Person")) is False
    assert value_match_normalised(gold, envelope("span", "Mira Stone")) is None


@pytest.mark.parametrize("kind", ["span", "number", "datetime", "boolean", "set", "ordered_list",
                                  "citation", "premise_correction", "env_state", "unknown"])
def test_normalised_value_diagnostic_is_entity_only(kind):
    assert value_match_normalised(envelope(kind), envelope(kind)) is None
    assert value_match_normalised(envelope(kind), envelope()) is None


@pytest.mark.parametrize("quote,evidence,expected", [
    (None, [], None), ("", ["text"], False), (" \t\n", ["text"], False),
    ("word", [], False), ("word", ["WORD"], True), ("  Hello\tWORLD ", ["hello world"], True),
    ("hello world", ["prefix HELLO\n world suffix"], True),
    ("hello world", ["hello", "world"], False), ("word", ["", "a word here"], True),
    ("café", ["CAFE\u0301"], True), ("STRASSE", ["Straße"], True),
    ("hello!", ["hello"], False), ("needle", ["haystack"], False), ("word", ["swordfish"], True),
])
def test_citation_parity_with_qa(quote, evidence, expected):
    citation = None if quote is None else dict(quote=quote, context_offset=999)
    assert citation_match(citation, evidence) is expected
    if citation is None:
        assert _cited(citation, evidence) is True  # QA permits no citation; reports use null.
    else:
        assert citation_match(citation, evidence) == _cited(citation, evidence)


# Captured by the prescribed baseline run before card_t2lite.schema.json existed.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "c58076ddfe03db217e4a0a0148d099acc3a092582d8bcd8bbbb76e32906cb458",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "da58d02c478868b410aa061a87bcfb03361d6ccce72f16f5eb8003e34093bd70",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "4cb57074695cdb387fa5ececdccc02df1ee18e663e930d7af74fac058f573c23",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "e1e5bc7657fa0708368108343982f9da4e6e2d71eab8eb9788c7abcc7ac66e3c",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "c7d239831e6dc6de1649ca3c0a54e9ce5cb74dfb4cad61c97a393cf8498603c3",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "ab7da7f6b650aaf9591dde45f10a8f188f0917ba1a2029bb6306a56ac7714271",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "c745bbcae7ca3aa3e570b021da42d8c6e4b96a9544668da0c19268d7a72de530",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "b473d4c0a499c6877adf4bdcb9144acf90d3615c43ee77188f9a1570459987c3",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "eb58346defe347cf04def39f3cab1bedea624cd70e4fab33b4988cb1f26ae348",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "b079a3d2ae24228361cb7dceb8afd82c2d4e17aa9eec6fd05a0f039c36136aed",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "ac0f250cb8d353985a8f5606fe2f7aa1295a2ba56e9de950bb71d42be0c08fc4",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "ba98c4cb5b0dceed74659c0b526d2f4e10ba979a421a52bc1ba324743828bd55",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "b2972c0b9e1acee9ab99fa0653a6fdab33dcdfffc976dc061e7e94ba9034b6b1",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "ad1bfbd2278ce6d325f686aecd1db09d815b1329d138744e88c6262f019a34f2",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "525eaac1a7ddf78dc468403c94346dc6db1809aaf51c7f609ab74f893dcf2c76",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "449f6e848d356c17b732dc1d5537df6e2a9997b74dc97c6a71c99a0c65d0778a",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "02e6b56244ec7c1e8ad4ff4d7283816ec804d5d19c69d03ab90b2bf47acd8c61",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "e2e73ebef40ff751fe9d7fc90492b4177698261cb730a3832c969f5720646dc1",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "2f759cf3e2b4d299aa084bbe335466817adc71a34d7c408786d4634b730768c2",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "327cddd2a2de5b845be8950963b3bc32d7080fd45328835a4d165bee0e030f1d",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "8716fb09b2cff31ebf4edfb24e553199d9927ddfa186e65b06f6037ee3f698cb",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "592f98980260d612cbc83654d7fc51b60794593c65cbd663d3afff488a72278c",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "04a236bc13f19c3e79ffa2ae1ab1a02e2214bca0fbdd3f68274be0fb8171a162",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "ee6689b36a081a070eec321b9cd7e9a7579093989d1663a7a8b1030e3bd3d994",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "716d492a962a017f0103e0d2756b62995c2c64c1127e243e59e086b1b671daf2",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "9ef4e4408ed728dd75ebd50a3930feceaa64e37351608ce467c7832d27dd960a",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "a597d3b35db676d97cc5d159b3438eb4881ea35ae9aaf11b1a7b3b59cad79130",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "67f56d7690fe06ac5369ee570263b5afb92276d55b722a914e76673d4a2cc248",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "dffb320c8658fee06cc0e756643644aad641f05abd734fb0897ec729a31b8db1",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "b3b8d17d170f57b12beaad818e9779aadf221cbeab498e452de07776f091b905",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "0ccbf32a1948fa0f06aac7c333f65973176536451e83d22227a209d4b5430bb7",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "d018fcf8b87ba7527c9e972f13e2b27ec47bbb9090ba907e190a5976988426bd",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "a0ef34b05d4d08d6eecae57f0b0dc570be075709be1c99094246250c4e29aef4",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "d946ecbfe9b65f6df4f00d86120e415e51d07ddc4f79f8c92a0cc2d85aa81518",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "6ddac1846e09691af9b38b6b1c3f38d8ad14f0f214821e39071b28b7038a32b2",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "673d8f4ab8fec41775da48c882ee86033db5f010ac34ca934323958630494286",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "0f7e70ca1f590db336266d2e7e3dec2aa0836f8c03478123258bc9b089b966e8",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "8a684e4723ca1f102ed09f05c3e4b226dbe507a3c09088ea8aee5dd6d2770a62",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "cfb1885216b716670b54dfd177d1560e625ee742dddc1a733e238104bd313030",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "7061ca526f1925c28710ca1af98f0b45bf291c2c2cb95e8cf62449bcf06ea48d",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "61dc15531d556533334feefce1d0fe6961001381a55e71caf0d4bd36e5e8b766",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "a3395eca793b5472beadab8fdbf0d87125b3eb249a2ee6821065386f7e633daa",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "dc45c511992cde17c51a250d522502f0a838216aad46247d38bbc3b9333283da",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "9fe7877095f9745bae649e24a956bf91f588105680312eb2c36fcd12c4d24ee3",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "5e69a6c9646f10778163c5d06d3229a0d70ee0dd99121a40d1a23979c6521bda",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "82bbc4beaedaf2c00aefbf050a866e54c7f884d399a18e4e45073bc2727c6ff4",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "cba5067fae5a651df38bd913d6c2237ac60f8c7fed9f07cf626ec25d2f332a28",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "4ae349fa331448e544a78f66d6e2931822fde1d2566194bb43ac170d95ea25da",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "d4cae7166b6f223aff2468998d4e8f827d1e0cc5d9f7feac16a0c075c55aa71a",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "2fe56d12746df75fc729723b1b3039f612bf85c76ddd00c573f288f5db623d75",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "d1ed2b0ccff84a692576306ab2cb39bbb4bf39e860bfa80961f7bafbc67ca189",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "fc658d5ea2122adc79bc1cede6fa1b4d7076cd5eff8f9367a320c7b86cefe7eb",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "728488063d1ee37fb060ab379b34575865f83cc921676b8dcf5b76a813b7f60b",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "0df74e375ad91360b4c9f6bd59ab4dcb97c6e12c60827ce5d4a5c118cbdb4dcc",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "6349b1ab76d83e91213b5e3996d78c3719eafd3603ff3309199a8909cc05bb8d",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "7101b831950d996972782352e7e031da9facf8cdc07b380c7fee93ac4fd1e74d",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "32a27af4cc1e7fcf9f613e0b7e9f62f752f0830dbcbe2e84543f4bf3d472d56a",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "b616e8182e2d05aab52ed038f3ab58288c35cd79b6bd29d8ef342c571d3db966",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "d8cfdeb8c01115df1ae70fcd6afff6a6d24610b402a4db78283f305cc2625887",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "c6c492964ccdc9da004c50aad88f0a7be3cc850d1314c68061103b536e77e7de",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "eada55564cab6101bb83b2516ce7993cc486006e23683e73925f648d213148c3",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "c8f06a1c38b83f1a034acc716ecdfdea2a6375b680172f773169664dcf49894c",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "98e397c4c59100be900fff7ac99be742dd3f679a74cf9a99d0c96886f0429185",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "cde39277938c4046f30b6ec00f1400973788eba62f8b9fec6fdc9023c2d86801",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "12116e3541bcdfc42a2373e83b1d47ae27375d16c10422eb089043c4644f0bf7",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "c907088f507e0330d821b989037a90c36f0c4e615e55787e8d536e557a713536",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "329108f74d3f8f01b2583aa2f3b45d9bb9784dfb8a729ae538533368836b6821",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "53f55998939e45f49676ab90489a41f2a326346f31099bebbed52233e5b69fcf",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "cbe5a637fb0afa8dfae5fa30ccbec96a0cb920bebaae74e2336bcfa59129cebf",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "952048df5f4a69f8f4f329b04dda8caf21d158c8ca53cc48f76ed13011970032",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "82c1b710e088027355b73f0a3240b8cfb60b494f8f6f4ec7d80049e4757bd977",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "e08adf601d3c75a746f4d5536d9c47d17eaaf021d9a3e90530ff47dbb103b137",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "d1e57fa0588ffb6d55dab3a5bb3ed7ec31ab8dd7d1d4768ec829d2162279b6eb",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "cf7364a76d89dd0d53b4067dc6878e754176221b08029835400392ccedbbb88b",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "62a3cb89e3c63e33496c505fefa8bb0d7cded1ebf31fea99f9de7fd1d5f4adcf",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "2d69c06136333370721e58e33911455e9acbbfd48c380c79145a8d9d19d4f805",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "46168bdd290dad157b95d83497e7a00a3e41eeeed7ae6cedac389ff01bcc9fa7",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "e2e754ae879bb1f2700bca0a81d0a25f9094acca5a1b156240b9ed0a404b8d6e",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "4838cbd382997785e0ba1e976e582d9e9ec2273c1fe13fbf47b212871cd687c4",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "739ee94fd8f64a2f3febbc6c859d6cd2829a7b2fb15cde9aa1caeff7ba885a51",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "225abce1ac072019c719cc8497ca24dc2fa710688ab293fddb3257c5913a89df",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "15266f3beccbc9f76a4196d9a9f5d3c15878ea28792bef1d453f7e33b4907717",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "2232c8505ec9f74a86d70411b840bc44c48af0cce7f2ca1cd98d4a27f0224441",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "e4eb492284d2a3aac211d22c805557ffeac64e1781c71b8ebd620bfb0d962139",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "c4ab94e244f1279fb469bd45474c90c53ed0528f955d9b721aff7c7038040bee",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "70ca2823a32a05e86b568cf9d0a2aa2cde684566bd8e63d5673a6f79f0c9a54d",
}


def test_existing_pack_tree_hashes_are_unchanged(tmp_path):
    result = build.build_tier("T0", tmp_path, harness_artifacts=[
        dict(name="hermes", version="test", sha256="a" * 64)])
    hashes = {rel: identity["tree_sha256"] for rel, identity in result["index"]["packs"].items()}
    assert hashes == LEGACY_PACK_HASHES
    for rel, expected in LEGACY_PACK_HASHES.items():
        assert manifest.tree_sha256(tmp_path / "T0" / rel) == expected

