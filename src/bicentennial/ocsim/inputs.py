"""A bar-2 runner writes this JSON container for point inputs.

Exactly {A: {no_memory: ARM, oracle_evidence: ARM}, A_prime: {same arms},
branches: {item_id: B0 | B1}}; ARM has items, bundles, singleton_lives.
Only board-condition control arms belong here (no Keep K10 subset).
Controls-cache entries are not a valid source: they use the scripted reader
and have no A′. Extra ARM keys, including reports, are ignored.
"""

import argparse
import json
import platform
import re
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.ocsim import locate, model, run
from bicentennial.stats import variance_inputs

NONRESULTS = ("BLOCKED", "N/A_EXPOSURE", "N/A_CLOCK")
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
                         and isinstance(iid, str) and isinstance(item["cell_id"], str),
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


def build(records: bytes, base: bytes, *, root: Path) -> bytes:
    """Merge point estimates into a complete, reader-validated C9.1 document."""
    document = json.loads(base)
    required = tuple(document["required"])
    rows, timing = load(records, required)
    _require(not run.c8_dirty(root), "C-8", "dirty tree")
    moments = variance_inputs.estimate(rows, timing_cells=timing)
    params, latent_flags = variance_inputs.to_latent(moments)
    _require(tuple(c.cell for c in params.cells) == required, "latent cells", "must equal required")
    flags = sorted(set(moments.flags) | set(latent_flags))
    for flag in flags:
        _require(flag in FLAGS or re.fullmatch(r"anova_undefined:(F|C):.+|no_aa:(F|C)", flag),
                 "latent_flags", f"unknown flag {flag}")
    for cell in params.cells:
        try:
            locate.build_table(cell, params.rho_t)
        except Exception as error:
            raise ValueError(f"cell {cell.cell} margin table: {error}") from error
        for config in run.margin_grid(required):
            margin = dict(config.margins)[cell.cell]
            try:
                model.interpolation(cell, margin)
            except Exception as error:
                raise ValueError(f"cell {cell.cell} margin {margin}: {error}") from error
    document.update(params=run._encode(asdict(params)), latent_flags=flags, sensitivity_params={},
                    provenance={"platform": platform.platform(), "python": platform.python_version(),
                                "records_sha256": sha256(records).hexdigest(),
                                "base_sha256": sha256(base).hexdigest()}, c8_hash=run.c8_hash(root))
    encoded = canon(document)
    _require(run._parse_inputs(encoded, root=root).params == params, "round trip", "params changed")
    return encoded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("records", "base", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args(argv)
    _require(not args.out.exists(), str(args.out), "output already exists")
    data = build(args.records.read_bytes(), args.base.read_bytes(),
                 root=Path(__file__).resolve().parents[3])
    with args.out.open("xb") as target:
        target.write(data)
    print(f"{args.out} {sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
