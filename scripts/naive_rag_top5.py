"""Offline algorithm decision and rebuilt-corpus disclosure for a pinned baseline."""

import argparse
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import traceback
from collections import Counter
from contextlib import closing, contextmanager
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from bicentennial.canon import canon
from bicentennial.controls import naive_rag as control
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.gitenv import git_env
from bicentennial.packs.install import verify
from bicentennial.packs.scoring import control_input, make_score
from bicentennial.runner.life import STEP_S
from bicentennial.systems.pins import PinsRefused, archive_hash
from bicentennial.systems.registry import SystemRefused, load_entry
from bicentennial.world.db import open_world
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule

CLASSES = ("equal", "order_only", "tie", "defect")


class Refused(ValueError):
    pass


def load_json(path):
    return json.loads(path.read_bytes())


def load_archive(entry, source, folder):
    tree = entry["recipe"]["archive_tree"]
    ref = tree["ref"]
    if re.fullmatch(r"[0-9a-f]{40}", ref) is None:
        raise Refused("entry_ref_not_commit")
    recipe = (ref, *((tree["subdirectory"],) if "subdirectory" in tree else ()))
    if archive_hash(source, recipe) != entry["artifact"]["sha256"]:
        raise Refused("pin_mismatch")
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", *recipe],
                             env=git_env(), capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder, filter="data")
    root = folder / tree.get("subdirectory", "")
    # The baseline manifest declares its identity as a top-level scalar.
    try:
        manifest = (root / "plugin.yaml").read_text()
    except (OSError, UnicodeError) as error:
        raise Refused("identity_mismatch") from error
    names = re.findall(r"^name:\s*([^\n]+)$", manifest, re.MULTILINE)
    if len(names) != 1 or names[0].strip().strip("\"'") != entry["recipe"]["provider"]:
        raise Refused("identity_mismatch")
    return root / "__init__.py"


@contextmanager
def load_baseline(path):
    """Load only the extracted package, with a minimal provider base."""
    agent, base = ModuleType("agent"), ModuleType("agent.memory_provider")
    base.MemoryProvider = object
    name = "receipt_baseline"
    with patch.dict(sys.modules, {"agent": agent, "agent.memory_provider": base}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        for child in ("store", "tfidf"):
            child_name = f"{name}.{child}"
            child_spec = importlib.util.spec_from_file_location(child_name, path.with_name(f"{child}.py"))
            child_module = importlib.util.module_from_spec(child_spec)
            sys.modules[child_name] = child_module
            child_spec.loader.exec_module(child_module)
            setattr(module, child, child_module)
        spec.loader.exec_module(module)
        yield module


def score_baseline(baseline, texts, prompt):
    """Score every chunk and obtain the independent top list from the search tool."""
    with tempfile.TemporaryDirectory() as home:
        provider = baseline.NaiveRagProvider()
        provider.initialize("receipt", hermes_home=Path(home))
        try:
            ids = {}
            for eid, text in texts.items():
                added = json.loads(provider.handle_tool_call("naive_rag_add", {"content": text}))
                ids[added["id"]] = eid
            rows = [(s, ids[mid], ordinal, text) for s, mid, ordinal, text in
                    baseline.tfidf.scored(provider.store.memories, prompt)]
            results = json.loads(provider.handle_tool_call("naive_rag_search", {"query": prompt}))["results"]
            top = [[ids.get(r["id"]), r["ordinal"]] for r in results]
            return rows, top
        finally:
            provider.shutdown()


def fraction(value):
    return [value.numerator, value.denominator]


def chunk_rows(rows):
    return {(eid, ordinal): (score, text) for score, eid, ordinal, text in rows}


def pairs(rows):
    return [[eid, ordinal] for _, eid, ordinal, _ in rows]


def compare_rows(expected, actual, control_k, baseline_top):
    """Compare all scores and classify the tool's top list against the control's."""
    left, right = chunk_rows(expected), chunk_rows(actual)
    differing = []
    for eid, ordinal in sorted(left.keys() | right.keys()):
        a, b = left.get((eid, ordinal)), right.get((eid, ordinal))
        if a != b:
            differing.append(dict(event_id=eid, ordinal=ordinal,
                control=None if a is None else dict(score=fraction(a[0]), text=a[1]),
                baseline=None if b is None else dict(score=fraction(b[0]), text=b[1])))
    a = expected[:control_k]
    left_top, right_top = pairs(a), baseline_top
    right_ids = list(map(tuple, right_top))
    scores = [right[k][0] if k in right else None for k in right_ids]
    if (differing or len(a) != len(right_top) or len(set(right_ids)) != len(right_ids)
            or [r[0] for r in a] != scores):
        kind = "defect"
    elif left_top == right_top:
        kind = "equal"
    elif set(map(tuple, left_top)) == set(right_ids):
        kind = "order_only"
    else:
        # With identical chunk scores and ranked score sequences, replacements at
        # the cut can only exchange chunks tied at the boundary.
        kind = "tie"
    top_differences = []
    for rank in range(max(len(left_top), len(right_top))):
        left_chunk = left_top[rank] if rank < len(left_top) else None
        right_chunk = right_top[rank] if rank < len(right_top) else None
        if left_chunk != right_chunk:
            top_differences.append(dict(rank=rank + 1, control=left_chunk, baseline=right_chunk))
    return dict(classification=kind, differing_chunks=differing, top_differences=top_differences,
                control_top=left_top, baseline_top=right_top)


class ReceiptRag(control.NaiveRag):
    """Observe the scoring calls made by the unmodified control run."""

    def __init__(self, baseline, calls):
        self.baseline, self.calls = baseline, calls
        super().__init__()

    def query(self, task, now):
        self.item_id = task["task_id"]
        return super().query(task, now)

    def scored(self, prompt, now):
        expected = super().scored(prompt, now)
        visible = [e for e in self.events.values() if e["t_sim"] <= now]
        orders = {}
        for order in ("event_id", "stream"):
            events = sorted(visible, key=lambda e: e["event_id"]) if order == "event_id" else visible
            actual, top = score_baseline(self.baseline, {e["event_id"]: e["text"] for e in events}, prompt)
            orders[order] = compare_rows(expected, actual, control.TOP_K, top)
        self.calls.setdefault(self.item_id, []).append(dict(orders=orders))
        return expected


def part1(inp, score, baseline):
    calls = {}
    with patch.object(control, "NaiveRag", lambda: ReceiptRag(baseline, calls)):
        arm = control.run(inp, score=score)
    counts = Counter({kind: 0 for kind in CLASSES})
    non_equal = []
    for iid in sorted(calls):
        kind = max((o["classification"] for c in calls[iid] for o in c["orders"].values()),
                   key=CLASSES.index)
        counts[kind] += 1
        if kind != "equal":
            non_equal.append(dict(item_id=iid, classification=kind, calls=sorted(
                calls[iid], key=lambda c: max(CLASSES.index(o["classification"])
                                             for o in c["orders"].values()), reverse=True)))
    return dict(counts=dict(counts), non_equal=non_equal,
                scoring_calls=sum(map(len, calls.values())), orders=["event_id", "stream"]), arm["retrieved"]


def rebuild(compiled, life_dir, branch, schedule, entry):
    """Replay only scripted write turns; snapshot their corpus before each probe."""
    rows = [json.loads(line) for line in (life_dir / f"stream.{branch}.jsonl").read_bytes().splitlines()]
    sources = {}
    for row in rows:
        if "text" in row:
            sources.setdefault(row["turn_key"], set()).add(row["event_id"])
    responder = ScriptedResponder(entry)
    write = entry["recipe"]["write"]
    tools = [dict(type="function", function=dict(name=write["tool"], parameters={}))]
    memories, origins, snapshots = {}, {}, {}
    probes = {p.index: p for p in compiled.probes}
    for session in compiled.script["sessions"]:
        if session["kind"] == "probe":
            for iid in probes[session["index"]].item_ids:
                snapshots[iid] = (dict(memories), dict(origins))
            continue
        plan = schedule.sessions[session["index"] - 1]
        for turn in session["turns"]:
            messages = [dict(role="user", content=turn["user"])]
            call = Call("write_turn", "write_turn", "chat", dict(messages=messages, tools=tools),
                        "scripted", dict(session=session["index"], turn=turn["n"]), "receipt")
            for tool in responder._write(call, messages):
                mid = f"m{len(memories) + 1:06d}"
                memories[mid] = json.loads(tool["arguments"])[write["content_key"]]
                origins[mid] = sorted(sources.get(f"{plan.session_id}/t{turn['n']}", ()))
    return snapshots


def compiled_corpora(pack_dir, entry):
    life_dir = pack_dir / "sealed/life"
    life = load_json(life_dir / "life.json")
    schedule = build_schedule(life["seed"], life["life"], named(life["scale"]))
    result = {}
    for branch in ("B0", "B1"):
        items = load_json(life_dir / f"items.{branch}.json")
        with closing(open_world(life_dir / f"world.{branch}.db", readonly=True)) as db:
            compiled = compile_script(life_dir, branch, schedule, db, items=items, step_s=STEP_S)
        result.update(rebuild(compiled, life_dir, branch, schedule, entry))
    return result


def source_events(top, origins=None):
    return {event for eid, _ in top for event in (origins.get(eid, ()) if origins is not None else [eid])}


def jaccard(a, b):
    return str(Fraction(len(a & b), len(a | b))) if a | b else "1"


def part2(inp, baseline, retrieved, corpora):
    items, mismatches = [], []
    keys = {k["item_id"]: k for k in inp.keys}
    for iid in sorted(retrieved):
        memories, origins = corpora[iid]
        prompt = keys[iid]["recall_query"]
        actual, top = score_baseline(baseline, memories, prompt)
        adapter = control.NaiveRag()
        # Each memory is one event; lexical order of these fixed-width ids is
        # write order for the bounded T1 corpus.
        adapter.events = {mid: dict(text=text, t_sim=0) for mid, text in memories.items()}
        expected = adapter.scored(prompt, 0)
        comparison = compare_rows(expected, actual, control.TOP_K, top)
        if comparison["classification"] != "equal":
            mismatches.append(dict(item_id=iid, comparison=comparison))
        sources = source_events(top, origins)
        items.append(dict(item_id=iid, control=jaccard(sources, source_events(retrieved[iid])),
                          same_corpus=jaccard(sources, source_events(pairs(expected[:control.TOP_K]), origins))))
    return dict(items=items, counts={key: dict(sorted(Counter(i[key] for i in items).items()))
                                    for key in ("control", "same_corpus")},
                corpus_check_mismatch=mismatches)


def receipt(entry, entry_sha256, pack_hash, packs, index, baseline):
    decisions, disclosures = [], []
    for rel in sorted(index["packs"]):
        pack_dir = packs / rel
        inp = control_input(pack_dir)
        score = make_score(load_json(pack_dir / "sealed/scoring.json"))
        decision, retrieved = part1(inp, score, baseline)
        decisions.append(dict(pack_id=inp.pack["pack_id"], **decision))
        disclosures.append(dict(pack_id=inp.pack["pack_id"], **part2(
            inp, baseline, retrieved, compiled_corpora(pack_dir, entry))))
    return dict(entry=dict(name=entry["name"], ref=entry["recipe"]["archive_tree"]["ref"],
                           sha256=entry["artifact"]["sha256"], file_sha256=entry_sha256),
                pack_hash=pack_hash,
                part1=dict(counts={k: sum(p["counts"][k] for p in decisions) for k in CLASSES}, packs=decisions),
                part2=dict(basis="rebuilt from the compiled script, not observed",
                           omissions="Hermes memory_write requests are not modelled",
                           counts={k: dict(sorted(Counter(i[k] for p in disclosures for i in p["items"]).items()))
                                   for k in ("control", "same_corpus")}, packs=disclosures),
                **{"pass": not any(p["counts"]["defect"] for p in decisions)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("entry", "plugin-source", "packs", "pack-hash", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        entry = load_entry(args.entry)
        entry_sha256 = sha256(Path(args.entry).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path = load_archive(entry, args.plugin_source, Path(folder))
            try:
                index = verify(args.packs, pack_hash=args.pack_hash)
            except (OSError, ValueError) as error:
                raise Refused("pack_hash_mismatch") from error
            if index["tier"] != "T1":
                raise Refused("pack_not_t1")
            with load_baseline(path) as baseline:
                result = receipt(entry, entry_sha256, args.pack_hash, Path(args.packs), index, baseline)
        Path(args.out).write_bytes(canon(result))
    except SystemRefused as error:
        print(error.reasons[0], file=sys.stderr)
        return 3
    except (Refused, PinsRefused) as error:
        print(str(error), file=sys.stderr)
        return 3
    except Exception:
        # The CLI's unexpected-failure convention: a crash writes no receipt and never shares exit 1 with a defect.
        print("tool_failure", file=sys.stderr)
        traceback.print_exc()
        return 70
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
