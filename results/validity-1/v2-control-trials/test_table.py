"""Synthetic fixture tests for tasks.py and table.py (validity round 1): frozen list, checks, scores, readings, filter.

Run directly: PYTHONPATH=<checkout>/src python -m pytest results/validity-1/v2-control-trials/test_table.py
(not in CI's testpaths). The fixture pack has five G1 lives, each with one twin pair of each v2 action template and a
v1 Wake pair that is not a target, and five G2 lives, each with one v2 count question and a v1 single that is not.
"""

import json
import sys
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import table  # noqa: E402
import tasks  # noqa: E402

G1 = tuple(f"LIFEZQG1{c}" for c in "ABCDE")
G2 = tuple(f"LIFEZQG2{c}" for c in "ABCDE")
ACTION = {"drift-chain-fault-v2": ("drift-chain-fault-v2", "drift-chain-fault-v2"),
          "drift-config-v2": ("drift-config-corrected-v2", "drift-config-hedged-v2"),
          "drift-quote-v2": ("drift-quote-v2", "drift-quote-v2")}
COUNT = "recall-count-v2"
TEMPLATES = (*ACTION, COUNT)
IDENTITY = "identity-zq-served-value"
ORDER = ("F1", "R1", "O1", "O2", "R2", "F2", "O3")
BASE = {"F": dict.fromkeys(TEMPLATES, [0] * 5),
        "R": {"drift-chain-fault-v2": [1000] * 5, "drift-config-v2": [0] * 5, "drift-quote-v2": [-1000] * 5,
              COUNT: [500] * 5},
        "O": dict.fromkeys(TEMPLATES, [1000] * 5)}
CHECK3_OK = "\n".join([f"commit {'b' * 40}", *(f"tests/runner/test_control_arms.py::{t} PASSED [{n}%]"
                                              for n, t in zip((33, 66, 100), table.CHECK3_TESTS, strict=True)),
                       "3 passed in 1.00s", "exit 0"])


def layout():
    """[(life, template_ref, index, bundle id or None, [(branch, item id, table)], target)] in a fixed order."""
    out = []
    for n, life in enumerate(G1):
        for j, ref in enumerate(ACTION):
            out.append((life, ref, n, f"BUNDLEZQ{n}{j}",
                        [("B0", f"ITEMZQ{n}{j}a", ACTION[ref][0]), ("B1", f"ITEMZQ{n}{j}b", ACTION[ref][1])], True))
        out.append((life, "wake-loop-v1", n, f"BUNDLEZQ{n}w",
                    [("B0", f"ITEMZQ{n}wa", "wake-loop-v1"), ("B1", f"ITEMZQ{n}wb", "wake-loop-v1")], False))
    for n, life in enumerate(G2):
        out.append((life, COUNT, n, None, [("B0", f"ITEMZQ{n}c", COUNT)], True))
        out.append((life, "drift-asof-v1", n, None, [("B0", f"ITEMZQ{n}s", "drift-asof-v1")], False))
    return out


def in_report(ref):
    return ref == "drift-chain-fault-v2"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def make_packs(root, edit=None):
    """edit(record) may change a record before it is written, or return False to drop it."""
    for genre, lives in (("G1", G1), ("G2", G2)):
        for life in lives:
            mine = [x for x in layout() if x[0] == life]
            records, items, reports = [], [], []
            for _, ref, _, bundle, members, _ in mine:
                tid, version = ref.rsplit("-v", 1)
                for branch, iid, tab in members:
                    rec = dict(template_id=tid, template_version=int(version), life=life, branch=branch,
                               item_id=iid, bundle_id=bundle)
                    if edit and edit(rec) is False:
                        continue
                    records.append(rec)
                    items.append(dict(item_id=iid, decision_table_ref=tab))
                    reports.append(dict(item_id=iid, in_context=in_report(ref)))
            sealed = root / "pack" / genre / life / "7" / "sealed"
            write(sealed / "pack.json", dict(genre=genre, items=items))
            write(sealed / "records.json", records)
            write(sealed / "naive_rag.json", dict(arm=dict(reports=reports)))
    write(root / "index.json", dict(packs={}))
    return root


def make_tasks(tmp_path, packs, edit=None, name="TASKS.json"):
    out = tmp_path / name
    code = tasks.main(["--packs", str(packs), "--spec", str(write_file(tmp_path / "spec.toml", "seed = 1")),
                       "--draw", str(write_file(tmp_path / "draw.json", "[1, 2]")), "--commit", "b" * 40,
                       "--edition", "2", "--out", str(out)])
    return code, out


def write_file(path, text):
    path.write_text(text)
    return path


def block_hashes():
    return {f"{life}/{branch}/{iid}": sha256(f"control text for {iid}".encode()).hexdigest()
            for life, _, _, _, members, _ in layout() for branch, iid, _ in members}


def make_arm(path, label, spec, twins=None, slot=0, pack_hash="p" * 64, identity=IDENTITY):
    """spec: template_ref -> five bundle scores by life; twins: {(template_ref, index, twin): score} overrides."""
    letter, out = label[0], {}
    for life, ref, n, _, members, target in layout():
        for t, (branch, iid, _) in enumerate(members):
            score = (twins or {}).get((ref, n, t), spec[ref][n]) if target else 0
            blocked = score == "B"
            out[f"{life}/{branch}/{iid}"] = dict(score_milli=None if blocked else score,
                                                 failure_class="BLOCKED" if blocked else None, stage="act")
    units = {f"{life}/{b}": dict(cache_key="k", cached=False) for life in G1 + G2 for b in ("B0", "B1")}
    write(path / "card.json", dict(tier="T2", model="m", effort="medium", pack_hash=pack_hash,
                                   pins=dict(scorer_commit="c" * 40, benchmark_commit="b" * 40),
                                   served_identity=identity, floor=dict(units=units)))
    write(path / "outcomes.json", out)
    start = 1793796303380 + slot * 10_000_000
    write(path / "units.json", dict(start_ms=start, end_ms=start + 6_000_000))
    write(path / "disclosures.json", dict(floor={u: dict(cached=False) for u in units}, live=dict(identity_drift=None)))
    arm = table.CONTROL[letter]
    presence = {f"{life}/{b}/{iid}": (letter == "O" or letter == "R" and in_report(ref))
                for life, ref, _, _, members, _ in layout() for b, iid, _ in members}
    for unit in units:
        life, branch = unit.split("/")
        write(path / arm / life / branch / "t2lite_probes.json", [
            dict(item_id=k.split("/", 2)[2], live=dict(served_by="live"), shadow=dict(in_context_initial=v))
            for k, v in presence.items() if k.startswith(f"{unit}/")])
    write(path / f"{arm}.json", {unit: dict(stops={unit.replace("/", ""): None}) for unit in units})
    write(path / "control.json", dict(arm=arm, frame_sha256=None if letter == "F" else "f" * 64,
                                      block_sha256={} if letter == "F" else block_hashes()))
    return path


@pytest.fixture
def packs(tmp_path):
    return make_packs(tmp_path / "packs")


@pytest.fixture
def run(tmp_path, packs, monkeypatch, capsys):
    monkeypatch.setattr(table, "recompute_blocks", lambda packs, control: block_hashes())
    monkeypatch.setattr(table, "frame_sha256", lambda: "f" * 64)
    code, tasks_path = make_tasks(tmp_path, packs)
    assert code == 0
    capsys.readouterr()
    pack_hash = table.pack_tree_hash(packs)

    def go(specs=None, twins=None, edit=None, slots=None, flags=(), order=ORDER, check3=CHECK3_OK, identities=None,
           tasks_sha=None, filter_out=None, attempts=None):
        argv = ["--packs", str(packs), "--tasks", str(tasks_path), "--tasks-sha256",
                tasks_sha or sha256(tasks_path.read_bytes()).hexdigest(), "--order", ",".join(order), *flags]
        if check3 is not None:
            (tmp_path / "check3.txt").write_text(check3)
            argv += ["--check3", str(tmp_path / "check3.txt")]
        if attempts:
            argv += ["--attempts", ",".join(attempts)]
        if filter_out:
            argv += ["--filter-out", str(filter_out)]
        for label in table.CORE:
            spec = dict(BASE[label[0]], **(specs or {}).get(label, {}))
            path = make_arm(tmp_path / "runs" / label, label, spec, (twins or {}).get(label),
                            slot=(slots or {}).get(label, ORDER.index(label)), pack_hash=pack_hash,
                            identity=(identities or {}).get(label, IDENTITY))
            if edit:
                edit(label, path)
            argv.append(f"{label}={path}")
        code = table.main(argv)
        return code, capsys.readouterr().out
    return go


def section(out, template):
    lines = out.split("== 4.")[1].split("== 5.")[0].splitlines()
    at = lines.index(next(x for x in lines if x.startswith(f"-- {template}:")))
    end = next(i for i in range(at, len(lines)) if lines[i].startswith("  reading: "))
    return lines[at:end + 1]


def reading_of(out, template):
    return section(out, template)[-1].removeprefix("  reading: ")


def edit_json(path, change):
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


# 1. The filter.
def test_filter_item_rule_on_every_combination():
    values = (1000, 500, 0, -500, -1000, None)
    for combo in product(values, repeat=3):
        trials = [{} if v is None else {"k": dict(score_milli=v)} for v in combo]
        passes, unknown = combo.count(1000), combo.count(None)
        # M1's twin rule (its table.py section 6): pass with two at 1000, fail when passes + unknown < 2.
        want = "pass" if passes >= 2 else "fail" if passes + unknown < 2 else "unresolved"
        assert table.twin(trials, "k") == ((passes, unknown), want)
    assert table.twin([{"k": dict(score_milli=500)}] * 3, "k")[1] == "fail"
    for verdicts in product(("pass", "fail", "unresolved"), repeat=2):
        want = "pass" if verdicts == ("pass", "pass") else "fail" if "fail" in verdicts else "unresolved"
        assert table.bundle_verdict(list(verdicts)) == want
    assert [table.bundle_verdict([v]) for v in ("pass", "fail", "unresolved")] == ["pass", "fail", "unresolved"]


def test_filter_end_to_end_and_filter_json(run, tmp_path):
    out_path = tmp_path / "FILTER.json"
    # Chain pair 0: twin b right in O1 only (fail). Pair 1: twin b BLOCKED in O2 and O3 (unresolved). Count question
    # 0 at +500 in every trial (never a pass), question 1 right in two of three (kept).
    twins = {"O1": {(COUNT, 0, 0): 500}, "O2": {("drift-chain-fault-v2", 0, 1): 0, ("drift-chain-fault-v2", 1, 1): "B",
                                                 (COUNT, 0, 0): 500, (COUNT, 1, 0): 0},
             "O3": {("drift-chain-fault-v2", 0, 1): 0, ("drift-chain-fault-v2", 1, 1): "B", (COUNT, 0, 0): 500}}
    code, out = run(twins=twins, flags=("--after-reruns",), filter_out=out_path)
    lines = out.split("== 5.")[1].splitlines()
    chain = next(x for x in lines if x.startswith("  drift-chain-fault-v2:"))
    count = next(x for x in lines if x.startswith(f"  {COUNT}:"))
    assert code == 0 and "bundles 5 kept 3 dropped 1 unresolved 1" in chain
    assert "items by (passes, unscored) {(1, 0): 1, (1, 2): 1, (3, 0): 8}" in chain
    assert "bundles 5 kept 4 dropped 1 unresolved 0" in count
    data = json.loads(out_path.read_bytes())
    assert out_path.read_bytes() == table.canon(data)
    assert data["tasks_sha256"] == sha256((tmp_path / "TASKS.json").read_bytes()).hexdigest()
    assert data["o_outcomes_sha256"]["O2"] == sha256((tmp_path / "runs/O2/outcomes.json").read_bytes()).hexdigest()
    assert data["templates"][COUNT]["dropped"] == [dict(life=G2[0], bundle_id=None, item_ids=["ITEMZQ0c"])]
    assert data["templates"]["drift-chain-fault-v2"]["unresolved"] == [
        dict(life=G1[1], bundle_id="BUNDLEZQ10", item_ids=["ITEMZQ10a", "ITEMZQ10b"])]
    assert len(data["templates"]["drift-quote-v2"]["kept"]) == 5


# 2. Scores.
def test_scores_twin_min_halves_and_c(run):
    # R: chain pairs right, quote pairs -1000, count questions +500 (+0.5 kept). R1 config pair 0: twins +1000, -1000.
    code, out = run({"O3": {"drift-quote-v2": [0] * 5}}, twins={"R1": {("drift-config-v2", 0, 0): 1000,
                                                                        ("drift-config-v2", 0, 1): -1000}})
    three = out.split("== 3.")[1].split("== 4.")[0]
    r1 = three.split("-- R1")[1].split("-- R2")[0].splitlines()
    assert code == 0 and f"  {COUNT}: bundles 5 +1000 0 +500 5 0 0 -500 0 -1000 0 non_result 0 points 50 (50.0)" in r1
    assert "  drift-config-v2: bundles 5 +1000 0 +500 0 0 4 -500 0 -1000 1 non_result 0 points -20 (-20.0)" in r1
    count = section(out, COUNT)
    assert count[0] == f"-- {COUNT}: bundles 5 repeats used F1 F2 R1 R2 O1 O2 O3 f 0 (0.0) r 50 (50.0) c 100 (100.0)" \
                       " c over O1,O2,O3 100 (100.0)"
    # c is O1 and O2 only; O3 enters c over three.
    quote = section(out, "drift-quote-v2")
    assert "f 0 (0.0) r -100 (-100.0) c 100 (100.0) c over O1,O2,O3 200/3 (66.7)" in quote[0]
    assert "-- R mean of the repeats used for each template" in three
    assert "  drift-config-v2: repeats ['R1', 'R2'] points -10 (-10.0)" in three


def test_completeness_is_per_template(run):
    # F2 left one chain twin unscored after its rerun: the chain template is read without F2 and is unresolved, while
    # the other templates are read with F2.
    code, out = run(twins={"F2": {("drift-chain-fault-v2", 2, 0): "B"}}, specs={"F1": {"drift-chain-fault-v2":
                                                                                   [0, 0, 1000, 0, 0]},
                                                                            "F2": {"drift-config-v2": [1000] * 5}},
                    flags=("--after-reruns",))
    chain, config = section(out, "drift-chain-fault-v2"), section(out, "drift-config-v2")
    assert code == 0 and "bundles 5 repeats used F1 R1 R2 O1 O2 O3 f 20 (20.0)" in chain[0]
    assert "check 6 drift-chain-fault-v2: repeats used F1 R1 R2 O1 O2 O3; left out F2 (incomplete on this template)" \
        in out.splitlines()
    assert "  completeness: repeats left out F2 (incomplete on this template)" in chain
    assert reading_of(out, "drift-chain-fault-v2") == "unresolved"
    assert "bundles 5 repeats used F1 F2 R1 R2 O1 O2 O3 f 50 (50.0)" in config[0]
    assert "check 6 drift-config-v2: repeats used F1 F2 R1 R2 O1 O2 O3; left out none" in out.splitlines()
    assert reading_of(out, "drift-config-v2") == "cleared"
    # O2 left out of the count template: c is unavailable, and the low and near-solved lines say so.
    code, out = run(twins={"O2": {(COUNT, 1, 0): "B"}}, flags=("--after-reruns",))
    count = section(out, COUNT)
    assert code == 0 and count[1].startswith("  low (c < 75): on means n/a margin_bundles n/a; each O trial alone:")
    assert count[1].endswith("O1 no, O3 no; disagreeing with the means n/a (mean unavailable)")
    assert all("agreeing on whether it applies n/a (mean unavailable) (printed only" in x for x in count[2:4])
    assert reading_of(out, COUNT) == "unresolved" and reading_of(out, "drift-quote-v2") == "cleared"


# 3. Readings.
def test_readings_by_precedence(run):
    code, out = run()
    assert code == 0 and [reading_of(out, t) for t in TEMPLATES] == ["cleared"] * 3 + ["format validated"]
    # Naive retrieval near-solves the chain template: labelled and printed, never in the reading.
    chain = section(out, "drift-chain-fault-v2")
    assert any(x.startswith("  naive (near-solved by naive retrieval): on means applies") for x in chain)
    assert any(x.startswith("  labelled near-solved by naive retrieval:") for x in chain)
    o = {k: dict.fromkeys(TEMPLATES, v) for k, v in (("O1", [1000] * 3 + [0] * 2), ("O2", [1000] * 4 + [0]),
                                                    ("O3", [1000] * 5))}
    code, out = run(o)
    assert all(reading_of(out, t) == "unstable" for t in TEMPLATES)  # 60, 80, 100: c = 70 but O3 alone is not low
    low = section(out, COUNT)[1]
    assert "on means applies" in low and "O1 applies, O2 no, O3 no; disagreeing with the means 2" in low
    lows = {k: dict.fromkeys(TEMPLATES, [1000] * 3 + [0] * 2) for k in ("O1", "O2", "O3")}
    code, out = run(lows)
    assert [reading_of(out, t) for t in TEMPLATES] == ["low"] * 4
    # A count question unscored in O2 after the rerun: unresolved, before unstable and low.
    blocked = {"O2": {(COUNT, 3, 0): "B"}}
    for specs in (o, lows):
        code, out = run(specs, twins=blocked, flags=("--after-reruns",))
        assert code == 0 and reading_of(out, COUNT) == "unresolved"
        assert section(out, COUNT)[-2] == "  completeness: repeats left out O2 (incomplete on this template)"
    assert reading_of(out, "drift-quote-v2") == "low"


def test_count_question_is_never_cleared(run):
    assert reading_of(run()[1], COUNT) == "format validated"
    assert "cleared" not in "\n".join(section(run()[1], COUNT))


# 3b. Identity, and the round's end.
def test_reference_identity_and_ties():
    def arms(ids):
        return {k: dict(card=dict(served_identity=v)) for k, v in zip(ORDER, ids, strict=True)}

    # A, then B before C, three each: B, though A's arm ran first.
    assert table.reference_identity(arms("ABCBCBC"), ORDER) == "B"
    assert table.reference_identity(arms("ACBCBCB"), ORDER) == "C"
    assert table.reference_identity(arms("BAAABBC"), ORDER) == "B"
    assert table.reference_identity(arms("CAAABBC"), ORDER) == "A"
    # Run order, not label order, decides: a rerun listed last is the latest arm.
    late = (*ORDER[1:], "F1")
    assert table.reference_identity({k: dict(card=dict(served_identity=v)) for k, v in
                                     zip(late, "ACBCBCB", strict=True)}, late) == "C"


def test_tie_end_to_end_and_mismatched_o_arm_is_unscored(run):
    ids = dict(zip(ORDER, ("A", "B", "C", "B", "C", "B", "C"), strict=True))
    code, out = run(identities=ids)
    assert code == 4 and f"reference identity {table.short('B')}" in out
    assert out.splitlines()[-1].startswith("pending before any score: F1 R2 O1 O3 -")
    # O3 mismatched after its rerun: its trials are unscored in the filter.
    ids = dict.fromkeys(ORDER, "A") | {"O3": "Z"}
    twins = {"O2": {("drift-quote-v2", 0, 0): 0}}
    code, out = run(identities=ids, twins=twins, flags=("--after-reruns",))
    quote = next(x for x in out.split("== 5.")[1].splitlines() if x.startswith("  drift-quote-v2:"))
    assert code == 0 and "trials unscored for O3" in out and "kept 4 dropped 0 unresolved 1" in quote
    assert all(reading_of(out, t) == "unresolved" for t in TEMPLATES)
    assert "-- O3 (identity mismatch: not pooled)" in out.splitlines()


def test_identity_drift_or_no_record_is_a_mismatch(run):
    for change, said in ((lambda d: d["live"].update(identity_drift=dict(served="later")), "yes"),
                         (lambda d: d.pop("live"), "not recorded")):
        def edit(label, path, change=change):
            if label == "O2":
                edit_json(path / "disclosures.json", change)
        code, out = run(edit=edit)
        line = next(x for x in out.splitlines() if x.startswith("O2: tier"))
        assert code == 4 and line.endswith(f"matches_reference True identity changed during the run {said}")
        code, out = run(edit=edit, flags=("--after-reruns",))
        assert code == 0 and "trials unscored for O2" in out


def test_a_rerun_failing_check_7_again_ends_the_round(run):
    def cached(label, path):
        if label == "R2":
            edit_json(path / "card.json", lambda d: d["floor"]["units"][f"{G1[0]}/B0"].update(cached=True))

    late = (*(k for k in ORDER if k != "R2"), "R2")
    code, out = run(edit=cached, order=late, slots={"R2": 9}, flags=("--reruns", "R2"))
    assert code == 5 and "ROUND ENDS: R2 fails check 7 again after its rerun (§4); no score is opened" in out
    assert [x for x in out.splitlines() if x.startswith("reading ")] == [f"reading {t}: unresolved" for t in TEMPLATES]
    assert "missing observations: arms without usable trials R2" in out
    assert "== 3." not in out and "points" not in out and "== 5." not in out
    # The same fault on an arm not rerun is an ordinary invalid row.
    code, out = run(edit=cached)
    assert code == 3 and out.splitlines()[-1] == "INVALID CONTROL ROW R2"


# 4. Checks closed before scores.
def test_checks_1_2_7_close_scores(run):
    def one_byte(label, path):
        if label == "R1":
            edit_json(path / "control.json", lambda d: d["block_sha256"].update(
                {sorted(d["block_sha256"])[0]: "0" * 64}))

    def first_request(label, path):
        if label == "O2":
            p = path / "oracle_evidence" / G2[0] / "B0" / "t2lite_probes.json"
            edit_json(p, lambda d: d[0]["shadow"].update(in_context_initial=False))

    def cached(label, path):
        if label == "F2":
            edit_json(path / "disclosures.json", lambda d: d["floor"][f"{G2[1]}/B1"].update(cached=True))

    for edit, name, check in ((one_byte, "R1", "check 1 R1"), (first_request, "O2", "check 2 O2"),
                              (cached, "F2", "check 7 F2")):
        code, out = run(edit=edit)
        assert code == 3 and out.splitlines()[-1] == f"INVALID CONTROL ROW {name}"
        assert next(x for x in out.splitlines() if x.startswith(check)).endswith("pass False")
        assert "== 3." not in out and "points" not in out
    assert "check 2 O2: needed fact in the probe turn's first request on 34 of 35 target items" in run(
        edit=first_request)[1]
    code, out = run(check3=CHECK3_OK.replace("exit 0", "exit 1"))
    assert code == 3 and "== 3." not in out and out.splitlines()[-1].startswith("CHECK 3 NOT SHOWN PASSING")


def test_check_7_reads_each_units_own_probes(run):
    def filed_under_b0(label, path):
        if label == "O1":
            unit = path / "oracle_evidence" / G1[0]
            b0, b1 = (json.loads((unit / b / "t2lite_probes.json").read_text()) for b in ("B0", "B1"))
            (unit / "B0" / "t2lite_probes.json").write_text(json.dumps(b0 + b1))
            (unit / "B1" / "t2lite_probes.json").write_text("[]")

    clean = next(x for x in run()[1].splitlines() if x.startswith("check 7 O1"))
    assert "probe keys (life, branch, item) matching the pack's records 50 of 50 unexpected 0" in clean
    code, out = run(edit=filed_under_b0)
    line = next(x for x in out.splitlines() if x.startswith("check 7 O1"))
    assert code == 3 and "probe files found 20" in line and "probe records 50 sent to the live reader 50" in line
    assert "matching the pack's records 46 of 50 unexpected 4" in line and line.endswith("pass False")
    assert out.splitlines()[-1] == "INVALID CONTROL ROW O1"


def test_check_3_after_reruns_ends_the_round(run):
    bad = CHECK3_OK.replace("exit 0", "exit 1")
    code, out = run(check3=bad)
    assert code == 3 and out.splitlines()[-1].endswith("no score is opened; rerun check 3 at the run commit")
    code, out = run(check3=bad, flags=("--after-reruns",))
    assert code == 5 and "ROUND ENDS: check 3 is not shown passing at the run commit after the reruns (§4)" in out
    assert "missing observations: arms without usable trials F1 F2 R1 R2 O1 O2 O3" in out
    assert [x for x in out.splitlines() if x.startswith("reading ")] == [f"reading {t}: unresolved" for t in TEMPLATES]
    assert "== 3." not in out and "points" not in out
    # A named rerun failing check 7 again ends the round while check 3 has not been rerun: only that arm is listed.
    def cached(label, path):
        if label == "R2":
            edit_json(path / "card.json", lambda d: d["floor"]["units"][f"{G1[0]}/B0"].update(cached=True))

    late = (*(k for k in ORDER if k != "R2"), "R2")
    code, out = run(check3=bad, edit=cached, order=late, slots={"R2": 9}, flags=("--reruns", "R2"))
    assert code == 5 and ("ROUND ENDS: R2 fails check 7 again after its rerun; check 3 not shown passing (not yet"
                          " rerun) (§4); no score is opened") in out
    assert "missing observations: arms without usable trials R2" in out.splitlines()
    assert "after the reruns" not in out and "== 3." not in out


def test_check_2_r_reads_the_target_items_against_the_scripted_report(run):
    def flip(label, path):
        if label == "R1":
            p = path / "naive_rag" / G1[0] / "B1" / "t2lite_probes.json"
            edit_json(p, lambda d: d[0]["shadow"].update(in_context_initial=not d[0]["shadow"]["in_context_initial"]))
    code, out = run(edit=flip)
    assert code == 3 and "check 2 R1: presence in the probe turn's first request equals the pack's scripted naive" \
        " report on 34 of 35 target items pass False" in out


def test_checks_4_and_5_need_after_reruns(run):
    code, out = run(twins={"O1": {(COUNT, 0, 0): "B"}})
    assert code == 4 and "== 3." not in out and out.splitlines()[-1].startswith("pending before any score: O1 -")
    assert "check 5 O1: target items 35 scored 34 BLOCKED 1 missing 0 complete False" in out
    code, out = run(identities={"F2": "other"})
    assert code == 4 and out.splitlines()[-1].startswith("pending before any score: F2 -")
    code, out = run(flags=("--checks-only",))
    assert code == 0 and "== 2." in out and "== 3." not in out


def test_run_order(run):
    code, out = run()
    assert code == 0 and "run order verified" in out.splitlines()
    assert "equals the declared order True | reruns named none" in out
    m1_order = ("F1", "R1", "O1", "O2", "R2", "O3", "F2")
    code, out = run(order=m1_order, slots={"O3": 5, "F2": 6})
    assert code == 3 and "RUN ORDER VIOLATION: the order listed is not the declared order" in out.splitlines()
    late = (*(k for k in ORDER if k != "R1"), "R1")
    code, out = run(order=late, slots={"R1": 9}, flags=("--reruns", "R1"))
    assert code == 0 and "run order verified" in out.splitlines()
    code, out = run(slots={"O2": 6, "O3": 3})
    assert code == 3 and "RUN ORDER VIOLATION: R2 starts before O2 ends" in out.splitlines()



def test_row_centres_in_the_order_the_arms_ran(run):
    def centres(out):
        return next(x for x in out.splitlines() if x.startswith("row centres"))

    code, out = run()
    assert code == 0 and centres(out).endswith("(positions 1-7) F 7/2 (3.5) R 7/2 (3.5) O 7/2 (3.5); O3 at 7"
                                               " (declared order: each centre 7/2)")
    # O1's first attempt ran in its slot (3rd); its rerun ran last, the 8th arm: O's centre is (4 + 8) / 2 = 6.
    late = (*(k for k in ORDER if k != "O1"), "O1")
    code, out = run(order=late, slots={"O1": 9}, flags=("--reruns", "O1"), attempts=(*ORDER, "O1.rerun"))
    assert code == 0 and centres(out).endswith("(positions 1-8) F 7/2 (3.5) R 7/2 (3.5) O 6 (6.0); O3 at 7"
                                               " (declared order: each centre 7/2)")
    # Two reruns after O3: R1 is 8th and O3 9th.
    two = ("F1", "O1", "O2", "R2", "F2", "R1", "O3")
    code, out = run(order=two, slots={"R1": 9, "O3": 10}, flags=("--reruns", "R1,O3"),
                    attempts=(*ORDER, "R1.rerun", "O3.rerun"))
    assert code == 0 and centres(out).endswith("(positions 1-9) F 7/2 (3.5) R 13/2 (6.5) O 7/2 (3.5); O3 at 9"
                                               " (declared order: each centre 7/2)")
    # A rerun run straight after its own first attempt.
    code, out = run(flags=("--reruns", "R1"), attempts=("F1", "R1", "R1.rerun", *ORDER[2:]))
    assert code == 0 and centres(out).endswith("(positions 1-8) F 4 (4.0) R 9/2 (4.5) O 9/2 (4.5); O3 at 8"
                                               " (declared order: each centre 7/2)")
    # Reruns named and no --attempts: not computed, never guessed.
    code, out = run(order=late, slots={"O1": 9}, flags=("--reruns", "O1"))
    assert code == 0 and centres(out) == "row centres in the order the arms actually ran: not computed (pass --attempts)"
    # An --attempts that does not fit: refused.
    for attempts, reruns, order in (((*ORDER, "O1.rerun"), "O1", ORDER), ((*ORDER, "O1.rerun"), "O3", late),
                                    (("O1.rerun", *ORDER), "O1", late), ((*ORDER, "O1.rerun", "X"), "O1", late),
                                    (ORDER[:-1] + ("O1.rerun",), "O1", late),
                                    (("R1", "F1", "R1.rerun", *ORDER[2:]), "R1", ORDER)):
        code, out = run(order=order, slots={"O1": 9}, flags=("--reruns", reruns), attempts=attempts)
        assert code == 3 and out.startswith("REFUSED: --attempts") and "== 1." not in out


# 5. Refusals.
def test_refusals(run, tmp_path):
    def no_control(label, path):
        if label == "O3":
            (path / "control.json").unlink()

    def other_control(label, path):
        if label == "R1":
            edit_json(path / "control.json", lambda d: d.update(arm="oracle_evidence"))

    def other_pack(label, path):
        if label == "F1":
            edit_json(path / "card.json", lambda d: d.update(pack_hash="e" * 64))

    assert run(edit=no_control) == (3, "REFUSED: O3 has no control.json (control rows only, §2)\n")
    assert run(edit=other_control) == (3, "REFUSED: R1's control is not naive_rag\n")
    assert run(tasks_sha="0" * 64) == (3, "REFUSED: TASKS.json sha256 differs from --tasks-sha256\n")
    code, out = run(edit=other_pack)
    assert code == 3 and "PACK MISMATCH: F1 pack_hash eeeeeeeeeeee" in out and "== 3." not in out


def test_run_commit_edition_and_the_frozen_list_both_ways(run, tmp_path):
    def other_commit(label, path):
        if label == "O2":
            edit_json(path / "card.json", lambda d: d["pins"].update(benchmark_commit="d" * 40))

    assert run(edit=other_commit) == (3, "REFUSED: O2 ran at another commit than TASKS.json names\n")
    path = tmp_path / "TASKS.json"
    whole = json.loads(path.read_bytes())
    # A list missing one count question, posted with its own sha256: refused, so no check can go vacuous.
    path.write_bytes(table.canon(dict(whole, rows=[r for r in whole["rows"] if r["item_id"] != "ITEMZQ2c"])))
    assert run() == (3, "REFUSED: TASKS.json rows differ from the pack's own target items (tasks.py)\n")
    path.write_bytes(table.canon(dict(whole, rows=[])))
    assert run() == (3, "REFUSED: TASKS.json rows differ from the pack's own target items (tasks.py)\n")
    path.write_bytes(table.canon(dict(whole, header=dict(whole["header"], edition=1))))
    assert run() == (3, "REFUSED: TASKS.json edition is not 2\n")
    path.write_bytes(table.canon(whole))
    assert run()[0] == 0


def test_tasks_pack_hash_and_absent_items_are_refused(tmp_path, packs, capsys, monkeypatch):
    code, path = make_tasks(tmp_path, packs)
    capsys.readouterr()
    sha = sha256(path.read_bytes()).hexdigest()
    base = ["--tasks", str(path), "--tasks-sha256", sha, "--order", ",".join(ORDER),
            *(f"{k}={tmp_path / k}" for k in table.CORE)]
    (packs / "extra.txt").write_text("x")
    assert table.main(["--packs", str(packs), *base]) == 3
    assert capsys.readouterr().out == "REFUSED: TASKS.json pack hash differs from the --packs tree hash\n"
    (packs / "extra.txt").unlink()
    data = json.loads(path.read_bytes())
    data["rows"][0]["item_id"] = "ITEMZQother"
    path.write_bytes(table.canon(data))
    monkeypatch.setattr(table, "pack_tree_hash", lambda p: data["header"]["pack_hash"])
    base[3] = sha256(path.read_bytes()).hexdigest()
    assert table.main(["--packs", str(packs), *base]) == 3
    assert capsys.readouterr().out == "REFUSED: 1 target items of TASKS.json are absent from the pack\n"


# 6. tasks.py.
def test_tasks_list_counts_sorted_and_hash(tmp_path, packs, capsys):
    code, path = make_tasks(tmp_path, packs)
    out = capsys.readouterr().out
    data = json.loads(path.read_bytes())
    assert code == 0 and path.read_bytes() == table.canon(data)
    assert out.splitlines()[-1].endswith(f"tasks sha256 {sha256(path.read_bytes()).hexdigest()}")
    assert out.splitlines()[0] == ("target items 35 {'drift-chain-fault-v2': 10, 'drift-config-v2': 10,"
                                   " 'drift-quote-v2': 10, 'recall-count-v2': 5}")
    rows = data["rows"]
    assert rows == sorted(rows, key=lambda r: (r["life"], r["branch"], r["item_id"])) and len(rows) == 35
    assert data["header"] == dict(commit="b" * 40, edition=2, spec_sha256=sha256(b"seed = 1").hexdigest(),
                                  draw_sha256=sha256(b"[1, 2]").hexdigest(), pack_hash=table.pack_tree_hash(packs))
    assert {r["decision_table_ref"] for r in rows} == {COUNT, "drift-chain-fault-v2", "drift-config-corrected-v2",
                                                       "drift-config-hedged-v2", "drift-quote-v2"}
    assert all((r["bundle_id"] is None) == (r["template_ref"] == COUNT) for r in rows)
    assert not [n for n in ("ITEMZQ", "BUNDLEZQ", "LIFEZQ", str(tmp_path)) if n in out]


@pytest.mark.parametrize("edit, said", [
    (lambda r: False if r["item_id"] == "ITEMZQ2c" else None, "count questions 4 over 5 G2 lives"),
    (lambda r: False if r["item_id"].startswith("ITEMZQ31") else None, "action tasks 28 in 14 pairs over 5 G1 lives"),
    (lambda r: False if r["life"] == G1[4] else None, "action tasks 24 in 12 pairs over 4 G1 lives"),
    (lambda r: r.update(template_version=1) if r["item_id"] == "ITEMZQ02a" else None,
     "the pack carries drift-quote-v1, not the v2 template"),
    (lambda r: r.update(template_id="recall-count", template_version=1, bundle_id=None)
     if r["item_id"] == "ITEMZQ0s" else None, "the pack carries recall-count-v1, not the v2 template"),
    (lambda r: r.update(life=G1[0]) if r["life"] == G2[0] else None, "1 lives are both G1 and G2"),
])
def test_tasks_refusals(tmp_path, capsys, edit, said):
    packs = make_packs(tmp_path / "other", edit=edit)
    code, path = make_tasks(tmp_path, packs)
    assert code == 3 and not path.exists() and capsys.readouterr().out.startswith(f"REFUSED: {said}")


def test_tasks_refuses_a_v1_decision_table(tmp_path, capsys, packs):
    sealed = packs / "pack" / "G1" / G1[0] / "7" / "sealed"
    edit_json(sealed / "pack.json", lambda d: d["items"][0].update(decision_table_ref="drift-chain-fault-v1"))
    code, _ = make_tasks(tmp_path, packs)
    assert code == 3 and "not a G1 twin with a v2 decision table" in capsys.readouterr().out


def test_tasks_refuses_a_count_item_with_the_v1_table(tmp_path, capsys, packs):
    sealed = packs / "pack" / "G2" / G2[0] / "7" / "sealed"
    edit_json(sealed / "pack.json", lambda d: d["items"][0].update(decision_table_ref="recall-count-v1"))
    code, _ = make_tasks(tmp_path, packs)
    assert code == 3 and "REFUSED: a recall-count-v2 item is not a single G2 question on B0 with the v2 table" \
        in capsys.readouterr().out


@pytest.mark.parametrize("item, table_ref", [("ITEMZQ01b", "drift-config-corrected-v2"),
                                              ("ITEMZQ01a", "drift-config-hedged-v2")])
def test_tasks_needs_one_corrected_and_one_hedged_table_per_config_pair(tmp_path, capsys, packs, item, table_ref):
    sealed = packs / "pack" / "G1" / G1[0] / "7" / "sealed"
    edit_json(sealed / "pack.json", lambda d: next(i for i in d["items"] if i["item_id"] == item).update(
        decision_table_ref=table_ref))
    code, _ = make_tasks(tmp_path, packs)
    assert code == 3 and capsys.readouterr().out == ("REFUSED: a drift-config-v2 pair does not carry one corrected and"
                                                     " one hedged table\n")


# Review fixes on the reading script.
def test_each_control_is_replayed_once(run, monkeypatch):
    calls = []
    monkeypatch.setattr(table, "recompute_blocks", lambda packs, control: calls.append(control) or block_hashes())
    assert run()[0] == 0 and sorted(calls) == ["naive_rag", "oracle_evidence"]


def test_check_7_refuses_a_duplicated_probe_record(run):
    def duplicate(label, path):
        if label == "O1":
            edit_json(path / "oracle_evidence" / G1[0] / "B0" / "t2lite_probes.json", lambda d: d.append(d[0]))

    assert "unexpected 0 duplicated 0 probe records 50" in next(
        x for x in run()[1].splitlines() if x.startswith("check 7 O1"))
    code, out = run(edit=duplicate)
    line = next(x for x in out.splitlines() if x.startswith("check 7 O1"))
    assert code == 3 and "unexpected 0 duplicated 1 probe records 51" in line and line.endswith("pass False")


def test_round_end_counts_arms_incomplete_on_a_template(run):
    def cached(label, path):
        if label == "R2":
            edit_json(path / "card.json", lambda d: d["floor"]["units"][f"{G1[0]}/B0"].update(cached=True))

    late = (*(k for k in ORDER if k != "R2"), "R2")
    code, out = run(edit=cached, order=late, slots={"R2": 9}, flags=("--reruns", "R2"), twins={"F2": {(COUNT, 0, 0): "B"}})
    assert code == 5 and f"  {COUNT}: target items 5, each without a usable trial in 2 of 7 arms (F2 R2)" in out
    assert "  drift-quote-v2: target items 10, each without a usable trial in 1 of 7 arms (R2)" in out.splitlines()


def test_section_1_names_the_code(run):
    _, out = run()
    for name, path in table.CODE.items():
        assert f"code {name} sha256 {sha256(path.read_bytes()).hexdigest()[:12]}" in out.splitlines()
    assert not [x for x in out.splitlines() if x.startswith("code ") and "/" in x]


def pack_refusal(tmp_path, packs, capsys, monkeypatch, change):
    code, path = make_tasks(tmp_path, packs)
    capsys.readouterr()
    header = json.loads(path.read_bytes())["header"]
    change(packs)
    monkeypatch.setattr(table, "pack_tree_hash", lambda p: header["pack_hash"])
    code = table.main(["--packs", str(packs), "--tasks", str(path), "--tasks-sha256",
                       sha256(path.read_bytes()).hexdigest(), "--order", ",".join(ORDER),
                       *(f"{k}={tmp_path / k}" for k in table.CORE)])
    return code, capsys.readouterr().out


def test_a_pack_breaking_tasks_rule_refuses_with_its_reason(tmp_path, packs, capsys, monkeypatch):
    def extra_v1(packs):
        sealed = packs / "pack" / "G2" / G2[0] / "7" / "sealed"
        edit_json(sealed / "records.json", lambda d: d.append(dict(template_id="recall-count", template_version=1,
                                                                   life=G2[0], branch="B0", item_id="ITEMZQx",
                                                                   bundle_id=None)))
        edit_json(sealed / "pack.json", lambda d: d["items"].append(dict(item_id="ITEMZQx",
                                                                         decision_table_ref="recall-count-v1")))
    assert pack_refusal(tmp_path, packs, capsys, monkeypatch, extra_v1) == (
        3, "REFUSED: the pack breaks the frozen list's rule (tasks.py): the pack carries recall-count-v1, not the v2"
           " template\n")


def test_records_naming_two_lives_refuse(tmp_path, packs, capsys, monkeypatch):
    def two_lives(packs):
        edit_json(packs / "pack" / "G1" / G1[0] / "7" / "sealed" / "records.json",
                  lambda d: next(r for r in d if r["item_id"] == "ITEMZQ0wa").update(life=G1[1]))
    assert pack_refusal(tmp_path, packs, capsys, monkeypatch, two_lives) == (
        3, "REFUSED: a sealed life's records do not name exactly one life\n")


# 7. No ids, text or paths.
def test_no_ids_text_or_paths(run, tmp_path):
    for kwargs in (dict(), dict(twins={"O1": {(COUNT, 1, 0): "B"}}, flags=("--after-reruns",),
                                filter_out=tmp_path / "FILTER.json"),
                   dict(edit=lambda label, path: label == "R2" and edit_json(
                       path / "card.json", lambda d: d["floor"]["units"][f"{G1[0]}/B0"].update(cached=True)),
                        order=(*(k for k in ORDER if k != "R2"), "R2"), slots={"R2": 9}, flags=("--reruns", "R2"))):
        code, out = run(**kwargs)
        assert code in (0, 5)
        needles = [*G1, *G2, IDENTITY, "control text", str(tmp_path), "ITEMZQ", "BUNDLEZQ", "LIFEZQ",
                   *block_hashes().values()]
        assert not [n for n in needles if n in out]
