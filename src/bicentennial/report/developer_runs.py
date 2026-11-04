"""Read comparable completed T2 runs and publish the developer signal."""

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.report.developer import (
    DeveloperReportRefused,
    _rows,
    developer_report,
)
from bicentennial.report.t2_card import validate_t2_card
from bicentennial.report.t2lite_flips import BASELINE_FIELDS

T2_SCOPE = "T2 system arm; wall time from RING0 §14.8 arm time"
REFUSAL_CODES = (
    "run_invalid:receipt", "run_incomplete", "run_invalid:card", "tier_unsupported",
    "run_invalid:units", "run_invalid:floor", "baseline_mismatch:<field>",
    "aa_prime:baseline_mismatch:<field>", "aa_prime:system_hash", "turn_wait_mismatch",
    "items_mismatch", "aa_prime:items_mismatch", "invalid_rows", "out_exists", "tool_failure",
    "hashseed", "source_checkout_required", "usage",
)
ROW_FIELDS = ("item_id", "cell_id", "stage", "score_milli", "failure_class", "base_verdict")


@dataclass(frozen=True)
class Run:
    card: dict
    card_bytes: bytes
    receipt: dict
    system_receipt: dict
    arm_time_ms: int
    rows: list
    floor_rows: list


def _read(path, code):
    try:
        raw = path.read_bytes()
        return json.loads(raw), raw
    except (OSError, ValueError, UnicodeError) as error:
        raise DeveloperReportRefused(code) from error


def _receipt(path):
    value, _ = _read(path, "run_invalid:receipt")
    try:
        validate("receipt", value)
    except (ValueError, TypeError) as error:
        raise DeveloperReportRefused("run_invalid:receipt") from error
    return value


def _tier(card):
    if type(card) is not dict:
        raise DeveloperReportRefused("run_invalid:card")
    if card.get("tier") != "T2":
        raise DeveloperReportRefused("tier_unsupported")


def load_run(directory):
    """Read in publication order, refusing at the first invalid artifact."""
    directory = Path(directory)
    receipt = _receipt(directory / "receipt.json")
    if receipt["run_status"] != "COMPLETE":
        raise DeveloperReportRefused("run_incomplete")
    card, raw = _read(directory / "card.json", "run_invalid:card")
    _tier(card)
    try:
        validate_t2_card(card)
    except (ValueError, TypeError, KeyError) as error:
        raise DeveloperReportRefused("run_invalid:card") from error
    system = _receipt(directory / "receipts/system.json")
    units, _ = _read(directory / "units.json", "run_invalid:units")
    try:
        arm_time = units["arm_time"]["arms"]["system"]["arm_time_ms"]
        if type(arm_time) is not int or arm_time < 0:
            raise ValueError("arm time")
    except (KeyError, TypeError, ValueError) as error:
        raise DeveloperReportRefused("run_invalid:units") from error
    floor, _ = _read(directory / "no_memory.json", "run_invalid:floor")
    excluded = {tuple(key) for key in card["not_scored_live"]}
    rows = [dict({key: item[key] for key in ROW_FIELDS}, life=item["life"], branch=item["branch"],
                 not_scored_live=(item["life"], item["branch"], item["item_id"]) in excluded)
            for item in card["items"]]
    floor_rows = []
    try:
        expected = {}
        for row in rows:
            expected.setdefault(f"{row['life']}/{row['branch']}", {})[row["item_id"]] = row
        if type(floor) is not dict or floor.keys() != expected.keys():
            raise ValueError("floor units")
        for unit, items in expected.items():
            outcomes = floor[unit]["outcomes"]
            if type(outcomes) is not dict or outcomes.keys() != items.keys():
                raise ValueError("floor items")
            for item_id, item in items.items():
                stored = outcomes[item_id]
                if (any(key in stored for key in ("life", "branch", "not_scored_live"))
                        or any(stored[key] != item[key] for key in ("item_id", "cell_id", "stage"))):
                    raise ValueError("floor identity")
                floor_rows.append(dict({key: stored[key] for key in ROW_FIELDS},
                    life=item["life"], branch=item["branch"],
                    not_scored_live=item["not_scored_live"]))
        _rows(floor_rows)
    except (ValueError, KeyError, TypeError) as error:
        raise DeveloperReportRefused("run_invalid:floor") from error
    return Run(card, raw, receipt, system, arm_time, rows, floor_rows)


def _field(card, field):
    for part in field.split("."):
        card = card[part]
    return card


def _baseline(current, previous, prefix=""):
    for field in BASELINE_FIELDS:
        if _field(current.card, field) != _field(previous.card, field):
            raise DeveloperReportRefused(prefix + "baseline_mismatch:" + field)


def report_runs(current, previous, aa_prime=None):
    """Load runs, establish comparability and derive the seed from exact card bytes."""
    current, previous = load_run(current), load_run(previous)
    prime = None if aa_prime is None else load_run(aa_prime)
    _baseline(current, previous)
    if prime is not None:
        _baseline(previous, prime, "aa_prime:")
        if previous.card["pins"]["system_hash"] != prime.card["pins"]["system_hash"]:
            raise DeveloperReportRefused("aa_prime:system_hash")
    runs = [current, previous] + ([] if prime is None else [prime])
    if len({receipt["turn_wait_s"] for run in runs
            for receipt in (run.receipt, run.system_receipt)}) != 1:
        raise DeveloperReportRefused("turn_wait_mismatch")
    seed = hashlib.sha256(b"".join(run.card_bytes for run in runs)).hexdigest()
    result = developer_report(current.rows, previous.rows,
        aa=None if prime is None else (previous.rows, prime.rows),
        receipts=(current.system_receipt, previous.system_receipt), seed=seed,
        floors=(current.floor_rows, previous.floor_rows), metrics_scope=T2_SCOPE,
        arm_times=(current.arm_time_ms, previous.arm_time_ms))
    result["pairing"] = dict(tier="T2", current_system_hash=current.card["pins"]["system_hash"],
        previous_system_hash=previous.card["pins"]["system_hash"],
        aa_prime_system_hash=None if prime is None else prime.card["pins"]["system_hash"],
        turn_wait_s=current.receipt["turn_wait_s"], seed=seed)
    validate("developer_report", result)
    return result


def _number(value):
    return "null" if value is None else f"{value['numerator']}/{value['denominator']}"


def _interval(value):
    return value if isinstance(value, str) else "[" + ", ".join(map(_number, value)) + "]"


def summary(report):
    """Plain text retains exact fractions and labels every reported quantity."""
    lines = [report["label"]]
    for name, entry in [(c["cell_id"], c) for c in report["cells"]] + [("pooled", report["pooled"])]:
        diff, aa = entry["diff"], entry["aa"]
        lines.append(f"{name}: estimate {_number(diff['estimate'])}; {diff['direction']}; "
                     f"p {_number(diff['p'])}; interval {_interval(diff['interval'])}; "
                     f"lives {diff['life_count']}; sign_changes {diff['sign_changes']}")
        lines.append(f"  q0 fraction {_number(aa['q0'])}; Wilson 95% interval ppm "
                     f"{aa['wilson_95_ppm']}; {aa['assumption']}; {aa['status']}")
        comp = aa["comparison"]
        lines.append("  A − A′: " + (aa["status"] if comp is None else
                     f"estimate {_number(comp['estimate'])}; {comp['direction']}; "
                     f"p {_number(comp['p'])}; interval {_interval(comp['interval'])}; "
                     f"lives {comp['life_count']}; sign_changes {comp['sign_changes']}"))
        sensitivity = aa["sensitivity"]
        lines.append(f"  sensitivity approximate: {sensitivity['status']}; "
                     f"{_number(sensitivity['value'])}; {sensitivity['exact_test_limit']}")
    metrics = report["operating_metrics"]
    lines.append("Operating metric deltas (current minus previous): " + metrics["scope"])
    for key in ("wall_ms", "requests", "store_growth_bytes", "tokens_by_role", "latency_summary"):
        lines.append(f"  {key}: {json.dumps(metrics[key], ensure_ascii=False, sort_keys=True)}")
    lines.append("Failure taxonomy: run | cell | stage | failure | exclusion | count | excluded count")
    for side, rows in report["failure_taxonomy"].items():
        for row in rows:
            lines.append(" | ".join(str(x) for x in (side, row["cell_id"], row["stage"],
                row["failure"], row["exclusion_reason"], row["count"], row["excluded_count"])))
    pairing = report["pairing"]
    for key in ("current_system_hash", "previous_system_hash", "aa_prime_system_hash"):
        lines.append(f"{key}: {pairing[key]}")
    lines.append("Per life: life | scored items | paired difference | current floor lift | previous floor lift")
    for row in report["pooled"]["per_life"]:
        lines.append(" | ".join([row["life"], str(row["scored_items"])] +
                     [_number(row[k]) for k in ("contribution", "current_lift", "previous_lift")]))
    return "\n".join(lines)


def run_report(*, current, previous, out, aa_prime=None):
    try:
        if os.path.lexists(out):
            raise DeveloperReportRefused("out_exists")
        result = report_runs(current, previous, aa_prime)
        raw, text = canon(result), summary(result)
        try:
            with open(out, "xb") as stream:
                stream.write(raw)
        except FileExistsError as error:
            raise DeveloperReportRefused("out_exists") from error
        print(text)
        return 0
    except DeveloperReportRefused as error:
        print(error.code, file=sys.stderr)
        return 3
    except Exception:
        print("tool_failure", file=sys.stderr)
        return 70
