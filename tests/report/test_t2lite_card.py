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
    "T0/api": "ba3b655e6c54b2dd964c58f0e60e19adc5f7d10ca61c589c6559cf347730fa18",
    "T0/hermes": "7a233827b7683487fa52db21ccb92eae2c24153eaa1d0d3ed98c6554f6365c3a",
    "T1/api": "a2e5ddde84135e675509b3823bf74f376bb58a4f000e96dab4e22805ada3e854",
    "T1/hermes": "a2e5ddde84135e675509b3823bf74f376bb58a4f000e96dab4e22805ada3e854",
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
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "ba2ad55a198cad7a238f6d5b11e732d90968ace5febb2e5d6b0bc47b178f5d1e",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "2b2faef07a160a64760932009b80166490438d8c8615bbb2f53dfcd2d40a2eed",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "e5799a59c39d58874a05106af65624d8d09d72a417cfb60f5d8597ef535eabde",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "1306e0402349cee78d76f98804b9e5307e452b007341b88f623626bb060a5eaf",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "35df2cfc55beca30437d62105cb6f247360323f36f840c112936494165dd7a03",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "f964e0097d57124f1a6fde8c93ea3d7b8ccf7e633d04410c59febf6d831ce5a5",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "e7f007e75d551e95b12ccb006f609bf9667cc639ff104dc3f16fd417a15fd2d9",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "1dcb0e46cd5a981266535958e230f6fef07532c0dce7cf5c05471289043879de",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "8daa5d7ff4b4df608dfb42085f6d01bb86e2cf766861c1b9474c23c658a06497",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "d7f250fe61fe3469468619e1780fcc90d607b7f846b92b214b2fd070bfd0376d",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "61e9d9e6701e47630245e3009fa08baac8558c57b0cefcf6a47c2302467d1c63",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "788af17b081fbf2fde4af699c2033e55f36d72a75fbd83862728308a2326ea2f",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "123d47a478dc325c0f9d436fa556f6c49a90d51e879956b1d92261a427ab06fc",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "66476a2b56ee7dd07b180f1cf4dcd6787c45d004ed4f8f5ba983cc12f5f8ba31",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "3296f41e732b6141b165b79ad389f675cea4b328f98e0a0daf86ed02c12006f1",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "c5d5a054549e5b04975b868147596f19b4ffa434947442152b1e08e8c2730ccc",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "26c49e3572116fbec770078be6e2ea41e16545dda633c2cc09b143dcc39ae0d8",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "f791fb107532b6b8d89d6d9f7c664dabd521684450b6e5266fbaa30a31cb4cac",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "4c431cdf9521ad54a859731c212d08b3a21609c6b13321a6ebb27ccade6d449b",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "a313707c463990a86290ed525fd526808bdac95639cc093ce0f99825e98af77e",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "bc0a2e6ffc1e0829a2c292d03c1d9a9857e7f942eee0cb215c34598c888d0271",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "e666a0f2567176ca983fb032e5e0c5e6b8e5502bba0b556f1a1d6e51de20dae5",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "ef713b49e2cf9b25871fcc3a53c1fba35e1a4338f99a553352d10ae8be0a311d",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "72bea52e1007b60db0a8c803520fdaf48f3930689a8379474be038dd1487f05a",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "bafec66218edf1835ed2b57ac3e9418f54f051fbedf4fd31a8088169d3f198db",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "c8354cb8d07167fcae123953e5fe11ce228779f7961f93c750eccfa94569f1bb",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "d5dae0175980fc00b522b71309ef15265e163c1a899dc999d6dc95877e75ed06",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "948a333a4de66c413a442a315c1e5d32e1ab5eb70d60b7dffd35745a25e56688",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "03b79a7d3ee93950d9ecb700d0cf7411dae95bad084aef2cdc76fb1bd9674079",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "b0497edf0175fc94c8a49bd67c76ecbba9aaacabe77b0535657e01d2335547d5",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "e6af760a6486d620888841140006ea27143cc66393d6d4ff274aed35b2f3f826",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "c1c72db734c0c452a47ca88be9a63774e7c55fb986f4ca7d7f5054bd0851805a",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "4de6954c4dd66605c628df3b83b0d54932029581839054ab492f2a8c212e388c",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "59b7fe73000e6ce4d39b9f1feae9b5373d7a4cedf26c5206f44490afc37144be",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "a903bdae0226477f23615c6f0e645c0bc0f1d2dc664654ed37fed987ac29fe4f",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "b3c50013fc44e33c5b400a43d167fdcc9d433e8b6cf718fd518c3f2b1398f14c",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "c03fe371c858b1588247ef10c0fce60bd3483b9926d8141f556f699d87e85355",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "2ad968e022b53323458097cbe355a4c31b0d2bbfde35fcf4e3d09963225d227e",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "e13ad078d4ea9b71a2b671b36e1d66fba6353511801c9a487402de2aa5f674e4",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "611e4840840b0776e9fab9117c88b4aeea29e0cd998112e208e47d5471e9be20",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "3a5b87266574f8e9b2e885ba6abf5a8c2717f83bf0caee567bc8e78f2071ffa8",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "fcd3aeb3a68672893259fd556e48abd9381b6bf48b9c15527e1190a9bc991d28",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "d3794f370b93322b30025336f642bdb426b219a6c5511fe11f9a99fcd37fe5ef",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "5fedbc60d41a8ee587d7ecf64fd343ccf25a7a569356775f10d5b434edfb1506",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "e5e492ca5d4f4a84ebce0249c1850f9cbedf4aa89c0d2c98b8edef721e97185b",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "9bddad6ca23eb2d3a1c4cd40a8eb7d8aef5621bb3d3d2d66fc0897cead8bc6df",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "93883ba28f0b35f03b49e42075964a11ca9bd51c6af198aad2d8be1d255d02b6",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "f270041fe5ec98bd3cee73e36721af0ad1be04cb0fd39c79bf5cb81461d28b98",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "e0a1862cf23b6f6381c5a42f37d1381587149ca5af0aac5fa74ec339c3608e13",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "e4d139487c27e46016005ed11b5da115ec1835a9fa43aa79cff6ea5b5bf120d2",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "bde31ca00f7489d82f3b7b6c57ed8cc7d8e8aedbd8013c51a56a196a0923b1f9",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "cc1c8479c0b00d347fb5aa38e431c6294f718355babae7ce116ad9501f36a370",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "7b7f22b97dc002a6a8f64998a39120b7217dd77b1a1bf60ba900c78e57cd8cad",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "d0d1524ce8ce8d5a0bd220166035dbb8177d437a319c8534e417fa0a56a3c4f0",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "4c8c39d750b77c902f7f73672d37d2df925b1e3f269feee79e1f52c2d22f99da",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "553526b0f018ed9bf8a2b263ed16fa2ed26029945fead7de3b95909e24789973",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "ab974ac1f49b70c732c0df795b08155c3f522e9f838af66c5f652aa02b0ec6b4",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "37f7a1ff62e95c7bbb67702afc3a3bd5dbbfc05afcb406ef22ccffdc99eb60c6",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "b23e30d3cad72ac0d888a753b1662cec11af8ea79476e7b5400576e9fe13f78c",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "19e248cac2855269246597355ae008a68dab305eff1c12e85afa97103f41b988",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "05c4d5ba0c75a8cbc496eda6c7faf560322bebddacc0be84d02751ff4c1dbae2",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "1df6ca23a805845900fc85c2a32e196bf5f5a1f3f37da2be41b45528ccdf08ad",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "64c99b108b1ab6685024f4a50dbaaa11a666446fdbf3af8f3eb5fe48623c6e72",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "f9898f5c711d4aca79cdb0fbd2926e87036463139b0c0ef78ca8012d2aa1987e",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "2f65ec7e9d2cafa1c03521ba5fada93a9c22dc0c366b8e55223be7be63f2b06a",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "5a42bfb009973074d600743ddec101bd18d55301e57187746d460ed3380e40ee",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "4b99d0ff8d62e02aed2164dc24d45b09647f02a73aa3a2375fcac1eaedbef8bb",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "ca9195cade8ebea53eafd0ed6072cec7bd53df3262a03c2d237119cdcfc361dd",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "0c86e0010e317f34e73fd16f6bee4ded08ba97142913b86ca1b087fc4ff50dd4",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "af9eea1ff56d254056c4543faca74f29b123ee58a371962ed7d0c74b51b29bd0",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "c94c2f7a04ad291edd2f446ee7fa71c499ee8be0010e867e56695ebb12b065cc",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "181deca1db2300881cd8bed5e6bc03ae6840f0ada8bb3c85490c18dddf9d0b82",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "06766b1d1bd1f2f4164b4a31880593fbeaddd549232a04d3fb5692e436c99746",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "43b2682e2d269da82d3cd4edf13b1d15e7a9f2ee75be8b5d5bd04981deacb827",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "eb5a5d25814316808b5ca607aab40396c44cd0353cfe07748780243822b37a70",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "5fd2e5e37d35748cbdde9f1fab1bcde56b894da3b6166802b16ed2f557549ac5",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "99a808248c12962dcad49215d41cfc3c007038b3cb9af3aa7c80d1006930aa92",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "2cbb2a742385ff21b0250da0b05dcdf16b1e403b751682a59d29898fd9a43674",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "dfaad8b74125c429e2e623e20dbe0baeb0c1ec72de1201a1c3efbf0f4701742d",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "d87c27a85401a5691be3b26c325c5aa5c038f1c3c0bb58ee6c75e36e7a43b4b1",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "5244be41a717b062a2088d3bc7016d7313cd8f31b6246ae20b6f859fed42a91c",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "30ef7c4f11c8bf75b9a06501c65ab5337916fed215c6365d15b838f972013c54",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "1a3a13d7fcf3442c7608badad4554e1f587f031d30e38a3744a9b9e582019fe2",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "92aa2b899d4ed21f303f3af0b0503b7e87f931e86e8991bd549ea3a0b9d02b2c",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "6468effc5dd565ee7501cf3dac2e406be51d3ca3c945193739e5be3c44246e9a",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "f9958562ea8a458a23d998927342f6e1c2ddab987302c1defb560496dbd2df1a",
}


def host_free_tree_sha256(root):
    """tree_sha256, with each world DB named by its schema and logical export instead of its bytes.

    The builder now normalizes writer header metadata (#327). These legacy digests
    still use stored DDL and logical exports to detect changes to world content,
    independently of SQLite's byte representation.
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
