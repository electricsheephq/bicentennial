"""Synthetic fixture tests for validity round 2 (results/validity-2/DECLARATION.md §3-§5).

Run directly: PYTHONPATH=<checkout>/src python -m pytest results/validity-2/control-trials/test_table.py
(not in CI's testpaths). Ten synthetic G1 lives hold one pair of each of the four target templates, plus a
non-target v1 pair. Scripted report/score and payload boundaries are replaced with deterministic fixture outputs;
no live reader, network or sockets. The loader recipe and the real anchor identities/test ids are checked too.
"""

import importlib.util
import json
import subprocess
import sys
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import table  # noqa: E402
import tasks  # noqa: E402

G1 = tuple(f"LIFEZQG1{c}" for c in "ABCDEFGHIJ")
ACTION = {"drift-chain-fault-v3": ("drift-chain-fault-v3", "drift-chain-fault-v3"),
          "drift-config-v3": ("drift-config-corrected-v3", "drift-config-hedged-v3"),
          "drift-quote-v3": ("drift-quote-v3", "drift-quote-v3"), "wake-loop-v1": ("wake-loop-v1", "wake-loop-v1")}
TEMPLATES = tuple(ACTION)
CHAIN, CONFIG, QUOTE, WAKE = TEMPLATES
IDENTITY = "identity-zq-served-value"
ORDER = ("F1", "R1", "B1", "G1", "W1", "O1", "O2", "W2", "G2", "B2", "R2", "F2", "O3")
BASE = {row: dict.fromkeys(TEMPLATES, [1000 if row == "O" else 0] * 10) for row in table.ROWS}
SCRIPTED = {"naive_rag": 1000, "bm25": -1000, "grep": 0, "recent_window": 1000}
CHECK3_OK = "\n".join([f"commit {'b' * 40}", *(f"tests/runner/test_control_arms.py::{t} PASSED [{n}%]"
                                              for n, t in enumerate(table.CHECK3_TESTS, 1)),
                       "15 passed in 1.00s", "exit 0"])


def layout():
    """Round 1's layout shape, with four target action pairs on each of ten G1 lives."""
    out = []
    for n, life in enumerate(G1):
        for j, ref in enumerate(ACTION):
            out.append((life, ref, n, f"BUNDLEZQ{n}{j}",
                        [("B0", f"ITEMZQ{n}{j}a", ACTION[ref][0]), ("B1", f"ITEMZQ{n}{j}b", ACTION[ref][1])], True))
        out.append((life, "drift-chain-v1", n, f"BUNDLEZQ{n}x",
                    [("B0", f"ITEMZQ{n}xa", "drift-chain-v1"), ("B1", f"ITEMZQ{n}xb", "drift-chain-v1")], False))
    return out


def in_report(ref, control="naive_rag"):
    return (ref == CHAIN) if control in ("naive_rag", "grep") else (ref == WAKE)


def scripted_arm(life, control):
    return dict(reports=[dict(item_id=iid, in_context=in_report(ref, control))
                         for owner, ref, _, _, members, _ in layout() if owner == life for _, iid, _ in members],
                items=[dict(item_id=iid, score_milli=SCRIPTED[control], failure_class=None)
                       for owner, _, _, _, members, _ in layout() if owner == life for _, iid, _ in members])


def fake_anchor(inp, cls, *, score):
    assert score == {"synthetic_scoring": True}
    control = next(name for name, factory in table.ANCHORS.items() if factory is cls)
    return scripted_arm(inp.parent.name, control)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def make_packs(root, edit=None):
    """edit(record) may change a record before it is written, or return False to drop it."""
    for life in G1:
        mine = [x for x in layout() if x[0] == life]
        records, items = [], []
        for _, ref, _, bundle, members, _ in mine:
            tid, version = ref.rsplit("-v", 1)
            for branch, iid, tab in members:
                rec = dict(template_id=tid, template_version=int(version), life=life, branch=branch,
                           item_id=iid, bundle_id=bundle)
                if edit and edit(rec) is False:
                    continue
                records.append(rec)
                items.append(dict(item_id=iid, decision_table_ref=tab))
        sealed = root / "pack" / "G1" / life / "7" / "sealed"
        write(sealed / "pack.json", dict(genre="G1", items=items, private="task text ZQ"))
        write(sealed / "records.json", records)
        write(sealed / "naive_rag.json", dict(arm=scripted_arm(life, "naive_rag")))
        write(sealed / "scoring.json", {"synthetic_scoring": True})
    write(root / "index.json", dict(packs={}))
    return root


def make_tasks(tmp_path, packs, edit=None, name="TASKS.json"):
    out = tmp_path / name
    code = tasks.main(["--packs", str(packs), "--spec", str(write_file(tmp_path / "spec.toml", "seed = 1")),
                       "--draw", str(write_file(tmp_path / "draw.json", "[1, 2]")), "--commit", "b" * 40,
                       "--edition", "3", "--out", str(out)])
    return code, out


def write_file(path, text):
    path.write_text(text)
    return path


def block_hashes():
    return {f"{life}/{branch}/{iid}": sha256(f"control text for {iid}".encode()).hexdigest()
            for life, _, _, _, members, _ in layout() for branch, iid, _ in members}


def make_arm(path, label, spec, twins=None, slot=0, pack_hash="p" * 64, identity=IDENTITY):
    """spec: template_ref -> ten bundle scores by life; twins: {(template_ref, index, twin): score} overrides."""
    letter, out = label[0], {}
    for life, ref, n, _, members, target in layout():
        for t, (branch, iid, _) in enumerate(members):
            score = (twins or {}).get((ref, n, t), spec[ref][n]) if target else 0
            blocked = score == "B"
            out[f"{life}/{branch}/{iid}"] = dict(score_milli=None if blocked else score,
                                                 failure_class="BLOCKED" if blocked else None, stage="act")
    units = {f"{life}/{b}": dict(cache_key="k", cached=False) for life in G1 for b in ("B0", "B1")}
    write(path / "card.json", dict(tier="T2", model="m", effort="medium", pack_hash=pack_hash,
                                   pins=dict(scorer_commit="c" * 40, benchmark_commit="b" * 40),
                                   served_identity=identity, floor=dict(units=units)))
    write(path / "outcomes.json", out)
    start = 1793796303380 + slot * 10_000_000
    write(path / "units.json", dict(start_ms=start, end_ms=start + 6_000_000))
    write(path / "disclosures.json", dict(floor={u: dict(cached=False) for u in units}, live=dict(identity_drift=None)))
    arm = table.CONTROL[letter]
    presence = {f"{life}/{b}/{iid}": (letter == "O" or letter in table.ANCHOR_ROWS and in_report(ref, table.CONTROL[letter]))
                for life, ref, _, _, members, _ in layout() for b, iid, _ in members}
    for unit in units:
        life, branch = unit.split("/")
        write(path / arm / life / branch / "t2lite_probes.json", [
            dict(item_id=k.split("/", 2)[2], live=dict(served_by="live"), shadow=dict(in_context_initial=v))
            for k, v in presence.items() if k.startswith(f"{unit}/")])
    write(path / f"{arm}.json", {unit: dict(stops={unit.replace("/", ""): None}) for unit in units})
    metadata = {}
    if arm in table.ANCHORS:
        metadata["anchor"] = table.card_anchors()[arm]
    if letter in ("G", "W"):
        metadata["reader_window"] = 32768
    write(path / "control.json", dict(arm=arm, frame_sha256=None if letter == "F" else "f" * 64,
                                      block_sha256={} if letter == "F" else block_hashes(), **metadata))
    write(path / "receipt.json", dict(tokens_by_role=[dict(role="summariser", input=0, output=0),
                                                      dict(role="main", input=100, output=20)]))
    return path


@pytest.fixture(autouse=True)
def offline_scripted(monkeypatch):
    monkeypatch.setattr(table, "control_input", lambda path: path)
    monkeypatch.setattr(table, "make_score", lambda obj: obj)
    monkeypatch.setattr(table, "run_anchor", fake_anchor)


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


# 1. Round 1's twin filter, scoring and completeness, adapted to all-action targets.
def test_filter_item_rule_on_every_combination():
    for combo in product((1000, 0, -1000, None), repeat=3):
        trials = [{} if v is None else {"k": dict(score_milli=v)} for v in combo]
        passes, unknown = combo.count(1000), combo.count(None)
        want = "pass" if passes >= 2 else "fail" if passes + unknown < 2 else "unresolved"
        assert table.twin(trials, "k") == ((passes, unknown), want)
    for verdicts in product(("pass", "fail", "unresolved"), repeat=2):
        want = "pass" if verdicts == ("pass", "pass") else "fail" if "fail" in verdicts else "unresolved"
        assert table.bundle_verdict(list(verdicts)) == want


def test_filter_end_to_end_and_filter_json(run, tmp_path):
    out_path = tmp_path / "FILTER.json"
    twins = {"O2": {(CHAIN, 0, 1): 0, (CHAIN, 1, 1): "B"},
             "O3": {(CHAIN, 0, 1): 0, (CHAIN, 1, 1): "B"}}
    code, out = run(twins=twins, flags=("--after-reruns",), filter_out=out_path)
    chain = next(x for x in out.split("== 5.")[1].splitlines() if x.startswith(f"  {CHAIN}:"))
    assert code == 0 and "bundles 10 kept 8 dropped 1 unresolved 1" in chain
    assert "items by (passes, unscored) {(1, 0): 1, (1, 2): 1, (3, 0): 18}" in chain
    data = json.loads(out_path.read_bytes())
    assert out_path.read_bytes() == table.canon(data)
    assert data["tasks_sha256"] == sha256((tmp_path / "TASKS.json").read_bytes()).hexdigest()
    assert data["o_outcomes_sha256"]["O2"] == sha256((tmp_path / "runs/O2/outcomes.json").read_bytes()).hexdigest()
    assert data["templates"][CHAIN]["unresolved"] == [
        dict(life=G1[1], bundle_id="BUNDLEZQ10", item_ids=["ITEMZQ10a", "ITEMZQ10b"])]
    assert len(data["templates"][WAKE]["kept"]) == 10


def test_scores_twin_min_and_c(run):
    code, out = run({"O3": {QUOTE: [0] * 10}}, twins={"R1": {(CONFIG, 0, 0): 1000, (CONFIG, 0, 1): -1000}})
    three = out.split("== 3.")[1].split("== 4.")[0]
    r1 = three.split("-- R1\n")[1].split("-- R2\n")[0].splitlines()
    assert code == 0 and f"  {CONFIG}: bundles 10 +1000 0 0 9 -1000 1 non_result 0 points -10 (-10.0)" in r1
    assert "c 100 (100.0) c over O1,O2,O3 200/3 (66.7)" in section(out, QUOTE)[0]
    assert f"  {CONFIG}: repeats ['R1', 'R2'] points -5 (-5.0)" in three
    assert "+500" not in out and "-500" not in out and "format validated" not in out


def test_completeness_is_per_template(run):
    code, out = run(twins={"F2": {(CHAIN, 2, 0): "B"}}, specs={"F1": {CHAIN: [1000] * 2 + [0] * 8}},
                    flags=("--after-reruns",))
    assert code == 0 and "f 20 (20.0)" in section(out, CHAIN)[0]
    assert reading_of(out, CHAIN) == "unresolved"
    assert all(reading_of(out, t) == "ranking candidate" for t in (CONFIG, QUOTE, WAKE))
    assert "F2 (incomplete on this template)" in out
    code, out = run(twins={"O2": {(WAKE, 1, 0): "B"}}, flags=("--after-reruns",))
    wake = section(out, WAKE)
    assert code == 0 and "on means n/a margin_bundles n/a" in wake[1]
    assert all("mean unavailable" in x for x in wake[2:7])
    assert reading_of(out, WAKE) == "unresolved"


# 2. Round 2 readings: low stability still precedes the five ranking flags.
def test_readings_by_precedence(run):
    code, out = run()
    assert code == 0 and [reading_of(out, t) for t in TEMPLATES] == ["ranking candidate"] * 4
    unstable = {k: dict.fromkeys(TEMPLATES, v) for k, v in (
        ("O1", [1000] * 6 + [0] * 4), ("O2", [1000] * 8 + [0] * 2), ("O3", [1000] * 10))}
    code, out = run(unstable)
    assert code == 0 and all(reading_of(out, t) == "unstable" for t in TEMPLATES)
    assert "O1 applies, O2 no, O3 no; disagreeing with the means 2" in section(out, WAKE)[1]
    lows = {k: dict.fromkeys(TEMPLATES, [1000] * 6 + [0] * 4) for k in ("O1", "O2", "O3")}
    assert all(reading_of(run(lows)[1], t) == "low" for t in TEMPLATES)
    for specs in (unstable, lows):
        code, out = run(specs, twins={"O2": {(WAKE, 3, 0): "B"}}, flags=("--after-reruns",))
        assert code == 0 and reading_of(out, WAKE) == "unresolved"


@pytest.mark.parametrize("row", ("R", "B", "G", "W"))
def test_each_anchor_at_40_prevents_a_candidate(run, row):
    # At the threshold: two repeats at 30 and 40 average 35; every combination remains below near-solved.
    specs = {f"{row}{n}": {CHAIN: [1000] * k + [0] * (10 - k)} for n, k in ((1, 3), (2, 4))}
    assert reading_of(run(specs)[1], CHAIN) == "ranking candidate"
    specs[f"{row}1"][CHAIN] = [1000] * 4 + [0] * 6
    assert reading_of(run(specs)[1], CHAIN) == "cleared"


@pytest.mark.parametrize("row", ("R", "B", "G", "W"))
def test_one_combination_flag_prevents_a_candidate(run, row):
    # f=-20, x means=-25, c=95: all mean flags say no and best anchor=0.
    # Only F1=-100 x X1=30 x O3=80 applies: threshold 26. Other 11 combinations say no.
    specs = {"F1": {CHAIN: [-1000] * 10}, "F2": {CHAIN: [1000] * 6 + [0] * 4},
             f"{row}1": {CHAIN: [1000] * 3 + [0] * 7},
             f"{row}2": {CHAIN: [-1000] * 8 + [0] * 2},
             "O2": {CHAIN: [1000] * 9 + [0]}, "O3": {CHAIN: [1000] * 8 + [0] * 2}}
    code, out = run(specs)
    assert code == 0 and reading_of(out, CHAIN) == "cleared"
    flag = next(x for x in section(out, CHAIN) if x.startswith(f"  {row.lower()} ("))
    assert "on means no" in flag and "combinations 12 agreeing with the means 11 unstable" in flag


def test_uninterpreted_and_floor_flags_prevent_a_candidate(run):
    specs = {k: {CHAIN: [1000] * 10} for k in ("F1", "F2")}
    code, out = run(specs)
    assert code == 0 and reading_of(out, CHAIN) == "cleared"
    assert all("on means not interpreted" in x for x in section(out, CHAIN)[2:7])
    specs = {k: {CHAIN: [1000] * 7 + [0] * 3} for k in ("F1", "F2")}
    _, out = run(specs)
    assert reading_of(out, CHAIN) == "cleared" and "labelled near-solved without memory" in out
    # A not-interpreted combination is distinct from no, even though neither applies.
    specs = {"F1": {CHAIN: [1000] * 10}, "F2": {CHAIN: [-1000] * 10}}
    _, out = run(specs)
    assert reading_of(out, CHAIN) == "cleared"
    assert any("on means no" in x and "6 unstable" in x for x in section(out, CHAIN)[2:6])


def test_flags_and_stability_print_for_every_template(run):
    _, out = run()
    for template in TEMPLATES:
        flags = section(out, template)[2:7]
        assert len(flags) == 5
        for row, name in (*table.ANCHOR_ROWS.items(), ("F", "without memory")):
            flag = next(x for x in flags if x.startswith(f"  {row.lower()} ("))
            assert name in flag and "on means no" in flag
            assert f"combinations {6 if row == 'F' else 12} agreeing with the means" in flag
            assert "stable" in flag


# 3. Identity, check failures, one-rerun rule, and the round's end (round 1's behavior).
def test_reference_identity_and_ties():
    def arms(ids):
        return {k: dict(card=dict(served_identity=v)) for k, v in zip(ORDER, ids, strict=True)}

    assert table.reference_identity(arms("ABCBCBCBCBCBC"), ORDER) == "B"
    assert table.reference_identity(arms("ACBCBCBCBCBCB"), ORDER) == "C"
    late = (*ORDER[1:], "F1")
    assert table.reference_identity(arms("ABCBCBCBCBCBC"), late) == "B"


def test_tie_end_to_end_and_mismatched_o_arm_is_unscored(run):
    ids = dict(zip(ORDER, "ABCBCBCBCBCBC", strict=True))
    code, out = run(identities=ids)
    assert code == 4 and f"reference identity {table.short('B')}" in out
    assert "pending before any score: F1 R2 B1 G2 W1 O2 O3 - rerun once" in out
    code, out = run(identities=dict.fromkeys(ORDER, "A") | {"O3": "Z"},
                    twins={"O2": {(QUOTE, 0, 0): 0}}, flags=("--after-reruns",))
    quote = next(x for x in out.split("== 5.")[1].splitlines() if x.startswith(f"  {QUOTE}:"))
    assert code == 0 and "trials unscored for O3" in out and "kept 9 dropped 0 unresolved 1" in quote
    assert all(reading_of(out, t) == "unresolved" for t in TEMPLATES)
    assert "-- O3 (identity mismatch: not pooled)" in out.splitlines()


@pytest.mark.parametrize("change,said", [
    (lambda d: d["live"].update(identity_drift=dict(served="later")), "yes"),
    (lambda d: d.pop("live"), "not recorded"),
])
def test_identity_drift_or_no_record_is_a_mismatch(run, change, said):
    def edit(label, path):
        if label == "O2":
            edit_json(path / "disclosures.json", change)
    code, out = run(edit=edit)
    assert code == 4 and f"matches_reference True identity changed during the run {said}" in out
    code, out = run(edit=edit, flags=("--after-reruns",))
    assert code == 0 and "trials unscored for O2" in out


def cached(label, path):
    if label == "R2":
        edit_json(path / "card.json", lambda d: d["floor"]["units"][f"{G1[0]}/B0"].update(cached=True))


def test_a_rerun_failing_check_7_again_ends_the_round(run):
    late = (*(k for k in ORDER if k != "R2"), "R2")
    code, out = run(edit=cached, order=late, slots={"R2": 15}, flags=("--reruns", "R2"))
    assert code == 5 and "ROUND ENDS: R2 fails check 7 again after its rerun (§4); no score is opened" in out
    assert [x for x in out.splitlines() if x.startswith("reading ")] == [f"reading {t}: unresolved" for t in TEMPLATES]
    assert "missing observations: arms without usable trials R2" in out
    assert "== 3." not in out and "points" not in out
    assert run(edit=cached)[0] == 3


def test_checks_1_2_7_close_scores(run):
    def one_byte(label, path):
        if label == "R1":
            edit_json(path / "control.json", lambda d: d["block_sha256"].update(
                {sorted(d["block_sha256"])[0]: "0" * 64}))

    def first_request(label, path):
        if label == "O2":
            p = path / "oracle_evidence" / G1[0] / "B0" / "t2lite_probes.json"
            edit_json(p, lambda d: d[0]["shadow"].update(in_context_initial=False))

    for edit, name, check in ((one_byte, "R1", "check 1 R1"), (first_request, "O2", "check 2 O2"),
                              (cached, "R2", "check 7 R2")):
        code, out = run(edit=edit)
        assert code == 3 and out.splitlines()[-1] == f"INVALID CONTROL ROW {name}"
        assert any(x.endswith("pass False") for x in out.splitlines() if x.startswith(check))
        assert "== 3." not in out and "points" not in out
    assert "on 79 of 80 target items" in run(edit=first_request)[1]


@pytest.mark.parametrize("change,matched,unexpected,duplicated", [
    ("misfile", 95, 5, 0), ("duplicate", 100, 0, 1),
])
def test_check_7_reads_each_units_own_probes(run, change, matched, unexpected, duplicated):
    def edit(label, path):
        if label == "O1":
            unit = path / "oracle_evidence" / G1[0]
            b0, b1 = (json.loads((unit / b / "t2lite_probes.json").read_text()) for b in ("B0", "B1"))
            if change == "misfile":
                (unit / "B0" / "t2lite_probes.json").write_text(json.dumps(b0 + b1))
                (unit / "B1" / "t2lite_probes.json").write_text("[]")
            else:
                (unit / "B0" / "t2lite_probes.json").write_text(json.dumps(b0 + [b0[0]]))
    code, out = run(edit=edit)
    line = next(x for x in out.splitlines() if x.startswith("check 7 O1"))
    assert code == 3 and "expected units 20 units listed 20 (card) 20 (disclosures)" in line
    assert f"matching the pack's records {matched} of 100 unexpected {unexpected} duplicated {duplicated}" in line


def test_check_3_after_reruns_ends_the_round(run):
    bad = CHECK3_OK.replace("exit 0", "exit 1")
    code, out = run(check3=bad)
    assert code == 3 and out.splitlines()[-1].endswith("rerun check 3 at the run commit")
    code, out = run(check3=bad, flags=("--after-reruns",))
    assert code == 5 and "after the reruns (§4)" in out
    assert "missing observations: arms without usable trials " + " ".join(table.CORE) in out
    assert "== 3." not in out and "points" not in out
    late = (*(k for k in ORDER if k != "R2"), "R2")
    code, out = run(check3=bad, edit=cached, order=late, slots={"R2": 15}, flags=("--reruns", "R2"))
    assert code == 5 and "check 3 not shown passing (not yet rerun)" in out
    assert "missing observations: arms without usable trials R2" in out


def test_check_3_missing_anchor_test_id_fails(run):
    missing = "test_b_anchor_initial_in_context_equals_the_scripted_report[grep]"
    bad = "\n".join(x for x in CHECK3_OK.splitlines() if missing not in x)
    code, out = run(check3=bad)
    assert code == 3 and f"{missing} not found" in out and "== 3." not in out


def test_check_3_ids_exist_at_checkout():
    # Collection only: no fixtures execute and none of the runner tests' sockets or live harnesses run.
    node = "tests/runner/test_control_arms.py::"
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                             *(node + t for t in table.CHECK3_TESTS)], cwd=table.REPO,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(node + t in result.stdout for t in table.CHECK3_TESTS)


def test_checks_4_5_pending_and_checks_only(run):
    code, out = run(twins={"O1": {(WAKE, 0, 0): "B"}})
    assert code == 4 and out.splitlines()[-1].startswith("pending before any score: O1 - rerun once")
    assert "check 5 O1: target items 80 scored 79 BLOCKED 1 missing 0 complete False" in out
    code, out = run(identities={"F2": "other"})
    assert code == 4 and out.splitlines()[-1].startswith("pending before any score: F2 - rerun once")
    code, out = run(flags=("--checks-only",))
    assert code == 0 and "== 2." in out and "== 3." not in out

# 4. New anchor metadata, payload and presence checks.
@pytest.mark.parametrize("label", ("B1", "G1", "W1"))
@pytest.mark.parametrize("fault", ("block", "name", "version", "spec_sha256", "code_sha256", "missing"))
def test_anchor_check_1(run, label, fault):
    def edit(name, path):
        if name == label:
            def change(d):
                if fault == "block":
                    d["block_sha256"][sorted(d["block_sha256"])[0]] = "0" * 64
                elif fault == "missing":
                    d.pop("anchor")
                else:
                    d["anchor"][fault] = 2 if fault == "version" else "0" * 64
            edit_json(path / "control.json", change)
    code, out = run(edit=edit)
    assert code == 3 and out.splitlines()[-1] == f"INVALID CONTROL ROW {label}" and "== 3." not in out


@pytest.mark.parametrize("control,label", (("bm25", "B1"), ("grep", "G1"), ("recent_window", "W1")))
@pytest.mark.parametrize("source", ("cards", "checkout"))
def test_anchor_identity_compares_both_authorities(run, monkeypatch, control, label, source, tmp_path):
    # Build valid arms first, then make precisely one authority differ (never the fixture's control record).
    original = table.checks

    def changed(*args):
        if source == "cards":
            changed_cards = tmp_path / "cards.md"
            content = table.CARDS.read_text()
            changed_cards.write_text(content.replace(table.card_anchors()[control]["code_sha256"], "0" * 64))
            monkeypatch.setattr(table, "CARDS", changed_cards)
        else:
            data = table.header()
            data["anchors"][control]["code_sha256"] = "0" * 64
            monkeypatch.setattr(table, "header", lambda: data)
        return original(*args)
    monkeypatch.setattr(table, "checks", changed)
    code, out = run()
    assert code == 3 and f"check 1 {label}: anchor identity False reader_window True pass False" in out


@pytest.mark.parametrize("label", ("G1", "W1"))
@pytest.mark.parametrize("value", (None, 16384))
def test_required_reader_window(run, label, value):
    def edit(name, path):
        if name == label:
            edit_json(path / "control.json", lambda d: d.pop("reader_window") if value is None
                      else d.update(reader_window=value))
    code, out = run(edit=edit)
    assert code == 3 and f"check 1 {label}: anchor identity True reader_window False pass False" in out


@pytest.mark.parametrize("label", ("F1", "R1", "B1", "O1"))
def test_other_rows_have_no_reader_window(run, label):
    def edit(name, path):
        if name == label:
            edit_json(path / "control.json", lambda d: d.update(reader_window=32768))
    assert run(edit=edit)[0] == 3


@pytest.mark.parametrize("label", ("R1", "B1", "G1", "W1"))
def test_check_2_compares_each_scripted_presence(run, label):
    def edit(name, path):
        if name == label:
            p = path / table.CONTROL[label[0]] / G1[0] / "B1" / "t2lite_probes.json"
            edit_json(p, lambda d: d[0]["shadow"].update(in_context_initial=not d[0]["shadow"]["in_context_initial"]))
    code, out = run(edit=edit)
    assert code == 3 and f"scripted {table.CONTROL[label[0]]} report on 79 of 80 target items pass False" in out


def test_load_pack_uses_installed_pack_and_sealed_scoring(packs, monkeypatch):
    inputs, scores, calls = [], [], []

    def inp(path):
        inputs.append(path)
        return path

    def score(obj):
        scores.append(obj)
        return obj

    def anchor(inp, cls, *, score):
        calls.append((inp, cls))
        return fake_anchor(inp, cls, score=score)

    monkeypatch.setattr(table, "control_input", inp)
    monkeypatch.setattr(table, "make_score", score)
    monkeypatch.setattr(table, "run_anchor", anchor)
    (reports, keys), refusal = table.load_pack(packs)
    assert refusal is None and len(keys) == 100 and set(reports) == set(G1)
    assert inputs == [p.parent for p in sorted(packs.glob("pack/*/*/*/sealed"))]
    assert scores == [{"synthetic_scoring": True}] * 10
    assert calls == [(inp, cls) for inp in inputs for cls in table.ANCHORS.values()]
    assert not list(packs.glob("pack/*/*/*/sealed/bm25.json"))
    assert reports[G1[0]]["naive_rag"] == {k: {r["item_id"]: r for r in v}
                                         for k, v in scripted_arm(G1[0], "naive_rag").items()}


def test_each_control_is_replayed_once(run, monkeypatch):
    calls = []
    monkeypatch.setattr(table, "recompute_blocks", lambda packs, control: calls.append(control) or block_hashes())
    assert run()[0] == 0 and sorted(calls) == ["bm25", "grep", "naive_rag", "oracle_evidence", "recent_window"]


def test_scripted_beside_live_never_changes_reading(run):
    code, out = run()
    lines = [x for x in out.splitlines() if x.startswith("scripted beside live ")]
    assert code == 0 and len(lines) == 16
    for template in TEMPLATES:
        for row, name in table.ANCHOR_ROWS.items():
            points = SCRIPTED[table.CONTROL[row]] // 10
            assert (f"scripted beside live {template} {name}: pairs 10 scripted points {points} ({points:.1f})"
                    " live points 0 (0.0) (scripted proxy; never enters the reading)") in lines
        assert reading_of(out, template) == "ranking candidate"


# 5. Compaction: the root receipt covers all attempts; one whole-arm rerun, then exclude.
def add_compaction(label, path):
    if label == "O3":
        edit_json(path / "receipt.json", lambda d: d["tokens_by_role"].append(
            dict(role="summariser", input=5, output=0)))


@pytest.mark.parametrize("label", ("F1", "R1", "B1", "G1", "W1", "O3"))
@pytest.mark.parametrize("input_tokens,output_tokens", ((1, 0), (0, 1)))
def test_compaction_pending_for_any_row(run, label, input_tokens, output_tokens):
    def edit(name, path):
        if name == label:
            edit_json(path / "receipt.json", lambda d: d["tokens_by_role"].append(
                dict(role="summariser", input=input_tokens, output=output_tokens)))
    code, out = run(edit=edit)
    assert code == 4 and f"check 8 {label}: compacted True pass False" in out
    assert out.splitlines()[-1].startswith(f"pending before any score: {label} - rerun once")
    assert "== 3." not in out


def test_compaction_rerun_and_filter(run, tmp_path):
    assert run(edit=add_compaction)[0] == 4
    # The named rerun's root receipt has zero summariser tokens; old aggregate receipts elsewhere are ignored.
    code, out = run(flags=("--reruns", "O3", "--after-reruns"), attempts=(*ORDER, "O3.rerun"))
    assert code == 0 and all(reading_of(out, t) == "ranking candidate" for t in TEMPLATES)
    assert "check 8 O3: compacted False pass True" in out
    out_path = tmp_path / "FILTER.json"
    code, out = run(edit=add_compaction, twins={"O2": {(CHAIN, 0, 0): 0}},
                    flags=("--reruns", "O3", "--after-reruns"), attempts=(*ORDER, "O3.rerun"), filter_out=out_path)
    assert code == 0 and all(reading_of(out, t) == "unresolved" for t in TEMPLATES)
    assert "O3 (compacted)" in out and "-- O3 (compacted: not pooled)" in out
    assert "trials unscored for O3" in out
    chain = next(x for x in out.split("== 5.")[1].splitlines() if x.startswith(f"  {CHAIN}:"))
    assert "kept 9 dropped 0 unresolved 1" in chain and "(1, 1): 1" in chain and "(2, 1): 19" in chain
    assert json.loads(out_path.read_bytes())["o_excluded"] == ["O3"]
    # With no --after-reruns, a compacted repeat still prints the parsable pending line.
    assert run(edit=add_compaction, flags=("--reruns", "O3"))[0] == 4


def test_zero_summariser_tokens_and_other_roles_do_not_compact(run):
    def edit(label, path):
        edit_json(path / "receipt.json", lambda d: d["tokens_by_role"].append(dict(role="aux", input=10, output=10)))
    code, out = run(edit=edit)
    assert code == 0 and out.count("compacted False pass True") == 13


# 6. Labels, order and centres: round 1's CLI and exit codes.
@pytest.mark.parametrize("fault", ("missing", "extra", "duplicate"))
def test_exact_thirteen_labels_refused(run, monkeypatch, fault):
    original = table.main

    def main(argv):
        if fault == "missing":
            argv = [v for v in argv if not v.startswith("B1=")]
        else:
            argv = [*argv, "B1=unused" if fault == "duplicate" else "X1=unused"]
        return original(argv)
    monkeypatch.setattr(table, "main", main)
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 2


@pytest.mark.parametrize("order", (ORDER[:-1], (*ORDER, "X1"), (*ORDER[:-1], "F1")))
def test_order_requires_thirteen_unique_labels(run, order):
    with pytest.raises(SystemExit) as exc:
        run(order=order)
    assert exc.value.code == 2


def test_run_order(run):
    code, out = run()
    assert code == 0 and "run order verified" in out.splitlines()
    wrong = (ORDER[1], ORDER[0], *ORDER[2:])
    code, out = run(order=wrong, slots={"F1": 1, "R1": 0})
    assert code == 3 and "RUN ORDER VIOLATION: the order listed is not the declared order" in out
    late = (*(k for k in ORDER if k != "R1"), "R1")
    code, out = run(order=late, slots={"R1": 15}, flags=("--reruns", "R1"))
    assert code == 0 and "run order verified" in out.splitlines()
    code, out = run(slots={"O2": 12})
    assert code == 3 and "W2 starts before O2 ends" in out


def test_row_centres_in_the_order_the_arms_ran(run):
    def centres(out):
        return next(x for x in out.splitlines() if x.startswith("row centres"))

    code, out = run()
    assert code == 0 and centres(out).endswith(
        "(positions 1-13) F 13/2 (6.5) R 13/2 (6.5) B 13/2 (6.5) G 13/2 (6.5) W 13/2 (6.5) O 13/2 (6.5);"
        " O3 at 13 (declared order: each centre 13/2)")
    late = (*(k for k in ORDER if k != "O1"), "O1")
    code, out = run(order=late, slots={"O1": 15}, flags=("--reruns", "O1"), attempts=(*ORDER, "O1.rerun"))
    assert code == 0 and "O 21/2 (10.5); O3 at 13" in centres(out)
    code, out = run(order=late, slots={"O1": 15}, flags=("--reruns", "O1"))
    assert code == 0 and centres(out).endswith("not computed (pass --attempts)")
    for attempts, reruns in (((*ORDER, "O1.rerun"), "O3"), (("O1.rerun", *ORDER), "O1"),
                              ((*ORDER, "O1.rerun", "X"), "O1"),
                              ((*ORDER, "O1.rerun", "O1.rerun"), "O1")):
        code, out = run(order=late, slots={"O1": 15}, flags=("--reruns", reruns), attempts=attempts)
        assert code == 3 and out.startswith("REFUSED: --attempts")


# 7. Round 1's frozen-list and control-only refusals, updated for edition 3.
def test_refusals(run):
    def no_control(label, path):
        if label == "O3":
            (path / "control.json").unlink()

    def no_receipt(label, path):
        if label == "O3":
            (path / "receipt.json").unlink()

    def other_control(label, path):
        if label == "R1":
            edit_json(path / "control.json", lambda d: d.update(arm="oracle_evidence"))

    def other_pack(label, path):
        if label == "F1":
            edit_json(path / "card.json", lambda d: d.update(pack_hash="e" * 64))

    assert run(edit=no_control) == (3, "REFUSED: O3 has no control.json (control rows only, §2)\n")
    assert run(edit=no_receipt) == (3, "REFUSED: O3 has no receipt.json (check 8)\n")
    assert run(edit=other_control) == (3, "REFUSED: R1's control is not naive_rag\n")
    assert run(tasks_sha="0" * 64) == (3, "REFUSED: TASKS.json sha256 differs from --tasks-sha256\n")
    code, out = run(edit=other_pack)
    assert code == 3 and "PACK MISMATCH: F1 pack_hash eeeeeeeeeeee" in out and "== 3." not in out


def test_run_commit_edition_and_frozen_list(run, tmp_path):
    def other_commit(label, path):
        if label == "O2":
            edit_json(path / "card.json", lambda d: d["pins"].update(benchmark_commit="d" * 40))
    assert run(edit=other_commit) == (3, "REFUSED: O2 ran at another commit than TASKS.json names\n")
    path = tmp_path / "TASKS.json"
    whole = json.loads(path.read_bytes())
    for rows in (whole["rows"][1:], []):
        path.write_bytes(table.canon(dict(whole, rows=rows)))
        assert run() == (3, "REFUSED: TASKS.json rows differ from the pack's own target items (tasks.py)\n")
    path.write_bytes(table.canon(dict(whole, header=dict(whole["header"], edition=2))))
    assert run() == (3, "REFUSED: TASKS.json edition is not 3\n")
    path.write_bytes(table.canon(whole))
    assert run()[0] == 0


def pack_refusal(tmp_path, packs, capsys, monkeypatch, change):
    _, path = make_tasks(tmp_path, packs)
    capsys.readouterr()
    header = json.loads(path.read_bytes())["header"]
    change(packs)
    monkeypatch.setattr(table, "pack_tree_hash", lambda p: header["pack_hash"])
    code = table.main(["--packs", str(packs), "--tasks", str(path), "--tasks-sha256",
                       sha256(path.read_bytes()).hexdigest(), "--order", ",".join(ORDER),
                       *(f"{k}={tmp_path / k}" for k in table.CORE)])
    return code, capsys.readouterr().out


def test_a_pack_breaking_tasks_rule_refuses(tmp_path, packs, capsys, monkeypatch):
    def old_version(packs):
        edit_json(packs / "pack" / "G1" / G1[0] / "7" / "sealed" / "records.json",
                  lambda d: d[0].update(template_version=2))
    assert pack_refusal(tmp_path, packs, capsys, monkeypatch, old_version) == (
        3, "REFUSED: 1 target items of TASKS.json are absent from the pack\n")


def test_records_naming_two_lives_refuse(tmp_path, packs, capsys, monkeypatch):
    def two_lives(packs):
        edit_json(packs / "pack" / "G1" / G1[0] / "7" / "sealed" / "records.json",
                  lambda d: next(r for r in d if r["item_id"] == "ITEMZQ0xa").update(life=G1[1]))
    assert pack_refusal(tmp_path, packs, capsys, monkeypatch, two_lives) == (
        3, "REFUSED: a sealed life's records do not name exactly one life\n")


def test_tasks_list_counts_sorted_and_hash(tmp_path, packs, capsys):
    code, path = make_tasks(tmp_path, packs)
    out = capsys.readouterr().out
    data = json.loads(path.read_bytes())
    assert code == 0 and path.read_bytes() == table.canon(data)
    assert out.splitlines()[-1].endswith(f"tasks sha256 {sha256(path.read_bytes()).hexdigest()[:12]}")
    rows = data["rows"]
    assert rows == sorted(rows, key=lambda r: (r["life"], r["branch"], r["item_id"])) and len(rows) == 80
    assert data["header"] == dict(commit="b" * 40, edition=3, spec_sha256=sha256(b"seed = 1").hexdigest(),
                                  draw_sha256=sha256(b"[1, 2]").hexdigest(), pack_hash=table.pack_tree_hash(packs))
    assert {r["template_ref"] for r in rows} == set(TEMPLATES) == set(tasks.TARGET_TEMPLATES)
    assert {r["decision_table_ref"] for r in rows} == {t for tables in ACTION.values() for t in tables}
    assert not [n for n in ("ITEMZQ", "BUNDLEZQ", "LIFEZQ", str(tmp_path)) if n in out]


@pytest.mark.parametrize("edit,said", [
    (lambda r: False if r["item_id"].startswith("ITEMZQ31") else None, "action tasks 78 in 39 pairs"),
    (lambda r: False if r["life"] == G1[4] else None, "action tasks 72 in 36 pairs over 9 G1 lives"),
    (lambda r: r.update(template_version=2) if r["item_id"] == "ITEMZQ02a" else None,
     "the pack carries drift-quote-v2, not the v3 template"),
    (lambda r: r.update(template_version=3) if r["item_id"] == "ITEMZQ03a" else None,
     "the pack carries wake-loop-v3, not the v1 template"),
    (lambda r: r.update(bundle_id=None) if r["item_id"] == "ITEMZQ03a" else None,
     "a wake-loop-v1 item is not a G1 twin"),
])
def test_tasks_refusals(tmp_path, capsys, edit, said):
    packs = make_packs(tmp_path / "other", edit=edit)
    code, path = make_tasks(tmp_path, packs)
    assert code == 3 and not path.exists() and capsys.readouterr().out.startswith(f"REFUSED: {said}")


@pytest.mark.parametrize("item,table_ref", [("ITEMZQ01b", "drift-config-corrected-v3"),
                                             ("ITEMZQ01a", "drift-config-hedged-v3"),
                                             ("ITEMZQ00a", "drift-chain-fault-v2")])
def test_tasks_decision_tables(tmp_path, capsys, packs, item, table_ref):
    sealed = packs / "pack" / "G1" / G1[0] / "7" / "sealed"
    edit_json(sealed / "pack.json", lambda d: next(i for i in d["items"] if i["item_id"] == item).update(
        decision_table_ref=table_ref))
    code, _ = make_tasks(tmp_path, packs)
    assert code == 3 and "REFUSED:" in capsys.readouterr().out


def test_section_1_names_the_code(run):
    _, out = run()
    for name, path in table.CODE.items():
        assert f"code {name} sha256 {sha256(path.read_bytes()).hexdigest()[:12]}" in out.splitlines()
    assert not [x for x in out.splitlines() if x.startswith("code ") and "/" in x]


# 8. The unchanged privacy boundary, including compacted and invalid arms.
def test_no_ids_text_or_paths(run, tmp_path):
    for kwargs in (dict(), dict(edit=add_compaction, flags=("--after-reruns",), filter_out=tmp_path / "FILTER.json"),
                   dict(edit=cached, order=(*(k for k in ORDER if k != "R2"), "R2"),
                        slots={"R2": 15}, flags=("--reruns", "R2"))):
        code, out = run(**kwargs)
        assert code in (0, 5)
        needles = [*G1, IDENTITY, "control text", "task text ZQ", str(tmp_path), "ITEMZQ", "BUNDLEZQ", "LIFEZQ",
                   *block_hashes().values()]
        assert not [n for n in needles if n in out]


# Baseline comparison: round 1's reading function accepts this same F/R/O context.
def test_round_1_logic_cannot_label_a_ranking_candidate(run, monkeypatch):
    path = table.HERE.parents[1] / "validity-1" / "v2-control-trials" / "table.py"
    spec = importlib.util.spec_from_file_location("round1_comparison", path)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    original = table.reading
    compared = []

    def compare(ctx, template):
        lines, result = original(ctx, template)
        old_lines, old_result = baseline.reading(ctx, template)
        assert result == "ranking candidate" and old_result == "cleared"
        assert len([x for x in lines if "near-solved" in x]) == 5
        assert len([x for x in old_lines if "near-solved" in x]) == 2
        compared.append(template)
        return lines, result
    monkeypatch.setattr(table, "reading", compare)
    assert run()[0] == 0 and set(compared) == set(TEMPLATES)
