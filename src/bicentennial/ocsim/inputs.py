"""A bar-2 runner writes this JSON container for point inputs.

Exactly {A: {no_memory: ARM, oracle_evidence: ARM}, A_prime: {same arms},
branches: {item_id: B0 | B1}}; ARM has items, bundles, singleton_lives.
Only board-condition control arms belong here (no Keep K10 subset).
Controls-cache entries are not a valid source: they use the scripted reader
and have no A′. Extra ARM keys, including reports, are ignored.
"""

import argparse
import json
import math
import multiprocessing
import os
import platform
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.ocsim import fitcheck, gaussian, locate, model, run
from bicentennial.stats import tcal, variance_inputs

NONRESULTS = ("BLOCKED", "N/A_EXPOSURE", "N/A_CLOCK")
FAILURE_CLASSES = (None, "FAIL_TASK", "SYSTEM_FAILURE", *NONRESULTS)
TRACKS = ("Wake", "Drift", "Tuesday", "Rachael", "Keep", "Recall", "Faults")
STAGES = ("remember", "survive", "act")
UNIT = ("ocsim", "inputs-bootstrap")
RESAMPLES = 1000
FAILURES = ("raised", "cells", "rho_t", "g")
FLAGS = frozenset((
    "twin_undefined", "fc_undefined", "aa_undefined", "rho_x_undefined",
    "rho_x_clamped", "rho_a_undefined", "rho_a_clamped", "icc_undefined",
    "icc_truncated", "icc_one", "twin_default", "sigma_d2_zero", "sigma_d2_constrained",
))
ARMS = {"no_memory": "F", "oracle_evidence": "C"}


def _require(ok, where, message):
    if not ok:
        raise ValueError(f"{where}: {message}")


def load(records: bytes, required: tuple[str, ...]) -> tuple[
    tuple[variance_inputs.ControlRecord, ...], frozenset[str]
]:
    """Validate every cell, then return required-cell records and timing cells."""
    _require(required == tuple(sorted(set(required))), "required", "must be sorted and unique")
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "container", f"duplicate key {key}")
            value[key] = item
        return value
    data = json.loads(records, object_pairs_hook=unique_keys)
    _require(isinstance(data, dict) and data.keys() == {"A", "A_prime", "branches"},
             "A/A_prime no_memory/oracle_evidence container", "unknown or missing run/key")
    branches, tracks, indexed, identities, result = data["branches"], {}, {}, {}, []
    singletons = {}
    _require(isinstance(branches, dict), "branches", "must be an object")
    for iid, branch in branches.items():
        _require(branch in ("B0", "B1"), f"A/A_prime no_memory/oracle_evidence {iid}", "bad branch")
    for name in ("A", "A_prime"):
        _require(isinstance(data[name], dict) and data[name].keys() == ARMS.keys(),
                 name, "unknown or missing arm")
        for arm, label in ARMS.items():
            where, items, bundles, members = f"{name} {arm}", {}, {}, {}
            output = data[name][arm]
            _require(isinstance(output, dict) and isinstance(output.get("items"), list)
                     and isinstance(output.get("bundles"), list)
                     and isinstance(output.get("singleton_lives"), dict), where, "malformed arm")
            for index, item in enumerate(output["items"]):
                iid = item.get("item_id") if isinstance(item, dict) else None
                at = f"{where} item {iid if isinstance(iid, str) else f'#{index}'}"
                _require(isinstance(item, dict) and {"item_id", "cell_id", "stage", "track",
                         "failure_class", "score_milli"} <= item.keys()
                         and isinstance(iid, str) and isinstance(item["cell_id"], str)
                         and item["failure_class"] in FAILURE_CLASSES
                         and item["track"] in TRACKS and item["stage"] in STAGES,
                         at, "malformed item")
                iid, cell = item["item_id"], item["cell_id"]
                at = f"{where} item {iid}"
                _require(iid not in items, at, "duplicate item")
                score, failure = item["score_milli"], item["failure_class"]
                _require(score is None or type(score) is int and -1000 <= score <= 1000,
                         at, "score out of range")
                _require((score is None) == (failure in NONRESULTS), at, "non-result score")
                _require(failure not in ("SYSTEM_FAILURE", "FAIL_TASK") or score == 0,
                         at, "system/task failure must score 0")
                _require(name == "A_prime" or cell not in tracks or tracks[cell] == item["track"],
                         at, "conflicting tracks")
                tracks[cell] = item["track"]
                if name == "A_prime":
                    _require(iid in indexed[("A", arm)][0], at, "A′ item missing from A")
                items[iid] = item
            for index, bundle in enumerate(output["bundles"]):
                bid = bundle.get("bundle_id") if isinstance(bundle, dict) else None
                at = f"{where} bundle {bid if isinstance(bid, str) else f'#{index}'}"
                _require(isinstance(bundle, dict) and {"bundle_id", "cell_id", "life", "items"}
                         <= bundle.keys() and all(isinstance(bundle[k], str)
                                                  for k in ("bundle_id", "cell_id", "life"))
                         and isinstance(bundle["items"], list)
                         and all(isinstance(i, str) for i in bundle["items"]), at, "malformed bundle")
                bid, cell = bundle["bundle_id"], bundle["cell_id"]
                at, ids = f"{where} bundle {bid}", bundle["items"]
                _require(bid not in bundles, at, "duplicate bundle")
                _require(len(ids) == 2 and len(set(ids)) == 2, at, "need two items")
                for iid in ids:
                    _require(iid not in members, f"{where} item {iid}",
                             f"item in two bundles: {members.get(iid)} and {bid}")
                    _require(iid in items and items[iid]["cell_id"] == cell,
                             f"{at} item {iid}", "missing item or conflicting cell")
                    _require(iid in branches, f"{at} item {iid}", "missing branch")
                _require({branches[i] for i in ids} == {"B0", "B1"}, at, "need B0 and B1")
                identity = (bundle["life"], cell, tuple(sorted(ids)))
                if name == "A_prime":
                    _require(indexed[("A", arm)][1].get(bid) == identity,
                             at, "A′ bundle missing from A or changed identity")
                _require(bid not in identities or identities[bid] == identity,
                         at, "conflicting bundle identity across arms/runs")
                identities[bid] = bundles[bid] = identity
                members.update((iid, bid) for iid in ids)
                oriented = sorted(ids, key=lambda i: branches[i])
                if cell in required:
                    result.append(variance_inputs.ControlRecord(
                        label, name, bundle["life"], cell, 0, bid,
                        *(items[i]["score_milli"] for i in oriented)))
            if name == "A":
                for iid, item in items.items():
                    if item["cell_id"] in required:
                        _require(iid not in output["singleton_lives"] and iid in members
                                 and item["stage"] == "act", f"{where} item {iid}",
                                 "required cell must be twin-only act"
                                 + ("; bad singleton" if iid in output["singleton_lives"] else ""))
            else:
                for iid, item in items.items():
                    for key in ("cell_id", "track", "stage"):
                        _require(item[key] == indexed[("A", arm)][0][iid][key],
                                 f"{where} item {iid}",
                                 f"A′ item differs from A: {key}"
                                 + (" (conflicting tracks)" if key == "track" else ""))
                    _require(item["cell_id"] not in required or iid in members,
                             f"{where} item {iid}", "A′ required-cell item outside every A′ bundle")
            for iid, life in output["singleton_lives"].items():
                _require(iid in items and iid not in members and isinstance(life, str),
                         f"{where} item {iid}", "bad singleton")
            for iid in items.keys() - members.keys():
                _require(iid in output["singleton_lives"], f"{where} item {iid}", "missing singleton")
            if name == "A_prime":
                for iid, life in output["singleton_lives"].items():
                    _require(singletons[arm].get(iid) == life, f"{where} item {iid}",
                             "A′ singleton differs from A")
            else:
                singletons[arm] = output["singleton_lives"]
            indexed[(name, arm)] = items, bundles
    for iid in branches:
        _require(any(iid in items for items, _ in indexed.values()),
                 f"A/A_prime no_memory/oracle_evidence item {iid}", "branch for an item in no arm")
    for cell in required:
        lives = [{r.life for r in result if r.run == "A" and r.arm == arm and r.cell == cell
                  and r.b0 is not None and r.b1 is not None} for arm in ("F", "C")]
        count = len(lives[0] & lives[1])
        _require(count >= 4, f"coverage {cell}", f"{count} lives; need at least 4")
    return (tuple(sorted(result, key=lambda r: (r.run, r.arm, r.bundle))),
            frozenset(cell for cell, track in tracks.items() if track == "Tuesday"))


@dataclass(frozen=True)
class _Context:
    rows: dict
    draws: tuple
    timing: frozenset
    required: tuple
    alloc: dict
    margins: dict


def _resample(context, r):
    rows = [replace(row, life=f"boot-{j:03d}", bundle=f"{row.bundle}#{j}")
            for j, life in enumerate(context.draws[r]) for row in context.rows[life]]
    flags, params = (), None
    try:
        moments = variance_inputs.estimate(rows, timing_cells=context.timing)
        params, latent = variance_inputs.to_latent(moments)
        flags = tuple(sorted(set(moments.flags) | set(latent)))
    except (ValueError, ArithmeticError):
        return r, "raised", None, params, flags
    if tuple(c.cell for c in params.cells) != context.required:
        return r, "cells", None, params, flags
    if params.rho_t <= -1 + 1e-6:
        return r, "rho_t", None, params, flags
    try:
        _, covariance = gaussian.moments(params, context.alloc, context.margins)
        g = max(covariance[k][k] for k in range(len(params.cells)))
        if not math.isfinite(g):
            raise ValueError("non-finite g")
    except (ValueError, ArithmeticError):
        return r, "g", None, params, flags
    return r, "ok", g, params, flags


def _resample_range(context, start, stop):
    return [_resample(context, r) for r in range(start, stop)]


def _ends(results, n, resamples):
    successes = sorted((row for row in results if row[1] == "ok"), key=lambda row: (row[2], row[0]))
    i = tcal.index(resamples, tcal.ppm(tcal.EIGHTY_PCT_PPM, n))
    failed = resamples - len(successes)
    if failed > i:
        return None, None
    return successes[i - failed], successes[resamples - 1 - i]


def _check_flags(flags, resamples):
    def known(flag):
        return flag in FLAGS or re.fullmatch(r"anova_undefined:(F|C):.+|no_aa:(F|C)", flag)
    for flag in flags:
        valid = known(flag) or flag == "inputs_bootstrap_ends_refused"
        for prefix in ("inputs_bootstrap:", "inputs_bootstrap_failed:", "inputs_bootstrap_failed="):
            if not flag.startswith(prefix):
                continue
            inner, _, count = flag.removeprefix(prefix).rpartition("=")
            total = prefix == "inputs_bootstrap_failed="
            if total:
                count = flag.removeprefix(prefix)
            pattern = r"(0|[1-9][0-9]*)/([1-9][0-9]*)" if total else r"([1-9][0-9]*)/([1-9][0-9]*)"
            match = re.fullmatch(pattern, count)
            valid = bool(match and int(match[2]) == resamples and int(match[1]) <= resamples
                         and (total or (known(inner) if prefix == "inputs_bootstrap:" else inner in FAILURES)))
        _require(valid, "latent_flags", f"unknown flag {flag}")


def _precheck(params, required, end=""):
    for cell in params.cells:
        try:
            locate.build_table(cell, params.rho_t)
        except Exception as error:
            raise ValueError(f"{end}cell {cell.cell} margin table: {error}") from error
        for config in run.margin_grid(required):
            margin = dict(config.margins)[cell.cell]
            try:
                model.interpolation(cell, margin)
            except Exception as error:
                raise ValueError(f"{end}cell {cell.cell} margin {margin}: {error}") from error


def build(records: bytes, base: bytes, *, root: Path, workers=1, resamples=RESAMPLES) -> bytes:
    """Merge point estimates and life-bootstrap ends into a validated C9.1 document."""
    _require(type(workers) is int and 1 <= workers <= (os.cpu_count() or 1),
             "workers", "workers must be an int in [1, cpu_count]")
    _require(type(resamples) is int and resamples > 0, "resamples", "must be a positive int")
    document = json.loads(base)
    required = tuple(document["required"])
    rows, timing = load(records, required)
    _require(not run.c8_dirty(root), "C-8", "dirty tree")
    moments = variance_inputs.estimate(rows, timing_cells=timing)
    params, latent_flags = variance_inputs.to_latent(moments)
    _require(tuple(c.cell for c in params.cells) == required, "latent cells", "must equal required")
    flags = sorted(set(moments.flags) | set(latent_flags))
    _check_flags(flags, resamples)
    _precheck(params, required)
    document.update(params=run._encode(asdict(params)), latent_flags=flags, sensitivity_params={},
                    provenance={"platform": platform.platform(), "python": platform.python_version(),
                                "records_sha256": sha256(records).hexdigest(),
                                "base_sha256": sha256(base).hexdigest()}, c8_hash=run.c8_hash(root))
    parsed = run._parse_inputs(canon(document), root=root)
    alloc = parsed.alloc_by_b[run.LADDER[0][1]]
    for cell in required:
        _require(sum(v for (k, _), v in alloc.items() if k == cell) > 0,
                 "alloc", f"zero count for cell {cell}")
    lives = tuple(sorted({row.life for row in rows}))
    context = _Context({life: tuple(row for row in rows if row.life == life) for life in lives},
                       fitcheck.draws(lives, resamples, UNIT), timing, required, alloc,
                       dict(run.margin_grid(required)[0].margins))
    if workers == 1:
        results = _resample_range(context, 0, resamples)
    else:
        results = []
        width = (resamples + workers - 1) // workers
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = [pool.submit(_resample_range, context, start, min(start + width, resamples))
                       for start in range(0, resamples, width)]
            for future in as_completed(futures):
                results.extend(future.result())
        results.sort(key=lambda row: row[0])
    failed = Counter(row[1] for row in results if row[1] != "ok")
    counts = Counter(flag for row in results if row[1] == "ok" for flag in set(row[4]))
    flags += [f"inputs_bootstrap:{flag}={c}/{resamples}" for flag, c in counts.items()]
    flags += [f"inputs_bootstrap_failed:{kind}={c}/{resamples}" for kind, c in failed.items()]
    flags += [f"inputs_bootstrap_failed={sum(failed.values())}/{resamples}"]
    low, high = _ends(results, len(lives), resamples)
    if low is None:
        flags.append("inputs_bootstrap_ends_refused")
    else:
        for name, end in (("inputs_low", low), ("inputs_high", high)):
            _precheck(end[3], required, name + " ")
            document["sensitivity_params"][name] = run._encode(asdict(end[3]))
    _check_flags(flags, resamples)
    document["latent_flags"] = sorted(set(flags))
    document["provenance"]["inputs_bootstrap"] = {
        "resamples": resamples, "unit": list(UNIT), "seed": fitcheck.SEED,
        "level_ppm": tcal.ppm(tcal.EIGHTY_PCT_PPM, len(lives)),
        "index": tcal.index(resamples, tcal.ppm(tcal.EIGHTY_PCT_PPM, len(lives))),
        "failed": sum(failed.values()), "low_resample": None if low is None else low[0],
        "high_resample": None if high is None else high[0],
        "low_g": None if low is None else float.hex(low[2]),
        "high_g": None if high is None else float.hex(high[2])}
    encoded = canon(document)
    _require(run._parse_inputs(encoded, root=root).params == params, "round trip", "params changed")
    return encoded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("records", "base", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    _require(not args.out.exists(), str(args.out), "output already exists")
    data = build(args.records.read_bytes(), args.base.read_bytes(),
                 root=Path(__file__).resolve().parents[3], workers=args.workers, resamples=RESAMPLES)
    with args.out.open("xb") as target:
        target.write(data)
    print(f"{args.out} {sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
