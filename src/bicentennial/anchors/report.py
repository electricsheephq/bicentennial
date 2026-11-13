"""Offline scripted screen; stdout contains only template-level counts."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.controls import naive_rag
from bicentennial.controls.cache import PACKAGE_ROOT, code_sha256, import_closure
from bicentennial.packs.scoring import control_input, make_score

from . import run
from .bm25 import BM25
from .grep import Grep
from .window import RecentWindow

ANCHORS = {"bm25": BM25, "grep": Grep, "recent_window": RecentWindow}
REPO = PACKAGE_ROOT.parents[1]


def load(path):
    return json.loads(path.read_bytes())


def header():
    anchors = {}
    for name, cls in ANCHORS.items():
        spec = f"specs/controls/{name}.md"
        files = import_closure(("anchors/__init__.py", cls.__module__.replace(
            "bicentennial.", "").replace(".", "/") + ".py"))
        anchors[name] = dict(version=1, spec=spec, spec_sha256=sha256((REPO / spec).read_bytes()).hexdigest(),
                             code_sha256=code_sha256(files), code_files=list(files))
    return dict(anchors=anchors, report_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                naive_rag_spec_sha256=sha256((REPO / "specs/controls/naive_rag.md").read_bytes()).hexdigest(),
                naive_rag_code_sha256=code_sha256(import_closure(("controls/naive_rag.py",))),
                window=16384, sensitivity_windows=[4096, 65536],
                score_label="scripted proxy; not a bound on a live reader's score",
                pair_policy="sealed bundle minimum; right > 0, confidently wrong < 0, no credit = 0")


def screen(packs, tasks=None):
    selected = None if tasks is None else {r["item_id"] for r in load(Path(tasks))["rows"]}
    found, rows, totals, pairs = set(), [], {}, []
    root = Path(packs)
    paths = [root / "sealed/pack.json"] if (root / "sealed/pack.json").is_file() else sorted(
        root.rglob("sealed/pack.json"))
    if not paths:
        raise ValueError("no built packs")
    for path in paths:
        pack_dir = path.parent.parent
        inp = control_input(pack_dir)
        refs = {r["item_id"]: f"{r['template_id']}-v{r['template_version']}"
                for r in load(pack_dir / "sealed/records.json")}
        score = make_score(load(pack_dir / "sealed/scoring.json"))
        arms = dict(naive_rag=naive_rag.run(inp, score=score), **{
            name: run(inp, cls, score=score) for name, cls in ANCHORS.items()})
        reports = {name: {r["item_id"]: r for r in arm["reports"]} for name, arm in arms.items()}
        outcomes = {name: {r["item_id"]: r for r in arm["items"]} for name, arm in arms.items()}
        sensitivity = {str(w): {r["item_id"]: r["in_context"] for r in run(
            inp, RecentWindow, score=score, window=w)["reports"]} for w in (4096, 65536)}
        ids = set(refs) if selected is None else set(refs) & selected
        if found & ids:
            raise ValueError("duplicate item across packs")
        found.update(ids)
        for iid in sorted(ids):
            totals.setdefault(refs[iid], {n: dict(pairs=0, right=0, confidently_wrong=0,
                no_credit=0, net_pair_points_milli=0) for n in arms})
            rows.append(dict(item_id=iid, template_ref=refs[iid], anchors={n: dict(
                presence=reports[n][iid]["in_context"], reader=reports[n][iid], outcome=outcomes[n][iid])
                for n in arms}, recent_window_presence={w: sensitivity[w][iid] for w in sensitivity}))
        for bundle in inp.pack["bundles"]:
            members = set(bundle["items"])
            if not members & ids:
                continue
            if not members <= ids:
                raise ValueError("task selection splits a pair")
            templates = {refs[i] for i in members}
            if len(templates) != 1:
                raise ValueError("pair has different template refs")
            ref = templates.pop()
            pairs.append(dict(bundle_id=bundle["bundle_id"], template_ref=ref, anchors={
                n: next(b for b in a["bundles"] if b["bundle_id"] == bundle["bundle_id"])
                for n, a in arms.items()}))
            for name, arm in arms.items():
                value = next(b["score_milli"] for b in arm["bundles"] if b["bundle_id"] == bundle["bundle_id"])
                if value is None:
                    raise ValueError("unscored pair")
                counts = totals[ref][name]
                counts["pairs"] += 1
                counts["right" if value > 0 else "confidently_wrong" if value < 0 else "no_credit"] += 1
                counts["net_pair_points_milli"] += value
    if selected is not None and found != selected:
        raise ValueError("tasks contain items absent from packs")
    return dict(header=header(), items=sorted(rows, key=lambda r: r["item_id"]),
                pairs=sorted(pairs, key=lambda p: p["bundle_id"]), templates=totals)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, help="TASKS.json with rows containing item_id; whole pairs only")
    args = parser.parse_args(argv)
    report = screen(args.packs, args.tasks)
    args.out.write_bytes(canon(report) + b"\n")
    for ref, anchors in sorted(report["templates"].items()):
        print(ref, " ".join(f"{n}:" + ",".join(f"{k}={v}" for k, v in c.items())
                            for n, c in anchors.items()))


if __name__ == "__main__":
    main()
