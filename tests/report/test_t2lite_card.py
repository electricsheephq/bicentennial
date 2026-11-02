"""T2-lite card and report-only diagnostic acceptance."""

import copy
import json
import runpy
import shutil
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import NAMES, SCHEMAS, validate
from bicentennial.controls import cache
from bicentennial.director.compiler.answer_contract import CONTRACT_SHA256
from bicentennial.packs import build, manifest, scoring
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


# Content digests of T0 packs, excluding code pins and SQLite writer-version bytes.
# Intentional content changes update these from the assertion's failure message.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "db43934ebb8904bc50e954865016f5245a7abcb80be7a6da1f85810313015741",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "961da62a4254649212f16a19a56f2c00ad8a25dde352eed15d1c4da06e635edc",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "323d5e6f9522511b920f8f55bc8e7621600d12fb767a75a987c4b208a37e46ab",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "821661ba9665a406323d0671e518f3ad4a376f812647c0f3429f5e860f832a69",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "058497e20a3ef0b8010902f5ceda1bcefe726de822eda3a20de13f669b3a26ce",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "56c0b6122cb3da59f9c7c6f130c9b38654f7eb3485c6aeeb0956dbae5a194418",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "ac9c4074bb938676629009d9fdac37673fe02dc0248d38e599f28f0853b1b08d",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "fc65537b6e751aeb66e6cc377fbaf913932a60c8008086932cc28b9bda216e19",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "bc1b19d48344e20bcaee9044cf84b82e5c1f45d9d151dd33ead05b53872dbd1f",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "63e569dd740295045958bcfbb75c568b8c333bb10e13b8ba33a119a1ed506122",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "46b1936ca033fb99e83fae33b0905c94c17d54cba430728672597c58b50134d4",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "2bded4101269f24c0ccc4daa133a3d68449b1748327c6eb1a051724b76e479b9",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "ee273805b0960a84f930e54296310cd8516c72bf0ef685305bc785b220e8b046",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "2f6e211bae8ee5132ad70b7bb68027bcf94cda92007dfcd9837c7d2b6fb2e15f",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "067016cd4eff067d99cf71246da93bf488ad5570af090b86e44b014f11be0124",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "5ac2fb18ea2013eda47c3ee8475a77576fc2c693cdb490eb4ac82128252e66fa",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "85a8ca71c9b007e8d65c7dd09fbbf6046def5cffe6c6c48c9a0c7def0b9ddf5d",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "7c06f79c85e90ca5516e3cf393d181d3170cc963da5fb845759a9952d76d6650",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "bd1bac14798ade260a8e8181850a40c7ba54cfb2a6c66b34c466c393de71aba4",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "6ec5ce488d3fb109d6ac26dc70aa63addb50d0fea431eb83af91dfa0ead83512",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "1470f187605b51e952cbde270f6935f3cd86c09e2fcc87c652996f7b5781bd7d",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "1a36d4da2bb2a4005d6905c52865d6f1ed9baa737ae126eb1b9fb655930e77b7",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "51ba105a81ff3355f250f835ee50b9a14f173c68cc967084a97804d3833b7acf",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "0b5032fb0d2f0f17b1b27b449215828a99a4e881893dc6fd787009c6f83f313e",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "ade3c57b78a9e16929af925937f6d4fb040aec19e630ef9bd5300c46a8ca7988",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "ff4dbfc270b5da98cb11477927c503b9a71d3cfee1129e593eba07fb72b6210d",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "731f3a099e02fefd96a1b01b978cfe001695d3961e8721389b2850eae7197b64",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "00056ab1c8ca54fc34cecd8a3997c6351170f804e792c6944e312547470613e0",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "112c3749807567dfd94d820fb1d2ba75f5b8d6cba36fb074da649689617c27dd",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "461cdecafbe82320798b5318741cf553c57ccf7b81ca979450da6fc22b9212ad",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "d44edcc54ad12fabf9a3ff660e62cc3a990eff839a9aa08973a5e8f66bde8dec",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "e4549541117cd7e3b12e1d89f770d3b22fc99d972eb85dd0f6ac0a2d0a339b8b",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "8f7f74c2e28ed26958e678e42f311c8a9bca1726fc1c8a2dd7f5b121fe65d373",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "66f784cf28267b06a796a7acd98c7573d019b7222151ef527a7a9e3edb569b76",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "83ee99103ed953e30d7d74d04be5774564c9a2a937e0ce522757ebb9c227ffc5",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "b6bd9456c2ddee43a2833cec1e7c3b6fee771a2a851843b398d984145736148c",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "6aeacd197c7ee32e61c0b1b8685bf017ff9fa99f8511baa949368e038e6f630f",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "e34e3f25660d78eec0a32c903d028fd4831edce038f691c5be1835f460cc2097",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "4682dd244dcbcd492f9e90927c0c66967934392e31ebadc29b19d75ad25b1646",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "85ce57b62dddd4bb13bcc871415fb7dae48ee37967cca289a1f94c0634ad2efc",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "d9e8fc1c42705b098278cb13c6db74b09685f923a43630ad7b9271ab963eb644",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "20d858cc111c8581b734cec41381d1d790e69fa75282460a6afb90efd561f4a8",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "125cbeee5982438c9bca01fa24728dcb57cf150d578851063e17f6731b7c675f",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "85a4d9e165c36af4212bafb3ac7730c5366e7f981d99be38792a6b930518442d",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "4373a991c74177979e87797a8906e1dbfd1bc91c9fd5f47d0eef7ad60547710a",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "4e0d98cf59363e559a09de89e8a5abdc0bfcd8d0aa10b73a5bb4fb01b779f181",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "211a224d6712618831c91daf8e00ceab8f93ce725c8df281318277b191ee8631",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "f170c66d38a73298d2fbe99384e25550f3762a8bea2239f64e4eb080baa38789",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "f77821f63d9e0c9a0ef0b12ca1d4cecc7ea47cf922ce2bac55d9e04262187e1f",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "0779d12d58eb3148afec93b39f0dc93557c6e3ecf0597527593f7a19849a5e9b",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "87596e400638d5ddce829c9527a149cadfd66aeb01cfbb238b0847e776ca6424",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "b2b090bc9f4a803361f8bfb4568480f61cb92a55b1f4ce42a8a837fa217e8373",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "57f0027381414d365c18122c398f0b18473ed93010bb965d112bc5f8bdb09c7b",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "933d0720aa66597ecfa396efbe47784af0951e9e9ce87ac3a40de43efbe9c255",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "bc29690469dc9042feffdf401c1f90e412403dd350967ed44b75432337ac4655",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "e93996f493e7d73fd92b0d441368a384bcea295596833f7be6a3b95215edbe0c",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "56e8ed8e29b2a6be387204e528dc080a7120f1aa97700eafaf9eb0e4b47a18db",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "43c74b0849927ee9035bf8eb6dbbc789bb94dd95e0f3fb4f1dae57b5f6973ff3",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "f41d07eee7a48ff93b6f538c8ca8427420b381de76e0a9125e8bd547fbd0faaf",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "ca76dac7c78e4a1827cd60e12f4c4201137055a6d7ee4b9f6105635da53e5f53",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "25972ffbd1941b16bba08de68a6d4496b1579fad105651770bc86ba600f21adb",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "8dfb164c1c6b8854b4aa0179d8a1b9ebca227368f32c720d66ac18e459d09557",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "497cd20bcd9c6e557ab586c2ca0bdf28b581395c0c300f801de54e847809bdb8",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "119a49b4fa314e794f3a37f8f0116507762b08d89410f8384babc816f44b229b",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "0ef6a344b14b07751aa1a72ff72e68361fb291a0ec5200ef601c4ad77c4a017d",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "df15b98d6bd468d26df6983fcc623513770cb6550af9dc944fe82d28e7723953",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "e3e7bd7b04f8eff8143acbefa65bca9c8757616aaa7659147cd8f04ac2a566fa",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "cdf45d9e865a77ef95f6109a31a7f6c1ddb1385503b0b2d343bc42306c940d19",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "d2fa1f31c73b5d68ed0df23956d2cfb2979070cd15c1ce927e7c927841e9776b",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "1d83bf1acb844e1fc93d20c7cb708ef6487a026524795513c689afc78dc6fcd7",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "00a3340f12aff738fa7d897648ef540d5422d45c98f91259b97727a651d0fcb8",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "aca21275092a775937da85d18cc90e8e27fd597af6752ca12f42d79f47301dbc",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "4773e8fdbeffbdb7a26c5d1aa69826162aab4f0f4a61e013e92b8549ec9296e3",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "ec5d7d3cdbbcea26daedbf44100b53d3b1a628ad4782298f050afdbc03259a5d",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "085ebdfdd00b1a9cf3e929158879937e81fd284c27d3f0771698ce671c88d2d1",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "74d98c7f5b106b83a64d5ec5a7b4a24cb42f1b2f20461908a369405e04bead8e",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "93e50be256cdf65c94a1bdea3f3368872758d127661d1c2ea4d2d511663686c7",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "6a17e00df184bd11ce512c99e9774ae53c4c0f8db6bda745594848a9a1cc6a63",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "eac2964d5cc33ec8b90466d1c1e19e436622b5ad1c1f7a914537b94932a8722a",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "835958615e69da7c2d34bde9ceeb6082c05f42bc30d2768b06b839b41235b67d",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "fa88ced2b898ecccd8bf6f03254a3ff73a19e3ed3f89c0966193070b8d791d65",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "671ed0e67db006a5a298f9471e9c54ce9cb4e51e6f86522918d95dc8dd4ad6a6",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "bb6a832fc68c022738a7664911b1a14d43b5e378f886919ccb052b58ad452f88",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "ac1b8b7f86af6420dfed7f9be8b991464cbb9a23a12a7360193673e4c53119ee",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "6f1deecfb9e2018191c8d7ee9df9f1a226d7693a71b00c4811210208a5bfbb93",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "8d85f6a1cf88b6ef2270ebc17e915a5e56aced7d3408599e74b64f3301cd4ca4",
}


CODE_PIN_FIELDS = ("scorer_sha256", "controls_sha256", "reader_sha256")


def rehash_projected(stored, original, projected):
    """Rehash a dependency while retaining any inconsistent stored content hash."""
    expected = sha256_canon(original)
    replacement = sha256_canon(projected)
    return replacement if stored == expected else dict(stored=stored, projected=replacement)


def masked_pack_files(root):
    """Remove direct code pins and rehash their content-bearing dependencies."""
    def load(rel):
        raw = (root / rel).read_bytes()
        data = json.loads(raw)
        assert canon(data) == raw
        return data

    original_score = load("sealed/scoring.json")
    score = copy.deepcopy(original_score)
    del score["code_sha256"]
    original_pack = load("sealed/pack.json")
    pack = copy.deepcopy(original_pack)
    pack["hashes"]["scoring"] = rehash_projected(
        pack["hashes"]["scoring"], original_score, score)

    original_controls = load("sealed/controls.json")
    controls = copy.deepcopy(original_controls)
    for name in CODE_PIN_FIELDS:
        del controls["key"][name]
    # This key hashes the scoring object both directly and through the pack.
    inp = scoring.control_input(root)
    original_lives = dict(pack=inp.pack, reader_keys=sorted(inp.keys, key=lambda k: k["item_id"]),
                          events=inp.events, now=inp.now, scoring_sha256=inp.scoring_sha256)
    del original_lives["pack"]["controls"]
    lives = copy.deepcopy(original_lives)
    lives["pack"]["hashes"]["scoring"] = pack["hashes"]["scoring"]
    lives["scoring_sha256"] = sha256_canon(score)
    controls["key"]["lives_sha256"] = rehash_projected(
        controls["key"]["lives_sha256"], original_lives, lives)
    controls["key_sha256"] = rehash_projected(
        controls["key_sha256"], original_controls["key"], controls["key"])
    controls["digest"] = rehash_projected(
        controls["digest"], {k: v for k, v in original_controls.items() if k != "digest"},
        {k: v for k, v in controls.items() if k != "digest"})
    pack["hashes"]["controls"] = rehash_projected(
        pack["hashes"]["controls"], original_controls, controls)
    data = load("manifest.json")
    for name in (*CODE_PIN_FIELDS, "controls_key_sha256"):
        del data["pins"][name]
    data["pins"]["scoring_sha256"] = rehash_projected(
        data["pins"]["scoring_sha256"], original_score, score)
    masked = {"sealed/scoring.json": canon(score), "sealed/controls.json": canon(controls),
              "sealed/pack.json": canon(pack)}
    for rel, raw in masked.items():
        original = (root / rel).read_bytes()
        entry = data["files"][rel]
        replacement = dict(size=len(raw), sha256=sha256(raw).hexdigest())
        if entry != dict(size=len(original), sha256=sha256(original).hexdigest()):
            replacement = dict(stored=entry, projected=replacement)
        data["files"][rel] = replacement
    masked["manifest.json"] = canon(data)
    return masked


def host_free_tree_sha256(root):
    """Hash pack content with code pins projected out and logical world DB hashes.

    A DB header records the writing SQLite library's version, so raw pack hashes differ
    between hosts (#327). The stored DDL text and the export do not, and the manifests carry
    only those DB hashes.
    """
    files = manifest.file_manifest(root)
    masked = masked_pack_files(root)
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
            raw = masked[rel]
            data = json.loads(raw)
            assert canon(data) == raw  # so hashing the parsed manifest hides no serialization change
            data["files"].update({name: dict(world=digest) for name, digest in worlds.items()})
            rows.append([rel, "manifest", sha256_canon(data)])
        elif rel in masked:
            raw = masked[rel]
            rows.append([rel, len(raw), sha256(raw).hexdigest()])
        else:
            rows.append([rel, files[rel]["size"], files[rel]["sha256"]])
    return sha256_canon(rows)


@pytest.fixture(scope="module")
def t0_pack_build(tmp_path_factory):
    root = tmp_path_factory.mktemp("pack-goldens")
    result = build.build_tier("T0", root, harness_artifacts=[
        dict(name="hermes", version="test", sha256="a" * 64)])
    return root / "T0", result


def test_existing_pack_trees_are_unchanged(t0_pack_build, tmp_path):
    root, result = t0_pack_build
    packs = result["index"]["packs"]
    digests = {rel: host_free_tree_sha256(root / rel) for rel in packs}
    # An intentional pack content change updates the table from this message.
    assert digests == LEGACY_PACK_HASHES, canon(digests).decode()
    for rel, identity in packs.items():
        assert manifest.tree_sha256(root / rel) == identity["tree_sha256"]
    # Another host's SQLite writes its own version number into each DB header.
    rel = sorted(packs)[0]
    copied = tmp_path / "pack"
    shutil.copytree(root / rel, copied)
    for db_path in sorted(copied.rglob("*.db")):
        data = bytearray(db_path.read_bytes())
        data[96:100] = (int.from_bytes(data[96:100], "big") ^ 1).to_bytes(4, "big")
        db_path.write_bytes(bytes(data))
    assert manifest.tree_sha256(copied) != packs[rel]["tree_sha256"]
    assert host_free_tree_sha256(copied) == LEGACY_PACK_HASHES[rel]


def changed_fields(before, after, prefix=""):
    """List every changed JSON leaf using paths relative to the file."""
    if isinstance(before, dict) and isinstance(after, dict):
        assert before.keys() == after.keys()
        return [path for key in sorted(before)
                for path in changed_fields(before[key], after[key], f"{prefix}/{key}")]
    if isinstance(before, list) and isinstance(after, list):
        assert len(before) == len(after)
        return [path for i, (a, b) in enumerate(zip(before, after, strict=True))
                for path in changed_fields(a, b, f"{prefix}/{i}")]
    return [prefix] if before != after else []


def test_code_pin_changes_leave_masked_pack_goldens_unchanged(t0_pack_build, tmp_path, monkeypatch):
    artifacts = [dict(name="hermes", version="test", sha256="a" * 64)]
    left, result = t0_pack_build
    after = tmp_path / "after"
    original = cache.code_sha256

    def changed_code_hash(paths, **kwargs):
        return sha256_canon(["changed code pin", original(paths, **kwargs)])

    for module in (cache, scoring, build):
        monkeypatch.setattr(module, "code_sha256", changed_code_hash)
    build.build_tier("T0", after, harness_artifacts=artifacts)
    right = after / "T0"
    files = manifest.file_manifest(left)
    assert files.keys() == manifest.file_manifest(right).keys()
    differences = {}
    for rel in sorted(files):
        a, b = (left / rel).read_bytes(), (right / rel).read_bytes()
        if a != b:
            differences[rel] = changed_fields(json.loads(a), json.loads(b))
    expected = {"index.json": sorted([
        *(f"/pins/{name}" for name in (*CODE_PIN_FIELDS, "scoring_code_sha256")),
        *(f"/packs/{rel}/tree_sha256" for rel in result["index"]["packs"])])}
    for rel in result["index"]["packs"]:
        expected[rel + "/manifest.json"] = sorted([
            *(f"/pins/{name}" for name in (*CODE_PIN_FIELDS, "controls_key_sha256", "scoring_sha256")),
            *(f"/files/sealed/{name}.json/sha256" for name in ("controls", "pack", "scoring"))])
        expected[rel + "/sealed/controls.json"] = sorted([
            *(f"/key/{name}" for name in (*CODE_PIN_FIELDS, "lives_sha256")), "/key_sha256", "/digest"])
        expected[rel + "/sealed/pack.json"] = ["/hashes/controls", "/hashes/scoring"]
        expected[rel + "/sealed/scoring.json"] = ["/code_sha256"]
    assert differences == expected, canon(differences).decode()
    before_hashes = {rel: host_free_tree_sha256(left / rel) for rel in result["index"]["packs"]}
    after_hashes = {rel: host_free_tree_sha256(right / rel) for rel in result["index"]["packs"]}
    assert before_hashes == after_hashes


@pytest.fixture
def copied_pack(t0_pack_build, tmp_path):
    root, result = t0_pack_build
    rel = sorted(result["index"]["packs"])[0]
    path = tmp_path / "pack"
    shutil.copytree(root / rel, path)
    return path


def test_item_content_change_changes_masked_pack_golden(copied_pack):
    before = host_free_tree_sha256(copied_pack)
    path = copied_pack / "sealed/life/items.B0.json"
    raw = path.read_bytes()
    # A single whitespace byte still changes the committed byte-level content golden.
    assert raw.endswith(b"\n")
    path.write_bytes(raw[:-1] + b" ")
    assert host_free_tree_sha256(copied_pack) != before


@pytest.mark.parametrize("field", [
    "history_set_hash", "world_hash_b0", "world_hash_b1", "seed_hash", "c7_sha256",
    "c7_entries", "scoring_sha256",
])
def test_manifest_content_pins_change_masked_pack_golden(copied_pack, field):
    before = host_free_tree_sha256(copied_pack)
    path = copied_pack / "manifest.json"
    data = json.loads(path.read_bytes())
    value = data["pins"][field]
    if isinstance(value, dict):
        key = sorted(value)[0]
        value[key] = "0" * 64 if value[key] != "0" * 64 else "1" * 64
    else:
        data["pins"][field] = "0" * 64 if value != "0" * 64 else "1" * 64
    path.write_bytes(canon(data))
    assert host_free_tree_sha256(copied_pack) != before


@pytest.mark.parametrize("rel,fields", [
    ("sealed/scoring.json", ("cases", 0, "item", "prompt")),
    ("sealed/scoring.json", ("evidence",)),
    ("sealed/controls.json", ("arms", "no_memory", "items", 0, "score_milli")),
    ("sealed/controls.json", ("key", "lives_sha256")),
    ("sealed/controls.json", ("key_sha256",)),
    ("sealed/controls.json", ("digest",)),
    ("sealed/pack.json", ("hashes", "scoring")),
    ("sealed/pack.json", ("hashes", "controls")),
    ("manifest.json", ("files", "sealed/controls.json", "sha256")),
])
def test_projected_files_retain_content_and_stored_hash_changes(copied_pack, rel, fields):
    before = host_free_tree_sha256(copied_pack)
    path = copied_pack / rel
    data = json.loads(path.read_bytes())
    parent = data
    for field in fields[:-1]:
        parent = parent[field]
    field = fields[-1]
    value = parent[field]
    if isinstance(value, str):
        parent[field] = value + "changed"
    elif isinstance(value, dict):
        parent[field] = dict(value, changed=["content"])
    else:
        parent[field] = value + 1
    path.write_bytes(canon(data))
    assert host_free_tree_sha256(copied_pack) != before
