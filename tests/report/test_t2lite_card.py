"""T2-lite card and report-only diagnostic acceptance."""

import copy
import json
import runpy
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon, sha256_canon
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
from bicentennial.world.db import open_world
from bicentennial.world.export import world_hash

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
        "harness": {"enum": ["harness: T1's settings, not the pin's defaults "
                             "(tool search off, api_max_retries 1, no auto-recovery)"]},
        "probe_writes": {"enum": ["probe-time memory writes: isolation is per checkpoint"]},
        "window": {"enum": ["window: W = 16K, inherited and provisional"]},
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


def test_items_need_one_order_with_unique_ids():
    card = cards.build_t2lite_card(**inputs())
    first, second = copy.deepcopy(card), copy.deepcopy(card)
    first["items"] = card["items"][::-1]
    second["items"] = [card["items"][0], card["items"][0]]
    for bad in (first, second):
        with pytest.raises(ValueError, match="^t2lite_card:items$"):
            cards.validate_t2lite_card(bad)
    with pytest.raises(ValueError, match="^t2lite_card:items$"):
        cards.build_t2lite_card(**dict(inputs(), items=second["items"]))


@pytest.mark.parametrize("field,bad,reason", [("score_milli", 5000, "score_milli: out of range"),
                                              ("infra_reruns", 9, "infra_reruns: at most two")])
def test_each_item_carries_item_outcome_semantics(field, bad, reason):
    card = cards.build_t2lite_card(**inputs())
    card["items"][0][field] = bad
    validate("card_t2lite", card)
    with pytest.raises(ValueError, match=reason):
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


def test_unknown_gold_has_no_value_diagnostic():
    # A never-observed item's gold is UNKNOWN; a live model may still assert a value for it.
    gold = envelope("unknown", None)
    assert value_match(gold, envelope()) is None
    assert value_match(gold, envelope("number", 3)) is None
    assert value_match_normalised(gold, envelope()) is None


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


# Host-free tree digests (host_free_tree_sha256 below) of a T0 build at the commit before
# card_t2lite.schema.json existed.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "926db94809da8278b27d75f60178c314394b40a50120eda5438432e7e2eba064",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "38470537c6b910f8055a634d0230ad01f279757c9dfa147d40888277e8ef40db",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "5935bc628c5e5568ee6e7ef9aed37c96f59607acff1cc318e15ad078ebeec3d9",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "204e25ea6619dab127610deaac317de31ac51d37e121e2b61e06309f12263253",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "87ec80a7c94bb5461884b5a77d341f7a373ebc836a55bd1554c8d543a1e5480c",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "04e21010a88d8cebefc2671776abe37b921852001c7b8d0a91981ed58d81b7f1",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "89834d8a044e3cb60a6cef5f3c79ede09bd752536583adbeb2bfa0c82419792e",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "be350a83709091dcae11f4d6a5184283e9ab202380d44d619531fa2c70f436cc",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "287d5aa08d00c99067b01d0dbaf1d16d7f736ac48e7a29085db5de3872c66919",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "0d54848a52a94b8cc319561a2442ae44d367de15a933199d29167b5b0953d814",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "409bf099e9f218d3d6a8972167e4d53b3aa992cf59fa74048b35e184e45b7516",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "77e7e448d49a0b6453d96139efb8a4758d63b971c79f45a500c6084863abadcd",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "31c8178abaf254ad58e2310086bcf035bbdee3faff76b243af2b97454964eb80",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "82c2b231ef5b96a16c01e30ac1a5f68f00b4e7e756331ff6374abb6b177ed7bc",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "40848c26b673878ab1fcec03dbec77f4808986f72b87c2dcb00e746b04ebab59",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "df024ebb8ce56f381def51953656a4eab1206fed57210d21958d9a13f4d0cd60",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "59c3c5f6d9ccdef39b764297920b2625ac4f3207674638628ed9d013de92c384",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "f5427f39957436cec8334e48bb9d42d3c4302820b1538ffd92d2905f79b27a5c",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "b00f008529df7b2607d2f0e33f73a44465112a10ed7e6a4144cf6cf1bc8faafe",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "957866b8a030c10c9b3096e28034b4a927e6b23fbc9c695dc508ba02ce65eb7e",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "32c5dc56b956f1ea603f2c858aaef7219f041bd50e5cf7fcc539daaf795875f0",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "abf31439010c80a6bdc72ecb25a0be42e4c853c42cc4e2166d5d5383d4697690",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "f7e15dcfb910d4555136e3888b0b37c419f625f1bcf7be5947b5a6c16bd8a506",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "985029f9f2a26a930555d3396571819a67d43b12ffc4c8bf974745a085b134de",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "fecc827089a00c4770cfa1991d780ea9b770d2db76af112278fbcc08bf953f55",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "293ec9dd94db688ddcfe08726319fa7727eca250ac70118c0bfa911ed6e99424",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "470bfe1f499b56fc3576f7791c79bf7f289ea2077647c9043d78997b4c494d88",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "01ddfa5c85e6610fd8c5f9e0589f0c17aa1f513dcc15682c68f11934b7a6c609",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "54f1a25c065cb034b8f4f2853b7deb8cb7de8ac6ebe46aaf5ac8fbd00c30f7d2",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "0299ece85f7320914d98923020bab77de5f8e60d6240be4c06ecc2b571ae7573",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "7c9a4b6a9523796940941fa5f4ac550aa638a1aaf57488aa92c4d796e9f4efd6",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "df99592dbbc8248327df65f515b7c0a55c9e4d1da1479dc94d58e1d85b1fdce3",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "365ea378bd01c5e6879d5e2a64af1ce18bdbe4e09089b8ba6cdb1bc6d6fec666",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "f6824369628bac71328eadc838c95c7076361e6a938e0148daa85e2cb3d84de9",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "8d7976dd962c757428f05d42bc799149a339614ae44e05f18cc83d6b2fd2186b",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "c85ec7d3f1fcbfae9e85f4e85dd44b6147f15cb0c32303a7424c79e94e698d9f",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "a8c2150f396b4ddf9293637b5166264ac52f4ea5c4823248246abb399129789a",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "cbb10e82d58f41e510e5ad6097fb96c8fafa727c308568ea0fecf6bb9f5a9667",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "3bee61ad808935d274365b7efcf96ee385782b5c647a86421a48b352c3883ee8",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "c7052433cfb5b4a678de81cc6c217d5a2c98c41cb43bc951fffe0ece9c50b64a",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "21dd7bd46048623ad31efcdc75b625b06939c9c022d5c0b9e166a089938a32ff",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "6965d1ee58377c55af0d785279aa206498c36bd4c39ad0961419e49cff63ac8b",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "3135cf8312cfff39528a18bf776803e5a6e17e1a4ec47aea1b6dc3f950f57f39",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "365a07ae19747156c856c0cd1bfae3f395fba4bd4ef498cfac2c610466f1a3ef",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "6b917c427f1658cb0a18dc60651a307429692a8eaa64b3638f69f4a6255b1b95",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "2efa1465aae817f7e6fb37f09dd8ee6a5817428ab345674431f5b8babd238e9c",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "08835da30560e20b6bad6329c54a634b884aa35ca3e602274048e8d4164f074e",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "f8f2023ac4386e4ca0cb6694d1ba2bb8f8a281f04aa5188b0e922e55a10bd4e7",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "95784370fae456185f873f4f3970a35de955ef8fe4cf748a9a791c10f27dbcdd",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "ae231bfbba74b1770e09158e204de10cb6dd64e80e476f3af882eda2f097fa35",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "d465785e221ab1bae333865b44879c522a532db4960c8bb6c403911521488143",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "0c1e994289689e33d2b16f01bb092e1b056dfc6c9e7ffb4d35e7d771625aa634",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "412bf1ebd209b62519c2bdd734b647e4a4456dccf318e6c1dc6a84241a14b638",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "5831af257dac8900331757fcc3620e6866e8451d5aee785a2f74a3b8e97db68a",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "16849d24ef2053b0afde02d303c3c33d4cfb6a7591b374ca116cb8e792d5f99c",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "0569e57f75e9d88dd464e5e800f7edda672c479a5f2b1cb7bb08603dec27211e",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "f5f63886b371af891ede4995ec8ba941b99f473c784c259b76a60c3e6d7ff2c9",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "5f22cb63a2a5c8ac22b94e4e1786ca8e1eb14c656653143e4ef4b68f977ecc76",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "7bcdc32fbe7a3185caf09da24258b0c0efe31b5f39835c7da0b12394f82b28b4",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "ecdbd1d88369ef21576b65bcab123928447a3c6b4a15436172c06aec8ca2868c",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "7850779b25d5d02c5a916ad03192db5831452468168a81a0f2b68b2674326532",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "bbd81ae31220140d5dc79c65fad793654bda66b3ebc475e89705d66fbb84b985",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "e95ffc2a6de2bbcb9d008506e096c01937268220d165ccf4049a5235e18fc3f9",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "985527bdccefbd6c4900cd6d610a567a8b2769b273d3a11974392f3bb1ed5ee8",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "1e6e84d7e13f88fe5b85687fee5392222167b49c17b28aaaae6467dbbe610ccb",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "59700a690014e6d2adb14f449d015b5a48e6ac95f261c4d92b1b5d296d5d52d9",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "944b65f0dac754cbd055faa16e22eba0e5102e8e9dc3245dd8b9ae8e4bf574bf",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "53dbf7a2ad6acf18c1d531f118685491ad85f5090ba6a3f37742c1da79550faa",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "c89ba0a7cc25460852864734b753773a42dc2aa9116435e6a156eb1e9db7fbc9",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "bbc351744ed2c9e3c2405bc78e00de390d19c18c7def43a348e1fa1ac0fd0ab7",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "255bb6ef632da3a7ab04cc2958b85186290bfb86a86edc11853f535fc4b55228",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "452064abcaf079148da878da1730f5fe4ca6177e0824e1b287249a4b0a1510bd",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "99778ebe334b79e9e3340a0651348323bab35b687c432b67b34765ca333cd977",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "f83afbc08b5eebe7bd516c15df9eccf10bb1cf563014938675818a1d8f7317c4",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "4d8228618ce3d926db689059a3bc3b1bf6bf2a2da7cbbbe2531ea83fac2c7f3c",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "b4839c430cc409d0a0dfdbcd6ea6f21136539c480fa9704eb442abadcc7c47b8",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "93a0284ec961f812a19357cbf12fbd4f755b5d1b819f9417a2eaae434ffcd4fb",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "10df0acedecac57117046d20e9d2c59f85155fe1c20167d7ade4008bfb0743d0",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "ee32131c134a498ff368b58ed64ed56387eb176233fe1c002cf25e3df1e36093",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "e8a535bd9bfb836f6944a0d022cd9efb55870be355933a12ec62282cc2019cee",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "67ba27d7780feb6661435dce00b392becb980812883b732f9ced9250348a35a4",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "e80df512843a429e02db23a91dec7a30c65e29a24183a707a07e4449b204503e",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "32df8e8541562ba2c69261bcfd0dcdc777d084abb1d3830fa516c95cc0472a4c",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "8fa1ea1855c244260610175171e86b7c23de810058ce872232487e40b3479ddd",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "05139a17d5f0addddd8951139b5e7a03b9a13938f7526fe4fb2e4dc02fd74496",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "3bfa739915c33ec4b7d1b49f11cf305c8d9286065f9a5351769712edf6a9f570",
}


def host_free_tree_sha256(root):
    """tree_sha256, with each world DB named by its logical export instead of its bytes.

    A DB header records the writing SQLite library's version, so raw pack hashes differ
    between hosts (#327); the export does not, and the manifests carry only those DB hashes.
    """
    files = manifest.file_manifest(root)
    worlds = {}
    for rel in files:
        if rel.endswith(".db"):
            with closing(open_world(root / rel)) as db:
                worlds[rel] = world_hash(db)
    rows = []
    for rel in sorted(files):
        if rel in worlds:
            rows.append([rel, "world_hash", worlds[rel]])
        elif rel == "manifest.json":
            data = json.loads((root / rel).read_bytes())
            data["files"].update({name: dict(world_hash=digest) for name, digest in worlds.items()})
            rows.append([rel, "manifest", sha256_canon(data)])
        else:
            rows.append([rel, files[rel]["size"], files[rel]["sha256"]])
    return sha256_canon(rows)


def test_existing_pack_trees_are_unchanged(tmp_path):
    result = build.build_tier("T0", tmp_path, harness_artifacts=[
        dict(name="hermes", version="test", sha256="a" * 64)])
    packs = result["index"]["packs"]
    assert {rel: host_free_tree_sha256(tmp_path / "T0" / rel) for rel in packs} == LEGACY_PACK_HASHES
    for rel, identity in packs.items():
        assert manifest.tree_sha256(tmp_path / "T0" / rel) == identity["tree_sha256"]
    # Another host's SQLite writes its own version number into each DB header.
    rel = sorted(packs)[0]
    for db_path in sorted((tmp_path / "T0" / rel).rglob("*.db")):
        data = bytearray(db_path.read_bytes())
        data[96:100] = (3053001).to_bytes(4, "big")
        db_path.write_bytes(bytes(data))
    assert manifest.tree_sha256(tmp_path / "T0" / rel) != packs[rel]["tree_sha256"]
    assert host_free_tree_sha256(tmp_path / "T0" / rel) == LEGACY_PACK_HASHES[rel]

