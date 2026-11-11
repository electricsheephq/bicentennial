"""Synthetic fixture tests for table.py: flag rules, checks 1, 2 and 7, run order, common support, filter yield, no ids.

Run directly: PYTHONPATH=<checkout>/src python -m pytest results/milestone-1/2026-11-11-separation-table/test_table.py
(not in CI's testpaths). The fixture has two lives; per life two value-twin pairs, one correction pair, one Wake pair.
"""

import json
import sys
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import table  # noqa: E402

LIVES = ("LIFEZQA", "LIFEZQB")
KINDS = {"value": ("DRIFT-CUR", "fork", 2), "corr": ("DRIFT-CUR", "trigger", 1), "wake": ("WAKE-LOOP", "fork", 1)}
IDENTITY = "identity-zq-served-value"
ORDER = ("F1", "R1", "O1", "H1", "H2", "O2", "R2", "F2", "O3")
BASE = {"F": {"value": [0] * 4, "corr": [0] * 2, "wake": [0] * 2},
        "R": {"value": [1000] * 4, "corr": [0] * 2, "wake": [0] * 2},
        "O": {"value": [1000] * 4, "corr": [1000] * 2, "wake": [0] * 2},
        "H": {"value": [1000, 0, -1000, 0], "corr": [1000] * 2, "wake": [0] * 2}}

# Check 3's evidence (§11.7): verbose pytest output of the named tests at the fixture cards' commit.
CHECK3_OK = "\n".join([f"commit {'b' * 40}", "testslot: slot 0 of 1 (marker 0)",
                        *(f"tests/runner/test_control_arms.py::{t} PASSED [{n}%]"
                          for n, t in zip((33, 66, 100), table.CHECK3_TESTS, strict=True)),
                        "3 passed in 1.00s", "exit 0"])


def layout():
    """[(life, kind, index within kind, bundle id, (twin ids))] in global order, plus one quiz id per life."""
    pairs, quiz, seen = [], {}, {k: 0 for k in KINDS}
    for n, life in enumerate(LIVES):
        for kind, (_, _, count) in KINDS.items():
            for _ in range(count):
                i = seen[kind]
                seen[kind] += 1
                pairs.append((life, kind, i, f"BUNDLEZQ{n}{kind}{i}", (f"ITEMZQ{n}{kind}{i}a", f"ITEMZQ{n}{kind}{i}b")))
        quiz[life] = f"ITEMZQ{n}quiz"
    return pairs, quiz


def row(score, stage="act", cell="DRIFT-CUR", in_context=True):
    """score "B" is a BLOCKED task (no score)."""
    verdict = {1000: "PASS", 0: "OMISSION", -1000: "FAIL_MEMORY"}.get(score) if stage == "act" else None
    blocked = score == "B"
    return dict(score_milli=None if blocked else score, failure_class="BLOCKED" if blocked else None,
                base_verdict=verdict, stage=stage, cell_id=cell,
                in_context=in_context, competing_present=False)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def sealed_arm(life, mine, quiz_id, report, score_of):
    ids = [i for p in mine for i in p[4]] + [quiz_id]
    items = [dict(item_id=i, stage="survive" if i == quiz_id else "act", score_milli=score_of(i), failure_class=None,
                  accuracy_correct=score_of(i) == 1000, cell_id="RECALL-AGG" if i == quiz_id else "X") for i in ids]
    return dict(items=items, reports=[dict(item_id=i, in_context=report[i]) for i in ids],
                bundles=[dict(bundle_id=p[3], life=life, items=list(p[4]), cell_id=KINDS[p[1]][0],
                              twin_type=KINDS[p[1]][1], score_milli=min(score_of(i) for i in p[4])) for p in mine])


def make_packs(root):
    pairs, quiz = layout()
    for life in LIVES:
        mine = [p for p in pairs if p[0] == life]
        report = {i: p[1] == "value" for p in mine for i in p[4]} | {quiz[life]: False}
        arms = [sealed_arm(life, mine, quiz[life], report, f) for f in
                (lambda i, r=report: 1000 if r[i] else 0, lambda i: 1000, lambda i: 0)]
        sealed = root / "pack" / "G1" / life / "1" / "sealed"
        write(sealed / "naive_rag.json", dict(arm=arms[0], rows=[]))
        write(sealed / "controls.json", dict(arms=dict(oracle_evidence=arms[1], no_memory=arms[2],
                                                       full_history=dict(fits=dict(run=0, of=len(report))))))
    return root


def block_hashes():
    pairs, quiz = layout()
    ids = [(p[0], i) for p in pairs for i in p[4]] + list(quiz.items())
    return {f"{life}/B0/{i}": sha256(f"control text for {i}".encode()).hexdigest() for life, i in ids}


def make_arm(path, label, spec, twins=None, cached=False, extra_floor=False, slot=0, pack_hash="p" * 64):
    """spec: kind -> pair scores in global order; twins: {(kind, index, twin 0 or 1): score} overrides."""
    pairs, quiz = layout()
    letter = label[0]
    out = {}
    for life, kind, i, _, ids in pairs:
        for t, iid in enumerate(ids):
            score = (twins or {}).get((kind, i, t), spec[kind][i])
            in_context = True if letter == "O" else kind == "value" if letter == "R" else score != 0
            out[f"{life}/B0/{iid}"] = row(score, cell=KINDS[kind][0], in_context=in_context)
    for life, iid in quiz.items():
        out[f"{life}/B0/{iid}"] = row(1000 if letter in "ROH" else 0, stage="survive", cell="RECALL-AGG",
                                      in_context=False)
    units = {f"{life}/B{b}": dict(cache_key="k", cached=False) for life in LIVES for b in (0, 1)}
    if cached:
        units[f"{LIVES[0]}/B0"]["cached"] = True
    write(path / "card.json", dict(tier="T2", system="hermes-native", model="m", effort="medium", pack_hash=pack_hash,
                                   pins=dict(scorer_commit="c" * 40, benchmark_commit="b" * 40), served_identity=IDENTITY, not_scored_live=[],
                                   floor=dict(served_identity=IDENTITY, units=units)))
    write(path / "outcomes.json", out)
    start = 1793796303380 + slot * 10_000_000  # one arm after another, in run-order slots
    write(path / "units.json", dict(start_ms=start, end_ms=start + 6_000_000))
    write(path / "disclosures.json", dict(floor={u: dict(cached=v["cached"], reason="r") for u, v in units.items()},
                                          live=dict(identity_drift=None)))
    if letter in table.CONTROL:
        # Each unit's probe records (served live) and the floor-shape file's stops, as #496 writes them.
        arm = table.CONTROL[letter]
        for unit in units:
            life, branch = unit.split("/")
            write(path / arm / life / branch / "t2lite_probes.json", [
                dict(item_id=k.split("/", 2)[2], live=dict(served_by="live", served="live"),
                     shadow=dict(in_context_initial=v["in_context"], in_context=v["in_context"]))
                for k, v in out.items() if k.startswith(f"{unit}/")])
        write(path / f"{arm}.json", {unit: dict(served_identity=IDENTITY, stops={unit.replace("/", ""): None},
            outcomes={k.split("/", 2)[2]: v for k, v in out.items() if k.startswith(f"{unit}/")}) for unit in units})
        write(path / "control.json", dict(arm=table.CONTROL[letter], frame_sha256=None if letter == "F" else "f" * 64,
                                          block_sha256={} if letter == "F" else block_hashes()))
    if extra_floor:
        write(path / "no_memory.json", {f"{life}/B0": dict(served_identity=IDENTITY, stops={}, outcomes={
            k.split("/", 2)[2]: dict(v) for k, v in out.items() if k.startswith(life)}) for life in LIVES})
    return path


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(table, "recompute_blocks", lambda packs, control: block_hashes())
    monkeypatch.setattr(table, "frame_sha256", lambda: "f" * 64)
    packs = make_packs(tmp_path / "packs")
    pack_hash = table.pack_tree_hash(packs)

    def go(specs=None, twins=None, cached=(), extra=(), edit=None, slots=None, flags=(), order=ORDER, check3=CHECK3_OK):
        specs = {k: dict(BASE[k[0]], **(specs or {}).get(k, {})) for k in table.CORE} | {k: BASE["H"] for k in extra}
        argv = ["--packs", str(packs), "--order", ",".join(order), *flags]
        if check3 is not None:
            (tmp_path / "check3.txt").write_text(check3)
            argv += ["--check3", str(tmp_path / "check3.txt")]
        for label, spec in specs.items():
            path = make_arm(tmp_path / "runs" / label, label, spec, (twins or {}).get(label), label in cached,
                            extra_floor=label in ("H1", "E1", "E2"),
                            slot=(slots or {}).get(label, ORDER.index(label) if label in ORDER else 20), pack_hash=pack_hash)
            if edit:
                edit(label, path)
            argv.append(f"{label}={path}")
        code = table.main(argv)
        return code, capsys.readouterr().out
    return go


def flags(out, kind):
    lines = out.splitlines()
    start = lines.index(next(x for x in lines if x.startswith(f"-- {kind}: common pairs")))
    return lines[start:start + 5]


def test_flag_rules():
    F = Fraction
    assert [table.state(x, F(0), F(100), F(100)) for x in ("low", "naive", "floor")] == ["no", "applies", "no"]
    assert [table.state(x, F(0), F(50), F(50)) for x in ("low", "naive", "floor")] == ["applies", "applies", "no"]
    assert table.state("floor", F(80), F(0), F(100)) == "applies"
    assert table.state("floor", F(69), F(0), F(100)) == "no"
    assert table.state("naive", F(0), F(69), F(100)) == "no" and table.state("naive", F(0), F(70), F(100)) == "applies"
    assert table.state("low", None, None, F(75)) == "no" and table.state("low", None, None, F(749, 10)) == "applies"
    # c <= f and c <= 0: the near-solved flags are not interpreted; low still reads.
    assert table.state("naive", F(100), F(100), F(100)) == "not interpreted"
    assert table.state("floor", F(-20), F(0), F(-10)) == "not interpreted"
    assert table.state("floor", F(-50), F(0), F(-10)) == "not interpreted"
    assert table.margin("naive", F(0), F(100), F(100), 4) == F(6, 5)
    assert table.margin("low", F(0), F(100), F(100), 4) == -1
    assert table.margin("floor", F(0), F(100), F(100), 4) == F(-14, 5)


def test_flags_end_to_end(run):
    code, out = run()
    assert code == 0 and "INVALID" not in out
    value, corr, wake = flags(out, "Drift, value twins"), flags(out, "Drift, correction twins"), flags(out, "Wake")
    assert "f 0 (0.0) r 100 (100.0) c 100 (100.0)" in value[0]
    assert "naive: on means applies margin_pairs 6/5 (1.2)" in value[2] and value[4].endswith(
        "classification: near-solved by naive retrieval")
    assert corr[4].endswith("classification: candidate")
    assert "naive: on means not interpreted" in wake[2] and wake[4].endswith("classification: low")
    # Co-occurring low and naive, stable across all combinations.
    half = {"wake": [1000, 0]}
    code, out = run({"R1": half, "R2": half, "O1": half, "O2": half, "O3": half})
    assert flags(out, "Wake")[4].endswith("classification: low + near-solved by naive retrieval; low governs first (§6)")
    # Instability, and c over O1,O2 against c over all three.
    code, out = run({"O3": {"value": [0] * 4}})
    value = flags(out, "Drift, value twins")
    assert "c 100 (100.0) c over O1,O2,O3 200/3 (66.7)" in value[0]
    assert "low: on means no" in value[1] and "combinations 3 agreeing on whether it applies 2 status unstable" in value[1]
    assert "combinations 12 agreeing" in value[2] and "combinations 6 agreeing" in value[3]
    assert value[4].endswith("classification: unstable; no classification")


def test_c_checks_detect_one_fault(run):
    def one_byte(label, path):
        if label == "R1":
            data = json.loads((path / "control.json").read_text())
            key = sorted(data["block_sha256"])[0]
            data["block_sha256"][key] = ("0" if data["block_sha256"][key][0] != "0" else "1") + data["block_sha256"][key][1:]
            (path / "control.json").write_text(json.dumps(data))

    def context(label, path):
        if label == "O2":
            set_first_request(path / "oracle_evidence", lambda record: False)

    for kw, name, check in ((dict(edit=one_byte), "R1", "check 1 R1"), (dict(cached=("F2",)), "F2", "check 7 F2"),
                            (dict(edit=context), "O2", "check 2 O2")):
        code, out = run(**kw)
        assert code == 3 and out.splitlines()[-1] == f"INVALID CONTROL ROW {name}"
        assert [x for x in out.splitlines() if x.startswith("INVALID")] == [f"INVALID CONTROL ROW {name}"]
        assert next(x for x in out.splitlines() if x.startswith(check)).endswith("pass False")
        assert "== 3." not in out and "Earlier evidence" not in out
    assert "blocks matched 17 of 18 mismatched 1" in run(edit=one_byte)[1]


def test_d_common_support(run):
    specs = {"F1": {"value": [1000, 0, 0, 0]}, "F2": {"value": [1000, 0, 0, 0]},
             "R1": {"value": [1000, 1000, 1000, 0]}, "R2": {"value": [1000, 1000, 1000, 0]}}
    _, base = run(specs)

    def drop(label, path):
        if label == "F2":
            data = json.loads((path / "outcomes.json").read_text())
            pair = layout()[0][0]
            for iid in pair[4]:
                del data[f"{pair[0]}/B0/{iid}"]
            (path / "outcomes.json").write_text(json.dumps(data))
    code, dropped = run(specs, edit=drop, flags=("--after-reruns",))
    assert code == 0
    six = [next(x for x in out.splitlines() if x.startswith("check 6")) for out in (base, dropped)]
    assert "'Drift, value twins': 4" in six[0] and "'Drift, value twins': 3" in six[1] and "total 7" in six[1]
    before, after = flags(base, "Drift, value twins"), flags(dropped, "Drift, value twins")
    assert before[0].startswith("-- Drift, value twins: common pairs 4 f 25 (25.0) r 75 (75.0) c 100 (100.0)")
    assert after[0].startswith("-- Drift, value twins: common pairs 3 f 0 (0.0) r 200/3 (66.7) c 100 (100.0)")
    assert all(a != b for a, b in zip(before[:4], after[:4], strict=True))
    assert after[4].endswith("classification: near-solved by naive retrieval unresolved; near-solved without memory"
                             " unresolved") and "row F incomplete" in dropped
    mean = [next(x for x in out.split("-- F mean")[1].splitlines() if "value twins" in x) for out in (base, dropped)]
    assert "common pairs 4" in mean[0] and "common pairs 3" in mean[1]
    assert "check 5 F2: scored action tasks assigned 16 scored 14 BLOCKED 0 missing 2 complete False" in dropped


def test_not_interpreted_is_a_disclosure_not_instability(run):
    # Fix 1: f = r = c = 0 on the means (near-solved flags not interpreted); O3 alone has one value pair right of four
    # (25 points; the fixture's value kind has four pairs), so in O3's combinations the near-solved flags read "no".
    zero = {"value": [0] * 4}
    _, out = run({k: zero for k in ("F1", "F2", "R1", "R2", "O1", "O2")} | {"O3": {"value": [1000, 0, 0, 0]}})
    value = flags(out, "Drift, value twins")
    assert "c 0 (0.0) c over O1,O2,O3 25/3 (8.3)" in value[0]
    assert "low: on means applies" in value[1] and value[1].endswith("status applies")
    assert "naive: on means not interpreted" in value[2] and value[2].endswith("agreeing on whether it applies 12"
                                                                              " status does not apply")
    assert "floor: on means not interpreted" in value[3] and value[3].endswith("6 status does not apply")
    assert value[4].endswith("classification: low") and "unstable" not in "\n".join(value)


def test_unresolved_flag_does_not_hide_a_stable_low(run):
    # Fix 2: F2 is incomplete (one value pair missing); O1-O3 complete, c = 100/3 on the three pairs left (the
    # fixture's four-pair kind cannot make 40).
    half = {"value": [1000, 1000, 0, 0]}

    def drop(label, path):
        if label == "F2":
            data = json.loads((path / "outcomes.json").read_text())
            pair = layout()[0][0]
            for iid in pair[4]:
                del data[f"{pair[0]}/B0/{iid}"]
            (path / "outcomes.json").write_text(json.dumps(data))
    code, out = run({"O1": half, "O2": half, "O3": half}, edit=drop, flags=("--after-reruns",))
    value = flags(out, "Drift, value twins")
    assert code == 0 and "row F incomplete" in out and value[1].endswith("status applies")
    assert value[4].endswith("classification: low; near-solved by naive retrieval unresolved; near-solved without"
                             " memory unresolved")
    # The correction kind keeps all its pairs but still uses the incomplete F row: no candidate.
    assert flags(out, "Drift, correction twins")[4].endswith("classification: near-solved by naive retrieval"
                                                             " unresolved; near-solved without memory unresolved")


def test_run_order_is_checked(run):
    code, out = run()
    assert code == 0 and "run order verified" in out.splitlines()
    # Fix 3: the directories labelled O2 and O3 ran in each other's slots.
    code, out = run(slots={"O2": ORDER.index("O3"), "O3": ORDER.index("O2")})
    assert code == 3 and "RUN ORDER VIOLATION: R2 starts before O2 ends" in out.splitlines()
    assert not [x for x in out.splitlines() if x.startswith("INVALID")] and "== 3." not in out


def test_e_filter_yield(run):
    # O1, O2, O3 per twin. Correction pair 0, twin b: 1000, 0, BLOCKED -> unresolved; pair 1, twin b: 1000, 1000,
    # BLOCKED -> pass. Wake (twins a right in all three): pair 0, twin b: 0, 0, BLOCKED -> fail; pair 1 passes.
    wake = {"wake": [1000, 1000]}
    twins = {"O2": {("corr", 0, 1): 0, ("wake", 0, 1): 0}, "O1": {("wake", 0, 1): 0},
             "O3": {("corr", 0, 1): "B", ("corr", 1, 1): "B", ("wake", 0, 1): "B"}}
    code, out = run({"O1": wake, "O2": wake, "O3": wake}, twins=twins, flags=("--after-reruns",))
    lines = out.split("== 6.")[1].split("== 7.")[0].splitlines()
    corr, wake_, value = (next(x for x in lines if x.startswith(f"  {k}: pairs"))
                          for k in ("Drift, correction twins", "Wake", "Drift, value twins"))
    assert code == 0 and corr.startswith("  Drift, correction twins: pairs 2 pass 1 fail 0 unresolved 1 (")
    assert corr.endswith("twins by (passes, unknown) {(1, 1): 1, (2, 1): 1, (3, 0): 2}")
    assert wake_.startswith("  Wake: pairs 2 pass 1 fail 1 unresolved 0 (")
    assert wake_.endswith("{(0, 1): 1, (3, 0): 3}")
    assert value.startswith("  Drift, value twins: pairs 4 pass 4 fail 0 unresolved 0") and value.endswith("{(3, 0): 8}")
    assert "Prospective filter yield; validates nothing" in out
    # Earlier case, no unknowns: correction twins b right in 2 of 3 (pair passes) and 1 of 3 (pair fails).
    _, out = run(twins={"O2": {("corr", 1, 1): 0}, "O3": {("corr", 0, 1): 0, ("corr", 1, 1): 0}})
    corr = next(x for x in out.split("== 6.")[1].splitlines() if x.startswith("  Drift, correction twins: pairs"))
    assert corr.startswith("  Drift, correction twins: pairs 2 pass 1 fail 1 unresolved 0")
    assert corr.endswith("{(1, 0): 1, (2, 0): 1, (3, 0): 2}")


def test_check_3_needs_its_tests_passing_at_the_run_commit(run):
    line = next(x for x in run()[1].splitlines() if x.startswith("check 3"))
    assert ("the runner's own tests at the run commit bbbbbbbbbbbb (§11.7): file names commit bbbbbbbbbbbb, ends with"
            " exit 0 True;") in line
    assert line.count(" {'PASSED': 1};") == 3 and line.endswith("pass True")
    # A warnings-summary heading names a test with no outcome word: it counts for nothing.
    warned = CHECK3_OK.replace("3 passed", f"tests/runner/test_control_arms.py::{table.CHECK3_TESTS[0]}\n  Warning\n3 passed")
    assert run(check3=warned)[0] == 0
    one = f"tests/runner/test_control_arms.py::{table.CHECK3_TESTS[2]}"
    for text in (None, CHECK3_OK.replace("b" * 40, "d" * 40), CHECK3_OK.replace("exit 0", "exit 1"),
                 CHECK3_OK.replace(f"{one} PASSED", f"{one} FAILED"), CHECK3_OK.replace(f"{one} PASSED [100%]\n", ""),
                 CHECK3_OK.replace("exit 0", f"SKIPPED {one}\nexit 0"), ""):
        code, out = run(check3=text)
        assert code == 3 and "== 3." not in out and "pass False" in next(x for x in out.splitlines() if x.startswith("check 3"))
        assert out.splitlines()[-1] == "CHECK 3 NOT SHOWN PASSING at the run commit (see check 3 above): no score is opened"
    assert "the run commit bbbbbbbbbbbb (§11.7): no --check3 file pass False" in run(check3=None)[1]
    # A malformed file fails without its own text reaching the output: no path, item id or traceback line.
    code, out = run(check3=f"/home/zq/{LIVES[0]}.py\nTraceback\n  File \"/home/zq/ITEMZQ0value0a.py\", line 1")
    assert code == 3 and "/home/zq" not in out and "ITEMZQ" not in out and "LIFEZQ" not in out and "Traceback" not in out
    assert "file names commit (no commit line), ends with exit 0 False;" in out


def test_identity_change_during_an_arm_is_a_mismatch(run):
    def drift(value):
        def edit(label, path):
            if label == "H1":
                data = json.loads((path / "disclosures.json").read_text())
                if value is None:
                    del data["live"]
                else:
                    data["live"]["identity_drift"] = value
                (path / "disclosures.json").write_text(json.dumps(data))
        return edit

    def header(out):
        return next(x for x in out.splitlines() if x.startswith("H1: tier"))

    assert header(run()[1]).endswith("matches_core True identity changed during the run no")
    for value, said in ((dict(model="m", baseline=IDENTITY, served="identity-zq-later"), "yes"), (None, "not recorded")):
        code, out = run(edit=drift(value))
        assert code == 4 and header(out).endswith(f"matches_core True identity changed during the run {said}")
        assert out.splitlines()[-1].startswith("pending before any score: H1 -") and "== 3." not in out
        code, out = run(edit=drift(value), flags=("--after-reruns",))
        assert code == 0 and "-- H1 (identity mismatch: not pooled)" in out.splitlines()
        assert "row H incomplete: repeats used ['H2']" in out


def test_h1_extra_floor_says_how_it_was_measured(run):
    assert ("-- extra floor (H1's no-memory floor, measured live on 4 of 4 units, taken from a cache or unconfirmed"
            " on 0; enters no mean, flag or comparison)") in run()[1].splitlines()
    code, out = run(cached=("H1",))
    assert code == 0 and "measured live on 3 of 4 units, taken from a cache or unconfirmed on 1;" in out


def test_check_7_needs_every_unit_live(run):
    def probes(path):
        return path / "oracle_evidence" / LIVES[0] / "B0" / "t2lite_probes.json"

    def served_none(label, path):
        if label == "O1":
            data = json.loads(probes(path).read_text())
            data[0]["live"]["served_by"] = None
            probes(path).write_text(json.dumps(data))

    def missing(label, path):
        if label == "O1":
            probes(path).unlink()

    def stopped(label, path):
        if label == "O1":
            data = json.loads((path / "oracle_evidence.json").read_text())
            data[f"{LIVES[0]}/B1"]["stops"] = {f"{LIVES[0]}B1": ["live_stop", 3]}
            (path / "oracle_evidence.json").write_text(json.dumps(data))

    def dropped(label, path):
        if label == "O1":
            unit = f"{LIVES[0]}/B0"
            for name, keys in (("card.json", ("floor", "units")), ("disclosures.json", ("floor",))):
                data = json.loads((path / name).read_text())
                target = data
                for key in keys:
                    target = target[key]
                del target[unit]
                (path / name).write_text(json.dumps(data))
            probes(path).unlink()

    def empty(label, path):
        if label == "O1":
            probes(path).write_text("[]")

    clean = next(x for x in run()[1].splitlines() if x.startswith("check 7 O1"))
    assert clean == ("check 7 O1: expected units 4 units listed 4 (card) 4 (disclosures) cached or unconfirmed 0 probe"
                     " files found 4 probed items covered 18 of 18 probe records 18 sent to the live reader 18 (answered"
                     " probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own"
                     " entry with no stop) pass True")

    def stop_record(value):
        def edit(label, path):
            if label == "O1":
                data = json.loads((path / "oracle_evidence.json").read_text())
                data[f"{LIVES[0]}/B1"]["stops"] = value
                (path / "oracle_evidence.json").write_text(json.dumps(data))
        return edit

    # A unit's stop record must be exactly its own entry with no stop: not empty, not another unit's, not two entries.
    odd = [stop_record(v) for v in ({}, {f"{LIVES[1]}B1": None}, {f"{LIVES[0]}B1": None, f"{LIVES[0]}B0": None})]
    for edit, part in ((served_none, "sent to the live reader 17"), (missing, "probe files found 3"),
                       (stopped, "stopped units 1"), (dropped, "units listed 3 (card) 3 (disclosures)"),
                       (empty, "probed items covered 9 of 18"), *((e, "stopped units 1") for e in odd)):
        code, out = run(edit=edit)
        line = next(x for x in out.splitlines() if x.startswith("check 7 O1"))
        assert code == 3 and part in line and line.endswith("pass False") and "== 3." not in out
        assert out.splitlines()[-1] == "INVALID CONTROL ROW O1"


def test_reruns_and_checks_only(run):
    def drop(label, path):
        if label == "F2":
            data = json.loads((path / "outcomes.json").read_text())
            del data[next(k for k in sorted(data) if data[k]["stage"] == "act")]
            (path / "outcomes.json").write_text(json.dumps(data))

    code, out = run(edit=drop)
    assert code == 4 and "== 3." not in out and out.splitlines()[-1] == (
        "pending before any score: F2 - rerun once (§2.4, §2.5), then run again with --after-reruns")
    code, out = run(edit=drop, flags=("--after-reruns",))
    assert code == 0 and "== 3." in out and "== 8. Full history" in out and "--after-reruns given True" in out
    code, out = run(flags=("--checks-only",))
    assert code == 0 and "== 2." in out and "== 3." not in out
    assert "equals the declared order True | reruns named none | --after-reruns given False" in out


def set_first_request(arm_dir, value, field="in_context_initial"):
    """Set field on the first scored action task's probe record (the fixture puts every task in B0)."""
    path = arm_dir / LIVES[0] / "B0" / "t2lite_probes.json"
    records = json.loads(path.read_text())
    record = next(r for r in records if not r["item_id"].endswith("quiz"))
    record["shadow"][field] = value(record)
    path.write_text(json.dumps(records))


def test_check_2_reads_the_probe_turns_first_request(run):
    # The live R smoke: a later request of the turn held a fact the reader fetched with its own tools. Check 2 reads
    # the first request, the one that carries the block; neither the latest request nor outcomes.json enters it.
    def latest_differs(label, path):
        if label == "R1":
            set_first_request(path / "naive_rag", lambda r: not r["shadow"]["in_context"], field="in_context")
            data = json.loads((path / "outcomes.json").read_text())
            key = next(k for k in sorted(data) if data[k]["stage"] == "act")
            data[key]["in_context"] = not data[key]["in_context"]
            (path / "outcomes.json").write_text(json.dumps(data))

    code, out = run(edit=latest_differs)
    assert code == 0 and next(x for x in out.splitlines() if x.startswith("check 2 R1")) == (
        "check 2 R1: presence in the probe turn's first request equals the pack's scripted naive report on 18 of 18"
        " tasks pass True")

    def first_differs(label, path):
        if label == "R2":
            set_first_request(path / "naive_rag", lambda r: not r["shadow"]["in_context_initial"])
        if label == "O3":
            set_first_request(path / "oracle_evidence", lambda r: False)
            set_first_request(path / "oracle_evidence", lambda r: True, field="in_context")

    code, out = run(edit=first_differs)
    assert code == 3 and "== 3." not in out
    assert [x for x in out.splitlines() if x.startswith("INVALID")] == ["INVALID CONTROL ROW O3", "INVALID CONTROL ROW R2"]
    assert "check 2 R2: presence in the probe turn's first request equals the pack's scripted naive report on 17 of 18" \
           " tasks pass False" in out.splitlines()
    assert "check 2 O3: needed fact in the probe turn's first request on 15 of 16 scored action tasks pass False" \
           in out.splitlines()


def test_run_order_must_be_the_declared_one(run):
    # R1 ran first and --order says so: no rerun explains it, so no score opens.
    first = ("R1", "F1", *ORDER[2:])
    code, out = run(order=first, slots={"R1": 0, "F1": 1})
    assert code == 3 and "== 3." not in out and "equals the declared order False | reruns named none" in out
    assert "RUN ORDER VIOLATION: the order listed is not the declared order" in out.splitlines()
    # A rerun named on the command line may run later than its slot ...
    late = (*(k for k in ORDER if k != "R1"), "R1")
    code, out = run(order=late, slots={"R1": 9}, flags=("--reruns", "R1"))
    assert code == 0 and "run order verified" in out.splitlines() and "reruns named R1" in out
    code, out = run(order=late, slots={"R1": 9})
    assert code == 3 and "RUN ORDER VIOLATION: the order listed is not the declared order" in out.splitlines()
    # ... but never before an arm whose slot comes before its own.
    code, out = run(order=first, slots={"R1": 0, "F1": 1}, flags=("--reruns", "R1"))
    assert code == 3 and "RUN ORDER VIOLATION: rerun R1 is listed before F1, whose slot comes before its own" \
        in out.splitlines()
    with pytest.raises(SystemExit):
        run(flags=("--reruns", "R1,R1"))


def test_every_core_repeat_missing(run):
    def gone(label, path):
        if label in table.CORE:
            remove_run(label)(label, path)

    code, out = run(extra=("E1",), edit=gone)
    assert code == 4 and "Earlier evidence" not in out and "== 2." not in out and "== 3." not in out
    assert out.splitlines()[-1].startswith("pending before any score: F1 F2 R1 R2 O1 O2 O3 H1 H2 -")
    code, out = run(extra=("E1",), edit=gone, flags=("--after-reruns",))
    assert code == 3 and "Earlier evidence" not in out and "== 3." not in out
    assert out.splitlines()[-1] == "no core arm has card.json and outcomes.json: no check, row, flag or comparison can be computed"
    assert run(edit=gone, flags=("--checks-only",))[0] == 4


def test_card_pins_must_be_equal(run):
    def other_commit(label, path):
        if label == "H2":
            card = json.loads((path / "card.json").read_text())
            card["pins"]["benchmark_commit"] = "d" * 40
            (path / "card.json").write_text(json.dumps(card))

    code, out = run(edit=other_commit)
    assert code == 3 and "== 3." not in out and "one commit for every core arm (card pins equal) False" in out
    assert ("PIN MISMATCH: benchmark_commit: bbbbbbbbbbbb (F1,F2,R1,R2,O1,O2,O3,H1); dddddddddddd (H2)"
            in out.splitlines())
    assert out.splitlines()[-1] == "CARD PINS DIFFER between core arms (see PIN MISMATCH above): not pooled"
    assert "card pins equal) True" in run()[1]


def remove_run(name):
    def edit(label, path):
        if label == name:
            for file in ("card.json", "outcomes.json"):
                (path / file).unlink()
            write(path / "refusal.json", dict(code="live_stop"))
    return edit


def test_missing_core_repeat(run):
    code, out = run(edit=remove_run("H2"))
    assert code == 4 and "== 3." not in out and "H2: missing (no card.json or outcomes.json; refusal code live_stop)" in out
    assert out.splitlines()[-1].startswith("pending before any score: H2 -")
    code, out = run(edit=remove_run("H2"), flags=("--after-reruns",))
    assert code == 0 and "== 8. Full history" in out and "row H incomplete: repeats used ['H1']" in out
    assert "-- H2: missing after its rerun (refusal code live_stop)" in out.splitlines()
    assert "-- H mean of ['H1'] (incomplete)" in out.splitlines()
    code, out = run(edit=remove_run("O2"), flags=("--after-reruns",))
    value = flags(out, "Drift, value twins")
    assert code == 0 and "c 100 (100.0)" in value[0] and "check 1 O2" not in out
    assert all(x.endswith("status unresolved") for x in value[1:4]) and value[4].endswith(
        "classification: low unresolved; near-solved by naive retrieval unresolved; near-solved without memory unresolved")


def test_a_row_with_no_usable_repeat_counts_no_pair(run):
    def remove(*names):
        def edit(label, path):
            for name in names:
                remove_run(name)(label, path)
        return edit

    def section(out, start, end):
        return out.split(start)[1].split(end)[0].splitlines()

    # Both H repeats missing after their reruns: H has no points, no support and no comparison.
    code, out = run(edit=remove("H1", "H2"), flags=("--after-reruns",))
    lines = out.splitlines()
    at = lines.index("-- H mean of [] (incomplete)")
    assert code == 0 and all(": common pairs 0 right n/a" in x for x in lines[at + 1:at + 7])
    heads = [x for x in section(out, "== 7.", "== 8.") if x.startswith("  H ")]
    gone = "; ".join(f"H minus {row} unresolved (no usable H repeat) on 0 pairs" for row in "FRO")
    assert len(heads) == 4 and all(f": H unresolved (no usable repeat) on 0 pairs; against {gone} (" in x for x in heads)
    # Both F repeats missing: only the comparisons with F are unresolved, on 0 pairs.
    code, out = run(edit=remove("F1", "F2"), flags=("--after-reruns",))
    seven = section(out, "== 7.", "== 8.")
    lines = out.splitlines()
    at = lines.index("-- F mean of [] (incomplete)")
    assert code == 0 and all(": common pairs 0 right n/a" in x for x in lines[at + 1:at + 7])
    assert ("  H Drift, value twins: H points 0 (0.0) on its own 4 scored pairs; against H minus F unresolved (no"
            " usable F repeat) on 0 pairs; R 100 (100.0), H 0 (0.0), H minus R -100 (-100.0) on 4 pairs; O 100 (100.0),"
            " H 0 (0.0), H minus O -100 (-100.0) on 4 pairs (each comparison on the pairs scored in every repeat of"
            " both rows)") in seven
    assert "    H minus F, Drift, value twins, per life (pairs): unresolved (no usable repeat)" in seven
    # Every control repeat missing: the flags' common support is empty, and every comparison is unresolved.
    code, out = run(edit=remove(*table.ROWS["F"], *table.ROWS["R"], *table.ROWS["O"]), flags=("--after-reruns",))
    check6 = next(x for x in out.splitlines() if x.startswith("check 6:"))
    assert code == 0 and check6.endswith(" total 0")
    value = next(x for x in section(out, "== 7.", "== 8.") if x.startswith("  H Drift, value twins:"))
    assert ("against H minus F unresolved (no usable F repeat) on 0 pairs; H minus R unresolved (no usable R repeat)"
            " on 0 pairs; H minus O unresolved (no usable O1 or O2 repeat) on 0 pairs (") in value


def test_pins_compare_in_full_and_optional_rows_need_the_same_code(run):
    def card_pins(**pins):
        def edit(label, path):
            if label in pins:
                card = json.loads((path / "card.json").read_text())
                card["pins"].update(pins[label])
                (path / "card.json").write_text(json.dumps(card))
        return edit

    # Two benchmark commits that share their first 12 characters still differ.
    code, out = run(edit=card_pins(H2=dict(benchmark_commit="b" * 12 + "e" * 28)))
    assert code == 3 and "== 3." not in out and "one commit for every core arm (card pins equal) False" in out
    assert "PIN MISMATCH: benchmark_commit: bbbbbbbbbbbb (F1,F2,R1,R2,O1,O2,O3,H1); bbbbbbbbbbbb (H2)" in out.splitlines()
    # An optional row at another scorer commit is shown, marked, and left out of the comparisons ...
    code, out = run(extra=("X-omega",), edit=card_pins(**{"X-omega": dict(scorer_commit="e" * 40)}))
    assert code == 0 and "X-omega: not run as declared (different code pins)" in out.splitlines()
    assert "  X-omega " not in out.split("== 7.")[1]
    # ... but its own system pins may differ.
    code, out = run(extra=("X-omega",), edit=card_pins(**{"X-omega": dict(system_hash="s" * 64, route_table_hash="t" * 64)}))
    assert code == 0 and "not run as declared" not in out and "  X-omega " in out.split("== 7.")[1]


def test_pack_hash_must_match_the_packs(run):
    def other_pack(label, path):
        if label == "H2":
            card = json.loads((path / "card.json").read_text())
            card["pack_hash"] = "e" * 64
            (path / "card.json").write_text(json.dumps(card))

    code, out = run(edit=other_pack)
    assert code == 3 and "== 3." not in out
    assert any(x.startswith("PACK MISMATCH: H2 pack_hash eeeeeeeeeeee (--packs ") for x in out.splitlines())
    assert out.splitlines()[-1] == "PACK DIFFERS from --packs for a core arm (see PACK MISMATCH above): not pooled"
    assert "PACK MISMATCH" not in run()[1]


def test_failed_optional_attempt(run):
    def refuse(label, path):
        if label == "X-omega":
            for name in ("card.json", "outcomes.json"):
                (path / name).unlink()
            write(path / "refusal.json", dict(code="live_stop", detail=["REFUSALDETAILZQ"]))

    code, out = run(extra=("X-omega",), edit=refuse)
    assert code == 0 and "X-omega: attempt failed, refusal code live_stop" in out.splitlines()
    assert "REFUSALDETAILZQ" not in out and "== 7." in out and "  X-omega " not in out.split("== 7.")[1]

    def refuse_c7(label, path):
        if label == "X-omega":
            for name in ("card.json", "outcomes.json"):
                (path / name).unlink()
            write(path / "refusal.json", dict(code="c7_changed"))

    assert "X-omega: attempt failed, refusal code c7_changed" in run(extra=("X-omega",), edit=refuse_c7)[1].splitlines()


def test_candidate_says_when_near_solved_flags_were_not_interpreted(run):
    right = {"corr": [1000, 1000]}
    code, out = run({k: right for k in table.CORE if k[0] in "FRO"})
    corr = flags(out, "Drift, correction twins")
    assert code == 0 and "f 100 (100.0) r 100 (100.0) c 100 (100.0)" in corr[0]
    assert corr[4].endswith("classification: candidate (near-solved flags not interpreted: c <= f or c <= 0)")
    assert flags(out, "Drift, value twins")[4].endswith("classification: near-solved by naive retrieval")


def test_optional_rows_run_after_the_core_arms_alone(run):
    code, out = run(extra=("X-omega",), slots={"X-omega": ORDER.index("H2")})
    assert code == 3 and "RUN ORDER VIOLATION: X-omega overlaps core arm H2" in out.splitlines() and "== 3." not in out
    code, out = run(extra=("X-omega", "X-holo"))  # both after the core arms, at the same time
    assert code == 0 and "X-omega: not run as declared (overlaps X-holo)" in out.splitlines()
    assert "X-holo: not run as declared (overlaps X-omega)" in out.splitlines()
    assert "-- X-omega (not run as declared: overlaps X-holo)" in out.splitlines()
    assert "  X-omega " not in out.split("== 7.")[1] and "  X-holo " not in out.split("== 7.")[1]
    code, out = run(extra=("X-holo",))
    assert code == 0 and "not run as declared" not in out and "  X-holo " in out.split("== 7.")[1]


def test_optional_rows_never_change_the_core_inventory(run):
    # An optional card from another pack that lists a core task as not scored live changes no core count or flag.
    def excludes(label, path):
        if label == "X-omega":
            card = json.loads((path / "card.json").read_text())
            pair = layout()[0][0]
            card.update(pack_hash="e" * 64, not_scored_live=[[pair[0], "B0", pair[4][0]]])
            (path / "card.json").write_text(json.dumps(card))

    _, base = run()
    code, out = run(extra=("X-omega",), edit=excludes)
    assert code == 0 and "X-omega: not run as declared (different pack)" in out.splitlines()
    six = [next(x for x in o.splitlines() if x.startswith("check 6")) for o in (base, out)]
    assert six[0] == six[1] and "total 8" in six[1]
    assert flags(out, "Drift, value twins") == flags(base, "Drift, value twins")


def test_each_comparison_prints_the_system_on_its_own_pairs(run):
    # F2 misses one value pair and is published after its rerun: H's points beside F are on F's three pairs.
    def drop(label, path):
        if label == "F2":
            data = json.loads((path / "outcomes.json").read_text())
            pair = layout()[0][0]
            for iid in pair[4]:
                del data[f"{pair[0]}/B0/{iid}"]
            (path / "outcomes.json").write_text(json.dumps(data))

    code, out = run(edit=drop, flags=("--after-reruns",))
    line = next(x for x in out.split("== 7.")[1].splitlines() if x.startswith("  H Drift, value twins:"))
    assert code == 0 and line.startswith("  H Drift, value twins: H points 0 (0.0) on its own 4 scored pairs; against")
    assert "against F 0 (0.0), H -100/3 (-33.3), H minus F -100/3 (-33.3) on 3 pairs;" in line


def test_per_life_differences_for_every_comparison(run):
    # H loses to R on value twins (H 1000, 0 | -1000, 0 against R right on all) and beats it on correction twins.
    _, out = run()
    lines = out.split("== 7.")[1].splitlines()
    value = next(x for x in lines if x.startswith("    H minus R, Drift, value twins, per life (pairs"))
    corr = next(x for x in lines if x.startswith("    H minus R, Drift, correction twins, per life (pairs"))
    assert "0 lives left out with none):" in value and "['-500', '-1500']" in value
    assert "sign_flip_p 1/2 0.5000 no significance claimed" in value
    assert "['1000', '1000']" in corr and "sign_flip_p 1/2 0.5000 no significance claimed" in corr
    assert sum(x.startswith("    H minus ") for x in lines) == 4 * 3 + 1


def test_f_no_ids_text_or_paths(run, tmp_path):
    code, out = run(extra=("X-holo", "E1", "E2"))
    assert code == 0
    for section in ("3x. Optional rows", "3e. Extra floor", "Earlier evidence", "== B. Scored", "-- E1 vs E2",
                    "no significance claimed", "== 8. Full history"):
        assert section in out
    pairs, quiz = layout()
    needles = [*LIVES, *quiz.values(), *(p[3] for p in pairs), *(i for p in pairs for i in p[4]), IDENTITY,
               "control text", str(tmp_path), "ITEMZQ", "BUNDLEZQ", "LIFEZQ", *block_hashes().values()]
    assert not [n for n in needles if n in out]
