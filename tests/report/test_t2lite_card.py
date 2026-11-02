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
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "433c3d9ff273050ace9c620a0fd39205938c8fe548467b32bcce1823f799535e",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "3b15d65d4bec9543d11eac648c8dcd0b3d505f9110dd2430cdcd0fa51d0bb952",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "a91963b46c9ed6e69347840a290cbca41324b15ff26e70ca8c7f541c94448690",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "7b879713c0d3ac42096758f0915c28152a82953c425e33bc03adf2bc0139e370",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "c6c5b0859648b70e74e71143ec3974d8b6ff52dac471655cf8947f49448734a4",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "49d73a00b7db4e65e970bbcbdd2b129fedcbd43bbb6f3515734226b2f7d6fa22",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "a6c5f86f5c479074eb11721cb1bf20964b989925dd09b8e8339b19334cc24d17",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "080de790097225ce97b940b016f1710bd35d57149decec746f29852b732da4e7",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "4153db0d66cb04c0237c5f05370bc026683360301701d262e07e7a59dabf1402",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "c136158f301e0ff79b43ac897b7445a1d845a626934a081f06d13c6058e15181",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "d7f46b118af5e47af7a500d2735c48ad3efcdc5fc070a2bbecdd1bc82d297cea",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "12cdcfd3cfd68c82ea77563b107eb52c58123509bc319b7659bf61235cd7da5c",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "188f494edaacad7d15e2d8f2bde5ee33fe92a24a4f75f0605686fa2d95c2da2f",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "d06774b2f5d635fd58552505d25c239a71afcdccdc55e934fa6df00ae9ccbfa4",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "743f91803b7ef492a89961782fad26d6157179a136fef51f8b2982caf0f96d51",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "ebb28c0fc16216f4eac5c56216b912602498f1af4abda86854b67f0adc8cd009",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "062fc119db398bfcd0421b5ae2dab4ac4517ee8ed7ce3b5ea83edc105db5c4d1",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "3ea7e20655937e4b5ef9b6edb9ae27205be8194b569c0cc7679a14190c14c9fd",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "c3e4c23a5953dc884ccce26c191a13e40bb3df69b300c16575529515bf8a3df0",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "936c611fcef197e7cf5fb7349c0718f60cda47612952449852cb18c5c9bce303",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "3ddab9549a900ca47669c59ef1c17566fb22afa8cce9de4c1bf27c33f091478b",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "6ffe095a735720df3a588a3b23065b41484504ccff691b421a9c5ad0ca09ef53",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "fdda16df0f76162b130aa687c9a53ec845019e29441d37130e5350fe5822db70",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "50635a3cdec0b73eb337d5b48567d466a3b21ed11e3ff523242c748c4f14c2e1",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "34484f14edce2ae4b52b9cc584a01875f4cee9f64827b847ab436acadea0d622",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "c58b2936149b07369e18f0474c262a6787fed89559a0958650577a0d39a8693a",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "98a04425bf66573731976ad727613fcb7733a862e59e1143c47ec3878208308c",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "91b383956d0db373233523e33e934689ee9804be8fbe14b5dacd226bb3c38236",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "fd2952193cabcb8387c71ee8e1d34a94a63cdda86730571bb7774df81bf18e83",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "00ba27910bdbc3af3f0d79dbae0f3c2f15865ab33a438239d6552694e60c88d3",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "63f991500dbf4fa86b79c9fced13e561eccbaec0be8bbd4d6f254519d5899ecc",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "b9593dcb5a8f814aa0523588cd3e970894338de64099056deefbab8ca7372d93",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "f72c3ed158ef9cdea59553129808b1e9702a8371ea685b5daa347bee73f6174d",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "3d195980a929fa15254eb1561eb8f7c5f994c1d7f86e8d1d3f76d666d35ebf4b",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "600bbdc6e1b1126e49c6f8a56f7b3d13714c8467fee4afc7cf336caa684923a2",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "c3f99ab1f137f4b46f1d78382af7ee10662f6f93488e3076290cec30676a2f47",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "c68b6215464beaac8522231819bd3bb5f7b51178778815d58177b6382ec81b6c",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "98fd3a1fdbc4650a3653d6ca62b598920fc9e5cc1768985a6789cccca0afc1cc",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "7f052f66574ea929f592ca1ed0eea10c26014d0a7513c5498b02937ed6588bba",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "a5233cf86b35b02aea8851933510c2e79cfa67720885cd4af20e8ea4bb68564d",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "e42bf731031046a9652990af2a66f7da96c54129a6994357d8ff34ce4c2e5de4",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "f1f27048f4e99c4834f792074a624c36fa701ea33c15b1352ce131203694b009",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "92706f74c810af02c13be02b0930f99f6e4fff8d641bc644bcc6fded3e4a188f",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "10a9ac34d069c30d1e2bb2251772cd1f91ccc5021611d419b209bbbcdca105f5",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "cdf8ddb57ccc2c81761123a888437a265f7ec01e69eb8effbab3cd2751bf765a",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "61986eabe4de50e86038b2c6b99b736c7b274e71702a0193655ee7a0358d2454",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "ff849ab411b39b62e4ef9fb4f74bd890ce6515b362f53abd422a9acbb8d35fb4",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "df136f76ba1354746dbdecc4cb6f38819f53c22aae868310ea2427ac605e79ff",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "621cb3c8a4725467c1482e311b24d153b87dfbfe2804d3aa8a0a02bf9f5b5a5f",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "5ebe26e6a896655a92a84ae6943bbd4fc29741f9f0a145d35d7165bd10643c5f",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "7bac00ebc6b7c334722bc1b26383ced3dc321f22ccbc44afe4effdb53bf4d868",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "97a836c19c3089f4c03c793159dbb9bbf297a1181345552ab9cb14528bf22f5e",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "54dd5a698fa469b98865fa91dc00a2dbddeb5f8c35f47f6a03cd6a8ea0d12c19",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "760eb5096c0878bd8f83165b6cc81f4810febe5646f2a3c2f8c04e49ea07c951",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "ab95edac9252eb5318245b9c108f1b5a145580cc747c0b647a8e46e916214fd0",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "8f5c8384e2c92fc7f377de8c406e03cfa0fa6a5541fde479ac9871b5a83b54e5",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "075cc6705dd37ebed70a67360bfbcbbb474ac1da7846e9ca7d90b9089df2d3ce",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "bac0ef3bd2a4aee6d64b7bdeb2ee10cffdcd3ff32f103240ee7bce4d794a717d",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "f18be86998e2e36bc6afa07ff71d3dd3e0ee0bfa90fd2f9f82e9da05c00d9eea",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "60131541656e2c74b1e294862b1059a23c9cb238e9bc942561da2f8acc2f39a8",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "65f19f5ba178180906b0ea28ed21b9ea5ec784d9f93cf3aaae429787785e5168",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "3af78515d1060ff9a8130e753f59038234e302ef34e43f7f4798c06b2cebebf1",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "8416d2d902175288080bea7186ee51c79ef039c8247a64bc0534e6f9f7680b1c",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "46d258cadf199ee19544e8ee49256524c1dc47dbfa7b7db1481f9d8274113aa7",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "908724fff217cc7db65792346d98c7fdd03ad7a500a2dee3b8e5b32a47609230",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "decdca4b9fad68dc5289e25366e1c5b1979f0ff487e2d7f7374f633250c78b0a",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "eaf5221e81e0d37912da1b351d3285b064ad574adff02b854a8a6aef03fdbf8f",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "8207404f031db13fd76c4d7bf17c0e327f77fe6cc1763faa48ef57c4e3533790",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "6dfc6f8ea60d9cbc3cbc76f0e440ea123226e012dbf96c60345278db28ec7099",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "9dfcc2ca86c5cc7ca3480dca0eab4f1880a58d859898b28e53ac9fbdc87c9bf8",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "8c3a8a9148b8fcd1b26ac1ad4a0e301c4df31a197dbd069072f0643cd1786458",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "087f4292f955e685c3e19d3cfdb29cddea12ad4e6209fe1eda838563e2e3e4ed",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "d036ce80aa5a58eb0396ce36f9557a2f3de55a82308d93c80d38701e8e46914e",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "ae97f3ef06f22c3b04c7d66eb2282c859276bfda452b10fb062d27f8d51a86f6",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "6da36a79817eddf309e2bd9f0a0aced4972fd1bf48e5819c6a81dee488302dfb",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "84c3f72cc66ce2b9ab5846069bf0fd8b7f4f75a9d3cee4c57e2c9fb4b594457d",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "7f654e575a0bede86473f8a75920c5e187bacef24ff150a400ff66204c8b3d3b",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "70285e39d48b1041811f80deeab99a46673aeabab6de996d5c1b0ba9a0c6396c",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "29f4bb50bbb54a28b3855818ba8ece9a427bf8790ac647d0ab2f71eb5dd4c2f2",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "5f3a7a73e795c281440a31cea685f01899c34ee7578a2f33ccc9ac5df06f3346",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "71529969bbb9e0b881cc3a716f9d2d2573921896b07cf39a623da29a9ad64de2",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "6b55ebc889fe3a53a74ad714bf7e745269840e2dfbb07185915bb31ed6639acc",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "fd5db13895b77ccfba2622a298f90b0527d11a277f6004b3354fe0caed7d4eaf",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "5bb58b67ff3106e6a7306734970bdf38a7c8b049a4d69841c977fbf29f8c3865",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "894e3de6b16791085812441e5ecedc5a8c5d224c131085352dcf6b30463e32e9",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "aeacc2bd4359c3c496147b9515e529cbc371528e97fca09709a9fd654dbdf46b",
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
