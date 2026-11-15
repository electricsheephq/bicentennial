"""Read the fresh-seed follow-up without opening scores while a check is pending.

Only frozen ranking and descriptive items supply scores. The unchanged round-2
and Milestone-1 readers supply the rule primitives; orchestration is local.
"""

import importlib.util
import json
import re
import sys
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from itertools import pairwise, product
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.stats.core import sign_flip_p

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load_module("followup_round2", REPO / "results/validity-2/control-trials/table.py")
frozen = load_module("followup_frozen", HERE / "tasks.py")
CODE = {"table.py": HERE / "table.py", "tasks.py": HERE / "tasks.py",
        "round 2 table.py": REPO / "results/validity-2/control-trials/table.py",
        "Milestone 1 table.py": rules.CODE["Milestone 1 table.py"]}
is_int, exact, short = rules.is_int, rules.exact, rules.short
state, margin = rules.state, rules.margin
bundle_score, pts, twin, bundle_verdict = rules.bundle_score, rules.pts, rules.twin, rules.bundle_verdict
recompute_blocks, frame_sha256, pack_tree_hash = rules.recompute_blocks, rules.frame_sha256, rules.pack_tree_hash
CONTROL, ANCHOR_ROWS, CHECK3_TESTS = rules.CONTROL, rules.ANCHOR_ROWS, rules.CHECK3_TESTS
scripted_reports = rules.load_pack
KINDS = frozen.TARGET_TEMPLATES
ROWS = {"F": ("F1", "F2"), "R": ("R1", "R2"), "O": ("O1", "O2", "O3"), "H": ("H1", "H2"),
        "B": ("B1",), "G": ("G1",), "W": ("W1",)}
DECLARED_ORDER = tuple(f"{pack}.{arm}" for pack, arms in (
    ("A", "F1 R1 O1 H1 H2 O2 R2 F2 O3 B1 G1 W1"),
    ("B", "F1 R1 O1 H1 H2 O2 R2 F2 O3 G1 W1 B1"),
    ("C", "F1 R1 O1 H1 H2 O2 R2 F2 O3 W1 B1 G1")) for arm in arms.split())
# The constant is shared with the run driver; all positions count attempts.
RERUN = "rerun once (§3, §4), then run again with --after-reruns"
PACK_PINS = ("controls_sha256", "reader_sha256", "scoring_code_sha256", "scorer_sha256")
H_PINS = ("system_hash", "harness_hash", "route_table_hash")


def read(path, default=None):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return default


def item_key(row):
    return "/".join(row[k] for k in ("life", "branch", "item_id"))


def load_pack(letter, packs, path, digest):
    """Bind the frozen bytes to this pack and recompute the unchanged scripted reports."""
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise frozen.Refused("task list hash")
    tasks = json.loads(raw)
    if canon(tasks) != raw:
        raise frozen.Refused("task list canonical form")
    if set(tasks) != {"header", "rows", "descriptive"} or set(tasks["header"]) != frozen.HEADER_FIELDS:
        raise frozen.Refused("task list shape")
    head = tasks["header"]
    if head["pack"] != letter or head["edition"] != frozen.EDITION:
        raise frozen.Refused("task list pack or edition")
    if (not re.fullmatch(r"[0-9a-f]{40}", head["commit"])
            or any(not re.fullmatch(r"[0-9a-f]{64}", head[k])
                   for k in ("draw_sha256", "spec_sha256", "pack_hash"))):
        raise frozen.Refused("task list header hashes")
    tree = pack_tree_hash(packs)
    if head["pack_hash"] != tree:
        raise frozen.Refused("task list pack hash")
    records = frozen.pack_records(packs)
    for key, function in (("rows", frozen.target_rows), ("descriptive", frozen.descriptive_rows)):
        rows, reason = function(records)
        if reason or tasks[key] != rows:
            raise frozen.Refused("task list " + key)
    reports, reason = scripted_reports(packs)
    if reason:
        raise frozen.Refused("scripted reports")
    index_pins = read(packs / "index.json", {}).get("pins", {})
    code_pins = [dict(read(p, {}).get("pins", {}), scoring_code_sha256=index_pins.get("scoring_code_sha256"))
                 for p in sorted(packs.glob("pack/*/*/*/manifest.json"))]
    return dict(letter=letter, path=packs, tasks=tasks, digest=digest, tree=tree,
                reports=reports[0], expected_keys=reports[1], records=records, code_pins=code_pins, index_pins=index_pins)


def positions(attempts, order, reruns):
    if attempts is None:
        raise frozen.Refused("run order: attempts required")
    seq = attempts.split(",")
    again = [entry.removesuffix(".rerun") for entry in seq[36:]]
    if (seq[:36] != list(DECLARED_ORDER) or len(again) != len(set(again))
            or set(again) != set(reruns) or any(entry != label + ".rerun" for entry, label in zip(seq[36:], again, strict=False))
            or not set(again) <= set(DECLARED_ORDER)):
        raise frozen.Refused("run order: declared first attempts then one rerun per named arm")
    place = {entry.removesuffix(".rerun"): n for n, entry in enumerate(seq, 1)}
    if sorted(place, key=place.get) != order:
        raise frozen.Refused("run order: order must describe the last attempts")
    return place


def reference_identity(arms, order):
    controls = {k: arm for k, arm in arms.items() if arm.get("row", k.split(".")[-1][0]) != "H"
                and arm["card"].get("served_identity") is not None}
    return rules.reference_identity(controls, order) if controls else None


def system_stop(path):
    """The last recorded attempt alone decides stop attribution; absence records no stop."""
    if not path.exists():
        return True
    data = read(path)
    if not isinstance(data, dict) or not isinstance(data.get("attempts"), list) or not data["attempts"]:
        return False
    last = data["attempts"][-1]
    if not isinstance(last, dict) or "stopped" not in last:
        return False
    stopped = last["stopped"]
    return stopped is None or (isinstance(stopped, list) and len(stopped) == 3 and stopped[0] == "SYSTEM_FAILURE")


def system_live(arm, pack):
    targets = {item_key(r): r for r in pack["tasks"]["rows"]}
    target_ids = {r["item_id"] for r in targets.values()}
    seen, misplaced, nonlive = Counter(), 0, 0
    units = {f"{life}/{branch}" for life in pack["reports"] for branch in ("B0", "B1")}
    files = set((arm["run"] / "system").glob("*/*/t2lite_probes.json"))
    for file in files:
        unit = f"{file.parent.parent.name}/{file.parent.name}"
        records = read(file, [])
        if not isinstance(records, list):
            records = []
        for record in records:
            if not isinstance(record, dict) or record.get("item_id") not in target_ids:
                continue
            key = unit + "/" + record["item_id"]
            if key not in targets:
                misplaced += 1
                continue
            seen[key] += 1
            nonlive += ((record.get("live") or {}).get("served_by") != "live"
                        and (arm["outcomes"].get(key) or {}).get("failure_class") != "SYSTEM_FAILURE")
    stopped = sum(not system_stop(arm["run"] / "system" / unit / "unit_diagnostics.json") for unit in units)
    covered = sum(seen[k] == 1 for k in targets)
    duplicated = sum(max(n - 1, 0) for n in seen.values())
    ok = covered == len(targets) and misplaced == 0 and nonlive == 0 and stopped == 0
    print(f"check 7 {arm['name']}: targets {len(targets)} covered_once {covered} duplicated {duplicated}"
          f" misplaced {misplaced} not_live_unexcused {nonlive} units {len(units)} stopped_or_unreadable {stopped} pass {ok}")
    print("system units have no cache path")
    return ok


def control_checks(arm, pack, block_cache):
    name, rec, row = arm["name"], arm["control"], arm["row"]
    if row == "F":
        payload = rec.get("frame_sha256") is None and rec.get("block_sha256") == {}
    else:
        if rec["arm"] not in block_cache:
            block_cache[rec["arm"]] = recompute_blocks(pack["path"], rec["arm"])
        want = block_cache[rec["arm"]]
        payload = bool(want) and rec.get("block_sha256") == want and rec.get("frame_sha256") == frame_sha256()
    window = rec.get("reader_window") == 32768 if row in ("G", "W") else "reader_window" not in rec
    anchor = True
    if row in ("B", "G", "W"):
        definition = rules.header()["anchors"][rec["arm"]]
        identity = dict(name=rec["arm"], **{k: definition[k] for k in ("version", "spec_sha256", "code_sha256")})
        anchor = rec.get("anchor") == rules.card_anchors().get(rec["arm"]) == identity
    ok1 = payload and window and anchor
    print(f"check 1 {name}: payload {payload} anchor identity {anchor} reader_window {window} pass {ok1}")
    expected_units = {f"{life}/{b}" for life in pack["reports"] for b in ("B0", "B1")}
    probes = {u: read(arm["run"] / rec["arm"] / u / "t2lite_probes.json") for u in sorted(expected_units)}
    first = {f"{unit}/{r.get('item_id')}": (r.get("shadow") or {}).get("in_context_initial")
             for unit, rows in probes.items() for r in (rows if isinstance(rows, list) else [])}
    targets = pack["tasks"]["rows"]
    ok2 = True
    if row != "F":
        correct = 0
        for target in targets:
            expected = (True if row == "O" else pack["reports"][target["life"]][rec["arm"]]["reports"].get(
                target["item_id"], {}).get("in_context"))
            key = item_key(target)
            correct += key in first and expected is not None and first[key] == expected
        ok2 = correct == len(targets)
        print(f"check 2 {name}: presence matches {correct} of {len(targets)} pass {ok2}")
    card_units = arm["card"].get("floor", {}).get("units", {})
    disclosed = arm["disclosures"].get("floor", {})
    cached = sum(card_units.get(u, {}).get("cached") is not False
                 or disclosed.get(u, {}).get("cached") is not False for u in expected_units)
    floor = read(arm["run"] / f"{rec['arm']}.json", {}) or {}
    stopped = sum((floor.get(u) or {}).get("stops") != {u.replace("/", ""): None} for u in expected_units)
    observed, count, live = Counter(), 0, 0
    for unit, rows in probes.items():
        for record in rows if isinstance(rows, list) else []:
            count += 1
            live += (record.get("live") or {}).get("served_by") == "live"
            observed[(*unit.split("/"), record.get("item_id"))] += 1
    found = sum(isinstance(rows, list) for rows in probes.values())
    duplicated = sum(n - 1 for n in observed.values())
    ok7 = (set(card_units) == expected_units and set(disclosed) == expected_units and cached == 0
           and found == len(expected_units) and count > 0 and live == count and stopped == 0
           and set(observed) == pack["expected_keys"] and duplicated == 0)
    print(f"check 7 {name}: units {len(expected_units)} files {found} records {count} live {live}"
          f" cached_or_unconfirmed {cached} stopped {stopped} duplicated {duplicated} pass {ok7}")
    return [number for number, ok in ((1, ok1), (2, ok2), (7, ok7)) if not ok]


def load_arms(given, packs):
    arms = {}
    for name in DECLARED_ORDER:
        run = Path(given[name])
        if not (run / "card.json").exists() or not (run / "outcomes.json").exists():
            continue
        row = name[2]
        card, outcomes = read(run / "card.json"), read(run / "outcomes.json")
        if not isinstance(card, dict) or not isinstance(outcomes, dict):
            raise frozen.Refused(name + " card or outcomes")
        rec, receipt = read(run / "control.json"), read(run / "receipt.json")
        if row != "H" and (not isinstance(rec, dict) or rec.get("arm") != CONTROL[row] or receipt is None):
            raise frozen.Refused(name + " control or receipt")
        if row == "H" and ((run / "control.json").exists() or card.get("system") != "hermes-native"):
            raise frozen.Refused(name + " system row")
        if card.get("pins", {}).get("benchmark_commit") != packs[name[0]]["tasks"]["header"]["commit"]:
            raise frozen.Refused(name + " benchmark commit")
        # Select score-bearing rows immediately. Unread scores never enter subsequent computations.
        selected = packs[name[0]]["tasks"]["rows"] + packs[name[0]]["tasks"]["descriptive"]
        outcomes = {item_key(r): outcomes[item_key(r)] for r in selected if item_key(r) in outcomes}
        arms[name] = dict(name=name, row=row, run=run, card=card, outcomes=outcomes, control=rec,
                          receipt=receipt, units=read(run / "units.json", {}) or {},
                          disclosures=read(run / "disclosures.json", {}) or {})
    return arms


def header(packs, arms, order, reruns, place):
    print("== 1. Header and identity")
    head = packs["A"]["tasks"]["header"]
    print("commit", head["commit"][:12], "edition", head["edition"], "draw hash", head["draw_sha256"][:12])
    for name, path in CODE.items():
        print("code", name, "sha256", sha256(path.read_bytes()).hexdigest()[:12])
    for p, pack in packs.items():
        print("pack", p, "targets", len(pack["tasks"]["rows"]), "descriptive", len(pack["tasks"]["descriptive"]),
              "tasks hash", pack["digest"][:12], "pack hash", pack["tree"][:12],
              "spec hash", pack["tasks"]["header"]["spec_sha256"][:12])
    print("run order", " ".join(order), "equals declared order", tuple(order) == DECLARED_ORDER)
    print("reruns named", " ".join(reruns) or "none")
    for p in frozen.PACKS:
        print(p, "row centres", " ".join(f"{r} {exact(Fraction(sum(place[f'{p}.{k}'] for k in ROWS[r][:2]), 2))}"
                                        for r in ("F", "R", "H", "O")),
              "positions", " ".join(f"{k} {place[f'{p}.{k}']}" for k in ("O3", "B1", "G1", "W1")))
    ref = reference_identity(arms, order)
    print("reference identity", short(ref) if ref is not None else "not recorded")
    for k in DECLARED_ORDER:
        if k not in arms:
            print(k + ": missing (no card.json or outcomes.json)")
    return ref


def pack_code_pins_equal(packs):
    codes = {}
    for p, pack in packs.items():
        codes[p] = {}
        for key in PACK_PINS:
            values = ([pack["index_pins"].get(key)] if key == "scoring_code_sha256" else
                      [m.get(key) for m in pack["code_pins"]])
            # Invalid values carry no printable hash; never echo arbitrary input.
            codes[p][key] = {v if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) else None
                             for v in values}
    recorded = all(values and None not in values for code in codes.values() for values in code.values())
    one_per_pack = all(len(values) == 1 for code in codes.values() for values in code.values())
    same = all(code == codes["A"] for code in codes.values())
    ok = recorded and one_per_pack and same
    print("pack code pins equal pass", ok)
    if not ok:
        for p, code in codes.items():
            for key, values in code.items():
                print("pack code pin", p, key, " ".join(v[:12] if v is not None else "not recorded"
                      for v in sorted(values, key=str)) if values else "not recorded")
    return ok


def checks(args, packs, arms, order, reruns, place):
    ref = header(packs, arms, order, reruns, place)
    print("== 2. Checks before any score")
    missing = set(DECLARED_ORDER) - arms.keys()
    invalid, failed, compacted, mismatch, bad_h = set(), {}, set(), set(), set()
    if not pack_code_pins_equal(packs):
        invalid.add("pack code pins")
    times = [(k, arms[k]["units"].get("start_ms"), arms[k]["units"].get("end_ms")) for k in order if k in arms]
    time_bad = any(not (is_int(s) and is_int(e) and s <= e) for _, s, e in times)
    overlaps = False if time_bad else any(b[1] < a[2] for a, b in pairwise(times))
    if time_bad or overlaps:
        invalid.add("run order")
    print("run order times pass", not (time_bad or overlaps))
    ordered = [arms[name] for name in order if name in arms]
    reference = next((arm for arm in ordered if arm["row"] != "H"), ordered[0] if ordered else None)
    reference_pins = reference["card"].get("pins", {}) if reference else {}

    def pins_match(arm):
        pins = arm["card"].get("pins", {})
        if arm["row"] != "H":
            return pins == reference_pins
        # H's commitment hashes belong to that arm's check 4 alone.
        return {k: v for k, v in pins.items() if k not in H_PINS} == {
            k: v for k, v in reference_pins.items() if k not in H_PINS}

    same_pins = all(pins_match(arm) for arm in ordered)
    if not same_pins:
        invalid.add("card pins")
    print("card pins equal pass", same_pins)
    blocks = {p: {} for p in frozen.PACKS}
    for name, arm in arms.items():
        pack = packs[name[0]]
        if arm["card"].get("pack_hash") != pack["tree"]:
            invalid.add(name)
            print("pack hash fail", name)
        if (ref is None or arm["card"].get("served_identity") != ref or rules.drift(arm) != "no"):
            mismatch.add(name)
        print(f"check 4 {name}: identity pass {name not in mismatch}")
        if arm["row"] == "H":
            pins_ok = all(arm["card"].get("pins", {}).get(k) == getattr(args, k) for k in H_PINS)
            print(f"check 4 {name}: commitment hashes pass {pins_ok}")
            live_ok = system_live(arm, pack)
            complete = all(is_int((arm["outcomes"].get(item_key(r)) or {}).get("score_milli"))
                           for r in pack["tasks"]["rows"])
            if not (pins_ok and live_ok and complete):
                bad_h.add(name)
        else:
            faults = control_checks(arm, pack, blocks[name[0]])
            if faults:
                failed[name] = faults
                invalid.add(name)
            if rules.compacted(arm["receipt"]):
                compacted.add(name)
            print(f"check 8 {name}: compacted {name in compacted} pass {name not in compacted}")
        scored = sum(is_int((arm["outcomes"].get(item_key(r)) or {}).get("score_milli")) for r in pack["tasks"]["rows"])
        print(f"check 5 {name}: scored {scored} of 40 pass {scored == 40}")
    commit = packs["A"]["tasks"]["header"]["commit"]
    lines = args.check3.read_text().splitlines() if args.check3 and args.check3.is_file() else []
    observed = [rules.outcomes_of(lines, t) for t in CHECK3_TESTS]
    ok3 = (lines[:1] == [f"commit {commit}"] and lines[-1:] == ["exit 0"]
           and all(c["PASSED"] >= 1 and sum(c.values()) == c["PASSED"] for c in observed))
    print("check 3: commit", commit[:12], "tests", len(CHECK3_TESTS), "pass", ok3)
    if arms and not ok3:
        invalid.add("check 3")
    bundles, members, left = [], {}, {}
    for p, pack in packs.items():
        for bundle in rules.bundles_of(pack["tasks"]["rows"]):
            bundles.append(dict(bundle, pack=p, life=(p, bundle["life"]),
                                keys=tuple(p + "/" + k for k in bundle["keys"])))
    for t in KINDS:
        members[t] = [b for b in bundles if b["template"] == t]
        left[t] = {}
        for k in DECLARED_ORDER:
            reason = ("missing" if k in missing else "invalid" if k in invalid else "identity mismatch" if k in mismatch
                      else "compacted" if k in compacted else "H checks" if k in bad_h else None)
            if reason is None:
                targets = [r for r in packs[k[0]]["tasks"]["rows"] if r["template_ref"] == t]
                if not all(is_int((arms[k]["outcomes"].get(item_key(r)) or {}).get("score_milli")) for r in targets):
                    reason = "incomplete on this kind"
            if reason:
                left[t][k] = reason
        print("check 6", t, "left out", " ".join(f"{k} ({why})" for k, why in left[t].items()) or "none")
    ctx = dict(args=args, packs=packs, arms=arms, invalid=invalid, failed=failed, missing=missing,
               mismatch=mismatch, compacted=compacted, bad_h=bad_h, bundles=bundles, members=members, left=left,
               templates=KINDS)
    ctx["use"] = {t: {row: [pooled_repeat(ctx, k) for k in repeats
                            if all(f"{p}.{k}" not in left[t] for p in frozen.PACKS)]
                       for row, repeats in ROWS.items()} for t in KINDS}
    return ctx


def pooled_repeat(ctx, repeat):
    return dict(name=repeat, outcomes={p + "/" + k: value for p in frozen.PACKS
                for k, value in ctx["arms"][f"{p}.{repeat}"]["outcomes"].items()})


def reading(ctx, t):
    used, support = ctx["use"][t], ctx["members"][t]
    means = {r: pts(used[r], support) for r in ROWS}
    f = means["F"]
    os = [a for a in used["O"] if a["name"] in ("O1", "O2")]
    c = pts(os, support) if len(os) == 2 else None
    lines = [f"kind {t}: " + " ".join(f"{r} {exact(means[r])}" for r in ("F", "R", "B", "G", "W")) + f" c {exact(c)}"]
    low = state("low", None, None, c)
    low_trials = [state("low", None, None, pts([o], support)) for o in used["O"]]
    disagree = any(flag != low for flag in low_trials)
    lines.append(f"low: on means {low} margin {exact(margin('low', None, None, c, len(support)))}"
                 f" combinations {len(low_trials)} agreeing {sum(flag == low for flag in low_trials)}"
                 + " trials " + ", ".join(f"{a['name']} {flag}" for a, flag in zip(used["O"], low_trials, strict=False)))
    candidate = []
    for row in (*ANCHOR_ROWS, "F"):
        flag = "floor" if row == "F" else "naive"
        mean = state(flag, f, means[row], c)
        combos = ([(pts([x], support), pts([y], support), pts([o], support))
                   for x, y, o in product(used["F"], used[row], used["O"])] if row != "F" else
                  [(pts([x], support), None, pts([o], support)) for x, o in product(used["F"], used["O"])])
        names = ([(x["name"], y["name"], o["name"]) for x, y, o in product(used["F"], used[row], used["O"])]
                 if row != "F" else [(x["name"], o["name"]) for x, o in product(used["F"], used["O"])])
        agree = sum(state(flag, *v) == mean for v in combos)
        candidate.append(mean == "no" and bool(combos) and agree == len(combos))
        lines.append(f"{row} flag: on means {mean} margin {exact(margin(flag, f, means[row], c, len(support)))}"
                     f" combinations {len(combos)} agreeing {agree}"
                     + " trials " + ", ".join("/".join(n) + " " + state(flag, *v) for n, v in zip(names, combos, strict=False)))
    left = {k: why for k, why in ctx["left"][t].items() if ".H" not in k}
    result = ("unresolved" if left else "unstable" if disagree else "low" if low == "applies" else
              "ranking candidate" if all(candidate) and max(means[r] for r in ANCHOR_ROWS) <= 35 else "cleared")
    if left:
        lines.append("left out " + " ".join(f"{k} ({why})" for k, why in left.items()))
    return lines, result


def pack_row(ctx, p, row, t):
    """One pack's row for kind t: every repeat of the row on that pack usable for t, pooled."""
    repeats = ROWS[row]
    arms = [dict(outcomes={p + "/" + key: value for key, value in ctx["arms"][f"{p}.{k}"]["outcomes"].items()})
            for k in repeats if f"{p}.{k}" not in ctx["left"][t]]
    members = [b for b in ctx["members"][t] if b["pack"] == p]
    return [bundle_score(arm["outcomes"], b) for arm in arms for b in members], len(arms) == len(repeats)


def score_line(scores):
    count = Counter(scores)
    got = [s for s in scores if s is not None]
    return (f"pairs {len(scores)} right {count[1000]} wrong {count[-1000]} without_credit {count[0]}"
            f" non_result {count[None]} points {exact(Fraction(sum(got), len(got)) / 10 if got else None)}")


def scores(ctx):
    print("== 3. Scores")
    for k in DECLARED_ORDER:
        for t in KINDS:
            local = [b for b in ctx["members"][t] if b["pack"] == k[0]]
            outcomes = {k[0] + "/" + key: val for key, val in ctx["arms"].get(k, {}).get("outcomes", {}).items()}
            values = [bundle_score(outcomes, b) for b in local]
            print(k, t, score_line(values), "incomplete" if k in ctx["left"][t] else "complete")
    for row, repeats in ROWS.items():
        for t in KINDS:
            for repeat in repeats:
                usable = next((a for a in ctx["use"][t][row] if a["name"] == repeat), None)
                values = [bundle_score(usable["outcomes"], b) if usable else None for b in ctx["members"][t]]
                print("pooled repeat", repeat, t, score_line(values), "complete" if usable else "incomplete")
            for p in frozen.PACKS:
                values, complete = pack_row(ctx, p, row, t)
                print("row", row, p, t, score_line(values), "complete" if complete else "incomplete")
            arms = ctx["use"][t][row]
            values = [bundle_score(arm["outcomes"], b) for arm in arms for b in ctx["members"][t]]
            print("row", row, "pooled", t, score_line(values), "complete" if len(arms) == len(repeats) else "incomplete")
    print("== 4. Readings")
    for t in KINDS:
        lines, result = reading(ctx, t)
        print("\n".join(lines))
        print(f"reading {t}: {result}")
        if result != "ranking candidate":
            print("differs from round 2:", t)


def row_repeats(row):
    return ROWS[row][:2] if row == "O" else ROWS[row]


def life_scores(ctx, row):
    repeats = row_repeats(row)
    if any(f"{p}.{k}" in ctx["left"][t] for t in KINDS for p in frozen.PACKS for k in repeats):
        return None
    arms = [pooled_repeat(ctx, k) for k in repeats]
    lives = sorted({b["life"] for b in ctx["bundles"]})
    return {life: pts(arms, [b for b in ctx["bundles"] if b["life"] == life]) / 100 for life in lives}


def comparison(differences, name):
    if differences is None:
        return dict(reading="unresolved", differences=None, nonzero=None, mean=None, p=None)
    values = list(differences.values())
    mean = sum(values) / len(values)
    nonzero = sum(v != 0 for v in values)
    # The statistics API requires string life keys. Pack and within-pack index remain distinct.
    p = sign_flip_p({str(k): v for k, v in differences.items()}, seed="fresh-seed-followup", name=name)
    result = "inconclusive" if nonzero < 6 else "holds" if mean > 0 and p < Fraction(1, 20) else "does not hold"
    return dict(reading=result, differences=differences, nonzero=nonzero, mean=mean, p=p)


def contrast_verdict(readings):
    return next((r for r in ("does not hold", "unresolved", "inconclusive") if r in readings), "holds")


def difference(ctx, a, b, name):
    left, right = life_scores(ctx, a), life_scores(ctx, b)
    return comparison(None if left is None or right is None else {k: left[k] - right[k] for k in left}, name)


def kind_points(ctx, row, kind):
    repeats = row_repeats(row)
    arms = [a for a in ctx["use"][kind][row] if a["name"] in repeats]
    return pts(arms, ctx["members"][kind]) if len(arms) == len(repeats) else None


def print_comparison(ctx, name, value, *, classify=True):
    verdict = value["reading"] + " " if classify else ""
    print(f"{name}: {verdict}nonzero {value['nonzero']} mean {exact(value['mean'])} p {exact(value['p'])}")
    if value["differences"] is not None:
        for p in frozen.PACKS:
            lives = sorted(life for life in value["differences"] if life[0] == p)
            for index, life in enumerate(lives, 1):
                print(name, p, index, "difference", exact(value["differences"][life]))


def contrasts(ctx):
    print("== 5. Contrasts")
    for name, row in (("Room", "O"), ("Use", "H")):
        comparisons = {}
        for anchor in ANCHOR_ROWS:
            title = f"{name} against {anchor}"
            value = difference(ctx, row, anchor, title)
            comparisons[anchor] = value["reading"]
            print_comparison(ctx, title, value)
            if value["reading"] == "unresolved":
                missing = {k: why for t in KINDS for k, why in ctx["left"][t].items()
                           if k[2:] in (*row_repeats(row), *row_repeats(anchor))}
                print(title, "left out", " ".join(f"{k} ({why})" for k, why in missing.items()))
            for t in KINDS:
                a, b = kind_points(ctx, row, t), kind_points(ctx, anchor, t)
                delta = None if a is None or b is None else a - b
                print(title, t, "points difference", exact(delta))
                if delta is not None and delta <= 0:
                    print(title, "zero or negative:", t)
        print(f"{name}: {contrast_verdict(list(comparisons.values()))}")
        for anchor, value in comparisons.items():
            if value == "does not hold":
                print(name, "does not hold against", anchor)


def descriptive(ctx):
    print("== 6. Descriptive kinds")
    excluded = ctx["invalid"] | ctx["mismatch"] | ctx["compacted"] | ctx["bad_h"]
    def values(labels, kind, *, pooled=False):
        got, missing = [], 0
        for label in labels:
            outcomes = ({} if pooled and label in excluded else ctx["arms"].get(label, {}).get("outcomes", {}))
            for r in ctx["packs"][label[0]]["tasks"]["descriptive"]:
                if r["template_ref"] != kind:
                    continue
                score = (outcomes.get(item_key(r)) or {}).get("score_milli")
                if is_int(score):
                    got.append(score)
                else:
                    missing += 1
        return f"scored {len(got)} not_scored {missing} points {exact(Fraction(sum(got), len(got)) / 10 if got else None)}"
    for label in DECLARED_ORDER:
        for kind in frozen.DESCRIPTIVE.values():
            print(f"descriptive {label} {kind}: {values([label], kind)}")
    for row, repeats in ROWS.items():
        for kind in frozen.DESCRIPTIVE.values():
            for p in frozen.PACKS:
                labels = [f"{p}.{k}" for k in repeats]
                print(f"descriptive {p}.{row} {kind}: {values(labels, kind, pooled=True)}")
            labels = [f"{p}.{k}" for p in frozen.PACKS for k in repeats]
            print(f"descriptive {row} {kind}: {values(labels, kind, pooled=True)}")


def also(ctx):
    print("== 7. Also printed")
    for t in KINDS:
        h, f = kind_points(ctx, "H", t), kind_points(ctx, "F", t)
        print("H minus F", t, "points", exact(None if h is None or f is None else h - f))
    print_comparison(ctx, "H minus F; no significance claimed", difference(ctx, "H", "F", "H minus F"), classify=False)
    pins = []
    for p, pack in ctx["packs"].items():
        code = {k: {m.get(k) for m in pack["code_pins"]} for k in PACK_PINS}
        pins.append(code)
        for key in PACK_PINS:
            print("pack code pin", p, key, " ".join(v[:12] if isinstance(v, str) else "not recorded" for v in sorted(code[key], key=str)))
        for row, control in CONTROL.items():
            if row not in ANCHOR_ROWS:
                continue
            outcomes = {p + "/" + item_key(r): pack["reports"][r["life"]][control]["items"].get(r["item_id"])
                        for r in pack["tasks"]["rows"]}
            for t in KINDS:
                members = [b for b in ctx["members"][t] if b["pack"] == p]
                # The live figure is section 3's row on this pack: its usable repeats, pooled (D19).
                scored = [v for v in pack_row(ctx, p, row, t)[0] if v is not None]
                live_pts = Fraction(sum(scored), len(scored)) / 10 if scored else None
                print("scripted beside live", p, row, t, "scripted points", exact(pts([dict(outcomes=outcomes)], members)),
                      "live points", exact(live_pts))
    print("three packs code pins agree", all(p == pins[0] for p in pins) and all(len(v) == 1 for p in pins for v in p.values()))
    for k, arm in ctx["arms"].items():
        live = arm["disclosures"].get("live", {})
        unreadable = arm["disclosures"].get("unreadable_state", [])
        arm_key = arm["control"]["arm"] if arm["control"] else "system"
        count = (unreadable.get(arm_key, 0) if isinstance(unreadable, dict)
                 else len(unreadable) if isinstance(unreadable, list) else unreadable if is_int(unreadable) else 0)
        identity = arm["card"].get("served_identity")
        count = count if is_int(count) else "not recorded"
        print(k, "sends", live.get("sends") if is_int(live.get("sends")) else "not recorded",
              "start", arm["units"].get("start_ms"), "end", arm["units"].get("end_ms"),
              "served identity", short(identity) if identity is not None else "not recorded", "unreadable_state", count)
        if arm["row"] != "H":
            continue
        phase = live.get("phase_sends", {})
        print(k, "phase sends", " ".join(f"{p} {phase.get(p) if is_int(phase.get(p)) else 'not recorded'}" for p in ("floor", "system")))
        units = {f"{life}/{b}" for life in ctx["packs"][k[0]]["reports"] for b in ("B0", "B1")}
        card = arm["card"].get("floor", {}).get("units", {})
        disclosed = arm["disclosures"].get("floor", {})
        floor = read(arm["run"] / "no_memory.json", {}) or {}
        cache = {u for u in units if card.get(u, {}).get("cached") is not False or disclosed.get(u, {}).get("cached") is not False}
        measured = {u for u in units - cache if card.get(u, {}).get("cached") is False and disclosed.get(u, {}).get("cached") is False
                    and (floor.get(u) or {}).get("stops") == {u.replace("/", ""): None}}
        print(k, "floor live", len(measured), "cached or unconfirmed", len(cache), "stopped or not recorded", len(units - measured - cache))
        receipt = read(arm["run"] / "receipts/system.json")
        if not isinstance(receipt, dict):
            print(k, "summariser input not recorded output not recorded")
        else:
            tokens = [r for r in receipt.get("tokens_by_role", []) if r.get("role") == "summariser"]
            print(k, "summariser input", sum(r["input"] for r in tokens if is_int(r.get("input"))),
                  "output", sum(r["output"] for r in tokens if is_int(r.get("output"))))


def oracle_filter(ctx):
    print("== 8. Oracle filter")
    output, total = {}, 0
    excluded = ctx["invalid"] | ctx["mismatch"] | ctx["compacted"]
    for p, pack in ctx["packs"].items():
        # Round 2's rule: a missing or excluded O arm's trial is unscored; an incomplete one keeps its scored items.
        labels = [f"{p}.{k}" for k in ROWS["O"]]
        unscored = [k for k in labels if k not in ctx["arms"] or k in excluded]
        trials = [{} if k in unscored else {p + "/" + key: value for key, value in ctx["arms"][k]["outcomes"].items()}
                  for k in labels]
        print("filter", p, "trials unscored", " ".join(unscored) or "none")
        result, excluded_by_kind = {}, {}
        for t in KINDS:
            excluded_by_kind[t] = [k for k in labels if k in ctx["left"][t]]
            kept = dict(kept=[], dropped=[], unresolved=[])
            for b in (b for b in ctx["members"][t] if b["pack"] == p):
                verdict = bundle_verdict([twin(trials, key)[1] for key in b["keys"]])
                kept[{"pass": "kept", "fail": "dropped", "unresolved": "unresolved"}[verdict]].append(dict(
                    life=b["life"][1], bundle_id=b["bundle_id"], item_ids=sorted(key.split("/", 3)[-1] for key in b["keys"])))
            result[t] = kept
            total += len(kept["kept"])
            print("filter", p, t, "kept", len(kept["kept"]), "dropped", len(kept["dropped"]), "unresolved", len(kept["unresolved"]))
        # Full outcome hashes bind the filter receipt; scores still come only from frozen rows.
        digests = {f"{p}.{k}": sha256((ctx["arms"][f"{p}.{k}"]["run"] / "outcomes.json").read_bytes()).hexdigest()
                   if f"{p}.{k}" in ctx["arms"] else None for k in ROWS["O"]}
        # o_excluded: the trials unscored here; o_excluded_by_kind: the O arms left out of each kind's readings.
        output[p] = dict(tasks_sha256=pack["digest"], o_outcomes_sha256=digests, o_excluded=unscored,
                         o_excluded_by_kind=excluded_by_kind, templates=result)
    print("filter total kept", total, "of 60")
    if ctx["args"].filter_out:
        raw = canon(output)
        ctx["args"].filter_out.write_bytes(raw)
        print("filter hash", sha256(raw).hexdigest()[:12])


def finish(ctx):
    args = ctx["args"]
    again = [k for k in DECLARED_ORDER if k in ctx["failed"] and k in args.reruns_list]
    if again or ("check 3" in ctx["invalid"] and args.after_reruns):
        reasons = [f"{k} fails check {','.join(map(str, ctx['failed'][k]))} after its rerun" for k in again]
        if "check 3" in ctx["invalid"]:
            reasons.append("check 3 not shown passing")
        print("RUN ENDS: " + "; ".join(reasons) + " (§4); no score is opened")
        gone = (list(DECLARED_ORDER) if "check 3" in ctx["invalid"] and args.after_reruns else
                [k for k in DECLARED_ORDER if any(k in left for left in ctx["left"].values())])
        print("missing observations:", " ".join(gone))
        for t in KINDS:
            print(f"reading {t}: unresolved")
        return 5
    if ctx["invalid"]:
        for fault in ("run order", "card pins", "pack code pins", "check 3"):
            if fault in ctx["invalid"]:
                print("fault:", fault)
        for k in DECLARED_ORDER:
            if k in ctx["invalid"] or ("card pins" in ctx["invalid"] and k in ctx["arms"]):
                print("INVALID CONTROL ROW", k)
        return 3
    pending = [k for k in DECLARED_ORDER if any(k in left for left in ctx["left"].values())]
    if not ctx["arms"]:
        if args.after_reruns:
            return 3
    # An arm is published as it is only after its one rerun; any other pending arm is still owed it (§3, D12).
    owed = [k for k in pending if not args.after_reruns or k not in args.reruns_list]
    if owed:
        print("pending before any score:", " ".join(owed), "-", RERUN)
        return 4
    if args.checks_only:
        return 0
    scores(ctx)
    contrasts(ctx)
    descriptive(ctx)
    also(ctx)
    oracle_filter(ctx)
    return 0


def main(argv=None):
    parser = frozen.Parser(description=__doc__)
    parser.add_argument("--pack", nargs=4, action="append", required=True)
    for key in (*H_PINS, "order", "attempts"):
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--reruns")
    for key in ("after-reruns", "checks-only"):
        parser.add_argument("--" + key, action="store_true")
    for key in ("check3", "filter-out"):
        parser.add_argument("--" + key, type=Path)
    parser.add_argument("arms", nargs="+")
    try:
        args = parser.parse_args(argv)
        given = dict(a.split("=", 1) for a in args.arms)
        if set(given) != set(DECLARED_ORDER) or len(args.arms) != 36:
            raise frozen.Refused("labels must be the 36 arms once each")
        order = args.order.split(",")
        if len(order) != 36 or set(order) != set(DECLARED_ORDER):
            raise frozen.Refused("run order labels")
        reruns = args.reruns.split(",") if args.reruns else []
        if len(reruns) != len(set(reruns)) or not set(reruns) <= set(DECLARED_ORDER):
            raise frozen.Refused("rerun labels")
        args.reruns_list = reruns
        place = positions(args.attempts, order, reruns)
        if any(not re.fullmatch(r"[0-9a-f]{64}", getattr(args, k)) for k in H_PINS):
            raise frozen.Refused("commitment hash format")
        if len(args.pack) != 3 or {p[0] for p in args.pack} != set(frozen.PACKS):
            raise frozen.Refused("three pack inputs required")
        packs = {letter: load_pack(letter, Path(path), Path(tasks), digest) for letter, path, tasks, digest in args.pack}
        headers = [packs[p]["tasks"]["header"] for p in frozen.PACKS]
        if any(len({h[k] for h in headers}) != 1 for k in ("commit", "draw_sha256")):
            raise frozen.Refused("lists must share one commit and draw")
        if any(len({h[k] for h in headers}) != 3 for k in ("pack_hash", "spec_sha256")):
            raise frozen.Refused("pack and spec hashes must be distinct")
        arms = load_arms(given, packs)
        return finish(checks(args, packs, arms, order, reruns, place))
    except frozen.Refused as error:
        print("REFUSED:", error)
        return 3
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        print("REFUSED: input shape or unreadable input")
        return 3


if __name__ == "__main__":
    sys.exit(main())
