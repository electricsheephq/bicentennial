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
# Intentional content changes update these from the assertion's failure message and are recorded in
# prereg/CHANGELOG.md, with a RING0 erratum when they change what the kit measures.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "15dc9abc9076cbaafe311b954b1e20c67bbc0455fcff38f057ed188d4f417556",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "454b066e16f23ecbda2ad7842624fb6d55272b3a261a7fb3d12ab0c3ebe74501",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "02e5c067f7dad28227ed4426b2db01e5ecd0c84d2d9e24e200071376e155ff1f",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "5f933becef1da13f2bbf8e1a62a5bde048581c972a0df8d68fa299a98e57e410",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "4a5820eccb80c3ceb0b79f601dc8e8ca8871fe6d914fa40cc5e13d1fe2917e8b",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "0ff4970218ff2dab6081028cb6629814d62502d8186fab94f71ffbf063ac0251",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "bf094057b4b3550be281d86b6c1a5c9ea470af99c8b6ca27837ffc0a8bf8650e",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "45af038396c8eb0be3f0ecca5e116b6912ff774b3b99b8ea377040c99f82506b",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "033245cc6850c9bebd71c7909a75a9eeb543c9637cc03fdb0ef3fb0f0238a205",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "f5fd2550e774d7236f4fcb49898638d6c4caba00193faf20f08ae81fa1cac816",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "63eabd5643ef12de5d893bdbfae10b398bd305ede776a5da0c2f2c08b3973a41",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "fb02dac818627db33ecfd5f32043f71820a48f263a963eec0997ee852a8d215a",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "9f56396a2a389f8d5eb3032c2bd8ca4bce340262691876ff1009fc47d824224b",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "ba530164a145db3eb0de06a8130882daf0ac292a80285701a58430efb242599b",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "a9fdef3b1cc02cc7ec5e8f2a448a41c4a52291a0c4d0d8bc6f4449342381dbde",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "35f6281b9b653c64f9626ffaba8b4b7eff6160623833b11f28017a91b520ddae",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "252b9f1bcfa0b1ddc96213440ca585b687e144340d4c7942501b738a3732112e",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "127e88038c89190ff8605d9c7d97103cec25db6bc39e8bc5d4bf9a76f95da5ec",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "c9240bb094e3fd76112c7f5738ac66d4fa348e12ca239c79a356ccac7e47bcb6",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "305f44565d0dae890e18cfaa5e16ff2b5c471b6dd92e761888674fc8f7916c51",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "ea8ada1f94703b04522b77763c93d184e3320b151302c0afe455a4a1ff6dbd71",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "1e2d4779d5e227cfdd660c08188af12668cd31df786d82c4593b783226b6eef7",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "de39be7f49f09aa7aa30e421a424ca7585828aa6d1f94d6a52b2688da79d635d",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "a74dce2bf006c7b86711da0769cb325bd4271e219d5f2b31b36b46548bc627d0",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "5341a7273747120646e0d0df5ff132192794791c8d41ed09cff6e74427c4aa43",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "61780e9eb616371a7de33ba8d52077e49b99d2f57c31f9b3c09b320661cbda11",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "0412b7d843bf3e446b33a13506b9202064f358edd157a38ac8ea1ff614338012",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "8f10c8e268ad5efe87011faabbc0fa6af102c02cb07b79f807a9b2268c2dfa4c",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "77dcacbb9efa4b9aae21950ca8a9103ab5c979b0e57c53d8f5bc778a79dd058f",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "1ab6a9f4f4817fad67910a3c6472c88e3a03f6a827aee7816dcf31efdb578872",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "e32fa8364519346e969b1520f5003c1059dedeb9188cc2cdb33a5db9e8cda4e0",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "9ce2b91ef4d79c07ea70e9736b5940de5baf22d6ac75ec42ad870c99adeda050",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "0bfc7b3133831bb5e857627909a5bc4e632003daecf5918e50707e37278dd57d",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "8676494957e1e1877323807044e3236b782d957b42619a63b27607c7e3cc34db",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "1f0777d6f5259edd527b66ccd9810dd0badfc5167b83e49405961b3193b6bb1b",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "f2f7029152c9dddeaf0cffade4e941117ddb1ff6aebd37f493fc00f851ffa5d4",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "744e620796d90f10f0a78221818ec0d7393f5ab7a007fcdb24f0883dca70e8b2",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "a0e0134878386617b84df5526652232d2613b80b19f30752f46bec06e866a59d",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "182a65cd9837493e32fb5bb63acb5513ce11f3c62932f799ffe1d007b78cd249",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "7f2e99a69303850a26ee1496d8f8bf8514a04fb71ed7a32c831e454ac9ef9c31",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "7535d4cb7c209f39f32abb3b57f2191b9d14f9a0291720e77d6d1a60f864ad73",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "9d6c2fd3255a1626a75bb09ffd610716b97549d38e0b5f696da4c3f9d2838ace",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "c61f31dbf7e3be7f05f7cc9762bc1bf194edbf823a77ead6323064ce1e62cbca",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "1b0740172f32e1c6183845d6a521e8e2bbfd827d91e75e3036a65bccfac5a3ee",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "61162870b0c961cba860ade398a414501a0c1ea20b4fa93ac5461d6d84c23ffb",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "945d15dd240921c8eb34965700bf3117d41f0af7f3371eb513ca7cc21d8e6eda",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "d81524437a70d1077d13e375869114b152c9288139bc12c250aa87a1fe7948a8",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "3fc08fad274a1caf15f1036f15819ad1ab317f46fd3f406e5dbd7f5dc16f39cc",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "29d7e51dbd381e722fd20e2cf9c04b5ca7dfccb6998dce59efe354e45b4e02a6",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "5bd2d37200215bb26ae7c96bb863c9835298353dded85a2b817edf545c39eaa3",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "9fb78fcf8bc2acf02bd53e8ff59d6902477477c88452695e8a61de538f805a5d",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "8768c0b83e1744ba182189428f7e75e7f5359727a0c47d4d1559f3e77e00e571",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "cdc8718f67353699dbc55d45cdc37c3c203181ba57849b3e410f4f527515ef28",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "36bcce00a9dbc0a4e321191b8dcc76aa9d18c9914da206368bf2220d58f445e6",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "8ecd7034a6c61dee3296b6f66c24aa64741177b552a0eb81410cabd37a7ba9fa",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "7a65b2bdd3aa6c78125047f9d5ada989b084bef6988a7e3191c718590133950c",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "bfe8ac821656016da103c0d42226e0b9df797a0047a54d284aadc7226cee50eb",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "cae534c225f780abae6edc5330c283548a565c832da3d55f305b31f866d33d4d",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "1aec5fc6ed67c88e8735e9f0e5b2e37f87ad6e12cc2b8c1e23f9cfaf781866d5",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "31f0706a787282053ba11b461eacb2735df9b3bb610e9d932f32f0578dbf1153",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "96ed4cc731453552f689082d6d203479a230f28153161934187934d2a48e98c9",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "a2a5e113a08d594e00c82d588d2c970c5b771b42c4dc4d00daad42916ec8c7ed",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "ed98e0ab6ec37e642c6fc1ce56f1abd52da527a75451bcd50b96cd6fe860c07f",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "7a97a9b2661a348d6c84331fb41d582f252f3356e2654a04d1816006f0614be6",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "042d4bed66d006380f8721337a4a33d6bb2ef21a616db4a48cdf7627585d5d68",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "71564ee57313d8923b0f6db58bd5224fc812360faea00bd7cc3af1b3807584b2",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "521e774a905ff2c39344d529cd438ab9540ea5752fc9002a97530c8967eda6a6",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "b4116669f6e7e7eb0511e9e94b8e1984bf291242300a208cece5c16dc5d978cc",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "d1cba7ccaff8f769fb08698a4c87f47eec0289ef193fa195d8476684ea49f96c",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "6162350a95d300471b0395fb33ba6eeb2ef140ffa2a5a121d697e9495f13fed1",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "72b07c452fc4fabd2bd91f3d4e741fdd55c1d9121923c9b5083ac0561188708d",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "6b24e8c082311d7843fdf00b100509109b7ef41be064030d97bccfedadb9b053",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "844f174d7343c6358f289122f7ac6d9dbcccf508707d7e69d6c24d5fced8214e",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "7bb38f6bfe76b08066d8c45175228e90ba85c10bfe9063602e102c7ef289d7e8",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "c86a53b01c2ee54514d5782ec4046087ed525bf2139426e4d8d4c799ed6c41b4",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "53b165da3a69755f5b4e1ad670ce0150dcc45628c2f56fd9943e59dd05549982",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "3d5c10ac6c78a9cf2934c0a81d3b7cce28482410ca4888f8fa605e1c16a0411f",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "23982e0b68f06c43061dc7022d38924d8b2f0db67b98c79d95966d4f28b4edd5",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "96debb36b2ecf363b4c08fe20bd9ab562e735065c91d778ec0d1655df05d0111",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "459153ca9d568399a3b50f24beb6ef901f3bf861ae73ce53d561f06f186ecfba",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "69f6fce49444810db43c02a84f4de751503b777814cb6b0d2ebb584cbe5621d0",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "35b15df96083678e0220ec6cc310b972b960baa8925535fae8c3a885fc4e2b31",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "244a43d450a9327300940db32fcdbdfd51ca399fdfdb3854ce512edc8686ac6a",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "1690073c07c6cefd08c0613057b9168bb7389ebacae169a3c9388469ee82fbe4",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "d9f0c3ac5bbf62ff09f2b04b684c7098ec4afccc61334e1aee92abd4be5e1ecf",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "a5346190167c1736eb4bf10d6014ad38bbf3d9eb4b0db4c0eb181c4aafade2dd",
}


CODE_PIN_FIELDS = ("scorer_sha256", "controls_sha256", "reader_sha256")

# The four code pins at this commit, kept apart from the pack goldens so a pin move shows here alone. A change that
# moves a pin updates this table from the failure message and says so in prereg/CHANGELOG.md.
CODE_PINS = {
    "controls": "4bc303193bdf7fad2d87b16707195e3c98375e969ce8de5aa03e580260650b6a",
    "reader": "90ed83e9bed4b80088108199d2434e03d078a2995ca6eca9023858125eb6835f",
    "scoring": "925f3fc812fd80974eea1780b359b58bbcd5f35c338b1f2daf710e6adfe49880",
    "scorer": "e4a37d895516e1654401877897164a71bda086b715b03bdb4ecb6ad79328aa49",
}


def test_code_pins_are_recorded():
    root = Path(cache.__file__).parents[1]
    scorer = [p.relative_to(root).as_posix() for p in sorted((root / "score").glob("*.py"))]
    pins = {name: scoring.code_sha256(files, root=root) for name, files in (
        ("controls", cache.CONTROL_FILES), ("reader", cache.READER_FILES), ("scoring", scoring.SCORING_FILES),
        ("scorer", scorer))}
    assert pins == CODE_PINS, canon(pins).decode()


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
    for name in CODE_PIN_FIELDS:
        del data["pins"][name]
    data["pins"]["controls_key_sha256"] = rehash_projected(
        data["pins"]["controls_key_sha256"], original_controls["key"], controls["key"])
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

    The builder now normalizes writer header metadata (#327). These legacy digests
    still use stored DDL and logical exports to detect changes to world content,
    independently of SQLite's byte representation.
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


def test_every_pack_carries_the_recorded_code_pins(t0_pack_build):
    # The pack goldens project these values out, so each pack's own copies are checked here.
    root, result = t0_pack_build
    expected = dict(scorer_sha256=CODE_PINS["scorer"], controls_sha256=CODE_PINS["controls"],
                    reader_sha256=CODE_PINS["reader"])
    for rel in result["index"]["packs"]:
        pack = root / rel
        pins = json.loads((pack / "manifest.json").read_bytes())["pins"]
        key = json.loads((pack / "sealed/controls.json").read_bytes())["key"]
        assert {name: pins[name] for name in CODE_PIN_FIELDS} == expected, rel
        assert {name: key[name] for name in CODE_PIN_FIELDS} == expected, rel
        assert json.loads((pack / "sealed/scoring.json").read_bytes())["code_sha256"] == CODE_PINS["scoring"], rel


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
    "c7_entries", "scoring_sha256", "controls_key_sha256",
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
    projected = masked_pack_files(copied_pack)[rel]
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
    if rel == "sealed/controls.json":
        # Re-seal the file's own hashes as a consistent build would (controls/cache.py), so the edited field is
        # the only difference left in it.
        if fields != ("key_sha256",):
            data["key_sha256"] = sha256_canon(data["key"])
        if fields != ("digest",):
            data["digest"] = sha256_canon({k: v for k, v in data.items() if k != "digest"})
    path.write_bytes(canon(data))
    # The edited file's own projection moves: a stale manifest file entry alone would also move the golden.
    assert masked_pack_files(copied_pack)[rel] != projected
    assert host_free_tree_sha256(copied_pack) != before
