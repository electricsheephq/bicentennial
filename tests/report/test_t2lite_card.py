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
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "2d17b44f72be89d5d384838eade9ac6535065f7d211c26cecbe36dedcbd64a1b",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "e5181c2e5f12b53c21f4d8b91e54ecce4a6b836f67388c284339293550219792",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "9bae76b9bbc715a430a59939e6ba9d857efbd4fe1811ff59ced495daa0a8b9fe",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "231d626c698df874e1e17c6fc890be010afc084780b97a0188e5fd78db893d27",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "c479af8209234a701e8d747e7b54b6f5c4c0f0079827c404a860e94a71910f5b",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "b16e75e760950bc56c68ce10e230b4f2997ee39a665445e4bced2467db131f22",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "ac8d8174f9607460770c3a718198e27f1d10b2b3836a2d25ace9aed63457faa6",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "2ea06af2350a5ca4aec2f271e52534ca2159128e640c8a6923e406d66388364f",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "0b62221f06478db6e9e0c3c48860232b1445e42d58e54952c85437396791c883",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "04098864547a29d0aaa4861738d03c753ef3117a804a07f0b84a9d225241a725",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "3b94f6477c7eb35e4280945d35a9aee7de73356fbd7c2facdcb578b79d99c86d",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "52eab956c371e52a31f74112298d2cd0519e11c99bae3001e92969457a0dfc6b",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "59fe294a53c5e41326ecc41b04b6dfab04189179246add60f0c2482d3f7b1db2",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "e6c123baf5c3504ac80de90e5ac7b202e42002e5c695851a0039e3422335eec5",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "d027367c728eed56f4dce9fcb73c57d1d9cd6e56877a62f1f9a5b7ad3d906d56",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "919b2138b5c4d10ba7bb6695ff6c75a25dc4b2b9a933d7e0f15496f3e7d9c831",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "6b8607b2356723f487861d9d9286ae462f4c746126214b93ae57cb9dbd3977ce",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "ba526022fefeaea805458bf2580f3c713fc813826e1a33813eb25dc7951cd1f4",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "af8dc34d999bdd502b3f2cd1426692e2cfdf26593f196282d2a3dd0fc84cdf55",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "bef3bd522ec99f62a23292744b3dfaa3e31fb0e188b3f6be76b61218bc84f832",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "5a04cd6a46517a622945bbadaca5e35e5a797c6549812eadd1e56cf8e5667b0e",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "de1b2fdaab78dbf6febba961c9cd992e7a087a6ef6b95dc07fd8a7e6adacf0d4",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "7a3428499ca2b8729c2296927ff1293983cb97c459655eb9e512df9ab0a6e007",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "bfaae73d2498e9de2e27226468d58c923a389114df88b8e5fec90eac3c00492c",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "6ebc1bcdeb575708fd930bf150d35eebb1038408a8596c4de62ab00378e01f6f",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "031a6cd40f7ba278bdfa706bee695510b65e16e846f0989179be14359c19c1d6",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "e6546489b54b251d038b76ca5f649c5963401317eb551539bebd01984bdfa3e5",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "ac361f062ce94effdf46a3d4512fde63b2fd6300700535d24fb5bbb155e788ee",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "6029d1e7cf6351b9cfcdd3b8c67427058abfcb1ab0d4f6657dacd70747a56688",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "dd427cf25ab3755c29daa9d737ebc420fe2a3007ce2ffaa9bbbf2a091469881f",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "3db0e1e7dd67283dc244ae0f93201b85acce4199b6a66b90b895f160ea20b9a1",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "44631ef4d533a3899e81fb80ec5d361b3f34891eb1d4faa105e15e7450fa1e03",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "cf356144c34a41bc9193bb865a2209cb311a0ef71b281c2b33e3d0d1b9195a37",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "adfc09ea4deb720658c3b70bd0f7160fdccf4bc9311b6bf489100fdc3ae1373b",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "c9e8cf36f627c71b9a877c795cf0837c9da483bf8a8ecc84b828f784327d0059",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "0bb7a854cef768f40359cc0aefd7a02cdb523500a1f42db7e11c684542bdfb3a",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "8dee5b1b8d1df5e02befb27d1ccbe8c4bddf8e24c0c4a1a46c49202750b2d0a5",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "55815d5f502bead99bc594f78b44e91ae85b036c1d0c3f1cfaf33cfc9a6408ab",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "a9d13fbb391666a1f1a3c9efe906eabe9a7192e23d6fac477a038e8c24957a25",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "fdef756929fd2d3b5105b8fedf84c20135428bf626485d3c4a27cb458d14391d",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "526ff58753e81132e279ea18d3d2123566147a40c7914f9c89d126b19d7bc340",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "af22966b90225fb211f3e19de32ee749191d610c4f9a1430fecc0f2fd4607581",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "cdaa0922f4545f36ef6a914f33d6074329f603929d907198f0b1bf733c34a7aa",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "bb5e8f31d0aed00134a051a4de5976b030bb2ec08c446ada9270e1c37efbdabe",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "5323fedcfdf33c7e82c0b6da795a8d1a768a912d0e000a06e9f1c36beb785c06",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "3292adc400db1a99e5c0029a492d7ae35a0f5c45ca26af180a468e321c2d968c",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "279700d528e9d8d5942889ac1d2ec9ac369bededc3a71352836007d31a252d3e",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "99498c3c4ce8af76999002a40c53ca9a8b60cffa5f66371c921308487a1b14d2",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "2185c0f4c2e7c540b2caa4d4d5fd8c24afedf142e8ca5833ebf9105e7a492850",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "05d51cc72ee8b0d0a425714b5c619d57b0c65e5a5622296903d0a8cae3603fdb",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "4b4621a684bad417670c34d8c45eade65c607dd0bbed75442ba2e174c904e869",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "cb83b4dbbd00b2912f8a533c106fcfedc0f197b0214e4c7470c63faa619ab82b",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "192651f0cb0264b054e39a4c18e81ca310b8ef71025fee6d00eadd529c96d57b",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "cf806ffacda094151d58bca2c7c78c6dad948dfffdc86008f6f6d0e83b13990e",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "826663d9432fc65c0b7279d4930c2a25e16d42b733f4305c70d8a35f0d985781",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "1f409a28549699d6c8af20c13ef53508da7670b0cffc13928ca8e5b0511e96b7",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "2fed5dc89f26b06489d44ad6c2fb0eb909e55f895f86026d6272c49461be7de3",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "6ae5c894b8a810922461a8da245f9d38d52a54a0f59fa4ac66e68467bdf49646",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "31e04f04ce07b7a0bac85abf761994c3e1519f2c475628435be1401511709758",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "9bea7ce92f4b3bc737cc3354bb599a0951f2a56911f91ea47eb8be5bc6f88f00",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "253522aa16a432306f62681d112f9e103eb16e5617be5404ab7558bae9b9a4bd",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "990630978402dfcb388ddcbe39951bfe33e9e18d5889a3c75b2366ab365c9769",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "3fd98d0525f8cf16482f1b3abdf25e37f98ad90ef0ed9e82a4363a67b2983bef",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "17fe9798bac88980e525b73541d0b2843aaaccab9ec7c252dbed3030d502b1e4",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "668680cf7002a9608832537fbaa0abd9e45fa950ea990b5fd65c145e49d24f9b",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "d684e46cf27b2d381a97e3a05a3cc896e02387fb38b4957970f43588c3efdeee",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "10fe1f0e8bc2d6003312443fd767b38ed5146550ed1445fa702c67ed344473a7",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "470bfc288999a67ed03b82abb01547519c006dbda3ba1ac179506a6aba7cc4ec",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "86bf4c376208b4b1e6e8fdab0f613b99d883e750e1ae799df6654229ed0f80fe",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "2ec9c0e847c80d4c1e38adf0c7025ad8e837b4b982646bcf88063f411b5aa4d8",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "943dee1902a3c6a2d1eb3d5d4da0527ae50078d178e2fd2ab6645caa7365f55f",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "4bc4a5fd03ae1bb02fb22ee21719272e44251a68594e8e92a8e6dc35b23870c7",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "0e152a0034c4cfb7f0f38fe1c5a38c91ad9e1763bdbaa5516a1cdd9c22e700a9",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "f6335f32593fe84ec63eaed10bf28d05870bf7759bd4204be434ead19e02bc17",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "70c863a65d58be150051b1c54fe816b630aaf08ce3f26e16ca5f89557d1a8587",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "cceb02c4b94de75c9218c798bdc42e1b1b523657029b6989ee4eb8e58a10e4d7",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "d78cce97b60cd254a119963c6f4ff80b63b4f0b4ffe0af4d0cbc3d86b2306dfb",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "6fa146ab815730e646be1be75ad66b98e0fbbb4b758cb35f9d0441f866a09f6f",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "09feba62d16f52e10fb547733ebbfa8d9cd35bdff68daecb64f1822073567e7d",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "012d3c04f5258653f9d4e3b5e926bacbd72ab4cdce238144867725acaf6ad429",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "483cf72c34b7f8b0c2fc57865d09df0ce3b3ddb8a665e4251e42cddefd2e0ff0",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "e0d2730164169598cf0eb8a46bd82399e2764ca570d7b78f429fe8c6e3ce9bb8",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "12358ee809cbbfe1c155fda070f11f284a3969afbcfd5f8378ea19bc2c690fad",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "9beebb8292fce682eb024fa9d49b844829776cfbb343f48a795a11d4a6109cff",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "605254792ba6693da4db886a8c203de044665284429a3ccf6149f1e381458677",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "d76fbf215b19a3338ea58f3bc5da041f944fee4838a8aa2cca8a1e6f115dded3"
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
