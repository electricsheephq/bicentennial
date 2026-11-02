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
                not_scored_live=[],
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
        "act": {"enum": ["Act: G1 actions are the live model's, scored by T1's action predicates"]},
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


@pytest.mark.parametrize("path,bad,reason", [
    (("score_milli",), 1001, "score_milli: out of range"),
    (("infra_reruns",), 3, "infra_reruns: at most two"),
    (("envelope", "confidence_milli"), 1001, "confidence exceeds 1000"),
    (("worst_case_milli",), 1001, "worst-case row mismatch"),
    (("envelope", "confidence_milli"), 400, "QA score disagrees with PREREG §3"),
])
def test_each_item_carries_item_outcome_semantics(path, bad, reason):
    # The project checker applies no schema maximum; item_outcome's own checks hold every bound.
    card = cards.build_t2lite_card(**inputs())
    *parents, field = path
    target = card["items"][0]
    for name in parents:
        target = target[name]
    target[field] = bad
    with pytest.raises(ValueError, match=reason):
        cards.validate_t2lite_card(card)


def live_row(**fields):
    return dict(inputs()["items"][0], **fields)


def unscored_row(iid="unscored"):
    return live_row(item_id=iid, stage="act", base_verdict=None, score_milli=None,
                    worst_case_milli=None, accuracy_correct=None, tuesday_class=None,
                    envelope=None, failure_class=None, stage_attribution=None,
                    benign_extra=False, carry_over=False)


def test_unscored_action_requires_listing():
    row = unscored_row()
    card = cards.build_t2lite_card(**dict(inputs(), items=[row], not_scored_live=[row["item_id"]]))
    assert card["items"] == [row] and card["not_scored_live"] == [row["item_id"]]
    card["not_scored_live"] = []
    with pytest.raises(ValueError, match="non-result must have null score"):
        cards.validate_t2lite_card(card)


@pytest.mark.parametrize("fields", [
    dict(score_milli=0), dict(worst_case_milli=0), dict(base_verdict="PASS"),
    dict(accuracy_correct=False), dict(tuesday_class="late"), dict(envelope=inputs()["items"][0]["envelope"]),
    dict(failure_class="BLOCKED"), dict(stage_attribution="used"), dict(benign_extra=True),
    dict(carry_over=True), dict(stage="remember"), dict(infra_reruns=3),
])
def test_listed_row_requires_unscored_action_form(fields):
    with pytest.raises(ValueError, match="^t2lite_card:not_scored_live$"):
        cards.build_t2lite_card(**dict(inputs(), items=[dict(unscored_row(), **fields)],
                                      not_scored_live=["unscored"]))


@pytest.mark.parametrize("listed", [["missing"], ["b", "a"], ["a", "a"]])
def test_unscored_list_requires_existing_sorted_unique_ids(listed):
    with pytest.raises(ValueError, match="^t2lite_card:not_scored_live$"):
        cards.build_t2lite_card(**dict(inputs(), items=[unscored_row("a"), unscored_row("b")],
                                      not_scored_live=listed))


def test_list_cannot_hide_a_scored_action_or_qa_row():
    scored = dict(unscored_row(), score_milli=1000, worst_case_milli=1000,
                  base_verdict="PASS", accuracy_correct=True)
    for row in (scored, live_row()):
        validate("item_outcome", row)
        with pytest.raises(ValueError, match="^t2lite_card:not_scored_live$"):
            cards.build_t2lite_card(**dict(inputs(), items=[row], not_scored_live=[row["item_id"]]))


@pytest.mark.parametrize("fields", [dict(competing_present=["z", "y"]),
    dict(competing_present=["option-a"]), dict(selected_option=None, competing_present=["z"])])
def test_unscored_row_keeps_shadow_invariants(fields):
    with pytest.raises(ValueError, match="^t2lite_card:shadow$"):
        cards.build_t2lite_card(**dict(inputs(), items=[dict(unscored_row(), **fields)],
                                      not_scored_live=["unscored"]))


@pytest.mark.parametrize("fields", [
    # The shadow found nothing in context, and the model asserted a wrong value anyway.
    dict(selected_option=None, envelope=dict(type="entity", value="Other", confidence_milli=1000, citation=None),
         score_milli=-1000, worst_case_milli=-1000),
    # Competing options were in context, and the model answered unknown.
    dict(competing_present=["option-z"], score_milli=0, worst_case_milli=0,
         envelope=dict(type="unknown", value=None, confidence_milli=0, citation=None)),
])
def test_a_live_answer_stands_apart_from_the_shadow_selection(fields):
    row = live_row(**fields)
    with pytest.raises(ValueError):
        validate("item_outcome", row)  # Ring 0 ties the answer to the reader's selection
    assert cards.build_t2lite_card(**dict(inputs(), items=[row]))["items"] == [row]


@pytest.mark.parametrize("fields", [
    dict(competing_present=["option-z", "option-y"]),
    dict(competing_present=["option-a"]),  # the row's own selection
    dict(selected_option=None, competing_present=["option-z"]),
])
def test_the_shadow_keeps_its_own_invariants(fields):
    with pytest.raises(ValueError, match="^t2lite_card:shadow$"):
        cards.build_t2lite_card(**dict(inputs(), items=[live_row(**fields)]))


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


def test_a_value_asserted_for_unknown_gold_never_matches():
    # A never-observed item's gold is UNKNOWN; a live model may still assert a value for it.
    gold = envelope("unknown", None)
    assert value_match(gold, envelope()) is False
    assert value_match(gold, envelope("number", 3)) is False
    assert value_match(gold, envelope("unknown", None)) is None
    assert value_match_normalised(gold, envelope()) is None
    item = dict(stage="remember", gold=dict(option_id="gold", never_observed=True),
                options=[dict(option_id="gold", envelope=gold)])
    assert score_qa(item, envelope(), evidence_texts=[]).correct is False


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


# Host-free tree digests (host_free_tree_sha256 below) of a T0 build on main. A change that
# moves packs on purpose updates them and records the move in prereg/CHANGELOG.md.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "c43efadc2fdd48229b430612c4e6480c3bd1539d8b9f8bed8b7da83c9d8f2242",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "a9c40a22f47ce13c36b883a090f300bf9ac2f3222e2d532eb53ee15fb8c7328b",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "2b85d1bd10981d6876821eb7d1f7170d1ada26284ffd31a574f9740f06b15053",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "4c4d2a438276b3ea45c563f21b36c0266f998f61ab11e112c5c26f52d5cec033",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "968b269e760c04ca7bbacaefbf77a8821608452b5bbb74ac08c8dbb96b6fbbc0",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "57b6e79cc144d15267d9306166e9d69bb2ea6eb05960c8afd20e3ba8acc28083",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "faab4dad9c911d7bb6687986dee0c384aa8959540d4e3073fb8452c3f146e702",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "3ba529813bff0a3791e1799abdf7bd6c81e327ded15ab77c622ce92ccf569911",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "6c6e6c4b513d50ca50c9b37adb15c70dbcee5cb954141d926a14ebb554999084",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "9e2cf73a320798bcc2b604ce19b54f967ec1bcfe51dc4f16e82966ac045e4202",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "96bcba0db77a48ccfed2ac5e4b8009d5868dd3cd0dc2037a87b2199da1ef11e1",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "0684496f0f502d190f88ce270f5a459201ae4a4dfa5404293ce6046e1dc85dd4",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "673c4a906e171d970d5a1ac935681917635dfcb73d10a5f2d628b0446a549e68",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "8f7fc6faa3ea6bc8f05557d99c639f12d98dcdde5b5ce6f654883c2efdfbcd05",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "9868b6f6dade8dd879e98a52b04dda437cfa181f9c907e62094a6fda3f03b891",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "d05ba2e3ce08bb003b0c67c63b614ca494ccbb4299d8eb448a3629f5f837198a",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "9ac3eedcb6b02de489f7eda4b457ed3792ac90940882ba75d8f1bcceda6bb087",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "ea9d1efee8f1b05509d96df9bd4dde3399589fd3227eb1f5d71de087cfcb91ad",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "af57d51a38970f671567b386de07d574efbd58f19f74f6ca0bea539da8908a72",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "8a74921c756cc1b6b8c9f4d1a3cf34bb378b136c5412f4db0fd55a3fa889b9dd",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "7aec18c3793c0b130d06d2349dffec6b18c8b2bd5faa647aa2f9cef3271867ba",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "fb36d9d9e00affbc242e39c3f583fec8d703485812d6c205624a35f575b3a0e6",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "7c023b09b3229d0f03830a24a81253891106a545c978abe37c2f997e6154a899",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "0a2c2fbea3feb93a17ca56ef236e3c69d38990fdb9c60b858044b0f1f116f27c",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "f0a7ccc72e5c448b39752211e32298b3284830d12d163111b6105a0e6b9ec3cc",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "f020938d66e73ce9cfbaaff31310e1737edab595f1f823a7b4bf4b5e370b3757",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "7ff745f15fe9c85f67d6a7a0c377b69ab4f0e3cfdc33d23a9516c1d288c626bd",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "2d75d35abfb8d438acff439953fe7655aa23881dc55daa039add90ad79010da9",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "72c4c64ee4d8222a6b0f53335f1697f12d210d798073f9ac6611384820b13cc8",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "c8a21233f682025e77dec7a009037cdefef093b558c52e7c2009dd4dd121dff0",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "761167486d0e1dbd45d5176eb671f5d8aab8bbde7b9324aaf7624538b4783fdd",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "89adcd225edff8e022ecc798e225cdd5b65c990bddf838d3826cb5118b391462",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "9ef81075e8ed2f48cc247029351d876195fa00d3a0624d2d8c49249030c376b5",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "2d74054d2217c52c8dc50f35b601085cc9103fb9a609c261f0186f5d135b3824",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "285e07e2061f9985b2c2ebe2aa88957dba893e8c75400615c90a2e637ef7f909",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "c404a494fff1987fe55e37d9ec2758a87aa21d0c51f95a40d9d674e9bd69b94a",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "8745c386b3b9f80cc28607911d1848f7e7ce109e2a534755a976122b8fa9b4c5",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "03d5c801937be5369b0197ca2edeaed89af94a2734e55e5f0a4edb4d1664da57",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "5ce7ce4271270b7f9dbd05f353496dbaf79c466b6fb20142129c7f8b05f44d52",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "eccae9737b2a9826556fd1125ef5a9b2ca194c5b2a6826bff32424a28b38b900",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "c306d83f5df8a2edd23167a50f2b719fb2d2dd85407f9d8d48b823a2f336b505",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "3ee3361893aadfd879e287f417fecfaaae3c9ea73bd19b6a6425161f23216b47",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "f8656b42a1cfe18ad8ddcbecf83e1522d45ec39f7b33a6c7888281be580d2ec6",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "ca8140f894e9284165d71f3dedc13021bdb95bba59da0dcd237cb1b0414a9373",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "669c8b2f0fbab2fe24f308b5719f86691f9d8a2c515632b1e3d7bcd2fc91fa1d",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "3c8b6183562694bcc275fdb23c26d6d8265d6300ea20d70ffe6abcd4b87f51c3",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "7a06e76c862f3fc9e0dbaa1a56fcf06118f8ebeb265737f72e4b19718d8ff14f",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "21a35f30d15fe07287aa64a1e2d6177205b6714b038f2af9eae07601fb45ff95",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "129e7504f74a0f9721624293bb8ba2228b8ed806287473be7fb2eeea01899654",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "f72c7c84ad0cceab6ba34d7d5086c5dbec41182783d828ab9c42ddfe0f053aeb",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "fe110ee0a14800eb2c220ff1536bcc8c35ef6bbbedfea3cb38d8bd879bf26534",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "cec328121cc7ce7282504e48d24317ba1233ea99dc225c4f20ea9b2c36ec8833",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "a751117fecbeb6ba0e895d609bddf6a22aa4a1c44c87ac27f60688e2a47f573e",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "50cffd9514c4d14b89c03f8514c7869c6298c394978ef7bae33e2df9d6504836",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "da6a5472941db7f06eb305d0c34d6de10be84e981eed71d8b6d605b6361a2c1f",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "69a066cf4c071dde6dfc86ceb6ca0e3c218405a08045416ea0acd5de1ce6af67",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "7e3fc2e3ab0059fd55bc64cbbafc98284fc0b12c7fe8bddfca15110690781ca8",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "8407e8309e167a24b939183e4d0c5e535500432635f7be8a0e00873e05073bf2",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "de558a6a8e64018e7f3be7ff89caee8650f749fdad9d9df9967a2fa2ec602926",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "277ee5fee588d7df8c1c3b537212e120a5e84e4ae2f7f93fea58f7f11246a3df",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "e6c1ab9e000d1bf58672707b1159c2fb774e56cc1548978ad03fe3d880773fcb",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "7cc9a5a34c726884fc729e42c162f9c773e2a6d02b6f94d4ee55e0a6f9796438",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "7b4ee367b876a01d06ccf480239c5289dc4c23356d2ee01e5f746c32151f13dd",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "7d1a9022999041265174f98627f9bf115bf46a4a7df77abdda7a52288a7521cd",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "6bfdd8aaa872f90147a7f0146afc8a1862a753477e16c811937e25521ff2a18d",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "f0ec20c2c2e8035d5e076d6bc18f8acf15f74f97c69c9e40c1cc024fd981632c",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "1deb64d9aac0d1ad02fdcc7749e841ef62fd031c00dd18eeb7dcbdfe94066f98",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "9239797dab1242d9c1f4bfcf43fbfc0a665b17692a5b9553e503a021e12491d0",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "b32c78c866297d2be54386b5c17c378d6a8793474851193769c7d2b894ddec5d",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "393858198f410e5b9fdac4d9e3db7b32fde821e29cc441336c0eb5a26215771c",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "9df5663e26b66c10295463f1b4db6fc70230adbe1cbaa6383c3b77d52cc62a58",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "8fffa38eec7411fd21a712fa3674ad3936b41b478f4895df19d8c5a980b75c04",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "7bbf5e95f12ba11b790a712547a0d91bdcf4be4222e8e97277fca0e8b8550897",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "175cff2486374806caa445c3f18f2cb2f597b3c5361a59cffdbf0a26afd17a82",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "20163858ee93d77da050457481bc4846e6b138bf00ef1f90f30f01ecc315d42d",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "553de7e41974aa98bc414295a9b545cc052ff0d76a30c3ae717c7499cb74519d",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "7e0d04f38a3957b65ebd31f0be25679d6602ee8d8517a4cb5ef24aeeb236425c",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "90907cffdcadef5820acccab0efda8279977f939dc2aae6ab5be534906083829",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "02a15d48bffcaf2893d49690bf18ac2a4ee03606e5ff97e4d11734a8a52f156c",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "3c5fc7b11ecfde28756e8c6139c81771f5b39d162fc897f714db18e86cce5ae0",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "f3d86ee0fa85c9c7a03cf36e318695f74ed10e53ad3bd90a4f100d0b1837aeea",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "6c61cbb9b156ed9dce23c8a0336344c0735b9c9c98fee4a3362e5d02549cc9f5",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "493161004f62ce41f85b2b0e0cf401bfc6b983ee32b2f65258ef7d741ffbfaf9",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "8ba9cb455876634f588892757117f148a1385ece5bdad46a56b27c602014a62c",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "28b73dc3210d933528cfc783a04cad35b6659a58eadc7c3aa502a016b812dd78",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "cf85f056d79f473ce685ce8535a96c6de78317e650b73b8f75809ecf6b885c9c",
}


def host_free_tree_sha256(root):
    """tree_sha256, with each world DB named by its schema and logical export instead of its bytes.

    A DB header records the writing SQLite library's version, so raw pack hashes differ
    between hosts (#327). The stored DDL text and the export do not, and the manifests carry
    only those DB hashes.
    """
    files = manifest.file_manifest(root)
    worlds = {}
    for rel in files:
        if rel.endswith(".db"):
            with closing(open_world(root / rel)) as db:
                ddl = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
                worlds[rel] = sha256_canon([[list(row) for row in ddl], world_hash(db)])
    rows = []
    for rel in sorted(files):
        if rel in worlds:
            rows.append([rel, "world", worlds[rel]])
        elif rel == "manifest.json":
            raw = (root / rel).read_bytes()
            data = json.loads(raw)
            assert canon(data) == raw  # so hashing the parsed manifest hides no serialization change
            data["files"].update({name: dict(world=digest) for name, digest in worlds.items()})
            rows.append([rel, "manifest", sha256_canon(data)])
        else:
            rows.append([rel, files[rel]["size"], files[rel]["sha256"]])
    return sha256_canon(rows)


def test_existing_pack_trees_are_unchanged(tmp_path):
    result = build.build_tier("T0", tmp_path, harness_artifacts=[
        dict(name="hermes", version="test", sha256="a" * 64)])
    packs = result["index"]["packs"]
    digests = {rel: host_free_tree_sha256(tmp_path / "T0" / rel) for rel in packs}
    # A change that moves packs on purpose updates the table from this message.
    assert digests == LEGACY_PACK_HASHES, canon(digests).decode()
    for rel, identity in packs.items():
        assert manifest.tree_sha256(tmp_path / "T0" / rel) == identity["tree_sha256"]
    # Another host's SQLite writes its own version number into each DB header.
    rel = sorted(packs)[0]
    for db_path in sorted((tmp_path / "T0" / rel).rglob("*.db")):
        data = bytearray(db_path.read_bytes())
        data[96:100] = (int.from_bytes(data[96:100], "big") ^ 1).to_bytes(4, "big")
        db_path.write_bytes(bytes(data))
    assert manifest.tree_sha256(tmp_path / "T0" / rel) != packs[rel]["tree_sha256"]
    assert host_free_tree_sha256(tmp_path / "T0" / rel) == LEGACY_PACK_HASHES[rel]
