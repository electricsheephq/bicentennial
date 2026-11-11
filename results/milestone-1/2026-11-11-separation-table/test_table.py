"""Synthetic fixture tests for table.py: flag rules, checks 1, 2 and 7, common support, filter yield, no ids printed.

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
BASE = {"F": {"value": [0] * 4, "corr": [0] * 2, "wake": [0] * 2},
        "R": {"value": [1000] * 4, "corr": [0] * 2, "wake": [0] * 2},
        "O": {"value": [1000] * 4, "corr": [1000] * 2, "wake": [0] * 2},
        "H": {"value": [1000, 0, -1000, 0], "corr": [1000] * 2, "wake": [0] * 2}}


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
    verdict = {1000: "PASS", 0: "OMISSION", -1000: "FAIL_MEMORY"}.get(score) if stage == "act" else None
    return dict(score_milli=score, failure_class=None, base_verdict=verdict, stage=stage, cell_id=cell,
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


def make_arm(path, label, spec, twins=None, cached=False, extra_floor=False):
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
    write(path / "card.json", dict(tier="T2", system="hermes-native", model="m", effort="medium", pack_hash="p" * 64,
                                   pins=dict(scorer_commit="c" * 40), served_identity=IDENTITY, not_scored_live=[],
                                   floor=dict(served_identity=IDENTITY, units=units)))
    write(path / "outcomes.json", out)
    write(path / "units.json", dict(start_ms=1793796303380, end_ms=1793802913487))
    write(path / "disclosures.json", dict(floor={u: dict(cached=v["cached"], reason="r") for u, v in units.items()}))
    if letter in table.CONTROL:
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

    def go(specs=None, twins=None, cached=(), extra=(), edit=None):
        specs = {k: dict(BASE[k[0]], **(specs or {}).get(k, {})) for k in table.CORE} | {k: BASE["H"] for k in extra}
        argv = ["--packs", str(packs), "--order", "F1,R1,O1,H1,H2,O2,R2,F2,O3"]
        for label, spec in specs.items():
            path = make_arm(tmp_path / "runs" / label, label, spec, (twins or {}).get(label), label in cached,
                            extra_floor=label in ("H1", "E1", "E2"))
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
    assert "naive: on means applies margin_pairs 6/5 (1.2)" in value[2] and value[4].endswith("classification: naive")
    assert corr[4].endswith("classification: candidate")
    assert "naive: on means not interpreted" in wake[2] and wake[4].endswith("classification: low")
    # Co-occurring low and naive, stable across all combinations.
    half = {"wake": [1000, 0]}
    code, out = run({"R1": half, "R2": half, "O1": half, "O2": half, "O3": half})
    assert flags(out, "Wake")[4].endswith("classification: low + naive; low governs first (§6)")
    # Instability, and c over O1,O2 against c over all three.
    code, out = run({"O3": {"value": [0] * 4}})
    value = flags(out, "Drift, value twins")
    assert "c 100 (100.0) c over O1,O2,O3 200/3 (66.7)" in value[0]
    assert "low: on means no" in value[1] and "combinations 3 agreeing 2 status unstable" in value[1]
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
            data = json.loads((path / "outcomes.json").read_text())
            data[next(k for k in sorted(data) if data[k]["stage"] == "act")]["in_context"] = False
            (path / "outcomes.json").write_text(json.dumps(data))

    for kw, name, check in ((dict(edit=one_byte), "R1", "check 1 R1"), (dict(cached=("F2",)), "F2", "check 7 F2"),
                            (dict(edit=context), "O2", "check 2 O2")):
        code, out = run(**kw)
        assert code == 3 and out.splitlines()[-1] == f"INVALID CONTROL ROW {name}"
        assert [x for x in out.splitlines() if x.startswith("INVALID")] == [f"INVALID CONTROL ROW {name}"]
        assert next(x for x in out.splitlines() if x.startswith(check)).endswith("pass False")
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
    code, dropped = run(specs, edit=drop)
    assert code == 0
    six = [next(x for x in out.splitlines() if x.startswith("check 6")) for out in (base, dropped)]
    assert "'Drift, value twins': 4" in six[0] and "'Drift, value twins': 3" in six[1] and "total 7" in six[1]
    before, after = flags(base, "Drift, value twins"), flags(dropped, "Drift, value twins")
    assert before[0].startswith("-- Drift, value twins: common pairs 4 f 25 (25.0) r 75 (75.0) c 100 (100.0)")
    assert after[0].startswith("-- Drift, value twins: common pairs 3 f 0 (0.0) r 200/3 (66.7) c 100 (100.0)")
    assert all(a != b for a, b in zip(before[:4], after[:4], strict=True))
    assert after[4].endswith("classification: unresolved") and "row F incomplete" in dropped
    mean = [next(x for x in out.split("-- F mean")[1].splitlines() if "value twins" in x) for out in (base, dropped)]
    assert "common pairs 4" in mean[0] and "common pairs 3" in mean[1]
    assert "check 5 F2: scored action tasks assigned 16 scored 14 BLOCKED 0 missing 2 complete False" in dropped


def test_e_filter_yield(run):
    # Correction pair 0: twins pass 3 and 2 of 3 (kept); pair 1: twins pass 3 and 1 of 3 (not kept).
    twins = {"O2": {("corr", 1, 1): 0}, "O3": {("corr", 0, 1): 0, ("corr", 1, 1): 0}}
    _, out = run(twins=twins)
    assert ("  Drift, correction twins: pairs 2 both twins pass 1 twins by trials passed {1: 1, 2: 1, 3: 2}"
            in out.splitlines())
    assert "  Drift, value twins: pairs 4 both twins pass 4 twins by trials passed {3: 8}" in out.splitlines()
    assert "Prospective filter yield; validates nothing" in out


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
