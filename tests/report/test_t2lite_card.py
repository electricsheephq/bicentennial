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


# Host-free T0 tree digests (host_free_tree_sha256 below), rebuilt for the T2 controls pin
# (#391, RING0 E25). Intentional pack moves update this table and prereg/CHANGELOG.md.
LEGACY_PACK_HASHES = {
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1": "608fd09d3a10230f6bdc7e39b625b382777a144852f2bcdaeec89e5c72ed71d5",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/2": "1c337d3b13d7869c9c9487ecb8d1bb2ae28a08b52b06263ffb61217316f796e6",
    "pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/3": "c8e3eb3828403e01bd516a96dd01111d427ff6ec9533445d82ea2400d3fbce23",
    "pack/G1/Drift/drift-chain@1/s2-d0-none/1": "037c50a904c4910d9a4b56f00e8fc74331a7f8912c8548f1a7ebdad8a934ffa8",
    "pack/G1/Drift/drift-chain@1/s3-d0-none/1": "c7cf09e9f93e82af563f5311c73f79fec8e2145e35690d37458304fe18264102",
    "pack/G1/Drift/drift-chain@1/s3-d1-compaction/1": "b1b0b8117f25d14a0a838fc4583b0552a43512769041c464930682063995109d",
    "pack/G1/Drift/drift-chain@1/s3-d1-gap/1": "58b44c9cd7cc44bd311c2009dfa79db21fb27ce29f8fa2e037779544575f9add",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/1": "eddfe4f5fe9c8576af8f200bc4c374e76a97ceb654d34494921810402092fc2e",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/2": "090661b3d653d16b696b2f490ec91ff8ea10cd542f1fddc00453a59ea0367b6d",
    "pack/G1/Drift/drift-chain@1/s3-d1-none/3": "d0ffbf0b9e4d96b66ed846f6f2cee25721f0627367fed1ec596f6977115804e2",
    "pack/G1/Drift/drift-config@1/s2-d0-none/1": "9af1db99efca33df8fd1152c4442ba175fdaf1bab502aefb21089c5b1a9a4a87",
    "pack/G1/Drift/drift-config@1/s3-d0-none/1": "92dc85bb2710f2e66fa0d855c534c1d5270ee0ab9293e00923ebec3eeabdef6d",
    "pack/G1/Drift/drift-config@1/s3-d1-gap/1": "2b1fd834bf74456f1e399bcb039ef259cb82684f26c193065488d2d77afb7b42",
    "pack/G1/Drift/drift-config@1/s3-d1-kill/1": "ca29d9db99ce18863ab184f877964bdba0c89d2ff1b3e94363ab85d5a8d19fb1",
    "pack/G1/Drift/drift-config@1/s3-d1-none/1": "8442fe84910992e5e9c80be8ac080653799ce0dd122ae4f3945a1a3b65920a5e",
    "pack/G1/Drift/drift-config@1/s3-d1-none/2": "1fd30b4ff78e48f04fbd4d88db7967bf431ace8586253504d5a60df59e31b567",
    "pack/G1/Drift/drift-config@1/s3-d1-none/3": "96cf45774eb45cc435f40e4d3a6dc0ecda91cab02fc49cd164e31372f84cc21b",
    "pack/G1/Drift/drift-quote@1/s2-d0-none/1": "2f7b24538623a61eb7b7913a1bc7b7f22a888ef180c25fbe721a5d9a671841f3",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/1": "01a909e8f0706310e9f72e616871fdb19f1e88c38f204f9d455073a6890fddaa",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/2": "d2b08a2d7fed4545b80b1f9fbb1551891e6cd75e634d4bd010c5bb5eab78e41a",
    "pack/G1/Drift/drift-quote@1/s3-d0-none/3": "484a9a2a85170bb1e926acef39b26ba5cdc03e6172fcd1cd670be157c8d0f5a6",
    "pack/G1/Drift/drift-quote@1/s3-d1-gap/1": "217398ce1cf5bb6a52f8556d41f468137f82636a3966804f4ecd46395c3c1ca5",
    "pack/G1/Drift/drift-quote@1/s3-d1-kill/1": "70cb437379e057c99e7d35577f916b46dd1443ffceb18d64d710449763538e67",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/1": "997e04edbc2ff9872cca5783c2de7d1a374ce32427d1e3eff5b929727ee47a96",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/2": "508530d0266184eefc889333552fd73b3bea95c97c4590a5dc1c9092905d05bf",
    "pack/G1/Drift/drift-quote@1/s3-d1-none/3": "2c4c055288100d098cee72bce01d4f11535711c5304b180a450fa4069a47c9d6",
    "pack/G1/Recall/recall-value@1/s2-d1-none/1": "b82b4ae19eb7ef69978104655243e334764e880bdbdcf29b5ef93b5be1211ce6",
    "pack/G1/Recall/recall-value@1/s3-d0-none/1": "313dfb2d7a458c15a769d6f6d2231f89a82f95e0f75ead1083efb9c995fbe7aa",
    "pack/G1/Recall/recall-value@1/s3-d1-kill/1": "9f4a3bef0e893579bc8db8694ddb56dc6befca12fb2892a5b681af5c2dd7d3ed",
    "pack/G1/Recall/recall-value@1/s3-d1-none/1": "58200e4a726c72b8b9af9f21918f8a9abb0ee011e5f0455a3f6b43e9ef55b726",
    "pack/G1/Recall/recall-value@1/s3-d1-none/2": "30d472c7f96eba444704040d99be776f2c2695d3364ef677a84469e71bb3a9a6",
    "pack/G1/Recall/recall-value@1/s3-d1-none/3": "82ea5d4e890a59d433b94bcdf6b6d3728752ed20c64458952c9a35d56c2ef090",
    "pack/G1/Recall/recall-value@1/s3-d2-none/1": "d13f23def54b7082976360a21f452640f7749308c2637ed7324820bacde51e5a",
    "pack/G1/Wake/wake-loop@1/s2-d1-none/1": "3e58826016f782026334c7b343803106ebbb596acba118b36ef5c5b491b8ec87",
    "pack/G1/Wake/wake-loop@1/s3-d1-kill/1": "f8729aa9a20244a6fe8977d2acb1f77fb31218791792840fb49244c24c146627",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/1": "e5f05560cca287cf7c1bf91ff71cd674f0053a1fa1a7b568c7ab3d4a759aa6f4",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/2": "961305c8a3ee93154e2a65d25811066c7281769e6bd51e3b6b0cd1145e1b16c2",
    "pack/G1/Wake/wake-loop@1/s3-d1-none/3": "62988ba1b300e08ad164556fa248bb09309519a6ae16865f0ded86585162dc6a",
    "pack/G1/Wake/wake-loop@1/s3-d2-none/1": "1fcbe13034225c7058fcf16fab3f83bb6f589f138ece6138cf57922459dca5d2",
    "pack/G2/Drift/drift-asof@1/s2-d0-none/1": "3e87cd69039510fa482a998250f06b4397f612e9782375a19b5fb2ca9bce1c27",
    "pack/G2/Drift/drift-asof@1/s3-d0-none/1": "985e8a0785db96eddd18cd8c73317d4731a7a8b929690f3ee3446d6f5bea3ade",
    "pack/G2/Drift/drift-asof@1/s3-d1-gap/1": "dfaf6e4e5562c7b057c5876da0b78ee504f3963f428c10326c09db71b57a75f4",
    "pack/G2/Drift/drift-asof@1/s3-d1-kill/1": "553e33278a8b8c601e331667d39a3647a0900db787e91f7aab1929096005d4d0",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/1": "b7c9b84e1861f9b6a134ecc93682785f64e3c162b648aab28862841a8212c56d",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/2": "64132418ac950ad405f7ffd6643dfa02b4748ecb574acc1823b8bb9f52a7b6ea",
    "pack/G2/Drift/drift-asof@1/s3-d1-none/3": "b1f2282c48d38a239da02ecd5f999b6ab0a90ab5ae6e7384faae9f810fe8cb81",
    "pack/G2/Drift/drift-booking@1/s2-d0-none/1": "8218d17da0e9be24da9a26e56282e762fda5aff158278004870691b5abf29b99",
    "pack/G2/Drift/drift-booking@1/s3-d0-none/1": "5dce235fddd6de27412f6f8bd8c6b3ec273c44b50ed4dedf9b8b6b45be69333a",
    "pack/G2/Drift/drift-booking@1/s3-d1-gap/1": "55a1b2393cebf13d178a24252dcff27bf26c0fc9f6adaa3a3bb8cf27719b4933",
    "pack/G2/Drift/drift-booking@1/s3-d1-kill/1": "1f8b1c6e708b073e63e0b06da765883562001b0aa235d02c3a05ec390ee67ec3",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/1": "e7ca9819d377d09f2973783aa9be7fdb59e698635d41bdbde26b8713a3d9536c",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/2": "cc1a2587967d5ccd5121b9a415e79607c815278474a58482310ade5db561995a",
    "pack/G2/Drift/drift-booking@1/s3-d1-none/3": "714bd0e22ab4faddf91717bab4e235971c7a542fba535fd1bba09f5dc2a66264",
    "pack/G2/Drift/drift-no-update@1/s2-d0-none/1": "b23fc011ea9d3852e82310bd47e6b0b7a7dc801529ec746692e1f12c0a443fde",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/1": "868e89949cc147340bdfb0c8c93c1100cefd26d1a8162530a8be6482a282f60b",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/2": "68929886806a8bf69b82a36b73367d31db01439a1ce2ccb240e6beb869da3a7c",
    "pack/G2/Drift/drift-no-update@1/s3-d0-none/3": "cb932c3d99461c0748df5245d94672436afbcfc462a4dfad58b2f9ae100c6bdc",
    "pack/G2/Drift/drift-no-update@1/s3-d1-gap/1": "a3431e0a32d2c4326c12ff8eba0c932ff6bc449f3e8c4d8f7761d8d4829f306a",
    "pack/G2/Drift/drift-no-update@1/s3-d1-kill/1": "d519708ced294b1865f1da731183334d0a983eabd0b06d32abfb6fc47a440f28",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/1": "b1e33690b68237ed51cee96a1effa1883b6e763fa60914ae2fc2f92a3eeb5073",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/2": "ede7b3118d4bc88128b90cbb8745b36bb6e7d66b4bd2b4c50479c004fe8f7d54",
    "pack/G2/Drift/drift-no-update@1/s3-d1-none/3": "d7ea40621f6b14cd62746665b07c5c00b25b8af078cfb739eae8ece1738be993",
    "pack/G2/Keep/keep-forget@1/s3-d1-gap/1": "dd8edd0317fc2647a5ec1fce7aeb8cd9ed52b345b7b14a0359d1d779224fe625",
    "pack/G2/Keep/keep-forget@1/s3-d1-kill/1": "d99c69d3514f54ff6335b8cbe0feb05a714ce862bb0737bc03e140481aa054ec",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/1": "c02d71ec0c540891c57ad072bc1094d6ff850bd444b523cb8aadd5235cb6711b",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/2": "deb5d320d9e58a71528ecf7cd65b5f8e180ea9a0a2a16a76a5b8b3665c9465c3",
    "pack/G2/Keep/keep-forget@1/s3-d1-none/3": "9d2f7b6bd73f66e85ebc816be4ec83936e0e49711a10dfe5aeb6d805003e209b",
    "pack/G2/Keep/keep-incidental@1/s2-d1-none/1": "6ae99bb826ebebf82bdf9290022ad4f0ecc6d39b32b3f6bb5b4db217bfeccc67",
    "pack/G2/Keep/keep-incidental@1/s3-d1-kill/1": "f9c2b8967f9ea67604a53f2d1728f4562bde83ad3c075c96bdb3bb09d0a55cb4",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/1": "51a741406b4018b59898451f8d0839de6c09680bf2ca17d188131c732711004f",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/2": "d28ef6b0ec48889a380d39d5f276459803d1947dfebf66e691f555fe3f7a3c8c",
    "pack/G2/Keep/keep-incidental@1/s3-d1-none/3": "d9eb4397101d6000618b9f7cbb33ce57cb0c000604a363646a8f7ff30dcd12e4",
    "pack/G2/Keep/keep-incidental@1/s3-d2-none/1": "658d5193dc06d6444c84ccef3543f2238cd4d692fe995dc8341ecad6466b2fac",
    "pack/G2/Keep/keep-neighbour@1/s2-d1-none/1": "c84226151921ad4df2609f26040aa65f6b1e47845baf1c85301c99130129a129",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-kill/1": "f804e1430bb60cc4cd0c73030149703b756ec9d0615f9b99a204f7326875304a",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/1": "48eba8129bd0018544f33e5ca647ad482b4bfa771c9b5ef047af57be4d0c779e",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/2": "c76134b828d9b2c7a6674d8e67610cf24988a7aa6a112ff168202a05149ce3e0",
    "pack/G2/Keep/keep-neighbour@1/s3-d1-none/3": "7f3a03911c5c85b736cebf605e1654dacca1bad5aa97f12b2657b9d44b490cb3",
    "pack/G2/Keep/keep-neighbour@1/s3-d2-none/1": "f130fb413f98c1a9d54c7da6e5b859b2ac8e0dc9b8003012a7e8341aa5698b6d",
    "pack/G2/Recall/recall-count@1/s2-d0-none/1": "9f426c82cd806114f6ed43217be8d9eedd391696bf3ed34e40ca8418cdca2ac8",
    "pack/G2/Recall/recall-count@1/s3-d0-none/1": "87b82fd6ae11ee43e576608db594561307a813b238959c5b42a3dd458f9a6b5a",
    "pack/G2/Recall/recall-count@1/s3-d1-gap/1": "308fa894c96681551dc14d3ab0e218c208b9dfaa0a2849674f81704af3e812fd",
    "pack/G2/Recall/recall-count@1/s3-d1-kill/1": "e81521f81649a9fc789f2aeb0b9751b15bf7876127a3225885fe400e350e4d4c",
    "pack/G2/Recall/recall-count@1/s3-d1-none/1": "ba846b449f738a89f3bdd6bb57f077979920d6523654dc31526d78ba3d842eef",
    "pack/G2/Recall/recall-count@1/s3-d1-none/2": "a21cbafa98a7c2269c55f4c1552d7cab3e6b1e1d921987df129d1611eb9d5eba",
    "pack/G2/Recall/recall-count@1/s3-d1-none/3": "94d2d930cb8cd5341e63e5954936b9e544bdd216277ec2aa94eb8822c01493e1",
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
