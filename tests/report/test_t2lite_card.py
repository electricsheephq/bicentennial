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
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "2db1b6280eaf71a343eb0a8825016c8776f50d4b9a94410d6e95124f83917a42",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "59dda19420886eb5688707b140437bb20603a7991c7efe1f2da24c07e5f1e104",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "f5c20046dfb9ad2ec21d4b90318b21e4e99ae413212201c969adf7e074bafc1a",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "0bd59365073d6cb1f2ef2aab5f1b4df8734e21f544318bb6ab34dd98ae47b359",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "fd1fee597fc01e6eedb4623c12f79ff98018481be55c651110d19aafdda5cc08",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "84071f9ffcbb7dbb0fdac72f1aac7dde9feb2df10fd3734a3360a85a78e8b770",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "065f2082f966b58223fe6289d0d0666d284d52ab8f7b98b9f0727631fa7e3525",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "642f8624ac11633caadea8bf6983be1ebd0cf8f85b35b52b82261f7f85918828",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "6e6a669c1cd18d21dad73ae3139be6c9c96136be38ac80d2bf2169a77a3e203f",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "4c8d00ed66441efc92b056bd24bc8f0b373c7a5398944362045544619c8feb42",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "45ae17982b3072aa296740dfac13fbed761a242a1a7468b79645e8202a6c85af",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "195ae5bba6255f71ca1559065e1ec5125974c13eeb0df2bae3be1aba4384bf53",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "5b4604ae9c1651b87c657e62a7bfe9ccaea618fc11d1d55d7d57e0ff04581766",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "8768ab10312d3f6e3c3830b9798f661c11b8bc1c5689c6635f35f58433e5e7c8",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "dc3cedb0fc18929d78f884246fe6570a8444e759e19654d7c3f83a45f3a7316e",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "c4acc4904abdd9bab60cde8353d8462523cce790ec81d209a8840c841df5311f",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "6dbddbf9d8d7514736d0f1054e800f7793532d4022a6b2dd2161a25b4e428d50",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "831faa1363ffb10ab0b3c1c6bf248a36f610d04ca40b1492cf2122c16c8b7e20",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "7e9977793c7b1d212d1b1f546d076f8e74fc2d5bfb5b65f66fc77133551bbae1",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "4abd93f4b7a6a196db6fe58750741c276b90fa88dc257d3c25a58f934ee46e0f",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "0e0284fa306c174aff12c1567b59984c9211ab251376f3143fb72275e26e7997",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "19d22f84df1024e3c7edc1fce2e62297779348a265871f3bd5309c43c18226a8",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "582ce8d2e511d5a9deebdba083f4d5813f00862abc9ae64047865de6513a5556",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "c8172d84a7cf1db44a8666d7cca72e09c0acb57267ecf444aff721b25cd046aa",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "f61b1733c1d094d305a0f0471c46a5ce651cde991f3b6001ad902d86abc9c1c0",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "8fd69e0f914d235a7af82f4f332d4d99e4812f8beb06c7e43955f817d1281149",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "4861e8d1142996610cb081ad0f389a750f50105cc1bf5b38d84bde3baaec427c",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "5d8ac72d7d93e3358d38fca7158944180ce120b9b71aeaae0eab64eeb8998ed4",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "bfc92d6302e5ff1d64c75a3b5720a47d9d831a40e974e5f15e31ce4c7b7b11af",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "cf7b1b612a730418c41c70a95cd15b34934de9d46f5843f459a59e8e35eb935c",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "c900613c30c60fbc467830fca56b8f78bc66b5b99b7f879c8e2fab4ca749d22c",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "256d5ed89beaa48781de599ed7443e62f6aa3543e6559083d4dc3b06e052c869",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "a82db2be35d7588726325ceec9595d495dcac9585910c531a68135b306f85563",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "bb27e717b0ac7b57fa9dc1efee8f3baa360c4a601ca60963f2052afbb46e4b4f",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "b54110f52798c426125ddbc3ba4ef14c1de0f94054fc86e59af3976d727ce3b1",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "73a1f5615b1b3c3135a323b07b83f89f5f9a5c9b562f2090bb05c3358b31a745",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "d4a32e188e441060d332011edebb67ba82d96dd09c82e7c9ee580e29b9d67cde",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "844458ab10e172083627c889b386b2ce93a532e95898ec6031525c5a5dcde055",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "3e1de12c1fa5cb4a65a5702115e1b8cc330b8e90973324dc36ff7fc73eb52478",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "8b1af2dc9e7c921d816fd2542fcf5c6fd040e77606e4772970dec21d637c9cb8",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "52c1e81772e3f793a5933ea566b855d5740fd7280ef02892daa3f3ee435e09de",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "6e0dda9e7ea61b0cbab66fc0ef578eddcdf3ff3f47e3c334911097a7e32861dd",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "af22588fda1f70f6d124b06c8d6680ee11091252583b0fc57a47d71dd1afc0f9",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "b0dfe9c5afa0427c6ff59e0ff5bc4a08c268f617f70681806f8b83904f7e9215",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "b01cf07dece101cd3c76cced6ea17e1a3b19fab1209d2aa2ad8dbdc90dbde155",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "6c954bbda855c859365f89909c603daf6f033867cd97f3013adfd1befaede380",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "19b8fce32fc3f7f16f2e4bdc81e2c8cd0fab98e51737464d3abafb9d95df226f",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "5fbf434253fb450b2548b0f5a32e25f3e8749f39f31b2588689c0d1c110d3875",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "954f383d0cac5f1cf4aa975808e93ff54726704bce1d318ae4c60b22498d30b7",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "2dbd82f42aa56c25ee5543b88a12a144690108dbb1d922c21c0e8df46637aa32",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "21f702988db5326bd942f6d2a3b73a19842ead9c8c138e2df3bf813447aec540",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "4f162d23b325ded5c3af02e45ca274c99578299174bab56ded5db843485584de",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "5356245b2a3601239db292027b95b3d4f7075000f0e7cc00a631c0511f9def5f",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "d82d99dbd5892024276080d46d2d36837722a18f918835fab6050554a8071dd2",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "6fc1ecef35bb972abf204e69f0cafc9898a3997e31166b0ca60f336c2a3016d8",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "c3f783e6154c3bafdee95bf989215f8ff14c419ff16a87c85ae5a5146749b9d9",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "ea6c6298a9394598368d4cbd2b2069084ef77bc88ab8bf60ca186454b88a1de9",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "6b13e6b2438c635e5136cc92cc067fb9cfdd0f89bbbdfe7e30c5723a9165242d",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "5802ef4685275f884d961be167d5fbac3c4511c1629318aa018168355cec1a82",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "7189415431e20253cf5ccc0461a6a140d1062311cca82c12f751ec2c851fce49",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "482e157da6cecc17906c400f95b029da3c96bc747123365bc3033d714aaee0ff",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "a20b699d08a23b0c5324a4637e84ec2c4a8bab7b4e1307b9c7744c70dba945f5",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "390b42368b8a1497485f11fc129edb4bd66be9ac4d6182d504045e73b8dce3d4",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "5ea8ad0ff2f4fb567fede80d6532f80d38687ff733c04d9c836c9d38c47d6d00",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "9101f04f9f88f6e50b0997b69cfd8e28efad171d14479ed206f0810e641e287d",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "5186df16d03bfabfd83b86b0389040c02e00a93c55fa20ea554572eba88e78f5",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "fcda9f4b9c4e648ac6ccc42e8d4e56d6593c7e69193192297d25443006fe45ce",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "75b5c397936c778fe6a966792b89e8b0c2358e904de69a9f221ded197fd68710",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "a1b7eecdec6e750636633d39d779daddf88a5985c6737b4f660ee60aadbec8bd",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "df4ce4a2ce75816983c72561c0ee177090baeefbf28c07536db9dbb932aaff35",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "a4404681299a2c01fb0a25a2a16ac18ec98ead1f7a61dd84709e63af66960789",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "09d1126662918f8b6672e8df7a80a7a085f51879a25714ed319e8ca8e4cef769",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "67e467aec7ac7ad355db5bf05368c4a5f3b8eb8051849c0cccb7396408d29d7b",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "932e1971683224d0f0f101717a4fcbb1f4cdca128953985417b1b3dd826a454c",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "418679b2b2486ce306741118d3d0ba4de992ef404e54a05d672ff53f238d8ed4",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "4730dc1bfbe944f60480d6e8aa001d22f353389c4994c4085155f60f7ee91603",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "d23c1bc1552d10c436457f4810e0eabb9b8aab995e66127da848dd3d6f289d33",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "2f5d93001a5d655344bc603a0dfa2e14d176f19df16c3a24c18bae6ba9139c4b",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "895ce8d9a1f2b9d4ef1436ff4520f843e457ff17dec32a992a38256c16706717",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "00a511ffe848d8c7280bac2da318e9d772d5d4b44dc0eb9c131a3f246f3db71d",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "b1c7d1aa01784c53d28f9fa070ddc9f7f1c6bba5c995d5f9122c30118093bc14",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "b62d4c5dee43a755362e677a773e48ca5cea200d64cd9ccca9937e69ebd149ff",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "53f61d8369e688bc56352a9e52ad990f02542b0f069f7b469f83bd464f1793e1",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "aec140a2313e4ac16ba1e7af4185442c8d3f9c9465abe4c138a9546855d9f3b9",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "f5a5a3dee5db20e7c2cc7df3d37f0b82ed9f386c0fc3d4590ad82147617d3a77",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "357e9d9fca6fa7e97d83281dab689796fac571df1d7a7d01ce168cc1648b2d2d",
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
