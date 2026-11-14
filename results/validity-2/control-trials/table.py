"""Validity round 2: how the finalists' control trials are read (results/validity-2/DECLARATION.md §3-§5).

Usage: python table.py --packs PACKS_DIR --tasks TASKS.json --tasks-sha256 HEX --order F1,R1,B1,G1,W1,O1,O2,W2,G2,B2,R2,F2,O3
       LABEL=RUN_DIR ... (all thirteen labels)
       [--reruns LABELS] [--attempts LIST] [--after-reruns] [--checks-only] [--check3 FILE] [--filter-out PATH]
Adapted from Milestone 1's table.py (imported by path; its checks, flag rules and twin filter rule are reused). Reads
only the target items of TASKS.json (tasks.py), grouped by template ref: an action pair scores twin_min of its twins,
all four templates use action pairs (+1000, 0, -1000). Prints, in order: 1 header and identity, with each row's centre
(F, R, B, G, W, O1-O2) and O3's position in the order the arms actually ran (§3); 2 checks before any score (§4); 3 scores by
template; 4 readings (§5); 5 the oracle filter (counts only; FILTER.json with --filter-out).
Exit 3: a refusal (a run without control.json or receipt.json, or with another row's control; a card at another commit than
TASKS.json names; TASKS.json with another sha256, edition, pack hash, or rows that are not exactly tasks.py's target
items of the pack; an inconsistent --attempts), or check 1, 2, 3 or 7, the run order, the card pins or the pack
failing. Exit 4: check 4, 5 or 8 open without --after-reruns. Exit 5: an arm named in --reruns fails check 1, 2 or 7
again, or check 3 still fails with --after-reruns, so the round ends (§4): the checks and missing observations are
printed, every template reads unresolved, and no score is opened. Each arm is rerun at most once, whatever check
failed: a rerun that fails check 1, 2 or 7 ends the round even when the arm was rerun for check 4 or 5 (§4.6, "after
the one rerun"). Check 8 reruns an arm once just like check 4; a repeat that compacted again is excluded.
Check 4's reference identity is the most common served identity among the arms; on a tie, the tied identity served to
the arm that ran earliest in --order. A drift disclosure, or none recorded, is a mismatch (M1 §11.15). Check 7 also
needs each unit's own probe file to hold exactly that unit's records. A template is read on the repeats that are
present, valid, identity-matched, uncompacted and score every target item of it (§4.6); any repeat left out makes it unresolved.
Row centres (§3) come from --attempts, every attempt in the order it ran; with reruns and no --attempts they are not
computed.
Prints counts, labels, 12-character hash prefixes and pass/fail only: never task text, answers, control text, item
or bundle ids, served identity values, or paths.
"""

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from fractions import Fraction
from hashlib import sha256
from itertools import pairwise, product
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The code that produced the output, printed in section 1: this script, tasks.py and Milestone 1's table.py.
CODE = {"table.py": HERE / "table.py", "tasks.py": HERE / "tasks.py",
        "Milestone 1 table.py": HERE.parents[1] / "milestone-1" / "2026-11-11-separation-table" / "table.py"}
_spec = importlib.util.spec_from_file_location("m1_table", CODE["Milestone 1 table.py"])
m1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m1)
_spec = importlib.util.spec_from_file_location("validity_tasks", HERE / "tasks.py")
frozen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frozen)

from bicentennial.anchors import run as run_anchor  # noqa: E402
from bicentennial.anchors.report import ANCHORS, header  # noqa: E402
from bicentennial.canon import canon  # noqa: E402
from bicentennial.packs.scoring import control_input, make_score  # noqa: E402
from bicentennial.score.bundle import twin_min  # noqa: E402

is_int, short, exact, read, refusal_code, outcomes_of = (m1.is_int, m1.short, m1.exact, m1.read, m1.refusal_code,
                                                         m1.outcomes_of)
state, margin = m1.state, m1.margin
recompute_blocks, frame_sha256, pack_tree_hash = m1.recompute_blocks, m1.frame_sha256, m1.pack_tree_hash

ROWS = {"F": ("F1", "F2"), "R": ("R1", "R2"), "B": ("B1", "B2"), "G": ("G1", "G2"),
        "W": ("W1", "W2"), "O": ("O1", "O2", "O3")}
CORE = tuple(a for arms in ROWS.values() for a in arms)
CONTROL = {"F": "no_memory", "R": "naive_rag", "B": "bm25", "G": "grep", "W": "recent_window", "O": "oracle_evidence"}
DECLARED_ORDER = ("F1", "R1", "B1", "G1", "W1", "O1", "O2", "W2", "G2", "B2", "R2", "F2", "O3")
RERUN = "rerun once (§4.4, §4.5, §4.8), then run again with --after-reruns"
VALUES = (1000, 0, -1000)
ANCHOR_ROWS = {"R": "naive retrieval", "B": "BM25", "G": "grep", "W": "the recent window"}
CARDS = HERE.parent / "cards" / "README.md"
REPO = HERE.parents[2]
# Local list: M1's memory-off and two text tests, each new anchor's block/presence tests, and all reader configs.
CHECK3_TESTS = (
    "test_c_floor_bodies_and_memory_off",
    *(f"test_a_block_is_the_pinned_controls_text_in_the_probe_turn[{c}]"
      for c in ("naive_rag", "oracle_evidence", "bm25", "grep", "recent_window")),
    *(f"test_b_anchor_initial_in_context_equals_the_scripted_report[{c}]" for c in ANCHORS),
    *(f"test_probe_session_writes_the_arms_reader_config[{c}]"
      for c in ("grep", "recent_window", "no_memory", "naive_rag", "oracle_evidence", "bm25")),
)


def card_anchors():
    """The cards' identities; the hashed spec's title supplies the version omitted from the table."""
    table = CARDS.read_text().split("## Anchor identities", 1)[1].split("\n## ", 1)[0]
    out = {}
    for name in ANCHORS:
        spec = f"specs/controls/{name}.md"
        rows = [line for line in table.splitlines() if f"`{spec}`" in line]
        hashes = re.findall(r"`([0-9a-f]{64})`", rows[0]) if len(rows) == 1 else []
        version = re.search(r"anchor v(\d+)", (REPO / spec).read_text().splitlines()[0])
        if len(hashes) == 2 and version:
            out[name] = dict(name=name, version=int(version[1]), spec_sha256=hashes[0], code_sha256=hashes[1])
    return out


def compacted(receipt):
    """The arm-level receipt aggregates every attempt, including discarded attempts (runner/t2.py)."""
    return any(r["role"] == "summariser" and (r["input"] != 0 or r["output"] != 0)
               for r in receipt["tokens_by_role"])


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
    """The target twin pairs (by bundle id); keys are life/branch/item_id."""
    groups = {}
    for r in rows:
        key = (r["template_ref"], r["life"], r["bundle_id"])
        groups.setdefault(key, dict(template=r["template_ref"], life=r["life"], bundle_id=r["bundle_id"],
                                    keys=[]))["keys"].append(f"{r['life']}/{r['branch']}/{r['item_id']}")
    return [dict(g, keys=tuple(sorted(g["keys"]))) for _, g in sorted(groups.items())]


def bundle_score(outcomes, b):
    """milli: twin_min of an action pair's twins."""
    rows = [outcomes.get(k) for k in b["keys"]]
    if any(r is None or not is_int(r.get("score_milli")) for r in rows):
        return None
    return twin_min(*rows)


def pts(arms, members):
    """100 times the mean bundle score over the arms' repeats on members (all scored in every arm)."""
    if not arms or not members:
        return None
    return Fraction(sum(bundle_score(a["outcomes"], b) for a in arms for b in members), len(arms) * len(members)) / 10


def line(scores):
    n, got = Counter(scores), [s for s in scores if s is not None]
    return (f"bundles {len(scores)} " + " ".join(f"{v:+d} {n[v]}" if v else f"0 {n[0]}" for v in VALUES) + f" non_result {n[None]}"
            f" points {exact(Fraction(sum(got), len(got)) / 10 if got else None)}")


def positions(attempts, order, reruns):
    """({label: 1-based position of the attempt used}, None) from --attempts (every attempt in the order it ran, a
    rerun written L.rerun), or (None, a refusal reason). With no reruns and no --attempts: the order's own positions;
    with reruns and no --attempts: ({}, None), never a guess (§3)."""
    if attempts is None:
        return ({k: n for n, k in enumerate(order, 1)} if not reruns else {}), None
    seq = attempts.split(",")
    firsts = [a for a in seq if a in CORE]
    again = [a.removesuffix(".rerun") for a in seq if a.endswith(".rerun")]
    if (firsts != list(DECLARED_ORDER) or sorted(again) != sorted(reruns) or len(firsts) + len(again) != len(seq)
            or any(seq.index(f"{r}.rerun") < seq.index(r) for r in again)):
        return None, ("--attempts must list the thirteen labels once each as first attempts in the declared order, each"
                      " --reruns label once more as L.rerun after it, and nothing else")
    last = {a.removesuffix(".rerun"): n for n, a in enumerate(seq, 1)}
    if sorted(last, key=last.get) != order:
        return None, "--attempts does not give the --order sequence (each label's last attempt)"
    return last, None


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
    """Per-life scripted reports and outcomes (anchors.report's recipe), and every sealed record's key.

    R is read from the sealed naive report; B/G/W run with the installed pack and sealed scoring cases, exactly
    as tests/runner/test_control_arms.py. No live reader and no report files written into the pack.
    """
    out, keys = {}, set()
    for sealed in sorted(Path(packs).glob("pack/*/*/*/sealed")):
        records = json.loads((sealed / "records.json").read_text())
        life = {r["life"] for r in records}
        if len(life) != 1:
            return None, "a sealed life's records do not name exactly one life"
        keys |= {(r["life"], r["branch"], r["item_id"]) for r in records}
        inp = control_input(sealed.parent)
        score = make_score(read(sealed / "scoring.json"))
        reports = dict(naive_rag=read(sealed / "naive_rag.json")["arm"], **{
            name: run_anchor(inp, cls, score=score) for name, cls in ANCHORS.items()})
        out[life.pop()] = {name: {field: {r["item_id"]: r for r in arm[field]} for field in ("reports", "items")}
                           for name, arm in reports.items()}
    return (out, keys), None


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
    parser.add_argument("--attempts", help="every attempt in the order it ran, a rerun written L.rerun (§3 centres)")
    parser.add_argument("arms", nargs="+", metavar="LABEL=RUN_DIR")
    args = parser.parse_args(argv)
    given = dict(a.split("=", 1) for a in args.arms)
    if sorted(given) != sorted(CORE) or len(args.arms) != len(CORE):
        parser.error("labels: all of " + " ".join(CORE))
    order = args.order.split(",")
    if sorted(order) != sorted(CORE):
        parser.error("--order must list the thirteen labels once each")
    reruns = args.reruns.split(",") if args.reruns else []
    if len(set(reruns)) != len(reruns) or not set(reruns) <= set(CORE):
        parser.error("--reruns must list labels, each once")
    place, refusal = positions(args.attempts, order, reruns)
    if refusal:
        return refuse(refusal)
    # The frozen list (§3): its posted sha256, its edition and pack, and exactly the pack's own target items.
    tasks, refusal = load_tasks(args.tasks, args.tasks_sha256)
    if refusal:
        return refuse(refusal)
    if tasks["header"]["edition"] != frozen.EDITION:
        return refuse(f"TASKS.json edition is not {frozen.EDITION}")
    tree = pack_tree_hash(args.packs)
    if tasks["header"]["pack_hash"] != tree:
        return refuse("TASKS.json pack hash differs from the --packs tree hash")
    present = {(rec["life"], rec["branch"], rec["item_id"], f"{rec['template_id']}-v{rec['template_version']}",
                rec["bundle_id"]) for _, rec, _ in frozen.pack_records(args.packs)}
    absent = sum((r["life"], r["branch"], r["item_id"], r["template_ref"], r["bundle_id"]) not in present
                 for r in tasks["rows"])
    if absent:
        return refuse(f"{absent} target items of TASKS.json are absent from the pack")
    rows, refusal = frozen.target_rows(frozen.pack_records(args.packs))
    if refusal:
        return refuse(f"the pack breaks the frozen list's rule (tasks.py): {refusal}")
    if rows != tasks["rows"]:
        return refuse("TASKS.json rows differ from the pack's own target items (tasks.py)")
    pack, refusal = load_pack(args.packs)
    if refusal:
        return refuse(refusal)
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
                          disclosures=read(run / "disclosures.json") or {}, receipt=read(run / "receipt.json"))
        if arms[name]["receipt"] is None:
            return refuse(f"{name} has no receipt.json (check 8)")
    # One commit for every arm (§3): anything run at another commit than the frozen list's voids the draw.
    other = [k for k in arms if arms[k]["card"]["pins"].get("benchmark_commit") != tasks["header"]["commit"]]
    if other:
        return refuse(f"{','.join(other)} ran at another commit than TASKS.json names")
    if not arms:
        print("== 1. Header and identity")
        for name, code in missing.items():
            print(f"{name}: missing (no card.json or outcomes.json; refusal code {code})")
        print("no arm has card.json and outcomes.json: no check or reading can be computed")
        if not args.after_reruns:
            print("pending before any score:", " ".join(missing), "-", RERUN)
            return 4
        return 3
    ctx = checks(args, pack, tasks, arms, order, reruns, missing, tree, place)
    if ctx["invalid"]:
        # §4: a rerun failing check 1, 2 or 7 again, or check 3 still failing after the reruns, ends the round.
        again = sorted(ctx["invalid"] & set(reruns), key=CORE.index)
        if again or ("check 3" in ctx["invalid"] and args.after_reruns):
            round_ends(ctx, again, args.after_reruns)
            return 5
        if ctx["violation"]:
            print(f"RUN ORDER VIOLATION: {ctx['violation']}")
        for what, text in (("card pins", "CARD PINS DIFFER between arms (see PIN MISMATCH above): not pooled"),
                           ("pack", "PACK DIFFERS from --packs for an arm (see PACK MISMATCH above): not pooled"),
                           ("check 3", "CHECK 3 NOT SHOWN PASSING at the run commit (see check 3 above): no score"
                                       " is opened; rerun check 3 at the run commit")):
            if what in ctx["invalid"]:
                print(text)
        for name in sorted(ctx["invalid"] & set(CORE), key=CORE.index):
            print("INVALID CONTROL ROW", name)
        return 3
    pending = sorted(ctx["mismatched"] | ctx["incomplete"] | ctx["compacted"] | set(missing), key=CORE.index)
    if pending and not args.after_reruns:
        print("pending before any score:", " ".join(pending), "-", RERUN)
        return 4
    if args.checks_only:
        return 0
    scores(ctx)
    oracle_filter(ctx, args)
    return 0


def checks(args, pack, tasks, arms, order, reruns, missing, tree, place):
    """Sections 1 and 2; returns what sections 3-5 need. Missing repeats enter no check (§4.6)."""
    pack, expected_keys = pack
    bundles = bundles_of(tasks["rows"])
    templates = sorted({b["template"] for b in bundles})
    targets = [k for b in bundles for k in b["keys"]]
    invalid, failed = set(), {}

    # 1. Header and identity.
    print("== 1. Header and identity")
    print("target items", len(targets), "bundles", len(bundles), "templates", " ".join(templates),
          "| tasks sha256", args.tasks_sha256.lower()[:12], "| pack_hash", tree[:12])
    for name, path in CODE.items():
        print(f"code {name} sha256 {sha256(path.read_bytes()).hexdigest()[:12]}")
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
    print("row centres in the order the arms actually ran: " + (
        f"(positions 1-{len(order) + len(reruns)}) " + " ".join(
            f"{r} {exact(Fraction(sum(place[k] for k in names[:2]), 2))}" for r, names in ROWS.items())
        + f"; O3 at {place['O3']} (declared order: each centre 13/2)" if place else "not computed (pass --attempts)"))
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
    cards, checkout = card_anchors(), header()["anchors"]
    for name in ran:
        arm, rec = arms[name], arms[name]["control"]
        if arm["row"] == "F":
            ok = rec.get("frame_sha256") is None and rec.get("block_sha256") == {}
            print(f"check 1 {name}: no blocks {rec.get('block_sha256') == {}} payload {ok}")
        else:
            if rec["arm"] not in blocks:  # one replay of each pinned control
                blocks[rec["arm"]] = recompute_blocks(args.packs, rec["arm"])
            want = blocks[rec["arm"]]
            got = rec.get("block_sha256") or {}
            matched = sum(got.get(k) == v for k, v in want.items())
            frame = rec.get("frame_sha256") == frame_sha256()
            ok = bool(frame and want and matched == len(want) == len(got))
            print(f"check 1 {name}: frame_sha256 {frame} blocks matched {matched} of {len(want)} mismatched"
                  f" {len(want) - matched} recorded but not recomputed {len(got.keys() - want.keys())} payload {ok}")
        window = rec.get("reader_window") == 32768 if arm["row"] in ("G", "W") else "reader_window" not in rec
        anchor_ok = True
        if rec["arm"] in ANCHORS:
            definition = checkout[rec["arm"]]
            want_anchor = dict(name=rec["arm"], **{k: definition[k] for k in ("version", "spec_sha256", "code_sha256")})
            anchor_ok = rec.get("anchor") == cards.get(rec["arm"]) == want_anchor
        ok = ok and window and anchor_ok
        print(f"check 1 {name}: anchor identity {anchor_ok} reader_window {window} pass {ok}")
        if not ok:
            failed.setdefault(name, []).append(1)
    expected_units = {f"{life}/{branch}" for life in pack for branch in ("B0", "B1")}
    probe_files = {name: {unit: read(arms[name]["run"] / arms[name]["control"]["arm"] / unit / "t2lite_probes.json")
                          for unit in sorted(expected_units)} for name in ran}
    # Check 2 reads the probe turn's first request, the one that carries the block (M1 §11.5), on the 80 targets.
    for name in [k for k in ran if arms[k]["row"] != "F"]:
        first = {f"{unit}/{r.get('item_id')}": (r.get("shadow") or {}).get("in_context_initial")
                 for unit, probes in probe_files[name].items() for r in probes or []}
        if arms[name]["row"] == "O":
            true = sum(first.get(k) is True for k in targets)
            print(f"check 2 {name}: needed fact in the probe turn's first request on {true} of {len(targets)} target"
                  f" items pass {true == len(targets)}")
            ok = true == len(targets)
        else:
            report = {k: pack.get(k.split("/")[0], {}).get(arms[name]["control"]["arm"], {}).get(
                "reports", {}).get(k.split("/", 2)[2], {}).get("in_context") for k in targets}
            equal = sum(k in first and report[k] is not None and first[k] == report[k] for k in targets)
            print(f"check 2 {name}: presence in the probe turn's first request equals the pack's scripted {arms[name]['control']['arm']}"
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
        found, records, live, stopped, observed = 0, 0, 0, 0, Counter()
        for unit, probes in probe_files[name].items():
            found += probes is not None
            for record in probes or []:
                records += 1
                live += (record.get("live") or {}).get("served_by") == "live"
                observed[(*unit.split("/", 1), record.get("item_id"))] += 1
            stopped += (floor_file.get(unit) or {}).get("stops") != {unit.replace("/", ""): None}
        # Each unit's own probe file holds exactly that unit's records, each once: one unit's probes never stand in
        # for another's, and no record is read twice.
        duplicated = sum(n - 1 for n in observed.values())
        ok = (set(units) == expected_units and set(disclosed) == expected_units and cached == 0
              and found == len(expected_units) and records > 0 and live == records and stopped == 0
              and set(observed) == expected_keys and duplicated == 0)
        print(f"check 7 {name}: expected units {len(expected_units)} units listed {len(units)} (card) {len(disclosed)}"
              f" (disclosures) cached or unconfirmed {cached} probe files found {found} probe keys (life, branch,"
              f" item) matching the pack's records {len(set(observed) & expected_keys)} of {len(expected_keys)}"
              f" unexpected {len(set(observed) - expected_keys)} duplicated {duplicated} probe records {records} sent to the live reader {live} stopped units"
              f" {stopped} pass {ok}")
        if not ok:
            failed.setdefault(name, []).append(7)
    invalid |= set(failed)
    compressed = {k for k in ran if compacted(arms[k]["receipt"])}
    for name in ran:
        print(f"check 8 {name}: compacted {name in compressed} pass {name not in compressed}")
    scripted = {row: {f"{life}/{r['branch']}/{r['item_id']}": pack[life][control]["items"].get(r["item_id"])
                      for r in tasks["rows"] for life in (r["life"],)}
                for row, control in CONTROL.items() if row in ANCHOR_ROWS}
    # §4.6, per template: a repeat is used for t only when it is present, valid, identity-matched, uncompacted and scores every
    # target item of t (M1 §11.1 is not imported). Any repeat left out makes t unresolved.
    members = {t: [b for b in bundles if b["template"] == t] for t in templates}
    use, left = {}, {}
    for t in templates:
        keys = [k for b in members[t] for k in b["keys"]]
        left[t] = {k: "missing" if k not in arms else "invalid" if k in invalid else "identity mismatch"
                   if k in mismatched else "compacted" if k in compressed else "incomplete on this template" for k in CORE
                   if k not in arms or k in invalid | mismatched | compressed
                   or not all(is_int((arms[k]["outcomes"].get(x) or {}).get("score_milli")) for x in keys)}
        use[t] = {r: [arms[k] for k in names if k not in left[t]] for r, names in ROWS.items()}
        print(f"check 6 {t}: repeats used {' '.join(k for k in CORE if k not in left[t]) or 'none'}; left out "
              + (", ".join(f"{k} ({why})" for k, why in left[t].items()) or "none"))
    return dict(args=args, arms=arms, bundles=bundles, templates=templates, members=members, targets=targets,
                invalid=invalid, failed=failed, violation=violation, missing=missing, mismatched=mismatched,
                incomplete=incomplete, compacted=compressed, scripted=scripted, use=use, left=left,
                tasks_sha256=args.tasks_sha256.lower())


def round_ends(ctx, again, after_reruns):
    """§4: a rerun failed check 1, 2 or 7 again, or check 3 still fails after the reruns. The checks are above; the
    missing observations, then no score. Check 3 voids every arm only once it still fails with --after-reruns."""
    check3 = "check 3" in ctx["invalid"]
    final3 = check3 and after_reruns
    said = [f"{k} fails check {','.join(map(str, ctx['failed'][k]))} again after its rerun" for k in again] + (
        ["check 3 is not shown passing at the run commit after the reruns"] if final3 else
        ["check 3 not shown passing (not yet rerun)"] if check3 else [])
    print(f"\nROUND ENDS: {'; '.join(said)} (§4); no score is opened")
    gone = list(CORE) if final3 else sorted(
        set(ctx["failed"]) | set(ctx["missing"]) | ctx["mismatched"] | ctx["compacted"], key=CORE.index)
    print("missing observations: arms without usable trials", " ".join(gone))
    for t in ctx["templates"]:
        n = sum(len(b["keys"]) for b in ctx["members"][t])
        mine = list(CORE) if final3 else sorted(set(gone) | set(ctx["left"][t]), key=CORE.index)
        print(f"  {t}: target items {n}, each without a usable trial in {len(mine)} of {len(CORE)} arms"
              f" ({' '.join(mine)})")
    for t in ctx["templates"]:
        print(f"reading {t}: unresolved")


def reading(ctx, t):
    """§5 precedence: unresolved, unstable, low, ranking candidate, cleared."""
    used, support, left = ctx["use"][t], ctx["members"][t], ctx["left"][t]
    means = {row: pts(used[row], support) for row in ROWS}
    f, r = means["F"], means["R"]
    two_o = [a for a in used["O"] if a["name"] in ("O1", "O2")]
    c = pts(two_o, support) if len(two_o) == 2 else None
    names = " ".join(a["name"] for row in used.values() for a in row) or "none"
    out = [f"-- {t}: bundles {len(support)} repeats used {names} " + " ".join(
        f"{row.lower()} {exact(means[row])}" for row in ("F", *ANCHOR_ROWS))
        + f" c {exact(c)} c over O1,O2,O3 {exact(pts(used['O'], support))}"]
    low = state("low", f, r, c)
    trials = [(a["name"], state("low", None, None, pts([a], support))) for a in used["O"]]
    disagree = [n for n, s in trials if s != low]
    told = ("n/a (mean unavailable)" if low == "n/a" else "n/a (no combinations)" if not trials
            else len(disagree))
    out.append(f"  low (c < 75): on means {low} margin_bundles {exact(margin('low', f, r, c, len(support)))};"
               f" each O trial alone: " + ", ".join(f"{n} {s}" for n, s in trials)
               + f"; disagreeing with the means {told}")
    labels, candidate_flags = [], []
    for row, name in (*((row, f"near-solved by {name}") for row, name in ANCHOR_ROWS.items()),
                      ("F", "near-solved without memory")):
        flag = "floor" if row == "F" else "naive"
        mean = state(flag, f, means[row], c)
        combos = ([(pts([x], support), pts([y], support), pts([o], support))
                   for x, y, o in product(used["F"], used[row], used["O"])] if row != "F" else
                  [(pts([x], support), None, pts([o], support)) for x, o in product(used["F"], used["O"])])
        agree = [state(flag, *v) == mean for v in combos]
        told = ("n/a (mean unavailable)" if mean == "n/a" else "n/a (no combinations)" if not agree
                else f"{sum(agree)} {'stable' if all(agree) else 'unstable'}")
        out.append(f"  {row.lower()} ({name}): on means {mean}"
                   f" margin_bundles {exact(margin(flag, f, means[row], c, len(support)))}"
                   f" combinations {len(agree)} agreeing with the means {told}")
        candidate_flags.append(mean == "no" and bool(agree) and all(agree))
        if mean == "applies":
            labels.append(name)
    if labels:
        out.append(f"  labelled {' + '.join(labels)}: a do-no-harm check, excluded from any claim that memory beats"
                   " retrieval (M1 §6)")
    if left:
        result = "unresolved"
        out.append("  completeness: repeats left out " + ", ".join(f"{k} ({why})" for k, why in left.items()))
    elif disagree:
        result = "unstable"
    elif low == "applies":
        result = "low"
    elif all(candidate_flags) and max(means[row] for row in ANCHOR_ROWS) <= 35:
        result = "ranking candidate"
    else:
        result = "cleared"
    return out, result


def scores(ctx):
    """Sections 3 and 4, printed only when every check passed and no rerun is pending."""
    arms, use, templates, members = ctx["arms"], ctx["use"], ctx["templates"], ctx["members"]
    print("\n== 3. Scores by template (bundle scores +1000 0 -1000 milli, non-result; points = 100 x mean)")
    for name in CORE:
        if name not in arms:
            print(f"-- {name}: missing after its rerun (refusal code {ctx['missing'][name]})")
            continue
        print(f"-- {name}" + (" (identity mismatch: not pooled)" if name in ctx["mismatched"] else "")
              + (" (compacted: not pooled)" if name in ctx["compacted"] else ""))
        for t in templates:
            print(f"  {t}: {line([bundle_score(arms[name]['outcomes'], b) for b in members[t]])}")
    for row in ROWS:
        print(f"-- {row} mean of the repeats used for each template")
        for t in templates:
            print(f"  {t}: repeats {[a['name'] for a in use[t][row]]} points {exact(pts(use[t][row], members[t]))}")
    for t in templates:
        for row, name in ANCHOR_ROWS.items():
            proxy = dict(outcomes=ctx["scripted"][row])
            print(f"scripted beside live {t} {name}: pairs {len(members[t])}"
                  f" scripted points {exact(pts([proxy], members[t]))} live points {exact(pts(use[t][row], members[t]))}"
                  " (scripted proxy; never enters the reading)")
    print("\n== 4. Readings (§5): f, r, b, g, w = means of each row's two arms; c = mean of O1,O2; exact points over each"
          " template's repeats used, each scoring every target item of the template")
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
    arms, excluded = ctx["arms"], ctx["invalid"] | ctx["mismatched"] | ctx["compacted"]
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
