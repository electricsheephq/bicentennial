"""Milestone 1: the separation table that results/milestone-1/DECLARATION.md says the results page prints.

Usage: python table.py --packs PACKS_DIR --order F1,R1,O1,H1,H2,O2,R2,F2,O3 F1=RUN_DIR ... H2=RUN_DIR
       [X-<name>=RUN_DIR ...] [E1=RUN_DIR E2=RUN_DIR [--earlier-packs PACKS_DIR]] [--reruns LABELS] [--after-reruns]
       [--checks-only]
Core labels F1 F2 R1 R2 O1 O2 O3 H1 H2 are required together; with E1/E2 only, it prints the earlier evidence alone.
Prints, in order: 1 header and identity; 2 checks before any score (declaration §2); 3 scored action pairs by kind
and life (§3); 4 single tasks, quiz items and agreement between repeats; 5 screening flags (§4); 6 filter yield (§6);
7 real systems (§5); 8 full history; then earlier evidence (step-1 by_kind.py on E1/E2). No score is printed while
a check is open: after section 2 it exits 3 when a control row fails check 1, 2 or 7, the run order is violated, or
the core arms' card pins differ (one commit for every row, §1), and 4 when a core arm fails check 4 or 5 and
--after-reruns is not given. The order listed must be the declared one; only a rerun named in --reruns may run
later than its slot, and never before an arm that was not itself rerun and whose slot comes before its own (§11.9). Check 2 reads the probe turn's
first request, the one that carries the block (in_context_initial in each unit's probe records, §11.5). Check 3 (memory off) cannot fail here: run outputs do not record request tools or the
memory block, so it prints as not visible, covered by the runner's tests at the pinned commit (#496:
test_c_floor_bodies_and_memory_off). --checks-only stops after section 2 (exit 0 when
nothing is pending). An X- attempt without card.json or outcomes.json is shown as failed with its refusal code only;
a core label in that state is a missing repeat: pending (exit 4) without --after-reruns, published as missing with it.
If no core arm has card.json and outcomes.json, it lists the missing arms and stops: 4 without --after-reruns, 3 with
it (no row exists to publish).
The core arms' card pack_hash must equal the --packs tree hash (bicentennial.packs.manifest.tree_sha256), or exit 3.
Pairs and loaders are step 1's (by_kind.py).
Prints counts, labels, 12-character hash prefixes and pass/fail only: never task text, answers, control text, item
or bundle ids, served identity values, or paths. Text arms need bicentennial.runner.control_arm (#496) importable.
"""

import argparse
import json
import re
import sys
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime
from fractions import Fraction
from hashlib import sha256
from io import StringIO
from itertools import combinations, pairwise, product
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
NOT_VISIBLE = ("not visible in run outputs (request bodies are not kept); covered by the runner's tests at the"
               " pinned commit (#496): test_c_floor_bodies_and_memory_off (no memory fence, memory section or memory or"
               " search tool in any control-arm request body) and test_a_block_is_the_pinned_controls_text_in_the_probe_turn"
               " (no sealed identifier, option id or honeypot token in any block); the block half was also checked on all"
               " ten lives of the pack")
DECLARED_ORDER = ("F1", "R1", "O1", "H1", "H2", "O2", "R2", "F2", "O3")
SYSTEM_PINS = ("system_hash", "route_table_hash")  # the card pins that name the system under test (runner/t2.py)
RERUN = "rerun once (§2.4, §2.5), then run again with --after-reruns"
NAMES = {"low": "low", "naive": "near-solved by naive retrieval", "floor": "near-solved without memory"}


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


def pack_tree_hash(packs):
    """The pack hash cards record: packs/install.py install() returns tree_sha256 of the installed tree."""
    from bicentennial.packs.manifest import tree_sha256
    return tree_sha256(packs)


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def refusal_code(run):
    """Only the refusal code string, never its detail."""
    code = (read(run / "refusal.json") or {}).get("code")
    return code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_,]+", code) else "none recorded"


def load_arm(name, run):
    if not ((run / "card.json").exists() and (run / "outcomes.json").exists()):
        return dict(name=name, failed=refusal_code(run))
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
    return dict(name=name, row=row, run=run, card=card, outcomes=outcomes, floor=floor, control=control,
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
    """The members scored in every arm given. No arm, no support: a row with no usable repeat counts no pair."""
    return [p for p in members if all(pair_score(a["outcomes"], p) is not None for a in arms)] if arms else []


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
    parser.add_argument("--reruns", help="core labels rerun after their first attempt, in the order they reran (§11.9)")
    parser.add_argument("--after-reruns", action="store_true",
                        help="publish arms still mismatched or incomplete after their one rerun (§2.4-§2.6)")
    parser.add_argument("--checks-only", action="store_true", help="print sections 1 and 2 only")
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
    reruns = args.reruns.split(",") if args.reruns else []
    if len(set(reruns)) != len(reruns) or not set(reruns) <= set(CORE) or (reruns and not core_given):
        parser.error("--reruns must list core labels, each once")
    pack = load_packs(args.packs)
    arms = {k: load_arm(k, Path(v)) for k, v in given.items() if not k.startswith("E")}
    failed = {k: arms.pop(k)["failed"] for k in list(arms) if "failed" in arms[k]}
    missing = {k: failed.pop(k) for k in CORE if k in failed}
    if core_given and not any(k in arms for k in CORE):
        # No core arm has its outputs: no check, row, flag or comparison exists, and earlier evidence is not shown.
        print("== 1. Header and identity")
        for name, code in missing.items():
            print(f"{name}: missing (no card.json or outcomes.json; refusal code {code})")
        print("no core arm has card.json and outcomes.json: no check, row, flag or comparison can be computed")
        if not args.after_reruns:
            print("pending before any score:", " ".join(missing), "-", RERUN)
            return 4
        return 3
    if arms:
        ctx = checks(args, pack, arms, order, missing)
        if ctx["invalid"]:
            # §2: an invalid control row is fixed and rerun before any score is opened.
            if ctx["violation"]:
                print(f"RUN ORDER VIOLATION: {ctx['violation']}")
            if "card pins" in ctx["invalid"]:
                print("CARD PINS DIFFER between core arms (see PIN MISMATCH above): not pooled")
            if "pack" in ctx["invalid"]:
                print("PACK DIFFERS from --packs for a core arm (see PACK MISMATCH above): not pooled")
            for name in sorted(ctx["invalid"] - {"run order", "card pins", "pack"}):
                print("INVALID CONTROL ROW", name)
            return 3
        pending = sorted((ctx["mismatched"] | ctx["incomplete"] | set(missing)) & set(CORE), key=CORE.index)
        if pending and not args.after_reruns:
            print("pending before any score:", " ".join(pending), "-", RERUN)
            return 4
        if args.checks_only:
            return 0
        scores(ctx, failed)
    elif args.checks_only:
        return 0
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
    return 0


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


def checks(args, pack, arms, order, missing):
    """Sections 1 and 2; returns what sections 3-8 need. Missing core repeats enter no check (§2.6)."""
    ran = [k for k in CORE if k in arms]
    if not ran:
        sys.exit("no core arm ran")
    # The task inventory comes from the pack and the core cards only: an optional row never changes the core table (§1).
    pairs = pairs_of(pack, {k: arms[k] for k in CORE if k in arms})
    kinds = sorted({p["kind"] for p in pairs}, key=kind_order)
    lives = sorted({p["life"] for p in pairs})
    tasks = [k for p in pairs for k in p["keys"]]
    invalid = set()

    # 1. Header and identity.
    print("== 1. Header and identity")
    reruns = args.reruns.split(",") if args.reruns else []
    print("run order", ",".join(order), "| equals the declared order", tuple(order) == DECLARED_ORDER,
          "| reruns named", ",".join(reruns) or "none", "| --after-reruns given", args.after_reruns)
    # Each arm in --order ran alone, after the one before it ended (units.json start and end times).
    for name, code in missing.items():
        print(f"{name}: missing (no card.json or outcomes.json; refusal code {code})"
              + (", published as missing after its rerun" if args.after_reruns else ""))
    # §1 fixes the order. Only a named rerun may run later than its slot, and never before an arm that was not itself
    # rerun and whose slot comes before its own (§11.9).
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
    # Optional rows run alone after the nine core arms (§1). Overlapping a core arm is an order fault; any other
    # departure keeps the row in section 3x, marked, and out of section 7.
    off_order, core_end = {}, max((e for _, _, e in times if is_int(e)), default=None)
    for name in [k for k in arms if k.startswith("X-")]:
        s, e = arms[name]["units"].get("start_ms"), arms[name]["units"].get("end_ms")
        if not (is_int(s) and is_int(e) and s <= e):
            off_order[name] = "no start or end time"
            continue
        hit = next((k for k, cs, ce in times if is_int(cs) and is_int(ce) and s < ce and cs < e), None)
        if hit:
            violation = violation or f"{name} overlaps core arm {hit}"
            continue
        other = next((k for k in arms if k.startswith("X-") and k != name and is_int(arms[k]["units"].get("start_ms"))
                      and is_int(arms[k]["units"].get("end_ms")) and s < arms[k]["units"]["end_ms"]
                      and arms[k]["units"]["start_ms"] < e), None)
        if core_end is not None and s < core_end:
            off_order[name] = "starts before the last core arm ends"
        elif other:
            off_order[name] = f"overlaps {other}"
    print("run order verified" if violation is None else f"RUN ORDER VIOLATION: {violation}")
    for name, reason in off_order.items():
        print(f"{name}: not run as declared ({reason})")
    if violation is not None:
        invalid.add("run order")
    # The core identity is the most common among core arms (ties: the earliest label in F1..H2).
    core_id = Counter(arms[k]["card"]["served_identity"] for k in ran).most_common(1)[0][0]
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
    # §1: one commit for every row. Differing card pins stop the table before any score.
    pins = sorted({key for k in ran for key in arms[k]["card"]["pins"]})
    differ = {key: sorted({str(arms[k]["card"]["pins"].get(key)) for k in ran}) for key in pins}
    differ = {key: values for key, values in differ.items() if len(values) > 1}
    print("one commit for every core arm (card pins equal)", not differ)
    for key, values in differ.items():
        print(f"PIN MISMATCH: {key}:", "; ".join(f"{v[:12]} ({','.join(k for k in ran if str(arms[k]['card']['pins'].get(key)) == v)})"
                                                 for v in values))
    if differ:
        invalid.add("card pins")
    # An optional row is compared with the core rows only on the same code: every card pin except the two that name
    # the system under test equals the core arms' (§1). Otherwise it is shown, marked, and left out of section 7.
    core_pins = arms[ran[0]]["card"]["pins"]
    for name in [k for k in arms if k.startswith("X-")]:
        mine = arms[name]["card"]["pins"]
        if any(str(mine.get(key)) != str(core_pins.get(key)) for key in (set(mine) | set(core_pins)) - set(SYSTEM_PINS)):
            print(f"{name}: not run as declared (different code pins)")
            off_order[name] = "different code pins"
    # §1: one pack for every row; the card's pack_hash is the installed tree's hash.
    expected_pack = pack_tree_hash(args.packs)
    for name in arms:
        if arms[name]["card"]["pack_hash"] != expected_pack:
            if name in CORE:
                print(f"PACK MISMATCH: {name} pack_hash {arms[name]['card']['pack_hash'][:12]}"
                      f" (--packs {expected_pack[:12]})")
                invalid.add("pack")
            else:
                print(f"{name}: not run as declared (different pack)")
                off_order[name] = "different pack"
    mismatched = {k for k in arms if arms[k]["card"]["served_identity"] != core_id}

    # 2. Checks before any score.
    print("\n== 2. Checks before any score (§2)")
    blocks, controls = {}, [k for k in ran if arms[k]["row"] in CONTROL]
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
    # Checks 2 and 7 read each unit's own probe records for the pack's expected units and probed items, not the run's
    # own list of them: <run>/<control arm>/<life>/<branch>/t2lite_probes.json.
    expected_units = {f"{life}/{branch}" for life in pack for branch in ("B0", "B1")}
    probed = {(life, i) for life in pack for i in pack[life]["arms"][SCRIPTED[0]]["reports"]}
    probe_files = {name: {unit: read(arms[name]["run"] / arms[name]["control"]["arm"] / unit / "t2lite_probes.json")
                          for unit in sorted(expected_units)} for name in controls}
    # Presence is read from the probe turn's first request, the one that carries the block (in_context_initial). A
    # later request of the same turn also holds what the reader fetched with its own tools (§11.5).
    for name in controls:
        arm = arms[name]
        first = {(unit.split("/", 1)[0], record.get("item_id")): (record.get("shadow") or {}).get("in_context_initial")
                 for unit, probes in probe_files[name].items() for record in probes or []}
        if arm["row"] == "O":
            true = sum(first.get(k) is True for k in tasks)
            print(f"check 2 {name}: needed fact in the probe turn's first request on {true} of {len(tasks)} scored"
                  f" action tasks pass {true == len(tasks)}")
            ok = true == len(tasks)
        elif arm["row"] == "R":
            reports = {(life, i): r["in_context"] for life in pack for i, r in pack[life]["arms"][SCRIPTED[0]]["reports"].items()}
            equal = sum(k in first and first[k] == v for k, v in reports.items())
            print(f"check 2 {name}: presence in the probe turn's first request equals the pack's scripted naive report"
                  f" on {equal} of {len(reports)} tasks pass {equal == len(reports)}")
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
        arm = arms[name]
        units = arm["card"]["floor"]["units"]
        disclosed = arm["disclosures"].get("floor", {})
        cached = sum(u["cached"] is not False for u in units.values()) + sum(
            disclosed.get(u, {}).get("cached") is not False for u in units)
        # Every unit's probe records were sent to the live reader and the unit was not stopped (answers: check 5).
        floor_file = read(arm["run"] / f"{arm['control']['arm']}.json") or {}
        found, records, live, stopped, covered = 0, 0, 0, 0, set()
        for unit, probes in probe_files[name].items():
            life = unit.split("/", 1)[0]
            found += probes is not None
            for record in probes or []:
                records += 1
                live += (record.get("live") or {}).get("served_by") == "live"
                covered.add((life, record.get("item_id")))
            stops = floor_file.get(unit, {}).get("stops")
            stopped += not isinstance(stops, dict) or any(v is not None for v in stops.values())
        covered &= probed
        ok = (set(units) == expected_units and set(disclosed) == expected_units and cached == 0
              and found == len(expected_units) and records > 0 and live == records and stopped == 0
              and covered == probed)
        print(f"check 7 {name}: expected units {len(expected_units)} units listed {len(units)} (card) {len(disclosed)}"
              f" (disclosures) cached or unconfirmed {cached} probe files found {found} probed items covered"
              f" {len(covered)} of {len(probed)} probe records {records} sent to the live reader {live} (answered"
              f" probes are counted by check 5) stopped units {stopped} (stops not all None, or none recorded) pass {ok}")
        if not ok:
            invalid.add(name)
    used = {r: [arms[k] for k in names if k in arms and k not in invalid | mismatched] for r, names in ROWS.items()}
    short_rows = {r for r, names in ROWS.items() if len(used[r]) < len(names) or {a["name"] for a in used[r]} & incomplete}
    for r in sorted(short_rows):
        print(f"row {r} incomplete: repeats used {[a['name'] for a in used[r]]}")
    support = {k: common(used["F"] + used["R"] + used["O"], [p for p in pairs if p["kind"] == k]) for k in kinds}
    print("check 6: pairs scored in every repeat of F, R and O used (common support for the flags):",
          {label(k): len(v) for k, v in support.items()}, "total", sum(map(len, support.values())))
    return dict(args=args, pack=pack, arms=arms, pairs=pairs, kinds=kinds, lives=lives, tasks=tasks, invalid=invalid,
                violation=violation, off_order=off_order, missing=missing, mismatched=mismatched, incomplete=incomplete, used=used, short_rows=short_rows,
                support=support)


def scores(ctx, failed):
    """Sections 3-8, printed only when no control row is invalid and no rerun is pending."""
    pack, arms, pairs, kinds, lives, tasks = (ctx[k] for k in ("pack", "arms", "pairs", "kinds", "lives", "tasks"))
    invalid, mismatched, used, short_rows, support, off_order, missing = (ctx[k] for k in (
        "invalid", "mismatched", "used", "short_rows", "support", "off_order", "missing"))

    # 3. Primary display.
    def groups(members):
        return ([(label(k), [p for p in members if p["kind"] == k]) for k in kinds]
                + [(f"life {n}", [p for p in members if p["life"] == life]) for n, life in enumerate(lives, 1)]
                + [(f"pooled diagnostic (all {len(members)})", members)])

    def display(rows, heading):
        print(f"\n== {heading}")
        for row, members_arms in rows:
            for arm in members_arms:
                if "missing" in arm:
                    print(f"-- {arm['name']}: missing after its rerun (refusal code {arm['missing']})")
                    continue
                print(f"-- {arm['name']}" + (" (INVALID CONTROL ROW)" if arm["name"] in invalid else "")
                      + (" (identity mismatch: not pooled)" if arm["name"] in mismatched else "")
                      + (f" (not run as declared: {off_order[arm['name']]})" if arm["name"] in off_order else ""))
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

    display([(r, [arms[k] if k in arms else dict(name=k, missing=missing[k]) for k in names]) for r, names in ROWS.items()],
            "3. Scored action pairs by kind and life (pairs, right, wrong, no credit, non-result, net, points)")
    optional = [arms[k] for k in arms if k.startswith("X-")]
    if optional or failed:
        display([(None, optional)], "3x. Optional rows (one attempt each; shown separately, never pooled)")
        for name, code in sorted(failed.items()):
            print(f"{name}: attempt failed, refusal code {code}")
    if "H1" in arms and arms["H1"]["floor"] is not None:
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
        for a, b in combinations([arms[k] for k in names if k in arms], 2):
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
        status, means = {}, {}
        for flag in ("low", "naive", "floor"):
            mean = means[flag] = state(flag, f, r, c)
            combos = {"low": [(f, r, pts([o], members)) for o in used["O"]],
                      "naive": [(pts([x], members), pts([y], members), pts([o], members))
                                for x, y, o in product(used["F"], used["R"], used["O"])],
                      "floor": [(pts([x], members), r, pts([o], members)) for x, o in product(used["F"], used["O"])]}[flag]
            # Stability and classification read only whether a flag applies; "not interpreted" is a disclosure.
            agree = [(s == "applies") == (mean == "applies") for s in map(lambda v: state(flag, *v), combos)]
            unresolved = any(row in short_rows for row in rows_of[flag]) or n == 0
            status[flag] = ("unresolved" if unresolved else "unstable" if not all(agree)
                            else "applies" if mean == "applies" else "does not apply")
            print(f"  {flag}: on means {mean} margin_pairs {exact(margin(flag, f, r, c, n))}"
                  f" combinations {len(agree)} agreeing on whether it applies {sum(agree)} status {status[flag]}")
        applied = [x for x in ("low", "naive", "floor") if status[x] == "applies"]
        open_ = [NAMES[x] + " unresolved" for x in ("low", "naive", "floor") if status[x] == "unresolved"]
        if "unstable" in status.values():
            verdict = "unstable; no classification"
        elif applied:
            verdict = "; ".join([" + ".join(NAMES[x] for x in applied)
                                 + ("; low governs first (§6)" if "low" in applied and len(applied) > 1 else "")] + open_)
        elif open_:
            verdict = "; ".join(open_)
        else:
            verdict = "candidate" + (" (near-solved flags not interpreted: c <= f or c <= 0)"
                                     if "not interpreted" in (means["naive"], means["floor"]) else "")
        print(f"  classification: {verdict}")
    print("flags: low c < 75; naive (near-solved by naive retrieval) r >= f + 0.7 (c - f); floor (near-solved"
          " without memory) f >= 0.7 c; near-solved flags not interpreted when c <= f or c <= 0. Margin in pairs ="
          " (left - right) x pairs / 100, low as 75 - c; it applies when the margin is > 0 (low) or >= 0. Combinations:"
          " one repeat per row used (naive F x R x O, floor F x O, low O); a flag is unstable when whether it applies"
          " differs between the means and any combination; not interpreted counts as not applying (disclosure only).")

    # 6. Filter yield.
    print("\n== 6. Prospective filter yield; validates nothing (each twin right with only its evidence in >= 2 of 3"
          " O trials)")
    # A trial without an integer score_milli (BLOCKED, no row, or an excluded arm) is unknown, not a failure.
    trials = [arms[k]["outcomes"] if k in arms and k not in invalid | mismatched else {} for k in ROWS["O"]]

    def twin(key):
        scored = [t[key]["score_milli"] for t in trials if key in t and is_int(t[key]["score_milli"])]
        passes, unknown = scored.count(1000), len(trials) - len(scored)
        return (passes, unknown), "pass" if passes >= 2 else "fail" if passes + unknown < 2 else "unresolved"

    for k in kinds:
        twins = [[twin(key) for key in p["keys"]] for p in pairs if p["kind"] == k]
        verdicts = Counter("pass" if all(v == "pass" for _, v in x) else "fail" if any(v == "fail" for _, v in x)
                           else "unresolved" for x in twins)
        print(f"  {label(k)}: pairs {len(twins)} pass {verdicts['pass']} fail {verdicts['fail']} unresolved"
              f" {verdicts['unresolved']} (twin: pass when right in >= 2 trials, fail when right + unknown < 2;"
              f" pair: pass when both twins pass, fail when either fails) twins by (passes, unknown)"
              f" {dict(sorted(Counter(c for x in twins for c, _ in x).items()))}")

    # 7. Real systems.
    print("\n== 7. Real systems against the control rows (§5); no significance claimed")
    systems = [("H", used["H"])] + [(a["name"], [a]) for a in optional
                                       if a["name"] not in mismatched and a["name"] not in off_order]

    def life_line(name, row, what, system, control, items, life_of, score, group):
        if not system or not control:
            print(f"    {name} minus {row}, {group}, per life ({what}): unresolved (no usable repeat)")
            return
        mine, theirs = per_life(system, items, life_of, score), per_life(control, items, life_of, score)
        d = {life: mine[life] - theirs[life] for life in mine}
        p = sign_flip_p(d, seed=SEED, name=f"{name}-minus-{row}-{group}-{what}") if d else None
        print(f"    {name} minus {row}, {group}, per life ({what}, milli; {what} scored in every repeat of both rows;"
              f" {len(lives) - len(d)} lives left out with none):", [str(d[life]) for life in sorted(d)],
              "exact two-sided sign_flip_p", "n/a" if p is None else f"{p} {float(p):.4f}", "no significance claimed")

    for name, system in systems:
        for k in kinds + [None]:
            group = label(k) if k else "pooled diagnostic"
            members = [p for p in pairs if k is None or p["kind"] == k]
            parts = []
            for row in "FRO":
                control = two_o if row == "O" else used[row]
                if not system or not control:
                    gone = name if not system else "O1 or O2" if row == "O" else row
                    parts.append(f"{name} minus {row} unresolved (no usable {gone} repeat) on 0 pairs")
                    continue
                both = common(system + control, members)
                s, other = pts(system, both), pts(control, both)
                diff = None if s is None or other is None else s - other
                parts.append(f"{row} {exact(other)}, {name} {exact(s)}, {name} minus {row} {exact(diff)} on {len(both)} pairs")
            own = common(system, members)
            head = (f"{name} points {exact(pts(system, own))} on its own {len(own)} scored pairs" if system
                    else f"{name} unresolved (no usable repeat) on 0 pairs")
            print(f"  {name} {group}: {head}; against " + "; ".join(parts)
                  + " (each comparison on the pairs scored in every repeat of both rows)")
            for row in "FRO":
                control = two_o if row == "O" else used[row]
                life_line(name, row, "pairs", system, control, common(system + control, members), lambda p: p["life"],
                          lambda a, p: pair_score(a["outcomes"], p), group)
        keys = [t for t in tasks if all(is_int(a["outcomes"].get(t, {}).get("score_milli")) for a in system + used["F"])]
        life_line(name, "F", "tasks", system, used["F"], keys, lambda t: t[0],
                  lambda a, t: a["outcomes"][t]["score_milli"], "pooled diagnostic")

    # 8. Full history.
    print("\n== 8. Full history")
    print("  fits the window on", sum(life["fits"]["run"] for life in pack.values()), "of",
          sum(life["fits"]["of"] for life in pack.values()), "items, summed over lives")


if __name__ == "__main__":
    sys.exit(main())
