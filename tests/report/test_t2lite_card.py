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
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "1e01d1625011b008bf418b759f8eafb680317549769ad544340a936fb03ce93d",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "2acf8bd5d924bbc95c65118405e335cda6121cc1a9be647af2a50546b9f09464",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "ea57693f75878e513b3efc50c88e822ea1c9559c9efae1514d7919263cab2dd0",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "6883f78a8c12c8f3b6afc3dd14db742d3f213e71b23a8f2408d446d78f55b188",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "91deb20d7d5dd458586a45ea4f7201e620b8df2599b65cd965a811a71ddae40e",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "099c5c0f2414d7d91d593cbd0d352adec0442a1f771f3ec1303ffc1cdca094c7",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "ce549975107967273fa5c8fcc43a04593d31013fbfd704c2160d3d82851e0bc1",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "8b4685cd03bfb46ae68d2b293c80f889185eeedd82da9a9df7890b46c059467f",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "b90171263d5f9473e3babf78ab85bf06df43200a7fa77d51273dd0f13c5af4b7",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "a4418240c5243ace879d4a3110da2daf94735762a9453ddc5515f08d694c002c",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "a83f6272e7c28dddab63982a2cd3530e3fc0d0a947af5a0b8655b1e01e8e75d0",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "8043c2e1f294a3709f309fcf170380f202ddd3fd715f259149bba2485775adf5",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "c2c9e71143c35027ac71bea311cf03f630f3825a407357f180daf6c14f235b42",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "2bbe29423852bdef212db7376f0dc746ba5ccf18dc6ac5e66d80014102c2f669",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "b4690e1de5e8c9ffc855ee0f3b4b2bdcdf7d3b4ce4e286bc147931d7c82e9a44",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "98b74445490a76e13a99b897ecde531f4c64070da985e71c5eabd569c445bafb",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "5ae7e5d11b54ebd8bde69e9110452a47cbd8ad587e58a5443db7fba98eed29d6",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "c0aa447aec3c423f66b3c1f15088c190cc3e2f63a842d5982b658e6a06915102",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "a4e9b0d8de8381c26e1ddc4de99eea75ee0e1c8244057aa88c9458736d6a658c",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "9080ca40272643b7c532272687023dcb60e2a9e120b2b3b6c629677acc3dc0dc",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "b2f6c0da41bd00dd20635087b8fcd28aa9aab4c0d984e3499680c00903813a98",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "184900bd22b1785abe91582fd43375e8f8679b7d58df6c123ca1a81a33153b1a",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "3ff5027b12545288f0f30c9b84110a1f078ac39447647811b02ec0de6a1738ed",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "718eccc1d091cfcd46a378520075f3d56c33c80f9f0d2c9b905a7e9878b35c42",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "f9fe0d69526bdcc6ea4990bca8b6fdbed8f70e7cb70d2597a8a36c0588f5a0a1",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "e5d30797776c25df9860216424430275df23ee431622fe41858820bcb106939b",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "1ff3abde8c958488aac06d407741279c2f28febd536006eabcefa3d946ab128c",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "7fb8a4b0763435faa7eade3485049cc7de983d59d750ca84ab42e395e77befa2",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "6d526ded1e3889a221881bd51363c7b8535e552cf80cffefadd124269ce057ee",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "f693736ab9e0ff974c77ca63e8cb3f5e9938c321259ffc403bea88460cf77028",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "281935c52a2a702c8ac342dff073df33b6e56f03f44854522d46264b86a803f5",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "f0893d699536163fba057ad4dea6596c00724b40f76cfa0fbd1e88aac87cfe2e",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "17b93322dca33c124dcecb43bc4b56eaff88596f5401c03c8818436b711798b1",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "fef9a022bdf1d93a5c3e44bc2dacdd33e157f8388c7971cc53eae92831427f2c",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "7938e0e101a063b3236f684777559ca6bc3e9bdf2eb6757a2d66ad07e30c2345",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "2411fd0e40c1ccc7c8be7629627348812a396b373926f0d0843407a5651befc1",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "8616ef11f9ebc64b4c66f85aa135c6c5165ed03a21f9bc98acd76c051a16989e",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "bcc50c236fe7a41f994cb02211dab89d45533339ee4e05652dddbecc0db654a5",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "30b403968986a16646edf25e6acabffc2ce6461215f01e0959ed9168fdce6789",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "6e1e9e8cf212f8457168d130e77cff32992ef21b53cc36a40d04178d4d2a3f87",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "532bb35c70b0f72cfc53840d529d3fdeea7f098d84e65f789407491f0c058cc6",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "eb278c85755902af675c8ec60e92be6c39ee24defc50335bb830dfa6c9db7fd5",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "0a6bb96918d101586fc79a923aa9d93502155963afc70dd3c6dc87162a9323cb",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "77cbf7570270f803ebeb2a43b7910982d51b3b4ffa8a4cceba333c3115415cab",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "61894a0d20a5c618d6979b096fa78980f4e39b84932f6d9e2acd5f66926e035d",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "d72da78b50ef94bd64666d4a46dddbedf93d5f82f516e8dea915f536eb1bb303",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "d0e0ee978e30e7b42ade13b546c4d07725c6a9a4f7c45d7c03f51df6ace90740",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "0cb5c4d16aac95f53054f792eaa1284ec9251ffc6ce0e4bd215d648a7f20a943",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "87c74ac8804bc9f4146b3cc462f5d225c3f384d696f027c7056aa8fba7710ec3",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "d7c090b5b89b0e8722af83e3e235333136d15061481d184a0c587b86e1c7e1c7",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "2d94e2983a859cdd8a22a1c17e2cf5c476e7926a4c487daf7521efb8bb97a79a",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "2a350012244318969d7a129a6d8ebf20c8f571f389b1d8c6196b3ad6626befd3",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "089a6ea4fdef44766b11e96b08084cb0afc9fd4f961c583e8ed47a008a5d7978",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "6ab192c422c61c69bed828308c88ac810b2ac2dba128733cc8e79f523035dc6a",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "dd4d37cae38a25d86b9018eca63d68824ebf50e5673c2dca96625695b9b53c35",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "6660348fe5f9b03059f575101266a26d6e4a2eae8905b3baf2fb7d3064059d00",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "cf2d0d56969538dbd8df7fd3038053307ef3dc6eb72f4061f17280b469ebd707",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "2ddc31533e45d41d4182df06d5b2fe51fcaf6d82c5f49ff584c3cabd5a0f795d",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "7ad115dacbad12e9f277840e8b292db0053f6ccb97fb61630f7111dcf7a550e7",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "b90c53f26592dbbdeffbccc59b941bdc974e43e57f042334739f6c380b4bce1e",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "7622e30f4a9b9aca09f3911d203e2e0a8ec4caea8bc445fdccbc4cd91fcce27f",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "9440a2ad38278fdab23ede0654f70da0850ea5f54add79c8fce9af10e51ce2ed",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "ace794e28d81b514c9d8ed4597572dbe565d415acfccd5f6385d646367203086",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "6f161fc9199471b9aeb7e6aa9b7dfcfb1cdef8bec69fae7fc62f56bd7645ac7e",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "1b547ddc642cf72d1bf8d927e07f315bcef00c4178adce064735176da9bc3f46",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "2c4c27d8855ff03663e017ea5f46231d5a66e4e07dd7c897e34709ac2455e5ef",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "9f03ba84f73303cad2ea3ed6c8dcf0c0d3f5b75af8769e6007cf8118a6ec4da5",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "beeabb26f6309a78afcabb47491a7465fab3ca99fca2653ab01f99f0768e738e",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "08630a75e2372c78dcfde6f15b91d0f99307563ea76cd7f7d5667c12174b320c",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "a05c56ed4bc0cce7f983e438bd52e459e9bc41028ff2ce15000069a919b719d2",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "6680d780a41b68313dc5181f161bc9d7bea4f5e9b3c28c83e7cc8dd88eab1deb",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "92bd87b4555f1f90fb56604f30855d8ea8c1fb0f3fb3074f73da7eae7455a8cd",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "ff5eecb96cf352d64a431f1cd510179428569aa2307ba1beabad782428914093",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "ed376f307753563ca13f3254951fb221ea18bab78eb38026f347f30b736bb966",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "d030ef9911667bcb9904646f3e8c24e2d3444c5ffcd64d6d42abc4092e12f064",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "20949cc93d5939c1fe5855c62b0f952effdc0b936b49908476425d807ff156a3",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "5eafa0ccd8625bcc921c8f87c94f711f7fe1bad14e0810528b0126c82cecf889",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "9bb16986136701af59632b2f938ab06b572d538d9963516fb72d3df069a3b668",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "2053b3b6c1c46448fd493dad547df55e8e7e5b9e4be07a97b232e67471259026",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "71987a6d161eaea386085a0f9c4f893d04bb6e0a40adac58cee212226a49a632",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "d5a33687cda995b2507def458e7d38e1b18731cbca37798740eb3d6ff88c8f25",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "9915966e06974558bdcd8d2857f6d9004dc54c3e6a935ce78f8c247257d1cfff",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "9c665e416ca85492ff317922734b3c0297c3843fbadc0208654c16463a4ae9db",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "382607bc9a11a42b36a14c9552d60c46d19279b4f83aa2877eac85b123b41855",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "3ba146d0277c0344c83e604ff9b63037dca853316cf854f5ef61b39d14fd7cb6",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "347d787e44eebf8cd984d9e1d709522501585f5222769d1135bbe5ed3d3e8897",
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
