"""Synthetic acceptance for the report-only T2-lite comparison."""

import copy
import json
from dataclasses import FrozenInstanceError, asdict
from fractions import Fraction
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.report import t2lite_flips as flips
from bicentennial.report.t1_gate import check_baseline
from bicentennial.report.t2lite_card import build_t2lite_card


def card(system="hermes-native", *, run=None, aa_prime=False):
    return build_t2lite_card(
        system=system, pack_hash="a" * 64, seed_hash="b" * 64,
        pins={"benchmark_commit": "1" * 40, "generator_commit": "2" * 40,
              "director_commit": "3" * 40, "scorer_commit": "4" * 40,
              "harness_hash": "c" * 64},
        model="synthetic-model", effort="medium", served_identity="synthetic-identity",
        aa_prime=aa_prime, items=card_items(run or {}), counts={},
        answer_contract_sha256="d" * 64)


ENVELOPE = {"type": "span", "value": "synthetic", "confidence_milli": 1000, "citation": None}


def card_items(run):
    """The card rows of a run's outcome records (a card vouches for its own outcomes)."""
    return [dict(item_id=iid, cell_id=r["cell_id"], stage=r["stage"], track=r["track"],
                 base_verdict=r["base_verdict"], benign_extra=False,
                 failure_class=r["failure_class"], infra_reruns=0, score_milli=r["score_milli"],
                 worst_case_milli=r["score_milli"], accuracy_correct=None, tuesday_class=None,
                 envelope=None if r["envelope"] == "missing" else ENVELOPE,
                 selected_option=None, competing_present=[], carry_over=False,
                 stage_attribution=r["stage_attribution"]) for iid, r in run.items()]


def test_t1_refuses_t2lite_before_lane_work():
    baseline = card()
    with pytest.raises(ValueError, match=r"\$: missing=.*gate_verdict.*extra="):
        check_baseline(canon(baseline), system=baseline["system"],
                       pins=dict(pack_hash=baseline["pack_hash"], seed_hash=baseline["seed_hash"]))


@pytest.mark.parametrize("side", ["current", "baseline"])
@pytest.mark.parametrize("field,value", [
    ("system", "no-memory"), ("pack_hash", "e" * 64), ("seed_hash", "e" * 64),
    ("model", "other-model"), ("effort", "high"),
    ("pins.harness_hash", "e" * 64), ("answer_contract_sha256", "e" * 64),
    ("pins.benchmark_commit", "e" * 40), ("pins.generator_commit", "e" * 40),
    ("pins.director_commit", "e" * 40), ("pins.scorer_commit", "e" * 40),
])
def test_each_comparability_field_refuses_with_its_path(side, field, value):
    cards = dict(current=card(), baseline=card())
    target = cards[side]
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    with pytest.raises(flips.BaselineRefused) as refused:
        flips.check_baseline_t2lite(cards["current"], cards["baseline"])
    assert refused.value.reason == field
    assert str(refused.value) == field


def test_identical_valid_cards_pass():
    assert flips.check_baseline_t2lite(card(), card()) is None


@pytest.mark.parametrize("side", ["current", "baseline"])
@pytest.mark.parametrize("invalid", ["t1", "missing", "hash", "profile", "null"])
def test_validation_precedes_comparison_and_refuses_non_t2lite(side, invalid):
    cards = dict(current=card(), baseline=card())
    bad = cards[side]
    if invalid == "t1":
        path = Path(__file__).resolve().parents[1] / "fixtures/scoring/contracts.json"
        cards[side] = json.loads(path.read_bytes())["contracts"]["card_ring0"]
        assert cards[side]["tier"] == "T1"
    elif invalid == "missing":
        del bad["counts"]
    elif invalid == "hash":
        bad["answer_contract_sha256"] = "bad hash"
    elif invalid == "profile":
        bad["profile"] = "system-live"
    else:
        cards[side] = None
    # Even an earlier comparability-field difference cannot hide an invalid card.
    cards["baseline" if side == "current" else "current"]["pack_hash"] = "f" * 64
    with pytest.raises(flips.BaselineRefused) as refused:
        flips.check_baseline_t2lite(cards["current"], cards["baseline"])
    assert refused.value.reason == f"invalid_card:{side}"


def test_profile_comparison_after_both_validations(monkeypatch):
    # L4 currently permits only probe-live. Isolate the comparison to pin its
    # behavior for a future valid profile, without weakening production validation.
    current, baseline = card(), card()
    baseline["profile"] = "future-profile"
    seen = []
    monkeypatch.setattr(flips, "validate_t2lite_card", lambda obj: seen.append(obj))
    with pytest.raises(flips.BaselineRefused) as refused:
        flips.check_baseline_t2lite(current, baseline)
    assert refused.value.reason == "profile"
    assert seen == [current, baseline]


def item(item_id="item-0", **changes):
    record = dict(
        item_id=item_id, score_milli=1000, failure_class=None, base_verdict="PASS",
        life="life-1", branch="B0", probe_point=10, probe_session=12,
        cell_id="FAULT-CRASH", track="Faults", stage="survive", genre="G1",
        template_ref="synthetic-template-v1", twin_bundle="bundle-1", twin_flip=False,
        in_context=True, stage_attribution="used", envelope="parsed",
        value_match=True, citation_match=True, crosses_cold_restart=True,
        swap_position="before")
    record.update(changes)
    return record


def test_frozen_record_projects_plain_dict_and_envelope_state():
    raw = item(envelope={"type": "span", "value": "synthetic"})
    raw["hermes"] = "/synthetic/local/hermes"
    record = flips.ItemOutcome.from_dict(raw)
    assert record.envelope == "parsed"
    assert "hermes" not in asdict(record)
    raw["envelope"]["value"] = "changed"
    assert record.envelope == "parsed"
    with pytest.raises(FrozenInstanceError):
        record.score_milli = 0
    assert flips.ItemOutcome.from_dict(item(envelope=None)).envelope == "missing"
    with pytest.raises(ValueError, match="envelope"):
        flips.ItemOutcome.from_dict(item(envelope="malformed"))


def test_planted_flip_keeps_both_records_and_every_diagnostic():
    baseline = item()
    current = item(score_milli=-1000, failure_class="FAIL_TASK", base_verdict="FAIL_MEMORY",
                   probe_session=13, twin_flip=True, in_context=False,
                   stage_attribution="retrieved", envelope="missing", value_match=False,
                   citation_match=False, crosses_cold_restart=False, swap_position="after")
    callback_items = []

    def rerun(record):
        callback_items.append(record)
        return "synthetic rerun"

    result = flips.flip_list({"item-0": baseline}, {"item-0": current}, rerun=rerun)
    assert result["rows"] == [dict(item_id="item-0", baseline=baseline, current=current,
                                   unstable=None, rerun="synthetic rerun")]
    assert callback_items == [flips.ItemOutcome.from_dict(baseline)]
    assert result["excluded"] == []
    assert result["counts"] == dict(items=1, flips=1, excluded=0, scored=1,
                                    aa_prime_scored=0, unstable=0)


def test_unchanged_and_metadata_only_changes_are_not_flips():
    baseline = {"item-0": item()}
    assert flips.flip_list(baseline, baseline)["rows"] == []
    current = {"item-0": item(base_verdict="FAIL_MEMORY", in_context=False, twin_flip=True)}
    assert flips.flip_list(baseline, current)["rows"] == []


def test_failure_class_alone_is_a_flip():
    result = flips.flip_list({"item-0": item()}, {"item-0": item(failure_class="FAIL_TASK")})
    assert len(result["rows"]) == 1
    assert result["rows"][0]["current"]["score_milli"] == 1000


@pytest.mark.parametrize("side", ["baseline", "current"])
@pytest.mark.parametrize("field", ["failure_class", "base_verdict"])
@pytest.mark.parametrize("reason", ["INFRA", "INFRA_FAILURE", "BLOCKED"])
def test_infra_or_blocked_on_either_side_is_excluded(side, field, reason):
    runs = dict(baseline={"item-0": item()}, current={"item-0": item(score_milli=-1000)})
    runs[side]["item-0"][field] = reason
    result = flips.flip_list(runs["baseline"], runs["current"])
    assert result["rows"] == []
    assert result["excluded"] == [dict(item_id="item-0", reason=reason,
                                       baseline=runs["baseline"]["item-0"],
                                       current=runs["current"]["item-0"])]
    assert result["counts"]["scored"] == 0


@pytest.mark.parametrize("side", ["baseline", "current"])
def test_g2_act_is_not_scored_live_on_either_side(side):
    runs = dict(baseline={"item-0": item()}, current={"item-0": item(score_milli=-1000)})
    runs[side]["item-0"].update(stage="act", genre="G2")
    result = flips.flip_list(runs["baseline"], runs["current"])
    assert result["rows"] == []
    assert result["excluded"][0]["reason"] == "not_scored_live"


@pytest.mark.parametrize("stage,genre", [("act", "G1"), ("remember", "G2")])
def test_g1_act_and_g2_qa_remain_scored(stage, genre):
    result = flips.flip_list({"item-0": item(stage=stage, genre=genre)},
                             {"item-0": item(stage=stage, genre=genre, score_milli=-1000)})
    assert len(result["rows"]) == 1
    assert result["excluded"] == []


def test_sort_is_life_branch_numeric_checkpoint_then_item_id():
    records = [item("z", life="life-2"), item("y", branch="B1"),
               item("x", probe_point=10), item("b", probe_point=2), item("a", probe_point=2)]
    baseline = {r["item_id"]: r for r in records}
    current = {iid: dict(r, score_milli=-1000) for iid, r in reversed(list(baseline.items()))}
    assert [r["item_id"] for r in flips.flip_list(baseline, current)["rows"]] == ["a", "b", "x", "y", "z"]


def band_runs():
    baseline = {f"i-{i}": item(f"i-{i}") for i in range(10)}
    prime = copy.deepcopy(baseline)
    prime["i-0"]["score_milli"] = -1000
    prime["i-1"]["failure_class"] = "FAIL_TASK"
    current = {iid: dict(r, score_milli=-1000) for iid, r in baseline.items()}
    return baseline, current, prime


def valid_band_runs():
    """band_runs under the scorer's rule that a task failure scores 0, so cards can carry it."""
    baseline, current, prime = band_runs()
    prime["i-1"]["score_milli"] = 0
    return baseline, current, prime


def test_aa_prime_two_of_ten_exact_fraction_milli_and_row_flags():
    baseline, current, prime = band_runs()
    result = flips.flip_list(baseline, current, aa_prime=prime)
    assert result["q0"] == Fraction(2, 10)
    assert isinstance(result["q0"], Fraction)
    assert result["q0_milli"] == 200
    assert {r["item_id"] for r in result["rows"] if r["unstable"]} == {"i-0", "i-1"}
    assert all(r["unstable"] is False for r in result["rows"][2:])
    assert result["counts"]["aa_prime_scored"] == 10
    assert result["counts"]["unstable"] == 2
    assert result["labels"] == []


def test_q0_denominator_is_scored_in_a_and_prime_only():
    baseline, current, prime = band_runs()
    for iid, a_changes, p_changes in [
        ("infra-a", dict(failure_class="INFRA"), {}),
        ("blocked-prime", {}, dict(failure_class="BLOCKED")),
        ("infra-prime", {}, dict(failure_class="INFRA_FAILURE")),
        ("g2", dict(stage="act", genre="G2"), {}),
        ("na-a", dict(score_milli=None, failure_class="N/A_EXPOSURE"), {}),
        ("na-prime", {}, dict(score_milli=None, failure_class="N/A_CLOCK")),
    ]:
        baseline[iid], prime[iid] = item(iid, **a_changes), item(iid, **p_changes)
        current[iid] = item(iid, score_milli=-1000)
    # A current-run exclusion must not change the measured A/A′ population.
    current["i-9"]["failure_class"] = "BLOCKED"
    result = flips.flip_list(baseline, current, aa_prime=prime)
    assert result["q0"] == Fraction(2, 10)
    assert result["q0_milli"] == 200
    assert result["counts"]["aa_prime_scored"] == 10
    assert result["counts"]["unstable"] == 2
    flags = {r["item_id"]: r["unstable"] for r in result["rows"]}
    # Instability still reports an outcome difference outside the q0 population,
    # but an item whose A′ never measured it has none.
    assert flags["na-a"] is True and flags["na-prime"] is True
    assert flags["blocked-prime"] is None and flags["infra-prime"] is None


def test_zero_instability_and_empty_scored_intersection():
    baseline, current, _ = band_runs()
    result = flips.flip_list(baseline, current, aa_prime=baseline)
    assert result["q0"] == Fraction(0) and result["q0_milli"] == 0
    empty = flips.flip_list({}, {}, aa_prime={})
    assert empty["q0"] is None and empty["q0_milli"] is None
    assert empty["labels"] == []
    assert empty["counts"]["aa_prime_scored"] == 0


def test_without_prime_null_instability_q0_and_label():
    baseline, current, _ = band_runs()
    result = flips.flip_list(baseline, current)
    assert all(r["unstable"] is None for r in result["rows"])
    assert result["q0"] is None and result["q0_milli"] is None
    assert result["labels"] == ["no A/A′ band"]


@pytest.mark.parametrize("system,plugin", [
    ("hermes-native", False), ("no-memory", False), ("synthetic-system", False),
    ("holographic", True), ("mem0-oss", True), ("omega", True),
])
def test_rerun_exact_published_format_and_plugin_presence(system, plugin):
    source_card = card(system)
    local_paths = dict(packs="/synthetic/local/packs", hermes="/synthetic/local/hermes",
                       plugin_source="/synthetic/local/plugin", out="/synthetic/local/out")
    source_card.update(local_paths)
    record = dict(item(), **local_paths)
    command = flips.rerun_command(source_card, record)
    expected_plugin = " --plugin-source <plugin checkout>" if plugin else ""
    if system == "omega":
        expected_plugin += " --model-cache <model cache>"
    assert command == (
        f"PYTHONHASHSEED=0 bicentennial t2lite --system {system} --packs <packs> "
        f"--pack-hash {'a' * 64} --hermes <hermes checkout>{expected_plugin} "
        "--only life-1:B0:10 --repeat 3 --out <new dir>")
    assert all(path not in command for path in local_paths.values())


@pytest.mark.parametrize("field,value", [
    ("system", "/synthetic/local/system"), ("system", "name;command"),
    ("life", "/synthetic/local/life"), ("branch", "B0:extra"),
    ("branch", "--option"), ("pack_hash", "../bad"),
    ("probe_point", "10 --out /synthetic/local/out"), ("probe_point", True),
])
def test_rerun_refuses_path_or_shell_tokens_in_identifiers(field, value):
    source_card, record = card(), item()
    (source_card if field in ("system", "pack_hash") else record)[field] = value
    with pytest.raises(ValueError):
        flips.rerun_command(source_card, record)


def test_report_canonical_bytes_labels_counts_and_no_fixture_paths():
    baseline, current, prime = valid_band_runs()
    for run in (baseline, current, prime):
        for record in run.values():
            record["hermes"] = "/synthetic/local/hermes"
            record["plugin_source"] = "/synthetic/local/plugin"
    baseline_card, current_card = card("omega", run=baseline), card("omega", run=current)
    prime_card = card("omega", run=prime, aa_prime=True)
    original = copy.deepcopy((baseline_card, current_card, prime_card, baseline, current, prime))
    result = flips.flip_report(current_card, baseline_card, baseline, current, aa_prime=prime,
                               aa_prime_card=prime_card)
    assert set(result) == {"rows", "excluded", "q0", "labels", "counts"}
    assert result["q0"] == dict(numerator=1, denominator=5, milli=200)
    assert result["counts"] == dict(items=10, flips=10, excluded=0, scored=10,
                                    aa_prime_scored=10, unstable=2)
    assert result["labels"] == [current_card["labels"][k] for k in sorted(current_card["labels"])]
    encoded = canon(result)
    assert json.loads(encoded) == result
    reordered = [dict(reversed(list(run.items()))) for run in (baseline, current, prime)]
    reversed_card = dict(reversed(list(current_card.items())))
    reversed_card["labels"] = dict(reversed(list(current_card["labels"].items())))
    again = flips.flip_report(reversed_card, baseline_card, *reordered[:2], aa_prime=reordered[2],
                              aa_prime_card=prime_card)
    assert encoded == canon(again)
    assert b"/synthetic/local/" not in encoded
    assert all("--plugin-source <plugin checkout>" in r["rerun"] for r in result["rows"])
    assert original == (baseline_card, current_card, prime_card, baseline, current, prime)
    no_band = flips.flip_report(current_card, baseline_card, baseline, current)
    assert no_band["q0"] is None
    assert no_band["labels"] == result["labels"] + ["no A/A′ band"]


def test_report_checks_baseline_before_making_rows():
    current, baseline = card(), card()
    baseline["answer_contract_sha256"] = "f" * 64
    with pytest.raises(flips.BaselineRefused) as refused:
        flips.flip_report(current, baseline, {}, {})
    assert refused.value.reason == "answer_contract_sha256"


def prime_report_inputs():
    baseline, current, prime = valid_band_runs()
    return dict(current_card=card(run=current), baseline_card=card(run=baseline),
                baseline_outcomes=baseline, current_outcomes=current,
                aa_prime=prime, aa_prime_card=card(run=prime, aa_prime=True))


def refusal(inputs):
    with pytest.raises(flips.BaselineRefused) as refused:
        flips.flip_report(**inputs)
    return refused.value.reason


def test_prime_with_its_card_gives_the_band():
    assert flips.flip_report(**prime_report_inputs())["q0"] == dict(
        numerator=1, denominator=5, milli=200)


@pytest.mark.parametrize("drop,reason", [
    ("aa_prime_card", "aa_prime:no_card"), ("aa_prime", "aa_prime:no_outcomes")])
def test_prime_outcomes_and_card_come_together(drop, reason):
    inputs = prime_report_inputs()
    del inputs[drop]
    assert refusal(inputs) == reason


def test_prime_card_must_record_aa_prime():
    inputs = prime_report_inputs()
    inputs["aa_prime_card"] = card(run=inputs["aa_prime"])
    assert refusal(inputs) == "aa_prime:flag"


@pytest.mark.parametrize("field,value", [
    ("system", "no-memory"), ("model", "other-model"), ("effort", "high"),
    ("pins.harness_hash", "e" * 64), ("pins.scorer_commit", "e" * 40)])
def test_prime_card_is_checked_against_the_baseline(field, value):
    inputs = prime_report_inputs()
    target = inputs["aa_prime_card"]
    *parents, last = field.split(".")
    for part in parents:
        target = target[part]
    target[last] = value
    assert refusal(inputs) == f"aa_prime:{field}"


def test_invalid_prime_card_is_refused_as_such():
    inputs = prime_report_inputs()
    del inputs["aa_prime_card"]["counts"]
    assert refusal(inputs) == "invalid_card:aa_prime"


@pytest.mark.parametrize("side,card_key,run_key", [
    ("current", "current_card", "current_outcomes"),
    ("baseline", "baseline_card", "baseline_outcomes"),
    ("aa_prime", "aa_prime_card", "aa_prime")])
@pytest.mark.parametrize("change", [
    dict(score_milli=0), dict(failure_class="FAIL_TASK"), dict(base_verdict="OMISSION"),
    dict(stage="remember"), "float_score", "extra_card_item", "missing_card_item"])
def test_each_card_vouches_only_for_its_own_outcomes(side, card_key, run_key, change):
    inputs = prime_report_inputs()
    run = inputs[run_key]
    if change == "extra_card_item":
        inputs[card_key] = card(run=dict(run, extra=item("extra")), aa_prime=side == "aa_prime")
    elif change == "missing_card_item":
        inputs[card_key] = card(run={k: v for k, v in run.items() if k != "i-9"},
                                aa_prime=side == "aa_prime")
    elif change == "float_score":
        run["i-5"]["score_milli"] = float(run["i-5"]["score_milli"])
    else:
        run["i-5"].update(change)  # the outcome record changes; its card row does not
    assert refusal(inputs) == f"items:{side}"


def test_cards_cannot_vouch_for_swapped_outcomes():
    inputs = prime_report_inputs()
    inputs["baseline_outcomes"], inputs["current_outcomes"] = (
        inputs["current_outcomes"], inputs["baseline_outcomes"])
    assert refusal(inputs) == "items:current"


def test_mapping_ids_must_match_and_dataclass_inputs_are_supported():
    record = flips.ItemOutcome.from_dict(item())
    assert flips.flip_list({"item-0": record}, {"item-0": record})["rows"] == []
    without_id = item()
    del without_id["item_id"]
    assert flips.flip_list({"item-0": without_id}, {"item-0": record})["rows"] == []
    with pytest.raises(ValueError, match="outcome key"):
        flips.flip_list({"wrong-id": record}, {"wrong-id": record})
    with pytest.raises(ValueError, match="identical item ids"):
        flips.flip_list({"item-0": record}, {})
    with pytest.raises(ValueError, match="identical item ids"):
        flips.flip_list({"item-0": record}, {"item-0": record}, aa_prime={})


def test_plugin_lists_equal_the_registry():
    from bicentennial.systems import hermes_plugin

    assert flips.PLUGIN_SYSTEMS == hermes_plugin.PROVIDERS.keys() | hermes_plugin.ENGINES.keys()
    assert flips.MODEL_CACHE_SYSTEMS == {
        name for name, env in hermes_plugin.WORKER_ENV.items()
        if any("{model_cache}" in value for value in env.values())}
