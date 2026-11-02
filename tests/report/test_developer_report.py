"""Offline constructed-row acceptance for the developer statistics contract."""

from copy import deepcopy
from dataclasses import fields
from fractions import Fraction

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.ocsim.run import rate_stats
from bicentennial.report import developer
from bicentennial.report.receipt import build_receipt
from bicentennial.report.t2lite_flips import ItemOutcome, flip_list

LABEL = "a developer signal; not predictive of the full tier; confirm on Ring 1 before claiming"
FEW = "too few lives for a clustered interval"


def row(life="life", item="item", score=0, **kw):
    return dict(life=life, branch="branch", item_id=item, cell_id="cell", stage="remember",
                score_milli=score, failure_class=None, base_verdict="PASS",
                not_scored_live=False, **kw)


def runs(deltas):
    a = [row(f"life-{i:02}", score=value) for i, value in enumerate(deltas)]
    b = [dict(r, score_milli=0) for r in a]
    return a, b


def report(a, b, **kw):
    return developer.developer_report(a, b, seed="constructed", **kw)


def fraction(number):
    return Fraction(number["numerator"], number["denominator"])


@pytest.mark.parametrize("n", [10, 9])
def test_item4_planted_difference_and_interval_threshold(n):
    result = report(*runs([250] * n))
    for stat in (result["pooled"]["diff"], result["cells"][0]["diff"]):
        assert stat["estimate"] == dict(numerator=1, denominator=4, milli=250)
        assert fraction(stat["p"]) == Fraction(2, 2**n)
        assert stat["direction"] == "current higher"
        assert stat["life_count"] == n
        assert stat["discordant"] == dict(current_higher=n, previous_higher=0)
        if n == 10:
            assert [fraction(x) for x in stat["interval"]] == [Fraction(1, 4)] * 2
        else:
            assert stat["interval"] == FEW


def test_items3_4_equal_life_weighting_pooled_and_negative_direction():
    a = [row("a", "one", 1000), row("a", "two", 0), row("b", "one", -1000)]
    a[1]["cell_id"] = "other"
    b = [dict(r, score_milli=0) for r in a]
    result = report(a, b)
    pooled = result["pooled"]["diff"]
    assert fraction(pooled["estimate"]) == Fraction(-1, 4)
    assert pooled["direction"] == "previous higher"
    assert pooled["discordant"] == dict(current_higher=1, previous_higher=1)
    assert fraction(result["cells"][0]["diff"]["estimate"]) == 0
    assert fraction(pooled["p"]) == 1
    assert report(b, a)["pooled"]["diff"]["direction"] == "current higher"


def test_items5_6_degenerate_and_four_discordant_not_estimable():
    a, b = runs([0] * 6)
    band = report(a, b, aa=(a, b))["pooled"]["aa"]
    assert band["q0"] == dict(numerator=0, denominator=1, milli=0)
    assert band["scored_items"] == 6
    assert band["wilson_95_ppm"] == rate_stats(0, 6)[2]
    assert band["sensitivity"]["status"] == "not estimable"
    a, b = runs([100, 200, 300, 400, 0, 0])
    result = report(a, b, aa=(a, b))
    for band in (result["cells"][0]["aa"], result["pooled"]["aa"]):
        assert band["sensitivity"]["discordant_items"] == 4
        assert band["sensitivity"]["status"] == "not estimable"
        assert band["sensitivity"]["value"] is None


def test_decision4_sample_standard_deviation_and_mde_rounding():
    # Contributions 1 and 3: sample s^2=2, L=2, hence MDE=2.80 exactly.
    a = [row("a", str(i), 1000) for i in range(3)]
    a += [row("b", str(i), 3000) for i in range(3)]
    b = [dict(r, score_milli=0) for r in a]
    sensitivity = report(a, b, aa=(a, b))["pooled"]["aa"]["sensitivity"]
    assert sensitivity["status"] == "approximate"
    assert sensitivity["approximate"] is True
    assert sensitivity["life_count"] == 2
    assert sensitivity["value"] == dict(numerator=14, denominator=5, milli=2800)
    assert sensitivity["exact_test_limit"] == "p cannot reach 0.025 unless at least 6 lives differ"
    a, b = runs([100, 200, 300, 400, 500])
    # Sample variance=1/40, MDE^2=49/1250; root truncated to six decimal places.
    mde = report(a, b, aa=(a, b))["pooled"]["aa"]["sensitivity"]["value"]
    assert fraction(mde) == Fraction(197989, 1000000)
    assert mde["milli"] == 198


@pytest.mark.parametrize("kind", ["one_life", "zero_variance"])
def test_item6_degenerate_spread_is_never_zero_mde(kind):
    a, b = runs([100] * 5)
    if kind == "one_life":
        a = [dict(r, life="one", item_id=str(i)) for i, r in enumerate(a)]
        b = [dict(r, life="one", item_id=str(i)) for i, r in enumerate(b)]
    result = report(a, b, aa=(a, b))["pooled"]["aa"]["sensitivity"]
    assert result["status"] == "not estimable"
    assert result["value"] is None


@pytest.mark.parametrize("field,value,reason", [
    ("failure_class", "INFRA", "INFRA"),
    ("failure_class", "INFRA_FAILURE", "INFRA_FAILURE"),
    ("base_verdict", "INFRA", "INFRA"),
    ("failure_class", "BLOCKED", "BLOCKED"),
    ("base_verdict", "BLOCKED", "BLOCKED"),
    ("not_scored_live", True, "not_scored_live"),
    ("score_milli", None, "no_int_score"),
])
@pytest.mark.parametrize("side", [0, 1])
def test_item2_exclusion_from_every_statistic_and_item8_taxonomy(field, value, reason, side):
    a, b = runs([100, 200])
    (a, b)[side][0][field] = value
    result = report(a, b, aa=(a, b))
    for entry in (result["pooled"], result["cells"][0]):
        stat, band = entry["diff"], entry["aa"]
        assert stat["excluded_items"] == 1
        assert stat["scored_items"] == stat["life_count"] == 1
        assert stat["estimate"]["milli"] == 200
        assert stat["discordant"]["current_higher"] == 1
        assert band["scored_items"] == band["unstable_items"] == 1
        assert band["comparison"]["excluded_items"] == 1
        assert band["sensitivity"]["discordant_items"] == 1
    taxonomy = result["failure_taxonomy"]["current" if side == 0 else "previous"]
    assert len(taxonomy) == 1
    assert taxonomy[0]["exclusion_reason"] == reason
    assert taxonomy[0]["count"] == 0
    assert taxonomy[0]["excluded_count"] == 1


def test_item8_failure_class_precedence_fallback_pass_and_schedule_stage():
    a = [row(item="a"), row(item="b"), row(item="c"), row(item="d")]
    a[0].update(failure_class="TIMEOUT", base_verdict="MISS", stage="survive")
    a[1].update(base_verdict="MISS", stage="act")
    a[2].update(base_verdict="MISS", stage="act")
    result = report(a, deepcopy(a))["failure_taxonomy"]
    expected = [dict(cell_id="cell", stage="act", failure="MISS", exclusion_reason=None,
                     count=2, excluded_count=0),
                dict(cell_id="cell", stage="survive", failure="TIMEOUT", exclusion_reason=None,
                     count=1, excluded_count=0)]
    assert result == dict(current=expected, previous=expected)


@pytest.mark.parametrize("change,code", [("missing", "items_mismatch"),
    ("extra", "items_mismatch"), ("aa_missing", "aa_prime:items_mismatch"),
    ("aa_extra", "aa_prime:items_mismatch"), ("duplicate", "invalid_rows"),
    ("metadata", "invalid_rows")])
def test_item11_pairing_refusals(change, code):
    a, b = runs([100, 200])
    aa = None
    if change.startswith("aa_"):
        aa = (deepcopy(a), deepcopy(b))
        target = aa[1]
    else:
        target = b
    if change.endswith("missing"):
        target.pop()
    elif change.endswith("extra"):
        target.append(row("extra"))
    elif change == "duplicate":
        target.append(deepcopy(target[0]))
    else:
        target[0]["cell_id"] = "other"
    with pytest.raises(developer.DeveloperReportRefused) as caught:
        report(a, b, aa=aa)
    assert caught.value.code == code
    assert str(caught.value) == code


@pytest.mark.parametrize("field", list(row()))
@pytest.mark.parametrize("mode", ["missing", "wrong_type"])
def test_item11_malformed_rows_refused(field, mode):
    a, b = runs([100])
    if mode == "missing":
        del a[0][field]
    else:
        a[0][field] = 1 if field != "score_milli" else True
    with pytest.raises(developer.DeveloperReportRefused, match="^invalid_rows$"):
        report(a, b)
    with pytest.raises(developer.DeveloperReportRefused, match="^invalid_rows$"):
        report(b, b, aa=(a, b))


def test_decision2_wilson_grid_matches_simulation_without_report_dependency():
    for n in (0, 1, 2, 5, 10, 97, 1000):
        for x in range(n + 1):
            assert developer._wilson(x, n) == rate_stats(x, n)[2]


def test_item5_q0_matches_flip_list_and_diff_uses_score_discordance():
    a, b = runs([100, 0, 0, 400, 0])
    for i, (left, right) in enumerate(zip(a, b, strict=True)):
        left["item_id"] = right["item_id"] = str(i)
    a[1]["failure_class"] = "TIMEOUT"
    a[3]["failure_class"] = "INFRA"
    a[4]["score_milli"] = None
    def outcomes(rows):
        return {str(i): ItemOutcome(**dict(
            {f.name: None for f in fields(ItemOutcome)},
            **{k: v for k, v in r.items() if k != "not_scored_live"},
            probe_point=1, genre="G1", envelope="missing")) for i, r in enumerate(rows)}
    flips = flip_list(outcomes(a), outcomes(a), aa_prime=outcomes(b))
    band = report(a, b, aa=(a, b))["pooled"]["aa"]
    assert fraction(band["q0"]) == flips["q0"] == Fraction(2, 3)
    assert band["q0"]["milli"] == flips["q0_milli"]
    assert band["comparison"]["discordant"]["current_higher"] == 1
    assert band["sensitivity"]["discordant_items"] == 1


def test_items9_10_determinism_schema_labels_no_aa_and_no_mutation(monkeypatch):
    a, b = runs([1, 2, 3])
    before = deepcopy((a, b))
    calls = []
    original = developer.validate
    def checked(name, value):
        calls.append(name)
        original(name, value)
    monkeypatch.setattr(developer, "validate", checked)
    first = report(a, b)
    second = report(list(reversed(a)), list(reversed(b)))
    assert canon(first) == canon(second)
    assert (a, b) == before
    assert calls == ["developer_report"] * 2
    assert first["label"] == LABEL
    for entry in [first["pooled"], *first["cells"]]:
        assert entry["aa"]["status"] == "no A/A′ pair supplied"
        assert entry["aa"]["sensitivity"]["status"] == "no A/A′ pair supplied"
    for bad in [dict(first, extra=1), dict(first, label="improved")]:
        with pytest.raises(ValueError):
            validate("developer_report", bad)
    bad = deepcopy(first)
    bad["pooled"]["diff"]["estimate"]["denominator"] = 0
    with pytest.raises(ValueError):
        validate("developer_report", bad)


def test_item10_empty_and_all_excluded_are_defined_and_validate():
    for a, b in [([], []), ([dict(row(), score_milli=None)], [row()])]:
        result = report(a, b, aa=(a, b))
        validate("developer_report", result)
        assert result["pooled"]["diff"]["estimate"] is None
        assert result["pooled"]["diff"]["p"] is None
        assert result["pooled"]["aa"]["q0"] is None
        assert result["pooled"]["aa"]["wilson_95_ppm"] == [0, 1000000]


def test_decisions1_5_keyed_draw_names_and_exact_interval_serialization(monkeypatch):
    calls = []
    def sign(values, *, seed, name):
        calls.append(("sign", seed, name))
        return Fraction(1, 512)
    def bootstrap(values, *, seed, name):
        assert len(values) == 10
        calls.append(("bootstrap", seed, name))
        return Fraction(-1, 3), Fraction(2, 3)
    monkeypatch.setattr(developer, "sign_flip_p", sign)
    monkeypatch.setattr(developer, "bootstrap_ci", bootstrap)
    a, b = runs([1] * 10)
    result = report(a, b, aa=(a, b))
    assert set(calls) == {(method, "constructed", name) for method in ("sign", "bootstrap")
                         for name in ("cell", "pooled", "aa:cell", "aa:pooled")}
    assert result["pooled"]["diff"]["interval"] == [
        dict(numerator=-1, denominator=3, milli=-333),
        dict(numerator=2, denominator=3, milli=667)]
    assert developer._number(Fraction(1, 2000))["milli"] == 0
    assert developer._number(Fraction(3, 2000))["milli"] == 2


def receipt(latencies, roles, wall, growth, timings=None):
    return build_receipt(run_status="COMPLETE", wall_start_ms=10, wall_end_ms=10+wall,
        latency_ms=latencies, load_milli=[0, 0, 0], busy_marker_readings=[],
        tokens_by_role=roles, runtime_by_role={}, spend_micro_usd=0,
        store_growth_bytes=growth, process_ids=[], ports=[], temporary_paths=[],
        raw_body_digest="0" * 64, timings=timings)


def test_item7_receipt_deltas_and_multiarm_scope():
    timings = [dict(arm=arm, life="life", branch="branch", attempt=0, pin_check_ms=0,
                    egress_pid_samples=None, egress_sample_ms=None, sessions=[])
               for arm in ("system", "no-memory")]
    current = receipt([10, 20, 30], {"probe_main": (100, 20), "write_turn": (10, 3)},
                      1000, 20, timings)
    previous = receipt([5, 15], {"probe_main": (40, 10), "aux": (5, 2)}, 700, 30)
    metrics = report([], [], receipts=(current, previous))["operating_metrics"]
    assert metrics == dict(scope="covers every arm the run executed", wall_ms=300, requests=1,
        store_growth_bytes=-10, tokens_by_role=[dict(role="aux", input=-5, output=-2),
            dict(role="probe_main", input=60, output=10), dict(role="write_turn", input=10, output=3)],
        latency_summary=dict(n=1, p50=15, p90=15, p95=15, max=15))
    empty = receipt([], {}, 0, 0)
    result = report([], [], receipts=(current, empty))["operating_metrics"]
    assert result["latency_summary"] == dict(n=3, p50=None, p90=None, p95=None, max=None)
    assert report([], [])["operating_metrics"] is None


def test_items5_6_cell_sensitivity_does_not_borrow_pooled_discordance():
    a, b = runs([100, 200, 300, 400, 100, 200, 300, 400, 500, 600])
    for i, (left, right) in enumerate(zip(a, b, strict=True)):
        for r in (left, right):
            r.update(life=f"life-{i % 2}", item_id=str(i),
                     cell_id="sparse" if i < 4 else "dense")
    result = report(a, b, aa=(a, b))
    cells = {r["cell_id"]: r for r in result["cells"]}
    assert cells["sparse"]["aa"]["sensitivity"]["status"] == "not estimable"
    assert cells["sparse"]["aa"]["scored_items"] == 4
    assert cells["dense"]["aa"]["sensitivity"]["status"] == "approximate"
    assert cells["dense"]["aa"]["scored_items"] == 6
    assert result["pooled"]["aa"]["sensitivity"]["status"] == "approximate"
    assert result["pooled"]["aa"]["scored_items"] == 10
