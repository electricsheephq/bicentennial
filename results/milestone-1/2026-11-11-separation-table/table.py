"""Milestone 1: the separation table that results/milestone-1/DECLARATION.md says the results page prints.

Usage: python table.py --packs PACKS_DIR --order F1,R1,O1,H1,H2,O2,R2,F2,O3 F1=RUN_DIR ... H2=RUN_DIR
       [X-<name>=RUN_DIR ...] [E1=RUN_DIR E2=RUN_DIR [--earlier-packs PACKS_DIR]]
Core labels F1 F2 R1 R2 O1 O2 O3 H1 H2 are required together; with E1/E2 only, it prints the earlier evidence alone.
Prints, in order: 1 header and identity; 2 checks before any score (declaration §2); 3 scored action pairs by kind
and life (§3); 4 single tasks, quiz items and agreement between repeats; 5 screening flags (§4); 6 filter yield (§6);
7 real systems (§5); 8 full history; then earlier evidence (step-1 by_kind.py on E1/E2). Exits 3 after printing
everything when any control row fails check 1, 2, 3 or 7. Pairs and loaders are step 1's (by_kind.py).
Prints counts, labels, 12-character hash prefixes and pass/fail only: never task text, answers, control text, item
or bundle ids, served identity values, or paths. Text arms need bicentennial.runner.control_arm (#496) importable.
"""

import argparse
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime
from fractions import Fraction
from hashlib import sha256
from io import StringIO
from itertools import combinations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "2026-11-04-live-runs-by-kind"))
import by_kind  # noqa: E402
from by_kind import (  # noqa: E402
    SCRIPTED,
    SEED,
    is_int,
    kind_order,
    label,
    load_packs,
    points,
    tally,
)

from bicentennial.score.bundle import twin_min  # noqa: E402
from bicentennial.stats.core import sign_flip_p  # noqa: E402

ROWS = {"F": ("F1", "F2"), "R": ("R1", "R2"), "O": ("O1", "O2", "O3"), "H": ("H1", "H2")}
CORE = tuple(a for arms in ROWS.values() for a in arms)
CONTROL = {"F": "no_memory", "R": "naive_rag", "O": "oracle_evidence"}
SEVEN = Fraction(7, 10)
NOT_VISIBLE = "not visible in run outputs; covered by #496's tests"


def short(text):
    return sha256(text.encode()).hexdigest()[:12]


def exact(v):
    return "n/a" if v is None else f"{v} ({float(v):.1f})"


def frame_sha256():
    from bicentennial.runner.control_arm import FRAME_SHA256
    return FRAME_SHA256


def recompute_blocks(packs, control):
    """{life/branch/item_id: sha256} of the pinned control's text per task, as control.json records it (#496)."""
    from bicentennial.runner.control_arm import probe_blocks

    from bicentennial.runner import t1
    out = {}
    for rel in sorted(json.loads((packs / "index.json").read_text())["packs"]):
        for (life, branch), texts in probe_blocks(t1._pack(packs, rel), control).items():
            out.update({f"{life}/{branch}/{iid}": sha256(text.encode()).hexdigest() for iid, text in texts.items()})
    return out


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def load_arm(name, run):
    if (run / "no_memory.json").exists():
        card, outcomes, floor = by_kind.load_run(run)
    else:
        card, outcomes, floor = read(run / "card.json"), {}, None
        for key, value in read(run / "outcomes.json").items():
            life, _branch, item_id = key.split("/", 2)
            assert (life, item_id) not in outcomes, "item id repeats within a life"
            outcomes[(life, item_id)] = value
    control = read(run / "control.json")
    row = name[0]
    if (control is not None) != (row in CONTROL):
        sys.exit(f"{name} is not a {'control' if row in CONTROL else 'system'} run")
    return dict(name=name, row=row, card=card, outcomes=outcomes, floor=floor, control=control,
                units=read(run / "units.json") or {}, disclosures=read(run / "disclosures.json") or {})


def pair_score(outcomes, pair):
    a, b = (outcomes.get(k) for k in pair["keys"])
    if a is None or b is None or not (is_int(a["score_milli"]) and is_int(b["score_milli"])):
        return None
    return twin_min(a, b)


def line(scores):
    right, wrong, none, nonresult = tally(scores)
    return (f"pairs {len(scores)} right {right} wrong {wrong} no_credit {none} non_result {nonresult}"
            f" net {right - wrong} points {points([s for s in scores if s is not None])}")


def common(arms, members):
    return [p for p in members if all(pair_score(a["outcomes"], p) is not None for a in arms)]


def pts(arms, members):
    """100 times the mean pair score over the arms' repeats on members (all scored in every arm)."""
    if not arms or not members:
        return None
    return Fraction(sum(pair_score(a["outcomes"], p) for a in arms for p in members), len(arms) * len(members)) / 10


def needs(flag, f, r, c):
    return {"low": (c,), "naive": (f, r, c), "floor": (f, c)}[flag]


def state(flag, f, r, c):
    if None in needs(flag, f, r, c):
        return "n/a"
    if flag == "low":
        return "applies" if c < 75 else "no"
    if c <= f or c <= 0:
        return "not interpreted"
    return "applies" if (r >= f + SEVEN * (c - f) if flag == "naive" else f >= SEVEN * c) else "no"


def margin(flag, f, r, c, n):
    """Margin in pairs: (left minus right) times pairs / 100, signed so that > 0 (low) or >= 0 means it applies."""
    if None in needs(flag, f, r, c):
        return None
    slack = 75 - c if flag == "low" else r - f - SEVEN * (c - f) if flag == "naive" else f - SEVEN * c
    return slack * n / 100


def per_life(arms, items, life_of, score):
    """{life: mean of score(arm, x) over the arms and that life's items}."""
    out = {}
    for life in sorted({life_of(x) for x in items}):
        mine = [x for x in items if life_of(x) == life]
        out[life] = Fraction(sum(score(a, x) for a in arms for x in mine), len(arms) * len(mine))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--earlier-packs", type=Path)
    parser.add_argument("--order")
    parser.add_argument("arms", nargs="+", metavar="LABEL=RUN_DIR")
    args = parser.parse_args(argv)
    given = dict(a.split("=", 1) for a in args.arms)
    bad = [k for k in given if k not in CORE and k not in ("E1", "E2") and not k.startswith("X-")]
    core_given = [k for k in CORE if k in given]
    if bad or len(core_given) not in (0, len(CORE)) or (not core_given and any(k.startswith("X-") for k in given)):
        parser.error("labels: all of " + " ".join(CORE) + ", optional X-<name>, E1, E2")
    order = args.order.split(",") if args.order else []
    if core_given and sorted(order) != sorted(CORE):
        parser.error("--order must list the nine core labels once each")
    pack = load_packs(args.packs)
    arms = {k: load_arm(k, Path(v)) for k, v in given.items() if not k.startswith("E")}
    invalid = set()
    if arms:
        invalid = table(args, pack, arms, order)
    earlier = [Path(given[k]) for k in ("E1", "E2") if k in given]
    if earlier:
        print("\n== Earlier evidence: the 4 November runs at an older commit (step-1 by_kind.py); never pooled")
        saved, sys.argv = sys.argv, ["by_kind.py", "--packs", str(args.earlier_packs or args.packs), *map(str, earlier)]
        buffer = StringIO()
        try:
            with redirect_stdout(buffer):
                by_kind.main()
        finally:
            sys.argv = saved
        print(not_scored_labels(buffer.getvalue(), load_arm("E1" if "E1" in given else "E2", earlier[0])), end="")
        if len(earlier) == 2:
            e = {n: load_arm(n, Path(given[n])) for n in ("E1", "E2")}
            agreement(e["E1"], e["E2"], pairs_of(load_packs(args.earlier_packs or args.packs), e))
    for name in sorted(invalid):
        print("INVALID CONTROL ROW", name)
    return 3 if invalid else 0


def not_scored_labels(text, first):
    """Step 1's section H labels unscored pairs by kind only; add their genre and "not scored live" to each label."""
    unscored = {(life, iid) for life, _branch, iid in first["card"]["not_scored_live"]}
    genres = "/".join(sorted({str(first["outcomes"][k].get("genre")) for k in unscored if k in first["outcomes"]}))
    lines, inside = [], False
    for row in text.split("\n"):
        inside = row.startswith("== H.") or (inside and not row.startswith("=="))
        head, sep, tail = row.partition(": pairs ")
        if inside and sep and row.startswith("  ") and not row.startswith("    "):
            row = f"{head}, {genres}, not scored live{sep}{tail}"
        lines.append(row)
    return "\n".join(lines)


def pairs_of(pack, arms):
    """The pack's bundles whose two twins are action tasks the live tier scores (not in any card's not_scored_live)."""
    unscored = {(life, iid) for a in arms.values() for life, _branch, iid in a["card"]["not_scored_live"]}
    pairs = []
    for life in sorted(pack):
        items = pack[life]["arms"][SCRIPTED[1]]["items"]
        for bundle in pack[life]["bundles"]:
            keys = tuple((life, iid) for iid in bundle["items"])
            if all(items[k[1]]["stage"] == "act" and k not in unscored for k in keys):
                pairs.append(dict(life=life, kind=(bundle["cell_id"], bundle["twin_type"]), keys=keys))
    return pairs


def agreement(a, b, pairs):
    both = [p for p in pairs if pair_score(a["outcomes"], p) is not None and pair_score(b["outcomes"], p) is not None]
    equal = sum(pair_score(a["outcomes"], p) == pair_score(b["outcomes"], p) for p in both)
    one, two = a["outcomes"], b["outcomes"]
    keys = [k for k in sorted(one.keys() & two.keys()) if is_int(one[k]["score_milli"]) or is_int(two[k]["score_milli"])]
    score = Counter(one[k]["cell_id"] for k in keys if one[k]["score_milli"] != two[k]["score_milli"])
    either = Counter(one[k]["cell_id"] for k in keys if (one[k]["score_milli"], one[k]["failure_class"])
                     != (two[k]["score_milli"], two[k]["failure_class"]))
    print(f"-- {a['name']} vs {b['name']}: scored pairs with equal score {equal} of {len(both)} scored in both;"
          f" keys only in one {len(one.keys() ^ two.keys())}")
    print("   task scores that differ (score_milli differs; tasks scored in either)", sum(score.values()),
          dict(sorted(score.items())))
    print("   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in"
          " either)", sum(either.values()), dict(sorted(either.items())))


def table(args, pack, arms, order):
    pairs = pairs_of(pack, arms)
    kinds = sorted({p["kind"] for p in pairs}, key=kind_order)
    lives = sorted({p["life"] for p in pairs})
    tasks = [k for p in pairs for k in p["keys"]]
    invalid = set()

    # 1. Header and identity.
    print("== 1. Header and identity")
    print("run order", ",".join(order))
    # The core identity is the most common among core arms (ties: the earliest label in F1..H2).
    core_id = Counter(arms[k]["card"]["served_identity"] for k in CORE).most_common(1)[0][0]
    for name, arm in arms.items():
        card, units = arm["card"], arm["units"]
        when = [datetime.fromtimestamp(units[k] / 1000, UTC).isoformat(timespec="seconds") if k in units else "n/a"
                for k in ("start_ms", "end_ms")]
        print(f"{name}: tier {card['tier']} {'control ' + arm['control']['arm'] if arm['control'] else 'system'}"
              f" model {card['model']} effort {card['effort']} pack_hash {card['pack_hash'][:12]} start {when[0]}"
              f" end {when[1]} served_identity {short(card['served_identity'])}"
              f" matches_core {card['served_identity'] == core_id}")
        print("  pins", json.dumps({k: card["pins"][k][:12] for k in sorted(card["pins"])}))
    print("every arm's served identity equal", len({a["card"]["served_identity"] for a in arms.values()}) == 1)
    print("one commit for every core arm (card pins equal)", len({json.dumps(arms[k]["card"]["pins"], sort_keys=True)
                                                                  for k in CORE}) == 1)
    mismatched = {k for k in arms if arms[k]["card"]["served_identity"] != core_id}

    # 2. Checks before any score.
    print("\n== 2. Checks before any score (§2)")
    blocks, controls = {}, [k for k in CORE if arms[k]["row"] in CONTROL]
    for name in controls:
        arm, rec = arms[name], arms[name]["control"]
        kind_ok = rec["arm"] == CONTROL[arm["row"]]
        if arm["row"] == "F":
            ok = kind_ok and rec["frame_sha256"] is None and rec["block_sha256"] == {}
            print(f"check 1 {name}: arm {rec['arm'] == 'no_memory'} no blocks {rec['block_sha256'] == {}} pass {ok}")
        else:
            want = blocks.setdefault(rec["arm"], recompute_blocks(args.packs, rec["arm"])) if kind_ok else {}
            got = rec["block_sha256"]
            matched = sum(got.get(k) == v for k, v in want.items())
            frame = rec["frame_sha256"] == frame_sha256()
            ok = kind_ok and frame and want and matched == len(want) == len(got)
            print(f"check 1 {name}: arm matches label {kind_ok} frame_sha256 {frame} blocks matched {matched} of"
                  f" {len(want)} mismatched {len(want) - matched} recorded but not recomputed {len(got.keys() - want.keys())}"
                  f" pass {bool(ok)}")
        if not ok:
            invalid.add(name)
    for name in controls:
        arm, out = arms[name], arms[name]["outcomes"]
        if arm["row"] == "O":
            true = sum(out.get(k, {}).get("in_context") is True for k in tasks)
            print(f"check 2 {name}: in_context true on {true} of {len(tasks)} scored action tasks pass {true == len(tasks)}")
            ok = true == len(tasks)
        elif arm["row"] == "R":
            reports = {(life, i): r["in_context"] for life in pack for i, r in pack[life]["arms"][SCRIPTED[0]]["reports"].items()}
            equal = sum(k in out and out[k].get("in_context") == v for k, v in reports.items())
            print(f"check 2 {name}: in_context equals the pack's scripted naive report on {equal} of {len(reports)}"
                  f" tasks pass {equal == len(reports)}")
            ok = equal == len(reports)
        else:
            continue
        if not ok:
            invalid.add(name)
    print("check 3 (F, R, O): memory block, search tool, answer key and option order in the block:", NOT_VISIBLE)
    print("check 4: see header (served identity); mismatched arms are not pooled:", len(mismatched))
    incomplete = set()
    for name, arm in arms.items():
        scored = sum(is_int(arm["outcomes"].get(k, {}).get("score_milli")) for k in tasks)
        blocked = sum(arm["outcomes"].get(k, {}).get("failure_class") == "BLOCKED" for k in tasks)
        print(f"check 5 {name}: scored action tasks assigned {len(tasks)} scored {scored} BLOCKED {blocked}"
              f" missing {sum(k not in arm['outcomes'] for k in tasks)} complete {scored == len(tasks)}"
              " (scored = integer score_milli; missing = no outcome row)")
        if scored < len(tasks):
            incomplete.add(name)
    for name in controls:
        units = arms[name]["card"]["floor"]["units"]
        disclosed = arms[name]["disclosures"].get("floor", {})
        cached = sum(u["cached"] is not False for u in units.values()) + sum(
            disclosed.get(u, {}).get("cached") is not False for u in units)
        ok = bool(units) and cached == 0 and set(disclosed) == set(units)
        print(f"check 7 {name}: units {len(units)} cached or unconfirmed {cached} pass {ok}")
        if not ok:
            invalid.add(name)
    used = {r: [arms[k] for k in names if k not in invalid | mismatched] for r, names in ROWS.items()}
    short_rows = {r for r, names in ROWS.items() if len(used[r]) < len(names) or {a["name"] for a in used[r]} & incomplete}
    for r in sorted(short_rows):
        print(f"row {r} incomplete: repeats used {[a['name'] for a in used[r]]}")
    support = {k: common(used["F"] + used["R"] + used["O"], [p for p in pairs if p["kind"] == k]) for k in kinds}
    print("check 6: pairs scored in every repeat of F, R and O used (common support for the flags):",
          {label(k): len(v) for k, v in support.items()}, "total", sum(map(len, support.values())))

    # 3. Primary display.
    def groups(members):
        return ([(label(k), [p for p in members if p["kind"] == k]) for k in kinds]
                + [(f"life {n}", [p for p in members if p["life"] == life]) for n, life in enumerate(lives, 1)]
                + [(f"pooled diagnostic (all {len(members)})", members)])

    def display(rows, heading):
        print(f"\n== {heading}")
        for row, members_arms in rows:
            for arm in members_arms:
                print(f"-- {arm['name']}" + (" (INVALID CONTROL ROW)" if arm["name"] in invalid else "")
                      + (" (identity mismatch: not pooled)" if arm["name"] in mismatched else ""))
                for group, members in groups(pairs):
                    print(f"  {group}: {line([pair_score(arm['outcomes'], p) for p in members])}")
            if row and len(ROWS.get(row, ())) > 1:
                print(f"-- {row} mean of {[a['name'] for a in used[row]]}" + (" (incomplete)" if row in short_rows else ""))
                for group, members in groups(pairs):
                    both = common(used[row], members)
                    t = [tally([pair_score(a["outcomes"], p) for p in both]) for a in used[row]]
                    m = [Fraction(sum(x[i] for x in t), len(t)) if t else None for i in range(3)]
                    print(f"  {group}: common pairs {len(both)} right {exact(m[0])} wrong {exact(m[1])}"
                          f" no_credit {exact(m[2])} points {exact(pts(used[row], both))} (common pairs = scored in every"
                          " repeat used; counts are means over repeats)")

    display([(r, [arms[k] for k in names]) for r, names in ROWS.items()],
            "3. Scored action pairs by kind and life (pairs, right, wrong, no credit, non-result, net, points)")
    optional = [arms[k] for k in arms if k.startswith("X-")]
    if optional:
        display([(None, optional)], "3x. Optional rows (one attempt each; shown separately, never pooled)")
    if arms["H1"]["floor"] is not None:
        extra = dict(name="extra floor (H1's own no-memory floor; enters no mean, flag or comparison)",
                     outcomes=arms["H1"]["floor"])
        display([(None, [extra])], "3e. Extra floor")
    else:
        extra = None

    # 4. Beside it: single tasks, quiz items, agreement.
    print("\n== 4. Single tasks in scored action pairs, quiz items, agreement between repeats")
    for arm in [arms[k] for k in arms] + ([extra] if extra else []):
        print(f"-- {arm['name']}")
        for k in kinds:
            rows = [arm["outcomes"].get(key) for p in pairs if p["kind"] == k for key in p["keys"]]
            present = [x for x in rows if x is not None]
            right, wrong, none, nonresult = tally([x["score_milli"] if is_int(x["score_milli"]) else None for x in present])
            print(f"  {label(k)}: tasks {len(rows)} right {right} wrong {wrong} no_credit {none}"
                  f" non_result {nonresult + len(rows) - len(present)} (no integer score_milli, or no row)"
                  f" base_verdict {dict(sorted(Counter(str(x['base_verdict']) for x in present).items()))}"
                  f" failure_class {dict(sorted(Counter(str(x['failure_class']) for x in present).items()))}")
        quiz = [x for x in arm["outcomes"].values() if x["stage"] == "survive"]
        print(f"  quiz items {len(quiz)} by cell: +1000, 0, -1000, other, net")
        for cell in sorted({x["cell_id"] for x in quiz}):
            s = [x["score_milli"] for x in quiz if x["cell_id"] == cell]
            plus, zero, minus = s.count(1000), s.count(0), s.count(-1000)
            print(f"    {cell}: {plus} {zero} {minus} {len(s) - plus - zero - minus} net {plus - minus}")
    for names in ROWS.values():
        for a, b in combinations([arms[k] for k in names], 2):
            agreement(a, b, pairs)

    # 5. Screening flags.
    print("\n== 5. Screening flags from control rows (§4): f, r = means of F1,F2 and R1,R2; c = mean of O1,O2;"
          " exact points on each kind's common support")
    two_o = [a for a in used["O"] if a["name"] in ("O1", "O2")]
    for k in kinds:
        members = support[k]
        n = len(members)
        f, r, c = pts(used["F"], members), pts(used["R"], members), pts(two_o, members)
        print(f"-- {label(k)}: common pairs {n} f {exact(f)} r {exact(r)} c {exact(c)}"
              f" c over O1,O2,O3 {exact(pts(used['O'], members))}")
        rows_of = {"low": "O", "naive": "FRO", "floor": "FO"}
        status = {}
        for flag in ("low", "naive", "floor"):
            mean = state(flag, f, r, c)
            combos = {"low": [(f, r, pts([o], members)) for o in used["O"]],
                      "naive": [(pts([x], members), pts([y], members), pts([o], members))
                                for x, y, o in product(used["F"], used["R"], used["O"])],
                      "floor": [(pts([x], members), r, pts([o], members)) for x, o in product(used["F"], used["O"])]}[flag]
            states = [state(flag, *v) for v in combos]
            unresolved = any(row in short_rows for row in rows_of[flag]) or n == 0
            status[flag] = "unresolved" if unresolved else "unstable" if any(s != mean for s in states) else mean
            print(f"  {flag}: on means {mean} margin_pairs {exact(margin(flag, f, r, c, n))}"
                  f" combinations {len(states)} agreeing {sum(s == mean for s in states)} status {status[flag]}")
        applied = [x for x in ("low", "naive", "floor") if status[x] == "applies"]
        if "unresolved" in status.values():
            verdict = "unresolved"
        elif "unstable" in status.values():
            verdict = "unstable; no classification"
        elif applied:
            verdict = " + ".join(applied) + ("; low governs first (§6)" if "low" in applied and len(applied) > 1 else "")
        elif "not interpreted" in status.values():
            verdict = "no flag applies, but a near-solved flag is not interpreted; candidate not determined"
        else:
            verdict = "candidate"
        print(f"  classification: {verdict}")
    print("flags: low c < 75; naive (near-solved by naive retrieval) r >= f + 0.7 (c - f); floor (near-solved"
          " without memory) f >= 0.7 c; near-solved flags not interpreted when c <= f or c <= 0. Margin in pairs ="
          " (left - right) x pairs / 100, low as 75 - c; it applies when the margin is > 0 (low) or >= 0. Combinations:"
          " one repeat per row used (naive F x R x O, floor F x O, low O); any disagreement is unstable.")

    # 6. Filter yield.
    print("\n== 6. Prospective filter yield; validates nothing (each twin right with only its evidence in >= 2 of 3"
          " O trials)")
    trials = [arms[k] for k in ROWS["O"] if k not in invalid | mismatched]
    if len(trials) < 3:
        print("  unresolved: needs O1, O2 and O3")
    for k in kinds if len(trials) == 3 else ():
        passes = [[sum(t["outcomes"].get(key, {}).get("score_milli") == 1000 for t in trials) for key in p["keys"]]
                  for p in pairs if p["kind"] == k]
        print(f"  {label(k)}: pairs {len(passes)} both twins pass {sum(min(x) >= 2 for x in passes)} (each twin"
              f" score_milli 1000 in >= 2 of O1, O2, O3) twins by trials passed"
              f" {dict(sorted(Counter(v for x in passes for v in x).items()))}")

    # 7. Real systems.
    print("\n== 7. Real systems against the control rows (§5); no significance claimed")
    systems = [("H", used["H"])] + [(a["name"], [a]) for a in optional if a["name"] not in mismatched]
    for name, system in systems:
        for k in kinds + [None]:
            members = [p for p in pairs if k is None or p["kind"] == k]
            parts = []
            for row in "FRO":
                both = common(system + (two_o if row == "O" else used[row]), members)
                s, other = pts(system, both), pts(two_o if row == "O" else used[row], both)
                diff = None if s is None or other is None else s - other
                parts.append(f"{row} {exact(other)}, {name} minus {row} {exact(diff)} on {len(both)} pairs")
            print(f"  {name} {label(k) if k else 'pooled diagnostic'}: {name} points {exact(pts(system, common(system, members)))};"
                  f" against " + "; ".join(parts) + " (pairs = scored in every repeat of both rows)")
        if not system or not used["F"]:
            print(f"  {name} minus F per life: unresolved (no usable repeat)")
            continue
        both = common(system + used["F"], pairs)
        keys = [t for t in tasks if all(is_int(a["outcomes"].get(t, {}).get("score_milli")) for a in system + used["F"])]
        for what, items, life_of, score in (
                ("pairs", both, lambda p: p["life"], lambda a, p: pair_score(a["outcomes"], p)),
                ("tasks", keys, lambda t: t[0], lambda a, t: a["outcomes"][t]["score_milli"])):
            mine, floor = per_life(system, items, life_of, score), per_life(used["F"], items, life_of, score)
            d = {life: mine[life] - floor[life] for life in mine}
            p = sign_flip_p(d, seed=SEED, name=f"{name}-minus-F-{what}") if d else None
            print(f"  {name} minus F per life, {what} (milli; {what} scored in every repeat of {name} and F;"
                  f" {len(d)} lives):", [str(d[life]) for life in sorted(d)],
                  "exact two-sided sign_flip_p", "n/a" if p is None else f"{p} {float(p):.4f}", "no significance claimed")

    # 8. Full history.
    print("\n== 8. Full history")
    print("  fits the window on", sum(life["fits"]["run"] for life in pack.values()), "of",
          sum(life["fits"]["of"] for life in pack.values()), "items, summed over lives")
    return invalid


if __name__ == "__main__":
    sys.exit(main())
