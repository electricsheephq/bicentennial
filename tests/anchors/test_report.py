"""Public-pack goldens, pinned-control equivalence and cross-process bytes."""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.anchors import WINDOW, run
from bicentennial.anchors.report import ANCHORS, REPO, header, main, screen
from bicentennial.controls.cache import (
    CONTROL_FILES,
    PACKAGE_ROOT,
    READER_FILES,
    code_sha256,
)
from bicentennial.packs.scoring import SCORING_FILES, control_input, make_score
from bicentennial.world.tokens import estimate_tokens

GOLDEN = Path(__file__).with_name("golden.json")


def load(path):
    return json.loads(path.read_bytes())


def test_public_t2_golden_citations_and_budgets(public_pack):
    inp = control_input(public_pack)
    keys = {k["item_id"]: k for k in inp.keys}
    golden = load(GOLDEN)
    for name, cls in ANCHORS.items():
        assert len(golden[name]) == 3
        for iid, citations in golden[name].items():
            key = keys[iid]
            adapter = cls()
            for e in inp.events[key["life"]][key["branch"]]:
                adapter.ingest(e)
            result = adapter.query(dict(task_id=iid, prompt=key["recall_query"]), inp.now[iid])
            assert result["citations"] == citations
            if name != "bm25":
                assert estimate_tokens(result["output"]) <= WINDOW


def test_screen_sealed_presence_scores_hashes_and_sensitivity(public_pack):
    report = screen(public_pack)
    sealed = load(public_pack / "sealed/naive_rag.json")["arm"]
    presence = {r["item_id"]: r["in_context"] for r in sealed["reports"]}
    assert {r["item_id"]: r["anchors"]["naive_rag"]["presence"] for r in report["items"]} == presence
    inp = control_input(public_pack)
    score = make_score(load(public_pack / "sealed/scoring.json"))
    for name, cls in ANCHORS.items():
        spec = report["header"]["anchors"][name]
        assert spec["spec_sha256"] == sha256((REPO / spec["spec"]).read_bytes()).hexdigest()
        assert spec["code_sha256"] == code_sha256(spec["code_files"])
        expected = {r["item_id"]: r for r in run(inp, cls, score=score)["reports"]}
        for row in report["items"]:
            reader = row["anchors"][name]["reader"]
            assert reader == expected[row["item_id"]]
            assert reader["recall_basis"] == ("chunk_quote" if name == "bm25" else "event_quote")
    assert report["pairs"]
    for template, anchors in report["templates"].items():
        for name, counts in anchors.items():
            values = [p["anchors"][name]["score_milli"] for p in report["pairs"]
                      if p["template_ref"] == template]
            assert counts == dict(pairs=len(values), right=sum(v > 0 for v in values),
                confidently_wrong=sum(v < 0 for v in values), no_credit=sum(v == 0 for v in values),
                net_pair_points_milli=sum(values))
    for w in (4096, 65536):
        expected = {r["item_id"]: r["in_context"] for r in run(
            inp, ANCHORS["recent_window"], score=score, window=w)["reports"]}
        assert {r["item_id"]: r["recent_window_presence"][str(w)] for r in report["items"]} == expected


def test_json_byte_determinism_and_safe_summary(public_pack, tmp_path):
    outputs = []
    for seed in ("1", "987654"):
        out = tmp_path / f"report-{seed}.json"
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(REPO / "src"))
        code = ("import runpy,sys; "
                "sys.addaudithook(lambda e,a: (_ for _ in ()).throw(AssertionError(e)) "
                "if e.startswith('socket.') else None); "
                "runpy.run_module('bicentennial.anchors.report',run_name='__main__')")
        proc = subprocess.run([sys.executable, "-c", code, "--packs", str(public_pack.parent),
            "--out", str(out)], check=True, capture_output=True, env=env, text=True)
        outputs.append((out.read_bytes(), proc.stdout))
        assert proc.stderr == ""
        pack = load(public_pack / "sealed/pack.json")
        for item in pack["items"]:
            assert item["item_id"] not in proc.stdout
            assert item["prompt"] not in proc.stdout
        assert "seed" not in proc.stdout
        assert all(line.split()[0] in load(out)["templates"] for line in proc.stdout.splitlines())
    assert outputs[0] == outputs[1]


def test_tasks_select_complete_pairs_and_refuse_missing_or_split(public_pack, tmp_path, capsys):
    pack = load(public_pack / "sealed/pack.json")
    selected = pack["bundles"][0]["items"]
    tasks, out = tmp_path / "tasks.json", tmp_path / "report.json"
    tasks.write_text(json.dumps(dict(rows=[dict(item_id=i) for i in selected])))
    main(["--packs", str(public_pack), "--out", str(out), "--tasks", str(tasks)])
    assert {r["item_id"] for r in load(out)["items"]} == set(selected)
    assert len(load(out)["pairs"]) == 1
    stdout = capsys.readouterr().out
    assert all(i not in stdout for i in selected)
    for ids, error in ((selected[:1], "splits a pair"), (["absent"], "absent from packs")):
        tasks.write_text(json.dumps(dict(rows=[dict(item_id=i) for i in ids])))
        with pytest.raises(ValueError, match=error):
            screen(public_pack, tasks)


def test_no_pack_refused(tmp_path):
    with pytest.raises(ValueError, match="no built packs"):
        screen(tmp_path)


def test_four_pins_unchanged_and_anchor_hashes_outside_controls():
    assert not any(p.startswith("anchors/") for p in CONTROL_FILES)
    scorer = [p.relative_to(PACKAGE_ROOT).as_posix() for p in sorted((PACKAGE_ROOT / "score").glob("*.py"))]
    assert [code_sha256(files) for files in (CONTROL_FILES, READER_FILES, SCORING_FILES, scorer)] == [
        "848935cdb04ff6dd3937a00d592f3cf933a42d69d96f8ca7d36e1506c31c1b63",
        "90ed83e9bed4b80088108199d2434e03d078a2995ca6eca9023858125eb6835f",
        "925f3fc812fd80974eea1780b359b58bbcd5f35c338b1f2daf710e6adfe49880",
        "0e5979ff5aff33f28ee6bd2d508174356dcd0c644e05f1208746257cae976f82"]
    for name, pin in header()["anchors"].items():
        assert "anchors/__init__.py" in pin["code_files"]
        assert f"anchors/{'window' if name == 'recent_window' else name}.py" in pin["code_files"]
