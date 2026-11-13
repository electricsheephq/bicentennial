"""Validity round 1: how the v2 templates' control trials are read (results/validity-1/DECLARATION.md §3-§5).

Usage: python table.py --packs PACKS_DIR --tasks TASKS.json --tasks-sha256 HEX --order F1,R1,O1,O2,R2,F2,O3
       F1=RUN_DIR F2=RUN_DIR R1=RUN_DIR R2=RUN_DIR O1=RUN_DIR O2=RUN_DIR O3=RUN_DIR
       [--reruns LABELS] [--after-reruns] [--checks-only] [--check3 FILE] [--filter-out FILTER.json]
Adapted from Milestone 1's table.py (imported by path; its checks, flag rules and twin filter rule are reused). Reads
only the target items of TASKS.json (tasks.py), grouped by template ref: an action pair scores twin_min of its twins,
a count question its own score_milli (halves kept). Prints, in order: 1 header and identity, with each row's centre
(F, R, O1-O2) and O3's position in the order the arms actually ran (§3); 2 checks before any score (§4); 3 scores by
template; 4 readings (§5); 5 the oracle filter (counts only; FILTER.json with --filter-out).
Exit 3: a refusal (a run without control.json or with another row's control, TASKS sha256 or pack hash mismatch, a
target item absent from the pack), or check 1, 2, 3 or 7, the run order, the card pins or the pack failing. Exit 4:
check 4 or 5 open without --after-reruns. Exit 5: an arm named in --reruns fails check 1, 2 or 7 again, so the round
ends (§4): the checks and missing observations are printed, every template reads unresolved, and no score is opened.
Check 4's reference identity is the most common served identity among the arms; on a tie, the tied identity served to
the arm that ran earliest in --order. A drift disclosure, or none recorded, is a mismatch (M1 §11.15).
Prints counts, labels, 12-character hash prefixes and pass/fail only: never task text, answers, control text, item
or bundle ids, served identity values, or paths.
"""

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from fractions import Fraction
from hashlib import sha256
from itertools import pairwise, product
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "m1_table", HERE.parents[1] / "milestone-1" / "2026-11-11-separation-table" / "table.py")
m1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m1)
_spec = importlib.util.spec_from_file_location("validity_tasks", HERE / "tasks.py")
frozen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frozen)

from bicentennial.canon import canon  # noqa: E402
from bicentennial.score.bundle import twin_min  # noqa: E402

is_int, short, exact, read, refusal_code, outcomes_of = (m1.is_int, m1.short, m1.exact, m1.read, m1.refusal_code,
                                                         m1.outcomes_of)
state, margin, SEVEN, CHECK3_TESTS = m1.state, m1.margin, m1.SEVEN, m1.CHECK3_TESTS
recompute_blocks, frame_sha256, pack_tree_hash = m1.recompute_blocks, m1.frame_sha256, m1.pack_tree_hash

ROWS = {"F": ("F1", "F2"), "R": ("R1", "R2"), "O": ("O1", "O2", "O3")}
CORE = tuple(a for arms in ROWS.values() for a in arms)
CONTROL = {"F": "no_memory", "R": "naive_rag", "O": "oracle_evidence"}
DECLARED_ORDER = ("F1", "R1", "O1", "O2", "R2", "F2", "O3")
COUNT_REF = "recall-count-v2"
RERUN = "rerun once (§4.4, §4.5), then run again with --after-reruns"
VALUES = (1000, 500, 0, -500, -1000)


def refuse(reason):
    print("REFUSED:", reason)
    return 3


def load_tasks(path, want):
    """(the TASKS.json object, None) or (None, a refusal): the file's sha256 must be the one given (posted before arm 1)."""
    data = path.read_bytes()
    if sha256(data).hexdigest() != want.lower():
        return None, "TASKS.json sha256 differs from --tasks-sha256"
    return json.loads(data), None


def bundles_of(rows):
    """The scored bundles: a twin pair (by bundle id) or one count question; keys are life/branch/item_id."""
    groups = {}
    for r in rows:
        key = (r["template_ref"], r["life"], r["bundle_id"] or r["item_id"])
        groups.setdefault(key, dict(template=r["template_ref"], life=r["life"], bundle_id=r["bundle_id"],
                                    keys=[]))["keys"].append(f"{r['life']}/{r['branch']}/{r['item_id']}")
    return [dict(g, keys=tuple(sorted(g["keys"]))) for _, g in sorted(groups.items())]


def bundle_score(outcomes, b):
    """milli: twin_min of an action pair's twins; a count question's own score_milli (+500 and -500 kept)."""
    rows = [outcomes.get(k) for k in b["keys"]]
    if any(r is None or not is_int(r.get("score_milli")) for r in rows):
        return None
    return twin_min(*rows) if len(rows) == 2 else rows[0]["score_milli"]


def pts(arms, members):
    """100 times the mean bundle score over the arms' repeats on members (all scored in every arm)."""
    if not arms or not members:
        return None
    return Fraction(sum(bundle_score(a["outcomes"], b) for a in arms for b in members), len(arms) * len(members)) / 10


def common(arms, members):
    return [b for b in members if all(bundle_score(a["outcomes"], b) is not None for a in arms)] if arms else []


def line(scores):
    n, got = Counter(scores), [s for s in scores if s is not None]
    return (f"bundles {len(scores)} " + " ".join(f"{v:+d} {n[v]}" if v else f"0 {n[0]}" for v in VALUES) + f" non_result {n[None]}"
            f" points {exact(Fraction(sum(got), len(got)) / 10 if got else None)}")


def positions(order, reruns):
    """{label: 1-based position of the attempt used, in the order the arms actually ran}. A rerun arm's first attempt
    ran in its declared slot, before the next arm listed whose slot comes after it, and before its own rerun (§3)."""
    seq, done = [], set()
    for k in order:
        for r in [r for r in DECLARED_ORDER if r in reruns and r not in done
                  and DECLARED_ORDER.index(r) <= DECLARED_ORDER.index(k) - (k not in reruns)]:
            seq.append(("first attempt", r))
            done.add(r)
        seq.append(("used", k))
    return {k: n for n, (what, k) in enumerate(seq, 1) if what == "used"}


def reference_identity(arms, order):
    """The most common served identity; on a tie, the tied identity served to the arm that ran earliest (§4.4)."""
    counts = Counter(a["card"]["served_identity"] for a in arms.values())
    top = max(counts.values())
    tied = {i for i, n in counts.items() if n == top}
    return next(arms[k]["card"]["served_identity"] for k in order if k in arms
                and arms[k]["card"]["served_identity"] in tied)


def drift(arm):
    live = arm["disclosures"].get("live")
    if not isinstance(live, dict) or "identity_drift" not in live:
        return "not recorded"
    return "no" if live["identity_drift"] is None else "yes"


def load_pack(packs):
    """{life: {item_id: naive report}} from the pack's scripted naive retrieval (check 2 R, check 7)."""
    out = {}
    for sealed in sorted(Path(packs).glob("pack/*/*/*/sealed")):
        life = {r["life"] for r in json.loads((sealed / "records.json").read_text())}
        assert len(life) == 1, "a sealed life's records name more than one life"
        reports = json.loads((sealed / "naive_rag.json").read_text())["arm"]["reports"]
        out[life.pop()] = {r["item_id"]: r for r in reports}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--tasks-sha256", required=True)
    parser.add_argument("--order", required=True)
    parser.add_argument("--reruns", help="labels rerun after their first attempt, in the order they reran (§4)")
    parser.add_argument("--after-reruns", action="store_true",
                        help="publish arms still mismatched or incomplete after their one rerun (§4.4-§4.6)")
    parser.add_argument("--checks-only", action="store_true", help="print sections 1 and 2 only")
    parser.add_argument("--check3", type=Path, help="verbose pytest output of CHECK3_TESTS run at the run commit")
    parser.add_argument("--filter-out", type=Path, help="write FILTER.json here when the scores are opened")
    parser.add_argument("arms", nargs="+", metavar="LABEL=RUN_DIR")
    args = parser.parse_args(argv)
    given = dict(a.split("=", 1) for a in args.arms)
    if sorted(given) != sorted(CORE):
        parser.error("labels: all of " + " ".join(CORE))
    order = args.order.split(",")
    if sorted(order) != sorted(CORE):
        parser.error("--order must list the seven labels once each")
    reruns = args.reruns.split(",") if args.reruns else []
    if len(set(reruns)) != len(reruns) or not set(reruns) <= set(CORE):
        parser.error("--reruns must list labels, each once")
    # The frozen list (§3): its posted sha256, its pack, and every target item present in the pack.
    tasks, refusal = load_tasks(args.tasks, args.tasks_sha256)
    if refusal:
        return refuse(refusal)
    tree = pack_tree_hash(args.packs)
    if tasks["header"]["pack_hash"] != tree:
        return refuse("TASKS.json pack hash differs from the --packs tree hash")
    present = {(rec["life"], rec["branch"], rec["item_id"], f"{rec['template_id']}-v{rec['template_version']}",
                rec["bundle_id"]) for _, rec, _ in frozen.pack_records(args.packs)}
    absent = sum((r["life"], r["branch"], r["item_id"], r["template_ref"], r["bundle_id"]) not in present
                 for r in tasks["rows"])
    if absent:
        return refuse(f"{absent} target items of TASKS.json are absent from the pack")
    arms, missing = {}, {}
    for name in CORE:
        run = Path(given[name])
        if not ((run / "card.json").exists() and (run / "outcomes.json").exists()):
            missing[name] = refusal_code(run)
            continue
        control = read(run / "control.json")
        if control is None:
            return refuse(f"{name} has no control.json (control rows only, §2)")
        if control.get("arm") != CONTROL[name[0]]:
            return refuse(f"{name}'s control is not {CONTROL[name[0]]}")
        arms[name] = dict(name=name, row=name[0], run=run, card=read(run / "card.json"), control=control,
                          outcomes=read(run / "outcomes.json"), units=read(run / "units.json") or {},
                          disclosures=read(run / "disclosures.json") or {})
    if not arms:
        print("== 1. Header and identity")
        for name, code in missing.items():
            print(f"{name}: missing (no card.json or outcomes.json; refusal code {code})")
        print("no arm has card.json and outcomes.json: no check or reading can be computed")
        if not args.after_reruns:
            print("pending before any score:", " ".join(missing), "-", RERUN)
            return 4
        return 3
    ctx = checks(args, load_pack(args.packs), tasks, arms, order, reruns, missing, tree)
    if ctx["invalid"]:
        again = sorted(ctx["invalid"] & set(reruns), key=CORE.index)
        if again:
            round_ends(ctx, again)
            return 5
        if ctx["violation"]:
            print(f"RUN ORDER VIOLATION: {ctx['violation']}")
        for what, text in (("card pins", "CARD PINS DIFFER between arms (see PIN MISMATCH above): not pooled"),
                           ("pack", "PACK DIFFERS from --packs for an arm (see PACK MISMATCH above): not pooled"),
                           ("check 3", "CHECK 3 NOT SHOWN PASSING at the run commit (see check 3 above): no score"
                                       " is opened")):
            if what in ctx["invalid"]:
                print(text)
        for name in sorted(ctx["invalid"] & set(CORE), key=CORE.index):
            print("INVALID CONTROL ROW", name)
        return 3
    pending = sorted(ctx["mismatched"] | ctx["incomplete"] | set(missing), key=CORE.index)
    if pending and not args.after_reruns:
        print("pending before any score:", " ".join(pending), "-", RERUN)
        return 4
    if args.checks_only:
        return 0
    scores(ctx)
    oracle_filter(ctx, args)
    return 0


def checks(args, pack, tasks, arms, order, reruns, missing, tree):
    """Sections 1 and 2; returns what sections 3-5 need. Missing repeats enter no check (§4.6)."""
    bundles = bundles_of(tasks["rows"])
    templates = sorted({b["template"] for b in bundles})
    targets = [k for b in bundles for k in b["keys"]]
    invalid, failed = set(), {}

    # 1. Header and identity.
    print("== 1. Header and identity")
    print("target items", len(targets), "bundles", len(bundles), "templates", " ".join(templates),
          "| tasks sha256", args.tasks_sha256.lower()[:12], "| pack_hash", tree[:12])
    print("run order", ",".join(order), "| equals the declared order", tuple(order) == DECLARED_ORDER,
          "| reruns named", ",".join(reruns) or "none", "| --after-reruns given", args.after_reruns)
    for name, code in missing.items():
        print(f"{name}: missing (no card.json or outcomes.json; refusal code {code})"
              + (", published as missing after its rerun" if args.after_reruns else ""))
    # §4: only a named rerun may run later than its slot, never before an arm that was not itself rerun and whose
    # slot comes before its own (M1 §11.9).
    at = {k: n for n, k in enumerate(order)}
    departure = (("the order listed is not the declared order" + (f" apart from the reruns named ({','.join(reruns)})"
                                                                   if reruns else ""))
                 if [k for k in order if k not in reruns] != [k for k in DECLARED_ORDER if k not in reruns] else
                 next((f"rerun {r} is listed before {k}, whose slot comes before its own"
                       for r in reruns for k in DECLARED_ORDER[:DECLARED_ORDER.index(r)]
                       if k not in reruns and at[k] > at[r]), None))
    times = [(k, arms[k]["units"].get("start_ms"), arms[k]["units"].get("end_ms")) for k in order if k in arms]
    violation = departure or next((f"{k} has no start or end time" for k, s, e in times
                                   if not (is_int(s) and is_int(e) and s <= e)), None) or next(
        (f"{b[0]} starts before {a[0]} ends" for a, b in pairwise(times) if b[1] < a[2]), None)
    print("run order verified" if violation is None else f"RUN ORDER VIOLATION: {violation}")
    place = positions(order, reruns)
    print(f"row centres in the order the arms actually ran (positions 1-{len(order) + len(reruns)}, each rerun arm's"
          " first attempt in its own slot): " + " ".join(
              f"{r} {exact(Fraction(sum(place[k] for k in names[:2]), 2))}" for r, names in ROWS.items())
          + f"; O3 at {place['O3']} (declared order: each centre 7/2)")
    if violation is not None:
        invalid.add("run order")
    ref = reference_identity(arms, order)
    for name in [k for k in order if k in arms]:
        arm = arms[name]
        card, units = arm["card"], arm["units"]
        when = [datetime.fromtimestamp(units[k] / 1000, UTC).isoformat(timespec="seconds") if is_int(units.get(k))
                else "n/a" for k in ("start_ms", "end_ms")]
        print(f"{name}: tier {card['tier']} control {arm['control']['arm']} model {card['model']} effort"
              f" {card['effort']} pack_hash {card['pack_hash'][:12]} start {when[0]} end {when[1]} served_identity"
              f" {short(card['served_identity'])} matches_reference {card['served_identity'] == ref}"
              f" identity changed during the run {drift(arm)}")
        print("  pins", json.dumps({k: card["pins"][k][:12] for k in sorted(card["pins"])}))
    print("reference identity", short(ref), "(most common; on a tie, the tied identity served to the earliest arm)")
    ran = [k for k in CORE if k in arms]
    pins = sorted({key for k in ran for key in arms[k]["card"]["pins"]})
    differ = {key: sorted({str(arms[k]["card"]["pins"].get(key)) for k in ran}) for key in pins}
    differ = {key: values for key, values in differ.items() if len(values) > 1}
    print("one commit for every arm (card pins equal)", not differ)
    for key, values in differ.items():
        print(f"PIN MISMATCH: {key}:", "; ".join(
            f"{v[:12]} ({','.join(k for k in ran if str(arms[k]['card']['pins'].get(key)) == v)})" for v in values))
    if differ:
        invalid.add("card pins")
    for name in ran:
        if arms[name]["card"]["pack_hash"] != tree:
            print(f"PACK MISMATCH: {name} pack_hash {arms[name]['card']['pack_hash'][:12]} (--packs {tree[:12]})")
            invalid.add("pack")
    mismatched = {k for k in ran if arms[k]["card"]["served_identity"] != ref or drift(arms[k]) != "no"}

    # 2. Checks before any score.
    print("\n== 2. Checks before any score (§4)")
    blocks = {}
    for name in ran:
        arm, rec = arms[name], arms[name]["control"]
        if arm["row"] == "F":
            ok = rec.get("frame_sha256") is None and rec.get("block_sha256") == {}
            print(f"check 1 {name}: no blocks {rec.get('block_sha256') == {}} pass {ok}")
        else:
            want = blocks.setdefault(rec["arm"], recompute_blocks(args.packs, rec["arm"]))
            got = rec.get("block_sha256") or {}
            matched = sum(got.get(k) == v for k, v in want.items())
            frame = rec.get("frame_sha256") == frame_sha256()
            ok = bool(frame and want and matched == len(want) == len(got))
            print(f"check 1 {name}: frame_sha256 {frame} blocks matched {matched} of {len(want)} mismatched"
                  f" {len(want) - matched} recorded but not recomputed {len(got.keys() - want.keys())} pass {ok}")
        if not ok:
            failed.setdefault(name, []).append(1)
    expected_units = {f"{life}/{branch}" for life in pack for branch in ("B0", "B1")}
    probed = {(life, i) for life in pack for i in pack[life]}
    probe_files = {name: {unit: read(arms[name]["run"] / arms[name]["control"]["arm"] / unit / "t2lite_probes.json")
                          for unit in sorted(expected_units)} for name in ran}
    # Check 2 reads the probe turn's first request, the one that carries the block (M1 §11.5), on the 35 targets.
    for name in [k for k in ran if arms[k]["row"] != "F"]:
        first = {f"{unit}/{r.get('item_id')}": (r.get("shadow") or {}).get("in_context_initial")
                 for unit, probes in probe_files[name].items() for r in probes or []}
        if arms[name]["row"] == "O":
            true = sum(first.get(k) is True for k in targets)
            print(f"check 2 {name}: needed fact in the probe turn's first request on {true} of {len(targets)} target"
                  f" items pass {true == len(targets)}")
            ok = true == len(targets)
        else:
            report = {k: pack.get(k.split("/")[0], {}).get(k.split("/", 2)[2], {}).get("in_context") for k in targets}
            equal = sum(k in first and report[k] is not None and first[k] == report[k] for k in targets)
            print(f"check 2 {name}: presence in the probe turn's first request equals the pack's scripted naive"
                  f" report on {equal} of {len(targets)} target items pass {equal == len(targets)}")
            ok = equal == len(targets)
        if not ok:
            failed.setdefault(name, []).append(2)
    commit = str(arms[ran[0]]["card"]["pins"].get("benchmark_commit"))
    lines = args.check3.read_text().splitlines() if args.check3 and args.check3.is_file() else []
    seen = {t: outcomes_of(lines, t) for t in CHECK3_TESTS}
    ok3 = (lines[:1] == [f"commit {commit}"] and lines[-1:] == ["exit 0"]
           and all(c["PASSED"] >= 1 and sum(c.values()) == c["PASSED"] for c in seen.values()))
    print("check 3 (memory off): the runner's own tests at the run commit", commit[:12], ":",
          "no --check3 file" if not lines else f"file names the run commit {lines[0] == f'commit {commit}'}, ends with"
          f" exit 0 {lines[-1] == 'exit 0'};" + "".join(f" {t} {dict(sorted(c.items())) or 'not found'};"
                                                       for t, c in seen.items()), "pass", ok3)
    if not ok3:
        invalid.add("check 3")
    print("check 4: see header; mismatched arms are not pooled and their trials count as unscored:", len(mismatched))
    incomplete = set()
    for name in ran:
        outcomes = arms[name]["outcomes"]
        scored = sum(is_int((outcomes.get(k) or {}).get("score_milli")) for k in targets)
        blocked = sum((outcomes.get(k) or {}).get("failure_class") == "BLOCKED" for k in targets)
        print(f"check 5 {name}: target items {len(targets)} scored {scored} BLOCKED {blocked} missing"
              f" {sum(k not in outcomes for k in targets)} complete {scored == len(targets)}")
        if scored < len(targets):
            incomplete.add(name)
    for name in ran:
        arm = arms[name]
        units = arm["card"]["floor"]["units"]
        disclosed = arm["disclosures"].get("floor", {})
        cached = sum(u.get("cached") is not False for u in units.values()) + sum(
            disclosed.get(u, {}).get("cached") is not False for u in units)
        floor_file = read(arm["run"] / f"{arm['control']['arm']}.json") or {}
        found, records, live, stopped, covered = 0, 0, 0, 0, set()
        for unit, probes in probe_files[name].items():
            found += probes is not None
            for record in probes or []:
                records += 1
                live += (record.get("live") or {}).get("served_by") == "live"
                covered.add((unit.split("/", 1)[0], record.get("item_id")))
            stopped += (floor_file.get(unit) or {}).get("stops") != {unit.replace("/", ""): None}
        covered &= probed
        ok = (set(units) == expected_units and set(disclosed) == expected_units and cached == 0
              and found == len(expected_units) and records > 0 and live == records and stopped == 0
              and covered == probed)
        print(f"check 7 {name}: expected units {len(expected_units)} units listed {len(units)} (card) {len(disclosed)}"
              f" (disclosures) cached or unconfirmed {cached} probe files found {found} probed items covered"
              f" {len(covered)} of {len(probed)} probe records {records} sent to the live reader {live} stopped units"
              f" {stopped} pass {ok}")
        if not ok:
            failed.setdefault(name, []).append(7)
    invalid |= set(failed)
    used = {r: [arms[k] for k in names if k in arms and k not in invalid | mismatched] for r, names in ROWS.items()}
    every = used["F"] + used["R"] + used["O"]
    members = {t: [b for b in bundles if b["template"] == t] for t in templates}
    support = {t: common(every, members[t]) for t in templates}
    print("check 6: bundles scored in every usable repeat (common support):",
          {t: f"{len(support[t])} of {len(members[t])}" for t in templates})
    return dict(args=args, arms=arms, bundles=bundles, templates=templates, members=members, targets=targets,
                invalid=invalid, failed=failed, violation=violation, missing=missing, mismatched=mismatched,
                incomplete=incomplete, used=used, support=support, tasks_sha256=args.tasks_sha256.lower())


def round_ends(ctx, again):
    """§4: a rerun failed check 1, 2 or 7 again. The checks are above; the missing observations, then no score."""
    said = [f"{k} fails check {','.join(map(str, ctx['failed'][k]))} again after its rerun" for k in again]
    print(f"\nROUND ENDS: {'; '.join(said)} (§4); no score is opened")
    gone = sorted(set(ctx["failed"]) | set(ctx["missing"]) | ctx["mismatched"], key=CORE.index)
    print("missing observations: arms without usable trials", " ".join(gone))
    for t in ctx["templates"]:
        n = sum(len(b["keys"]) for b in ctx["members"][t])
        print(f"  {t}: target items {n}, each without a usable trial in {len(gone)} of {len(CORE)} arms")
    for t in ctx["templates"]:
        print(f"reading {t}: unresolved")


def reading(ctx, t):
    """(lines, reading) for one template by §5's precedence: unresolved, unstable, low, cleared/format validated."""
    used, members, support = ctx["used"], ctx["members"][t], ctx["support"][t]
    f, r = pts(used["F"], support), pts(used["R"], support)
    two_o = [a for a in used["O"] if a["name"] in ("O1", "O2")]
    c = pts(two_o, support) if len(two_o) == 2 else None
    out = [f"-- {t}: bundles on the common support {len(support)} of {len(members)} f {exact(f)} r {exact(r)}"
           f" c {exact(c)} c over O1,O2,O3 {exact(pts(used['O'], support))}"]
    low = state("low", f, r, c)
    trials = [(a["name"], state("low", None, None, pts([a], support))) for a in used["O"]]
    disagree = [n for n, s in trials if (s == "applies") != (low == "applies")]
    out.append(f"  low (c < 75): on means {low} margin_bundles {exact(margin('low', f, r, c, len(support)))};"
               f" each O trial alone: " + ", ".join(f"{n} {s}" for n, s in trials)
               + f"; disagreeing with the means {len(disagree)}")
    labels = []
    for flag, name in (("naive", "near-solved by naive retrieval"), ("floor", "near-solved without memory")):
        mean = state(flag, f, r, c)
        combos = ([(pts([x], support), pts([y], support), pts([o], support))
                   for x, y, o in product(used["F"], used["R"], used["O"])] if flag == "naive" else
                  [(pts([x], support), r, pts([o], support)) for x, o in product(used["F"], used["O"])])
        agree = [(state(flag, *v) == "applies") == (mean == "applies") for v in combos]
        out.append(f"  {flag} ({name}): on means {mean} margin_bundles {exact(margin(flag, f, r, c, len(support)))}"
                   f" combinations {len(agree)} agreeing on whether it applies {sum(agree)}"
                   f" {'stable' if all(agree) else 'unstable'} (printed only; never enters the reading)")
        if mean == "applies":
            labels.append(name)
    if labels:
        out.append(f"  labelled {' + '.join(labels)}: a do-no-harm check, excluded from any claim that memory beats"
                   " retrieval (M1 §6)")
    gone = [k for k in CORE if k not in {a["name"] for row in used.values() for a in row}]
    if gone or len(support) < len(members):
        result = "unresolved"
        out.append(f"  completeness: repeats missing or mismatched {' '.join(gone) or 'none'}; bundles with an"
                   f" unscored item {len(members) - len(support)}")
    elif disagree:
        result = "unstable"
    elif low == "applies":
        result = "low"
    else:
        result = "format validated" if t == COUNT_REF else "cleared"
    return out, result


def scores(ctx):
    """Sections 3 and 4, printed only when every check passed and no rerun is pending."""
    arms, used, templates, members = ctx["arms"], ctx["used"], ctx["templates"], ctx["members"]
    print("\n== 3. Scores by template (bundle scores +1000 +500 0 -500 -1000 milli, non-result; points = 100 x mean)")
    for name in CORE:
        if name not in arms:
            print(f"-- {name}: missing after its rerun (refusal code {ctx['missing'][name]})")
            continue
        print(f"-- {name}" + (" (identity mismatch: not pooled)" if name in ctx["mismatched"] else ""))
        for t in templates:
            print(f"  {t}: {line([bundle_score(arms[name]['outcomes'], b) for b in members[t]])}")
    for row in ROWS:
        print(f"-- {row} mean of {[a['name'] for a in used[row]]} on the common support")
        for t in templates:
            print(f"  {t}: bundles {len(ctx['support'][t])} points {exact(pts(used[row], ctx['support'][t]))}")
    print("\n== 4. Readings (§5): f, r = means of F1,F2 and R1,R2; c = mean of O1,O2; exact points on each template's"
          " common support")
    for t in templates:
        lines, result = reading(ctx, t)
        print("\n".join(lines))
        print(f"  reading: {result}")


def twin(trials, key):
    """M1's twin rule: pass with two trials at 1000; fail when passes + unscored < 2; otherwise unresolved."""
    scored = [t[key]["score_milli"] for t in trials if key in t and is_int(t[key]["score_milli"])]
    passes, unknown = scored.count(1000), len(trials) - len(scored)
    return (passes, unknown), "pass" if passes >= 2 else "fail" if passes + unknown < 2 else "unresolved"


def bundle_verdict(verdicts):
    return "pass" if all(v == "pass" for v in verdicts) else "fail" if "fail" in verdicts else "unresolved"


def oracle_filter(ctx, args):
    """Section 5 and FILTER.json: PREREG-v0.5 §4 filter 3 over O1-O3; an excluded arm's trial is unscored."""
    arms, excluded = ctx["arms"], ctx["invalid"] | ctx["mismatched"]
    trials = [arms[k]["outcomes"] if k in arms and k not in excluded else {} for k in ROWS["O"]]
    print("\n== 5. Oracle filter over O1, O2, O3 (an item passes with >= 2 trials at 1000; a bundle is kept when every"
          " item passes); trials unscored for", " ".join(k for k in ROWS["O"] if k not in arms or k in excluded)
          or "no arm")
    out = {}
    for t in ctx["templates"]:
        kept = {"pass": [], "fail": [], "unresolved": []}
        items = Counter()
        for b in ctx["members"][t]:
            found = [twin(trials, k) for k in b["keys"]]
            items.update(c for c, _ in found)
            kept[bundle_verdict([v for _, v in found])].append(dict(
                life=b["life"], bundle_id=b["bundle_id"], item_ids=sorted(k.split("/", 2)[2] for k in b["keys"])))
        print(f"  {t}: bundles {len(ctx['members'][t])} kept {len(kept['pass'])} dropped {len(kept['fail'])}"
              f" unresolved {len(kept['unresolved'])}; items by (passes, unscored) {dict(sorted(items.items()))}")
        out[t] = dict(kept=kept["pass"], dropped=kept["fail"], unresolved=kept["unresolved"])
    if args.filter_out:
        digests = {k: sha256((arms[k]["run"] / "outcomes.json").read_bytes()).hexdigest() if k in arms else None
                   for k in ROWS["O"]}
        args.filter_out.write_bytes(canon(dict(tasks_sha256=ctx["tasks_sha256"], o_outcomes_sha256=digests,
                                               o_excluded=sorted(k for k in ROWS["O"] if k not in arms or k in excluded),
                                               templates=out)))
        print("FILTER.json written, sha256", sha256(args.filter_out.read_bytes()).hexdigest()[:12])


if __name__ == "__main__":
    sys.exit(main())
