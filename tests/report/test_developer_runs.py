"""Offline T2 directory, CLI, reproducibility and per-life acceptance."""

import copy
import hashlib
import json
import re
import runpy
from fractions import Fraction
from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.canon import canon
from bicentennial.report import developer, developer_runs, t2_card
from bicentennial.report.receipt import build_receipt
from bicentennial.report.t2lite_flips import BASELINE_FIELDS

ROOT = Path(__file__).resolve().parents[2]
CARD = runpy.run_path(str(Path(__file__).with_name("test_t2_card.py")))["complete_card"]
ROWS = runpy.run_path(str(Path(__file__).with_name("test_developer_report.py")))


def number(value):
    return None if value is None else Fraction(value["numerator"], value["denominator"])


def put(directory, name, value):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(value))


def receipt(*, n=1, wall=100, wait="3.0"):
    return build_receipt(run_status="COMPLETE", wall_start_ms=0, wall_end_ms=wall,
        latency_ms=[10] * n, load_milli=[0, 0, 0], busy_marker_readings=[],
        tokens_by_role={"probe_main": (n * 10, n)}, runtime_by_role={}, spend_micro_usd=0,
        store_growth_bytes=n * 5, process_ids=[], ports=[], temporary_paths=[],
        raw_body_digest="0" * 64, turn_wait_s=wait)


def write_run(directory, *, card=None, floor_score=0, cached=False, n=1, wall=100, arm=50,
              slots=8):
    card = CARD() if card is None else card
    if cached:
        for unit in card["floor"]["units"].values():
            unit["cached"] = True
        card["counts"].update(t2_card._row_counts(card))
    t2_card.validate_t2_card(card)
    put(directory, "receipt.json", receipt(n=30, wall=wall + 800))
    put(directory, "card.json", card)
    put(directory, "receipts/system.json", receipt(n=n, wall=wall))
    put(directory, "units.json", {"slots": slots,
        "arm_time": {"arms": {"system": {"arm_time_ms": arm}}}})
    floor = {}
    for item in card["items"]:
        unit = floor.setdefault(f"{item['life']}/{item['branch']}",
                               dict(outcomes={}, stops={}, served_identity="synthetic-floor"))
        unit["outcomes"][item["item_id"]] = dict(
            {key: item[key] for key in developer_runs.ROW_FIELDS}, score_milli=floor_score)
    put(directory, "no_memory.json", floor)
    return directory


@pytest.fixture
def pair(tmp_path):
    return write_run(tmp_path / "current"), write_run(tmp_path / "previous")


@pytest.fixture(autouse=True)
def offline_cli(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)


def invoke(pair, out, prime=None):
    args = ["report", "--current", str(pair[0]), "--previous", str(pair[1]), "--out", str(out)]
    return cli.main(args + ([] if prime is None else ["--aa-prime", str(prime)]))


def test_per_life_reversal_zero_and_regression():
    a, b = ROWS["runs"]([1000, -250, 0])
    report = developer.developer_report(a, b, seed="constructed")
    table = report["pooled"]["per_life"]
    assert [r["life"] for r in table] == [r["life"] for r in a]
    assert [number(r["contribution"]) for r in table] == [1, Fraction(-1, 4), 0]
    assert all(r["scored_items"] == 1 for r in table)
    assert all(r["current_lift_items"] == r["previous_lift_items"] == 0 for r in table)
    for entry in [report["pooled"], *report["cells"]]:
        assert entry["diff"]["sign_changes"] == 1
    regression = developer.developer_report(b, a, seed="constructed")
    assert regression["pooled"]["diff"]["direction"] == "previous higher"
    assert regression["pooled"]["diff"]["sign_changes"] == 1
    zero = developer.developer_report(*ROWS["runs"]([1000, -1000, 0]), seed="constructed")
    assert zero["pooled"]["diff"]["sign_changes"] is None


@pytest.mark.parametrize("cached", [False, True])
def test_floor_lifts_use_each_runs_floor(tmp_path, cached):
    current = write_run(tmp_path / "current", floor_score=-500, cached=cached)
    previous = write_run(tmp_path / "previous", floor_score=100, cached=cached)
    report = developer_runs.report_runs(current, previous)
    table = {r["life"]: r for r in report["pooled"]["per_life"]}
    assert number(table["life-alpha"]["current_lift"]) == Fraction(1, 2)
    assert number(table["life-alpha"]["previous_lift"]) == Fraction(-1, 10)
    assert number(table["life-beta"]["current_lift"]) == Fraction(3, 2)
    assert number(table["life-beta"]["previous_lift"]) == Fraction(9, 10)
    floor = json.loads((current / "no_memory.json").read_bytes())
    floor["life-alpha/B0"]["outcomes"]["item-a"].update(failure_class="BLOCKED", score_milli=None)
    put(current, "no_memory.json", floor)
    table = developer_runs.report_runs(current, previous)["pooled"]["per_life"]
    assert number(table[0]["current_lift"]) == Fraction(3, 2)


@pytest.mark.parametrize("side", ["system", "floor"])
def test_lift_exclusion_in_either_arm_and_null(side):
    a, b = ROWS["runs"]([1000, 1000])
    floor = copy.deepcopy(b)
    (a if side == "system" else floor)[0]["not_scored_live"] = True
    result = developer.developer_report(a, b, floors=(floor, b), seed="constructed")
    table = {r["life"]: r for r in result["pooled"]["per_life"]}
    if side == "floor":
        assert table[a[0]["life"]]["current_lift"] is None
        assert table[a[0]["life"]]["current_lift_items"] == 0
    else:
        assert a[0]["life"] not in table
    assert number(table[a[1]["life"]]["current_lift"]) == 1
    assert table[a[1]["life"]]["current_lift_items"] == 1


@pytest.mark.parametrize("excluded_side", ["current", "previous"])
def test_lift_item_counts(tmp_path, excluded_side):
    blocked = CARD()
    blocked["items"][0].update(failure_class="BLOCKED", score_milli=None,
        worst_case_milli=None, envelope=None, infra_reruns=2, repro=None)
    blocked["counts"].update(t2_card._row_counts(blocked))
    current = write_run(tmp_path / "current", card=blocked if excluded_side == "current" else None)
    previous = write_run(tmp_path / "previous", card=blocked if excluded_side == "previous" else None)
    report = developer_runs.report_runs(current, previous)
    row = report["pooled"]["per_life"][0]
    assert row["life"] == "life-alpha"
    assert row["scored_items"] == 1
    current_excluded = excluded_side == "current"
    assert row["current_lift_items"] == (1 if current_excluded else 2)
    assert row["previous_lift_items"] == (2 if current_excluded else 1)
    assert number(row["current_lift"]) == (1 if current_excluded else 0)
    assert number(row["previous_lift"]) == (0 if current_excluded else 1)
    assert number(row["contribution"]) == 0
    assert number(row["current_lift"]) - number(row["previous_lift"]) != number(row["contribution"])
    text = developer_runs.summary(report)
    assert "current floor lift | current lift items | previous floor lift | previous lift items" in text
    assert ("life-alpha | 1 | 0/1 | 1/1 | 1 | 0/1 | 2" if current_excluded else
            "life-alpha | 1 | 0/1 | 0/1 | 2 | 1/1 | 1") in text


def assert_refusal(pair, out, code, capsys, prime=None):
    with pytest.raises(developer.DeveloperReportRefused) as caught:
        developer_runs.report_runs(*pair, prime)
    assert caught.value.code == code
    assert invoke(pair, out, prime) == 3
    captured = capsys.readouterr()
    assert captured.err == code + "\n"
    assert captured.out == ""
    assert not out.exists()


@pytest.mark.parametrize("artifact,change,code", [
    ("receipt.json", "incomplete", "run_incomplete"),
    ("receipt.json", "missing", "run_invalid:receipt"),
    ("receipt.json", "invalid", "run_invalid:receipt"),
    ("card.json", "missing", "run_invalid:card"),
    ("card.json", "tier", "tier_unsupported"),
    ("card.json", "invalid", "run_invalid:card"),
    ("receipts/system.json", "missing", "run_invalid:receipt"),
    ("receipts/system.json", "invalid", "run_invalid:receipt"),
    ("units.json", "missing", "run_invalid:units"),
    ("units.json", "invalid", "run_invalid:units"),
    ("units.json", "negative", "run_invalid:units"),
    ("units.json", "bool", "run_invalid:units"),
    ("units.json", "slots_missing", "run_invalid:units"),
    ("units.json", "slots_zero", "run_invalid:units"),
    ("units.json", "slots_bool", "run_invalid:units"),
    ("units.json", "slots_string", "run_invalid:units"),
    ("no_memory.json", "missing", "run_invalid:floor"),
    ("no_memory.json", "unit", "run_invalid:floor"),
    ("no_memory.json", "item", "run_invalid:floor"),
    ("no_memory.json", "field", "run_invalid:floor"),
    ("no_memory.json", "identity", "run_invalid:floor"),
    ("no_memory.json", "invalid", "run_invalid:floor"),
])
def test_artifact_refusals_loader_and_command(pair, tmp_path, capsys, artifact, change, code):
    path = pair[0] / artifact
    value = json.loads(path.read_bytes())
    if change == "missing":
        path.unlink()
    else:
        if change == "incomplete":
            value["run_status"] = "INFRA_FAILURE"
        elif change == "tier":
            value = {"tier": "T3"}  # Tier refusal must precede card validation.
        elif change == "unit":
            value.pop(next(iter(value)))
        elif change in ("item", "field", "identity"):
            outcomes = next(iter(value.values()))["outcomes"]
            if change == "item":
                outcomes.clear()
            elif change == "field":
                next(iter(outcomes.values())).pop("base_verdict")
            else:
                next(iter(outcomes.values()))["item_id"] = "different"
        elif change in ("negative", "bool"):
            value["arm_time"]["arms"]["system"]["arm_time_ms"] = -1 if change == "negative" else True
        elif change == "slots_missing":
            value.pop("slots")
        elif change.startswith("slots_"):
            value["slots"] = {"slots_zero": 0, "slots_bool": True, "slots_string": "8"}[change]
        else:
            value = {"tier": "T2"} if artifact == "card.json" else {}
        put(pair[0], artifact, value)
    with pytest.raises(developer.DeveloperReportRefused) as caught:
        developer_runs.load_run(pair[0])
    assert caught.value.code == code
    assert_refusal(pair, tmp_path / "out", code, capsys)


@pytest.mark.parametrize("field", BASELINE_FIELDS)
@pytest.mark.parametrize("prime_side", [False, True])
def test_baseline_fields_from_imported_tuple(pair, tmp_path, capsys, field, prime_side):
    prime = write_run(tmp_path / "prime") if prime_side else None
    directory = prime if prime_side else pair[0]
    card = json.loads((directory / "card.json").read_bytes())
    parent = card
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    old = parent[parts[-1]]
    parent[parts[-1]] = "e" * len(old) if field.endswith("commit") or "hash" in field or "sha256" in field else old + "-different"
    put(directory, "card.json", card)
    code = "run_invalid:card" if field == "profile" else (
        "aa_prime:" if prime_side else "") + "baseline_mismatch:" + field
    assert_refusal(pair, tmp_path / "out", code, capsys, prime)


@pytest.mark.parametrize("field", ["route_table_hash", "write_turn_package_hash"])
@pytest.mark.parametrize("prime_side", [False, True])
def test_t2_comparability_pins(pair, tmp_path, capsys, field, prime_side):
    prime = write_run(tmp_path / "prime") if prime_side else None
    directory = prime if prime_side else pair[0]
    card = json.loads((directory / "card.json").read_bytes())
    card["pins"][field] = "e" * 64
    put(directory, "card.json", card)
    code = ("aa_prime:" if prime_side else "") + "baseline_mismatch:pins." + field
    assert_refusal(pair, tmp_path / "out", code, capsys, prime)


def test_t2lite_baseline_fields_unchanged():
    assert BASELINE_FIELDS == (
        "system", "pack_hash", "seed_hash", "model", "effort", "pins.harness_hash",
        "answer_contract_sha256", "pins.benchmark_commit", "pins.generator_commit",
        "pins.director_commit", "pins.scorer_commit", "profile",
    )


def test_aa_prime_system_hash_refusal(pair, tmp_path, capsys):
    card = CARD()
    card["pins"]["system_hash"] = "e" * 64
    prime = write_run(tmp_path / "prime", card=card)
    assert_refusal(pair, tmp_path / "out", "aa_prime:system_hash", capsys, prime)


@pytest.mark.parametrize("side", ["current", "previous", "prime", "system"])
def test_turn_wait_refusal(pair, tmp_path, capsys, side):
    prime = write_run(tmp_path / "prime")
    directory = {"current": pair[0], "previous": pair[1], "prime": prime, "system": pair[0]}[side]
    name = "receipts/system.json" if side == "system" else "receipt.json"
    value = json.loads((directory / name).read_bytes())
    value["turn_wait_s"] = "2.0"
    put(directory, name, value)
    assert_refusal(pair, tmp_path / "out", "turn_wait_mismatch", capsys, prime)


def test_version_hashes_command_output_and_no_overwrite(pair, tmp_path, capsys):
    card = CARD()
    card["pins"]["system_hash"] = "e" * 64
    write_run(pair[0], card=card)
    out = tmp_path / "report.json"
    assert invoke(pair, out) == 0
    report = json.loads(out.read_bytes())
    assert out.read_bytes() == canon(report)
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == report["label"]
    assert captured.err == ""
    for key in ("current_system_hash", "previous_system_hash"):
        assert report["pairing"][key] in captured.out
    assert report["pairing"]["current_system_hash"] != report["pairing"]["previous_system_hash"]
    for text in ("q0 fraction", "Wilson 95% interval", "A − A′", "sensitivity approximate",
                 "p cannot reach 0.025 unless at least 6 lives differ", "Failure taxonomy",
                 "Per life", "sign_changes", "too few lives for a clustered interval"):
        assert text in captured.out
    before = out.read_bytes()
    assert invoke(pair, out) == 3
    assert capsys.readouterr().err == "out_exists\n"
    assert out.read_bytes() == before
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "absent")
    assert invoke(pair, link) == 3
    assert capsys.readouterr().err == "out_exists\n"


def test_numeric_crashed_g2_uses_list_and_same_statistics(pair, tmp_path):
    prime = write_run(tmp_path / "prime")
    before = developer_runs.report_runs(*pair, prime)
    for directory in (*pair, prime):
        card = json.loads((directory / "card.json").read_bytes())
        action = next(r for r in card["items"] if r["stage"] == "act")
        action.update(failure_class="SYSTEM_FAILURE", score_milli=0, worst_case_milli=-1000,
                      envelope=None, accuracy_correct=False)
        t2_card.validate_t2_card(card)
        put(directory, "card.json", card)
        row = next(r for r in developer_runs.load_run(directory).rows if r["stage"] == "act")
        assert row["not_scored_live"] is True
    after = developer_runs.report_runs(*pair, prime)
    for first, second in zip([before["pooled"], *before["cells"]],
                             [after["pooled"], *after["cells"]], strict=True):
        assert first["diff"] == second["diff"]
        assert first["aa"] == second["aa"]
        assert first["diff"]["scored_items"] == 3
        assert first["diff"]["life_count"] < 10


@pytest.mark.parametrize("with_prime", [False, True])
def test_seed_card_bytes_and_reproducible_command(pair, tmp_path, with_prime):
    prime = write_run(tmp_path / "prime") if with_prime else None
    directories = [*pair] + ([] if prime is None else [prime])
    expected = hashlib.sha256(b"".join((d / "card.json").read_bytes() for d in directories)).hexdigest()
    out1, out2 = tmp_path / "one", tmp_path / "two"
    assert invoke(pair, out1, prime) == invoke(pair, out2, prime) == 0
    assert out1.read_bytes() == out2.read_bytes()
    assert json.loads(out1.read_bytes())["pairing"]["seed"] == expected
    for directory in directories:
        path = directory / "card.json"
        raw = path.read_bytes()
        path.write_bytes(raw + b" ")
        assert developer_runs.report_runs(*pair, prime)["pairing"]["seed"] != expected
        path.write_bytes(raw)


def test_operating_metrics_system_receipt_and_arm_time(tmp_path):
    current = write_run(tmp_path / "current", n=5, wall=900, arm=120)
    previous = write_run(tmp_path / "previous", n=2, wall=100, arm=80)
    metrics = developer_runs.report_runs(current, previous)["operating_metrics"]
    assert metrics["scope"] == developer_runs.T2_SCOPE
    assert metrics["wall_ms"] == 40
    assert metrics["requests"] == 3
    assert metrics["tokens_by_role"] == [dict(role="probe_main", input=30, output=3)]
    assert metrics["store_growth_bytes"] == 15
    assert metrics["latency_summary"]["n"] == 3


def test_slots_reported_and_equal_slots_keep_wall_delta(tmp_path):
    current = write_run(tmp_path / "current", arm=120)
    previous = write_run(tmp_path / "previous", arm=80)
    report = developer_runs.report_runs(current, previous)
    assert report["pairing"]["current_slots"] == report["pairing"]["previous_slots"] == 8
    assert report["pairing"]["aa_prime_slots"] is None
    assert report["operating_metrics"]["wall_ms"] == 40
    assert report["operating_metrics"]["wall_ms_reason"] is None
    text = developer_runs.summary(report)
    assert "current_slots: 8" in text and "previous_slots: 8" in text
    assert "wall_ms: 40" in text and "wall_ms_reason: null" in text


def test_different_slots_null_wall_delta(tmp_path):
    current = write_run(tmp_path / "current", arm=120, n=5)
    previous = write_run(tmp_path / "previous", arm=80, n=2)
    equal = developer_runs.report_runs(current, previous)
    write_run(current, arm=120, n=5, slots=4)
    different = developer_runs.report_runs(current, previous)
    assert different["pairing"]["current_slots"] == 4
    assert different["pairing"]["previous_slots"] == 8
    assert different["operating_metrics"]["wall_ms"] is None
    assert different["operating_metrics"]["wall_ms_reason"] == "slots_differ"
    text = developer_runs.summary(different)
    assert "current_slots: 4" in text and "previous_slots: 8" in text
    assert "wall_ms: null" in text and 'wall_ms_reason: "slots_differ"' in text
    for report in (equal, different):
        del report["pairing"]["current_slots"]
        del report["operating_metrics"]["wall_ms"]
        del report["operating_metrics"]["wall_ms_reason"]
    assert different == equal


def test_aa_prime_slots_reported_only(tmp_path):
    current = write_run(tmp_path / "current", arm=120)
    previous = write_run(tmp_path / "previous", arm=80)
    prime = write_run(tmp_path / "prime")
    equal = developer_runs.report_runs(current, previous, prime)
    write_run(prime, slots=4)
    different = developer_runs.report_runs(current, previous, prime)
    assert different["pairing"]["aa_prime_slots"] == 4
    assert "aa_prime_slots: 4" in developer_runs.summary(different)
    assert different["operating_metrics"]["wall_ms"] == 40
    assert different["operating_metrics"]["wall_ms_reason"] is None
    equal["pairing"]["aa_prime_slots"] = 4
    assert different == equal


def test_aa_is_previous_and_prime(pair, tmp_path):
    prime_card = CARD()
    prime_card["items"][0].update(score_milli=1000, worst_case_milli=1000, repro=None)
    prime_card["counts"].update(t2_card._row_counts(prime_card))
    prime = write_run(tmp_path / "prime", card=prime_card)
    current_card = CARD()
    current_card["items"][1].update(score_milli=-1000, worst_case_milli=-1000)
    write_run(pair[0], card=current_card)
    report = developer_runs.report_runs(*pair, prime)
    expected = developer.developer_report(developer_runs.load_run(pair[1]).rows,
        developer_runs.load_run(prime).rows, seed=report["pairing"]["seed"])
    assert report["pooled"]["aa"]["comparison"] == expected["pooled"]["diff"]


def test_unexpected_error_code(pair, tmp_path, capsys, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("constructed")
    monkeypatch.setattr(developer_runs, "report_runs", broken)
    assert invoke(pair, tmp_path / "out") == 70
    assert capsys.readouterr().err == "tool_failure\n"


def test_guide_flags_codes_label_and_erratum(capsys):
    text = (ROOT / "docs/developers/report.md").read_text()
    with pytest.raises(SystemExit) as caught:
        cli.main(["report", "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    for flag in re.findall(r"`(--[^`\s]+)", text):
        assert flag in help_text
    table = text.split("| Code | Cause |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
    codes = re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE)
    assert len(codes) == len(set(codes))
    assert set(codes) == set(developer_runs.REFUSAL_CODES)
    assert developer._LABEL in text
    for field in BASELINE_FIELDS + ("pins.route_table_hash", "pins.write_turn_package_hash"):
        assert field in text
    assert "slots_differ" in text
    spec = (ROOT / "specs/ring0/RING0.md").read_text().split("### 14.10", 1)[1].split("## 15", 1)[0]
    assert "**Erratum, 2026-11-04 (#392): the per-life table and T2's operating metrics.**" in spec


@pytest.mark.parametrize("prime_side,metadata,code", [
    (False, False, "items_mismatch"),
    (True, False, "aa_prime:items_mismatch"),
    (False, True, "invalid_rows"),
])
def test_valid_cards_with_different_items_reach_part1(pair, tmp_path, capsys,
                                                     prime_side, metadata, code):
    card = CARD()
    if metadata:
        for item in card["items"]:
            item["cell_id"] = "different-cell"
        card["groups"] = [["different-cell", "act"], ["different-cell", "remember"]]
    else:
        for item in card["items"]:
            item["item_id"] = "different-item"
            if item["repro"]:
                item["repro"] = "/".join(["kept", item["life"], item["branch"], item["item_id"]])
        for identity in card["not_scored_live"]:
            identity[2] = "different-item"
    prime = write_run(tmp_path / "prime", card=card) if prime_side else None
    if not prime_side:
        write_run(pair[0], card=card)
    assert_refusal(pair, tmp_path / "out", code, capsys, prime)


@pytest.mark.parametrize("artifact,code", [
    ("receipt.json", "run_invalid:receipt"),
    ("card.json", "run_invalid:card"),
    ("receipts/system.json", "run_invalid:receipt"),
    ("units.json", "run_invalid:units"),
    ("no_memory.json", "run_invalid:floor"),
])
def test_malformed_json_refusal(pair, tmp_path, capsys, artifact, code):
    (pair[0] / artifact).write_bytes(b"{")
    assert_refusal(pair, tmp_path / "out", code, capsys)


def test_public_new_text_has_no_local_paths():
    paths = runpy.run_path(str(ROOT / "scripts/public_check.py"))["PATHS"]
    for relative in ("docs/developers/report.md", "src/bicentennial/report/developer_runs.py",
                     "tests/report/test_developer_runs.py"):
        assert not paths.search((ROOT / relative).read_text())
