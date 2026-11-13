"""Offline T2 card schema, identity, exclusion and determinism contracts."""

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import NAMES, SCHEMAS, validate
from bicentennial.report import t2_card as cards


def schema():
    return json.loads((SCHEMAS / "card_t2.schema.json").read_bytes())


def inputs():
    fixture = Path(__file__).resolve().parents[1] / "fixtures/scoring/contracts.json"
    old = json.loads(fixture.read_bytes())["contracts"]["card_ring0"]
    row = dict(old["items"][0], life="life-alpha", genre="G1", branch="B0",
               probe_point=5, repro=None)
    failed = dict(row, score_milli=-1000, worst_case_milli=-1000,
                  repro="kept/life-alpha/B0/item-a")
    unscored = dict(row, life="life-beta", genre="G2", stage="act", envelope=None,
                    base_verdict=None, score_milli=None, worst_case_milli=None,
                    accuracy_correct=None, tuesday_class=None, failure_class=None,
                    stage_attribution=None, benign_extra=False, carry_over=False)
    items = [failed, dict(row, branch="B1", probe_point=10), unscored,
             dict(row, life="life-beta", genre="G2", branch="B1", probe_point=10)]
    pin_names = ("benchmark_commit", "generator_commit", "director_commit", "scorer_commit",
                 "harness_hash", "system_hash", "route_table_hash", "write_turn_package_hash")
    counts = dict(units=4, lives=2, floor_cached_units=1, null_citation=0,
                  not_scored_live=1, infra=0, kept_copies=1)
    counts.update({"items.G1.remember": 2, "items.G2.remember": 1, "items.G2.act": 1})
    return dict(system="synthetic-system", pack_hash="a" * 64, seed_hash="b" * 64,
                pins={name: old["pins"][name] for name in pin_names},
                model="synthetic-model", effort="medium", served_identity="synthetic-identity",
                aa_prime=False, items=items, counts=counts, answer_contract_sha256="c" * 64,
                not_scored_live=[["life-beta", "B0", "item-a"]], seed_source={"kind": "public"},
                groups=[["wake-1", "act"], ["wake-1", "remember"]],
                floor=dict(served_identity="synthetic-floor", units={
                    f"{i['life']}/{i['branch']}": dict(cache_key="d" * 64, cached=n == 0)
                    for n, i in enumerate(items)}), controls_broken=[])


def complete_card():
    return cards.build_t2_card(**inputs())


def test_item_1_complete_two_life_card_and_item_2_fresh_canonical_builds():
    args = inputs()
    before = copy.deepcopy(args)
    card = cards.build_t2_card(**args)
    assert cards.validate_t2_card(card) is None
    assert "card_t2" in NAMES and validate("card_t2", card) is None
    assert card["tier"] == "T2" and "gate_verdict" not in card
    assert len({i["life"] for i in card["items"]}) == 2
    assert {i["branch"] for i in card["items"]} == {"B0", "B1"}
    assert len(card["not_scored_live"]) == 1
    reordered = {key: args[key] for key in reversed(args)}
    reordered["items"] = args["items"][::-1]
    assert canon(card) == canon(cards.build_t2_card(**reordered))
    assert card == json.loads(canon(card))
    card["items"][0]["item_id"] = "changed"
    card["pins"]["system_hash"] = "e" * 64
    card["floor"]["units"].clear()
    card["counts"]["units"] = 0
    assert args == before


def test_item_1_schema_retains_frozen_fields_and_fixed_labels():
    old = json.loads((SCHEMAS / "card_t2lite.schema.json").read_bytes())
    new = schema()
    assert new["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert (SCHEMAS / "card_t2.schema.json").read_bytes() == canon(new)
    assert set(old["required"]) <= set(new["required"])
    changed = {"tier", "pins", "items", "labels", "not_scored_live", "counts"}
    for field in old["properties"].keys() - changed:
        assert new["properties"][field] == old["properties"][field]
    old_row = old["properties"]["items"]["items"]
    new_row = new["properties"]["items"]["items"]
    for field in old_row["properties"].keys() - {"item_id"}:
        assert new_row["properties"][field] == old_row["properties"][field]
    labels = complete_card()["labels"]
    assert "t2lite" not in labels
    assert labels["t2"] == ("T2: live probe answers only; write turns, compaction, extraction "
                            "and embeddings scripted; not predictive of the full tier; never certifies")
    assert labels["probe_writes"] == "probe-time memory writes: isolation is per item"
    assert labels["window"] == "W = 16K, inherited from T1 and provisional"
    assert labels["act_g2"] == "G2 actions not scored live"
    for label, prop in old["properties"]["labels"]["properties"].items():
        if label not in {"t2lite", "probe_writes", "window"}:
            assert new["properties"]["labels"]["properties"][label] == prop


def test_item_2_system_failure_kept_but_g2_action_crash_excluded():
    card = complete_card()
    failed, action = card["items"][0], card["items"][2]
    for row in (failed, action):
        row.update(failure_class="SYSTEM_FAILURE", score_milli=0,
                   worst_case_milli=-1000, envelope=None)
    action["accuracy_correct"] = False
    cards.validate_t2_card(card)
    assert failed["repro"] == "kept/life-alpha/B0/item-a"
    assert [action[k] for k in ("life", "branch", "item_id")] in card["not_scored_live"]
    assert action["repro"] is None
    action["repro"] = "kept/life-beta/B0/item-a"
    with pytest.raises(ValueError, match="^t2_card:repro_ineligible$"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("tier", ["T2-lite", "T1"])
def test_item_2_wrong_tier_refused(tier):
    card = dict(complete_card(), tier=tier)
    with pytest.raises(ValueError, match="^t2_card:tier$"):
        cards.validate_t2_card(card)
    with pytest.raises(ValueError, match="tier"):
        validate("card_t2", card)


@pytest.mark.parametrize("arm", ["no_memory", "naive_rag", "oracle_evidence", "bm25", "grep", "recent_window"])
def test_a_control_arms_card_names_the_arm(arm):
    # A live control arm (RING0 §15) runs through the system's harness with memory off: its card says which arm.
    assert "control" not in complete_card()
    card = cards.build_t2_card(**inputs(), control=arm)
    assert card["control"] == arm and validate("card_t2", card) is None
    assert {k: v for k, v in card.items() if k != "control"} == complete_card()
    with pytest.raises(ValueError, match="control"):
        validate("card_t2", dict(card, control="hermes-native"))


def test_item_2_gate_verdict_refused():
    card = dict(complete_card(), gate_verdict=None)
    with pytest.raises(ValueError, match="^t2_card:gate_verdict$"):
        cards.validate_t2_card(card)
    with pytest.raises(ValueError, match="gate_verdict"):
        validate("card_t2", card)


@pytest.mark.parametrize("label", schema()["properties"]["labels"]["required"])
def test_item_2_every_label_required_and_fixed(label):
    card = complete_card()
    card["labels"][label] += "changed"
    with pytest.raises(ValueError, match=label):
        cards.validate_t2_card(card)
    del card["labels"][label]
    with pytest.raises(ValueError, match="^t2_card:labels$"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("violation", ["order", "duplicate"])
def test_item_2_items_sorted_unique_by_life_branch_id(violation):
    card = complete_card()
    assert len({i["item_id"] for i in card["items"]}) == 1
    if violation == "order":
        card["items"] = card["items"][::-1]
    else:
        card["items"].insert(0, copy.deepcopy(card["items"][0]))
    with pytest.raises(ValueError, match="^t2_card:items$"):
        cards.validate_t2_card(card)


def test_item_2_builder_refuses_duplicate_identity():
    args = inputs()
    args["items"].append(copy.deepcopy(args["items"][0]))
    with pytest.raises(ValueError, match="^t2_card:items$"):
        cards.build_t2_card(**args)


@pytest.mark.parametrize("triples", [
    [["absent", "B0", "item-a"]],
    [["life-beta", "B0", "item-a"], ["life-beta", "B0", "item-a"]],
    [["life-beta", "B0", "item-a"], ["life-alpha", "B0", "item-a"]],
    [["life-beta", "B0"]],
])
def test_item_2_not_scored_triples_sorted_unique_subset(triples):
    card = dict(complete_card(), not_scored_live=triples)
    with pytest.raises(ValueError, match="^t2_card:not_scored_live$"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("triples", [[], [["life-alpha", "B0", "item-a"],
                                           ["life-beta", "B0", "item-a"]]])
def test_item_2_not_scored_is_exactly_g2_actions(triples):
    with pytest.raises(ValueError, match="^t2_card:not_scored_live_g2$"):
        cards.validate_t2_card(dict(complete_card(), not_scored_live=triples))


def test_item_2_repro_on_passing_item_refused():
    card = complete_card()
    card["items"][1]["repro"] = "kept/life-alpha/B1/item-a"
    with pytest.raises(ValueError, match="^t2_card:repro_ineligible$"):
        cards.validate_t2_card(card)


def test_item_2_repro_must_be_own_kept_path():
    card = complete_card()
    card["items"][0]["repro"] = "kept/life-alpha/B1/item-a"
    with pytest.raises(ValueError, match="^t2_card:repro_path$"):
        cards.validate_t2_card(card)


def test_item_2_failed_item_without_kept_copy_has_null_repro():
    card = complete_card()
    card["items"][0]["repro"] = None
    card["counts"]["kept_copies"] = 0
    cards.validate_t2_card(card)


def test_item_2_blocked_item_cannot_have_repro():
    card = complete_card()
    card["items"][0].update(failure_class="BLOCKED", score_milli=None,
                            worst_case_milli=None, envelope=None, infra_reruns=2)
    with pytest.raises(ValueError, match="^t2_card:repro_ineligible$"):
        cards.validate_t2_card(card)
    card["items"][0]["repro"] = None
    card["counts"]["kept_copies"] = 0
    cards.validate_t2_card(card)


@pytest.mark.parametrize("name", sorted(inputs()["counts"]))
def test_item_2_required_counts_present(name):
    card = complete_card()
    del card["counts"][name]
    reason = "counts_items" if name.startswith("items.") else "counts"
    with pytest.raises(ValueError, match=f"^t2_card:{reason}$"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("value", [-1, True, "1"])
def test_item_1_counts_are_named_nonnegative_integers(value):
    card = complete_card()
    card["counts"]["units"] = value
    with pytest.raises(ValueError, match="units"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_item_2_floor_units_match_items(change):
    card = complete_card()
    units = card["floor"]["units"]
    if change == "extra":
        units["absent/B0"] = dict(cache_key="a" * 64, cached=False)
    else:
        del units["life-alpha/B0"]
    with pytest.raises(ValueError, match="^t2_card:floor_units$"):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("groups", [
    [["wake-1", "remember"], ["wake-1", "act"]], [["wake-1", "remember"]],
    [["wake-1", "act"], ["wake-1", "act"], ["wake-1", "remember"]],
    [["other", "act"], ["wake-1", "remember"]], [["wake-1"]],
])
def test_item_2_groups_sorted_unique_and_exact(groups):
    with pytest.raises(ValueError, match="^t2_card:groups$"):
        cards.validate_t2_card(dict(complete_card(), groups=groups))


@pytest.mark.parametrize("source", [{"kind": "public"},
                                    {"kind": "ring1-draw", "draw_sha256": "a" * 64}])
def test_item_1_seed_source_accepts_public_and_ring1(source):
    assert cards.build_t2_card(**dict(inputs(), seed_source=source))["seed_source"] == source


@pytest.mark.parametrize("source", [{"kind": "ring1-draw"},
                                    {"kind": "public", "draw_sha256": "a" * 64},
                                    {"kind": "ring1-draw", "draw_sha256": "bad"}])
def test_item_2_seed_source_requires_exact_variant(source):
    with pytest.raises(ValueError, match="seed_source"):
        cards.build_t2_card(**dict(inputs(), seed_source=source))


@pytest.mark.parametrize("name", inputs()["pins"])
def test_item_1_each_pin_required_including_system_hash(name):
    card = complete_card()
    del card["pins"][name]
    with pytest.raises(ValueError, match=name):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("name", ["system_hash", "route_table_hash", "write_turn_package_hash"])
@pytest.mark.parametrize("bad", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_item_1_new_pins_are_exact_lowercase_hex(name, bad):
    card = complete_card()
    card["pins"][name] = bad
    with pytest.raises(ValueError, match=name):
        cards.validate_t2_card(card)


@pytest.mark.parametrize("field", schema()["required"])
def test_item_1_all_card_fields_required(field):
    card = complete_card()
    del card[field]
    with pytest.raises(ValueError):
        cards.validate_t2_card(card)


def test_item_2_reuses_frozen_item_and_shadow_semantics():
    card = complete_card()
    card["items"][1]["score_milli"] = 1001
    with pytest.raises(ValueError, match="score_milli: out of range"):
        cards.validate_t2_card(card)
    card = complete_card()
    card["items"][2]["competing_present"] = ["z", "y"]
    with pytest.raises(ValueError, match="^t2lite_card:shadow$"):
        cards.validate_t2_card(card)


def test_item_2_genre_is_consistent_for_each_life():
    card = complete_card()
    card["items"][1]["genre"] = "G2"
    with pytest.raises(ValueError, match="^t2_card:life_genre$"):
        cards.validate_t2_card(card)


def test_item_1_broken_control_rows_recorded_without_refusal():
    broken = [dict(stage="act", track="Tuesday")]
    assert cards.build_t2_card(**dict(inputs(), controls_broken=broken))["controls_broken"] == broken
    with pytest.raises(ValueError, match="track"):
        cards.build_t2_card(**dict(inputs(), controls_broken=[dict(stage="act")]))


def test_item_1_broken_control_rows_hold_one_order():
    ordered = [dict(stage="act", track="Tuesday"), dict(stage="remember", track="Wake")]
    assert cards.build_t2_card(**dict(inputs(), controls_broken=ordered))["controls_broken"] == ordered
    for rows in (ordered[::-1], [ordered[0], ordered[0]]):
        with pytest.raises(ValueError, match="t2_card:controls_broken"):
            cards.build_t2_card(**dict(inputs(), controls_broken=rows))


def test_item_1_incidental_session_and_store_ids_do_not_change_card(tmp_path):
    args = inputs()
    kept = tmp_path / args["items"][0]["repro"]
    kept.mkdir(parents=True)
    store = kept / "store.json"
    hashes, encoded = [], []
    for suffix in ("first", "second"):
        store.write_bytes(canon(dict(session_id=f"session-{suffix}", store_id=f"store-{suffix}",
                                    answer=args["items"][0]["envelope"])))
        hashes.append(sha256(store.read_bytes()).hexdigest())
        encoded.append(canon(cards.build_t2_card(**args)))
    assert hashes[0] != hashes[1]
    assert encoded[0] == encoded[1]
    for forbidden in ("session_id", "store_id", "store_hash", "store_sha256"):
        card = complete_card()
        card["items"][0][forbidden] = "a" * 64
        with pytest.raises(ValueError, match=forbidden):
            cards.validate_t2_card(card)


@pytest.mark.parametrize("value", [[], None, "card"])
def test_item_2_non_object_card_refused(value):
    with pytest.raises(ValueError, match="t2_card:object"):
        cards.validate_t2_card(value)


@pytest.mark.parametrize("key", ["units", "lives", "not_scored_live", "floor_cached_units", "kept_copies",
                                 "null_citation", "items.G1.remember", "items.G2.act"])
def test_item_1_counts_the_rows_define_agree_with_them(key):
    args = inputs()
    args["counts"][key] += 1
    with pytest.raises(ValueError, match="t2_card:counts_values"):
        cards.build_t2_card(**args)


def test_item_1_null_citation_counts_asserted_answers_without_a_citation():
    args = inputs()
    args["items"][1] = dict(args["items"][1], envelope=dict(args["items"][1]["envelope"], citation=None))
    args["counts"]["null_citation"] = 1
    assert cards.build_t2_card(**args)["counts"]["null_citation"] == 1
    # An unknown answer always has a null citation (runner/t2lite.py), so it is not counted.
    args["items"][1] = dict(args["items"][1], base_verdict="OMISSION", score_milli=0, worst_case_milli=0,
                            accuracy_correct=None, envelope=dict(type="unknown", value=None, confidence_milli=0,
                                                                 citation=None))
    args["counts"]["null_citation"] = 0
    assert cards.build_t2_card(**args)["counts"]["null_citation"] == 0


def test_item_1_infra_and_absent_cells_are_not_derived_from_rows():
    args = inputs()
    args["counts"].update({"infra": 5, "items.G1.act": 0})
    assert cards.build_t2_card(**args)["counts"]["infra"] == 5
    args["counts"]["items.G1.act"] = 1
    with pytest.raises(ValueError, match="t2_card:counts_values"):
        cards.build_t2_card(**args)
