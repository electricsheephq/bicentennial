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


# Host-free tree digests (host_free_tree_sha256 below) of a T0 build at the commit before
# card_t2lite.schema.json existed.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "cdbf0970ca61eccdaaeec3a09705d870d041d822376df27a8a8960361b58934a",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "66c333e80f43aa3a1fbb85dd44b3a62dfae28f6de5f8d79812d7030ba2ff9a59",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "3b2aa2ff36260c0f206dd83ff4f12d70d040450aff2f540d8a3d490828421a18",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "40eceaff9609e01a3c4df8711651ff13f9a5bd27ca8c44931b47d44baabee962",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "21d693c78402bb1d16888e56d3ab2f872af1fa5218bb8c0b1de22948c27b62c5",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "997311f4f0db7a977e7f27fc91311188efe68c60f92ee631a433af3f36146329",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "c58696eba2ee60d793cc5e06abc8c146291b8424ebbab0a54e2d8e01bad3c246",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "0e1f5a6448515bc861e43fb157e564914c784c16e3182e6350a2b870d9731445",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "24ab3aed9a20800e7a3c16a0bd057eb59a5c214f0daab2df5fb297bfa0b592e4",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "b841d26136818fe87b943f1af909494c16da403915d5cbb2181829eea433f545",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "5087c011f260a115df4a68dfc2577f499fa83b471566f6573c79ca4dfc26a28b",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "18f22e7b265549510356737d61f7891dc374a80f9ea89511ce3e94c12793cba8",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "d7e185e49395d5f590f73f891b16b5190eb223782bfa9510a7a1e9b3d456d297",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "f7e2458bbc37edbdf6a6a8ae5eecf75805ad4b845c90f4d6d4349087e1d72d75",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "6b1f1961be063286b0fc4f4088774a02ace11c3f3e11b599941c99d171fa041b",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "42a34a6fd03226dcc26a03ce0523def5d8a1fd05db5aea716c0b1e7aab84c999",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "7a3b4714d23ec594f876fa811a94d7eb143912f6d7560158f0553866b53678ac",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "b8fd927dc39a853d571d1dab2620c8753f450a33119a384a6461284763685f5f",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "42cd37fc81b5fa00f2e045469fc64becad88c668583e33722ee2208b5902b7b2",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "48ea8479f537aaee4ec6786cc08da08ac562464905f8ef64a98bd145a1d4d7af",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "4f10e1567c2a5fa39a95688f270801cdc2c00517e4924ac97654d1db1c121e6d",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "3783f4de9b92499889e1709ffbc732bf0119972bdd426b75d9e138eb03bf872a",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "d81fd8ed27509524fb12563edeb1827f5a5e77331667140442e47688d4bfa4ac",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "fb9cfbbfb28ec9cf3c5b80037effddf60b89903961642b180231a28a98c54b1a",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "bd3983765976971a1cc9f2bb32cd4a8b994d6eb5275c39069743d47e6add3e25",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "d338a99e6f468c09c79a1728106eb0fbb8b37b101c3b43a6d4ef883db1ac8b2c",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "eb8580e29dfb71ccc094e8dd966dd38045135f1a46dc81c8af1791378614412e",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "3b6143efdbbd6112159e19af7a5bf2c14c5ce93bc55e7a23f9a1d4adeab0dc57",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "ce76aff9beefc560b9484d36c19ecc01c5901af3992a90ab46a55d8084c5332e",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "8ef0a543bac4fe48974d808ef671e23c0e1366d1a3bc1320ef7c3b425aa17924",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "5d923436335a7393e770de9aaf1de8b61b6b151f4645f486c8c7451b68d7dfd0",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "4f07b1676bf754baf3147b775ecf74d150d72f6a601ef83da45664106e345c23",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "1baef56c70163a430681f5a00b2cf07d97b182c1f8aaab9c46202e97ebed4d8d",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "21afa29a6055ea57b5cd56ec81148e010e9ee5cfccbba1c82a7904f2ebe66cd8",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "77bbab29b017e1da7b40c6c58fd5305fb3255d931c86320849c67777f37cad71",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "749d470424679f6e9bfe00ddf7248fab0f9f7abc5dcb3e20c8c6bd212070cbb1",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "061bd6c4bac283a2d6a68573c8b60d62283ab435a561f75887d03cf5a4921200",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "3f4bb8bce77ade89c9bc149a0eaa17450688847f0752083d1542538fcc5775ac",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "511fc1e8fc27eaac55a5b317faf175ab7ce4f03778c9390a81e2c70dea7fcfef",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "9cec01e70f067da65cdd20499d1d53927f30696bbed84c38e3f31984dc9bd95a",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "48efe34c0d20ccbc3b49305866cb8224c81a905cfac6969f332e13082e38386c",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "4a1e22ae416b0ea603bbd84baf7f5f0d87719ba35153ef846e9d34c51f8503bc",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "9466fabde57e6540bac31adb183b10f85f81b6eb0629ba250c9125b1871d7413",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "03c6b4edae6f8d7b46a0d1e858a5d1c165e55552e4b7bc5570d867a3b771c898",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "165a707edb12917cc3d73b2cfe6032f1e7814b971d594782ae295be87e25b1c2",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "45b14e63bceef84d4108d3aadba53c7e0cee60058a50d98f50d937660d7882e2",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "40192ce2c493d5161bf0f5cecec0808641b788f8f94d86ca4a102afb6c8df2a6",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "abc1f8adee6f5430fd95b15b3fc253506b5fee5e5a20cf64d873317f4efff4e4",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "ca8ff224e38279454154377bc6c20d4162e6da0b915293ef6e869f9f07365f46",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "2d55767dec8afe043b5ae596bd04418bb9232a37f728ccdc93b1030689a28dd0",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "badd71a3e1d6dd1e6a1ba18e0bdd01fe18c5fc441152d9df974550a41547fbac",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "1934f134834f4b0cb99d6031be802e96e1f11ed656721dd83fcd849bde41404c",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "0df35e09f9d781dd072d0b43b9f9e2046099e6e56eda64eda939ad51be7dd5a7",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "7a823f49c9dc96f9d673c3ba2e452636fbc38274ae85e025bc9a020d35541422",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "a382d6cdfe93a3d847f03b4c4c501c9d0a60f82f960f2ab839595eed0a93e9f7",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "4c0fd09fbb3079b8d36b229db1fb20e0f022a7e5277d03952e244cf5001152d7",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "5e051d304b8b2e6e22683701334f7f912abd9ae026dd7d02cf310a264b40440e",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "bc81c5bcdaa9c04fb0acd46e6d7cd6fb56f8bed265461597284930ce2976c10b",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "970e3586718795c6c61a0157382c12f4148df1b59e924d47ff0218ecef09c419",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "e81274536035e7c34a93c9bb02c2d220a85a083f420e4f796657f77c9c13382f",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "9eeb29b1651810cb4803a43eb469e517a673df4bffa12809ed1ffd0e356d5a1a",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "fd3922c21038dde6619fc6dcf96f7dab0cd3dc7f6f7d6d0866f1e2c1365aa1c9",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "1e6c041e2709e64203f270889a7f3e7f743b2489a101ebeae494f61b138ffce3",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "eaeac8f69b5522da925dd774dcc2a908cf2d1c08a9d73abc31f037fd40dd9a04",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "fe33ec2ac9bebe79e1133ccca20305230fcaa155333d66545a76fcbd1f527ee6",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "ddea5b75677439ca2366152c9816a24479ded7b52417fe97014bbd9cd5769cf7",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "282dc936560cbac5653d71035322392771ed1e116bec3d9c0182bba744fca493",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "61487a9309564b9a90f4d459160403dc4bf6611b24702c94d651d9bd5bc9c940",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "0085668f68ce4b12658d629581546bf7c83411a35427475e6c6f13fa2e2187bc",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "b9b5dfcdcdf61de4e3f0be5bdb91a2e7e619751918d3313309fae961474bf2da",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "be9f42796cee9d80782eb6e593bec672c8fc45fa76bc9460cedd90a1995ebac8",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "9a8a64a0fcc428291c22bf5c1dd85b5ebc5f062659802d93222607d26e9cb991",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "27b19be31b8fb271045b3023ee1e03a4d7b10dc691528f34ae2afb8f831e29ab",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "add6425927a975c08ce946763c53a3dbd60cef6e4d7782ef5a8c7dcbfe023b06",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "eebf942aefa7aff053c2f252c5114c3d809d2809cd8fa664246732059b555b96",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "24c30a63e9cf065f7cd68ef6f5f908673341311f2fba9b3e3b56d76d9e714425",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "6e8bb18cce71eb050f8e9f9ce23be2dcc366ef2aa3a4e75917fc63ef36b24811",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "280cdf85bc3c9bff86cbd07dbf66b758356cf5a59f3298c1ebae7c69c2d3eddd",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "bb399a5ed2f9187e64c6af136862a3079b9a2253009e5a7143de0db4410684d0",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "8beda922c1873cd4cae19eba20313eafad9f338024c62b8b48110ddbe32eaac4",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "27d317f5112c9067c1b6955f6b6084c4dd407555d1f0cccf1978cd1bcb108e80",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "b779e3a25784aa3b557a092405fd41497d2358301c0a268f2902345f280c24dc",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "7c34f66b2c20d6bb2954a8715047b90b7e9f38fe1d962a70feb6028ebd9e176e",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "1fe6d9eefc90a7ce673503cc2f7ac82e672c1967a62a504e95f5e0a89d69d9ae",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "b9ad3ab97e53b9c9bcdb94a74468d59da760ed800a49c4ecc8cb2ae40cfbae12",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "37229b2175a93b36c1f91a139fa01cd04a330d5c0b923c5ff4c9ea110b4eaee8",
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
    assert {rel: host_free_tree_sha256(tmp_path / "T0" / rel) for rel in packs} == LEGACY_PACK_HASHES
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
