"""Offline receipts, archived-code mutations and deterministic T1 reconstruction."""

import importlib.util
import json
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.controls import naive_rag as control
from bicentennial.controls.common import ControlInput
from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.gitenv import git_env
from bicentennial.items.protocol import CANARY
from bicentennial.packs.build import build_tier
from bicentennial.packs.install import install
from bicentennial.score.qa import score_qa
from bicentennial.systems.pins import archive_hash

ROOT = Path(__file__).resolve().parents[1]
SUBDIRECTORY = "baselines/naive-rag-hermes"
REF = "aa30438e9c3402f6a4e761174694e33b1de1f3aa"
SPEC = importlib.util.spec_from_file_location("top5_receipt", ROOT / "scripts/naive_rag_top5.py")
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)


def git(source, *args):
    return subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                          check=True, env=git_env()).stdout.decode().strip()


def entry_for(source, ref):
    return dict(name="naive-rag-dev", licence="Apache-2.0", harness="hermes",
        artifact=dict(name="naive-rag-dev", version="1.0.0", sha256=archive_hash(source, (ref, SUBDIRECTORY))),
        fresh_install_hash="2" * 64,
        write_tools=[dict(tool=t, actions=[]) for t in ("naive_rag_add", "naive_rag_delete")],
        read_tools=["naive_rag_search"],
        surfaces=[dict(root="HERMES_HOME", relative=".", volatile_paths=[])],
        own_model_routes=[], structured_formats={}, settle=dict(kind="none", bound_s=0),
        machine_class="light", benchmark_operator_runs=True,
        recipe=dict(provider="naive-rag-dev", archive_tree=dict(ref=ref, subdirectory=SUBDIRECTORY),
            enabled=True, worker_environment={}, file_time_sites=[], unscripted=[],
            write=dict(tool="naive_rag_add", fixed={}, content_key="content")))


def toml(value):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k) + " = " + toml(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(toml, value)) + "]"
    return json.dumps(value, ensure_ascii=False)


def write_entry(path, entry):
    path.write_text("\n".join(json.dumps(k) + " = " + toml(v) for k, v in entry.items()))
    return path


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / SUBDIRECTORY, source / SUBDIRECTORY,
                    ignore=shutil.ignore_patterns("__pycache__"))
    git(source, "init", "-q")
    git(source, "add", SUBDIRECTORY)
    env = dict(git_env(), GIT_AUTHOR_NAME="Fixture", GIT_COMMITTER_NAME="Fixture",
               GIT_AUTHOR_EMAIL="fixture", GIT_COMMITTER_EMAIL="fixture",
               GIT_AUTHOR_DATE="2000-01-01T00:00:00Z", GIT_COMMITTER_DATE="2000-01-01T00:00:00Z")
    subprocess.run(["git", "-C", str(source), "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"],
                   env=env, check=True, capture_output=True)
    return source, entry_for(source, git(source, "rev-parse", "HEAD"))


@pytest.fixture(scope="module")
def packs(tmp_path_factory):
    root = tmp_path_factory.mktemp("t1-packs")
    started = time.monotonic()
    result = build_tier("T1", root, harness_artifacts=[])
    print(f"T1 build seconds: {time.monotonic() - started:.3f}")
    installed = root / "installed"
    digest = install(root / "T1", installed)
    assert digest == result["pack_hash"]
    return installed, digest


def invoke(tmp_path, source, packs, entry=None, name="receipt.json", cli=False):
    repo, original = source
    path = write_entry(tmp_path / "entry.toml", entry or original)
    out = tmp_path / name
    args = ["--entry", str(path), "--plugin-source", str(repo), "--packs", str(packs[0]),
            "--pack-hash", packs[1], "--out", str(out)]
    if cli:
        child = subprocess.run([sys.executable, "-P", str(ROOT / "scripts/naive_rag_top5.py"), *args],
                               capture_output=True, text=True)
        assert not child.stderr, child.stderr
        status = child.returncode
    else:
        status = receipt.main(args)
    return status, out


def read(path):
    return json.loads(path.read_bytes())


def test_built_archive_passes(source, packs, tmp_path):
    # A dirty checkout must never be imported in place of the archive.
    for file in ("__init__.py", "store.py", "tfidf.py"):
        (source[0] / SUBDIRECTORY / file).write_text("raise AssertionError('checkout imported')\n")
    status, out = invoke(tmp_path, source, packs, cli=True)
    result = read(out)
    assert status == 0 and result["pass"]
    assert result["part1"]["counts"]["defect"] == 0
    assert sum(result["part1"]["counts"].values()) > 0
    assert all(p["orders"] == ["event_id", "stream"] and p["scoring_calls"] > 0
               for p in result["part1"]["packs"])
    assert result["part2"]["basis"] == "rebuilt from the compiled script, not observed"
    assert "memory_write" in result["part2"]["omissions"]
    assert all(not p["corpus_check_mismatch"] for p in result["part2"]["packs"])
    assert result["entry"]["file_sha256"] == sha256((tmp_path / "entry.toml").read_bytes()).hexdigest()


def test_real_v1_archive_passes(packs, tmp_path):
    present = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", REF + "^{commit}"],
                             capture_output=True, env=git_env()).returncode == 0
    if not present:
        pytest.skip("v1 archive commit is absent in this shallow clone")
    source = ROOT, entry_for(ROOT, REF)
    status, out = invoke(tmp_path, source, packs)
    assert status == 0 and read(out)["part1"]["counts"]["defect"] == 0
    assert read(out)["entry"]["ref"] == REF
    assert read(out)["entry"]["sha256"] == archive_hash(ROOT, (REF, SUBDIRECTORY))


def synthetic_input():
    items, keys, events, now = [], [], {}, {}
    for life in ("life-a", "life-b"):
        events[life] = {}
        for branch in ("B0", "B1"):
            texts = ["alpha"] * 7 + ["alpha " + "x" * 234 + " b", "unrelated"]
            stream = [dict(event_id=f"e{n:02d}", text=text, t_sim=0, kind="message", actor="user")
                      for n, text in enumerate(texts)]
            # All API event kinds, with a call preceding its result in stream order.
            stream[0]["kind"] = "tool_call"
            stream[1].update(kind="tool_result", call_id=stream[0]["event_id"])
            stream = [stream[0], stream[1], *reversed(stream[2:])]
            stream.append(dict(event_id="future", text="alpha future", t_sim=100, kind="message", actor="user"))
            events[life][branch] = stream
            iid = life + "-" + branch
            items.append(dict(canary=CANARY, item_id=iid, stage="remember", track="Recall", cell_id="RECALL-ABST",
                probe_point=1, prompt="Public prompt differs from the sealed query", options=[dict(
                    option_id=iid + "-u", tokens=[], envelope=dict(type="unknown", value=None, confidence_milli=0))],
                gold=dict(option_id=iid + "-u", never_observed=True), gold_spans=[],
                decision_table_ref="unused", precondition=None, memory_tag="memory_exclusive", labels=[]))
            keys.append(dict(canary=CANARY, item_id=iid, life=life, branch=branch, recall_query="alpha",
                             required=[], competing=[], forbidden=[], oracle_spans=[]))
            now[iid] = 1
    pack = dict(canary=CANARY, pack_id="fixture-pack", tier="T1", genre="G2", seeds=[1],
                lives=sorted(events), items=items, bundles=[], qa_order=sorted(now),
                controls={n: "not run in v0.1" for n in
                          ("no_memory", "oracle_evidence", "full_history", "naive_rag")}, hashes={})
    return ControlInput(pack, tuple(keys), events, now, "0" * 64)


def synthetic_run(monkeypatch, tmp_path, source, packs, mutation=None, inp=None, file="tfidf.py"):
    inp = inp or synthetic_input()
    monkeypatch.setattr(receipt, "control_input", lambda p: inp)
    monkeypatch.setattr(receipt, "make_score", lambda obj: lambda item, result: score_qa(
        item, result.envelope, evidence_texts=[]))
    memories = {f"m{n:06d}": e["text"] for n, e in enumerate(
        next(iter(inp.events.values()))["B0"], 1) if e["t_sim"] <= 1}
    origins = {mid: [f"e{n:02d}"] for n, mid in enumerate(memories)}
    monkeypatch.setattr(receipt, "compiled_corpora", lambda *a: {i: (memories, origins) for i in inp.now})
    load = receipt.load_baseline

    @contextmanager
    def mutated(path):
        if mutation:
            before, after = mutation
            target = path.with_name(file)
            text = target.read_text()
            assert before in text
            target.write_text(text.replace(before, after))
        with load(path) as baseline:
            yield baseline

    monkeypatch.setattr(receipt, "load_baseline", mutated)
    return invoke(tmp_path, source, packs)


@pytest.mark.parametrize("mutation", [
    ("TOP_K = 5", "TOP_K = 4"),
    ("CHUNK_CHARS = 240", "CHUNK_CHARS = 239"),
    ("return ln_fixed(1 + F(2 * (n - df) + 1, 2 * df + 1))",
     "return 1 + ln_fixed(1 + F(2 * (n - df) + 1, 2 * df + 1))"),
    ("dot > 0", "dot >= 0"),
], ids=["top_k", "chunk_chars", "idf", "zero_dot"])
def test_algorithm_mutants_are_defects(monkeypatch, tmp_path, source, packs, mutation):
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs, mutation)
    assert status == 1
    assert read(out)["part1"]["counts"]["defect"] > 0 and not read(out)["pass"]


def test_tool_cut_mutant_is_defect(monkeypatch, tmp_path, source, packs):
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs,
        ("len(results) == TOP_K", "len(results) == TOP_K - 1"), file="__init__.py")
    result = read(out)
    assert status == 1 and not result["pass"]
    assert result["part1"]["counts"]["defect"] > 0
    orders = [o for p in result["part1"]["packs"] for i in p["non_equal"]
              for c in i["calls"] for o in c["orders"].values()]
    assert all(not o["differing_chunks"] and len(o["control_top"]) == 5
               and len(o["baseline_top"]) == 4 for o in orders)
    assert all(p["corpus_check_mismatch"] for p in result["part2"]["packs"])


def test_tool_top_matches_scored(source, tmp_path, monkeypatch):
    folder = tmp_path / "archive"
    folder.mkdir()
    with receipt.load_baseline(receipt.load_archive(source[1], source[0], folder)) as baseline:
        texts = {f"m{n:06d}": text for n, text in enumerate(
            ["alpha " * 90, "alpha beta", "alpha", "alpha gamma"] * 2, 1)}
        rows, top = receipt.score_baseline(baseline, texts, "alpha")
        assert len(top) == baseline.tfidf.TOP_K == 5
        assert top == receipt.pairs(rows[:baseline.tfidf.TOP_K])
        assert rows == baseline.tfidf.scored(texts, "alpha")
        # A second call must use a fresh store, including for empty results.
        assert receipt.score_baseline(baseline, {}, "alpha") == ([], [])

        handle = baseline.NaiveRagProvider.handle_tool_call

        def unrecognized_id(provider, tool, args):
            result = json.loads(handle(provider, tool, args))
            if tool == "naive_rag_search":
                result["results"][0]["id"] = "event"
            return json.dumps(result)

        monkeypatch.setattr(baseline.NaiveRagProvider, "handle_tool_call", unrecognized_id)
        rows, top = receipt.score_baseline(baseline, {"event": "alpha"}, "alpha")
        assert top == [[None, 0]]  # An unknown memory id cannot alias an event id.
        assert receipt.compare_rows(rows, rows, control.TOP_K, top)["classification"] == "defect"
        assert receipt.source_events(top, {"event": ["source"]}) == set()


def test_scores_below_top5_decide(monkeypatch, tmp_path, source, packs):
    # The tail has a lower score than all seven alpha-only chunks. Changing its
    # score leaves both top lists intact and must still fail the decision.
    before = "return sorted(ranked, key=lambda r: (-r[0], int(r[1][1:]), r[2]))"
    after = ("ranked = [(s + 1 if 'x' * 234 in text else s, mid, o, text) for s, mid, o, text in ranked]\n"
             "    " + before)
    mutation = before, after
    inp = synthetic_input()
    for branches in inp.events.values():
        for stream in branches.values():
            stream.sort(key=lambda e: e["event_id"])
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs, mutation, inp)
    result = read(out)
    assert status == 1 and result["part1"]["counts"]["defect"] > 0
    calls = [c for p in result["part1"]["packs"] for i in p["non_equal"] for c in i["calls"]]
    assert all(o["control_top"] == o["baseline_top"] and o["differing_chunks"]
               for c in calls for o in c["orders"].values())


def test_stream_order_scores_decide(monkeypatch, tmp_path, source, packs):
    before = "return sorted(ranked, key=lambda r: (-r[0], int(r[1][1:]), r[2]))"
    # In event-id order m000003 is alpha-only; in stream order it is the
    # nonmatching event. Alter a score only when that stream order is present.
    after = ("if memories.get('m000003') == 'unrelated':\n"
             "        ranked = [(s + 1, mid, o, text) for s, mid, o, text in ranked]\n    " + before)
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs, (before, after))
    result = read(out)
    assert status == 1 and result["part1"]["counts"]["defect"] > 0
    calls = [c for p in result["part1"]["packs"] for i in p["non_equal"] for c in i["calls"]]
    assert all(c["orders"]["event_id"]["classification"] == "equal" for c in calls)
    assert all(c["orders"]["stream"]["classification"] == "defect" for c in calls)


def test_reversed_ties_are_not_defects(monkeypatch, tmp_path, source, packs):
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs,
        ("int(r[1][1:]), r[2]", "-int(r[1][1:]), r[2]"))
    result = read(out)
    counts = result["part1"]["counts"]
    assert status == 0 and counts["defect"] == 0
    assert any(p["corpus_check_mismatch"] for p in result["part2"]["packs"])
    assert counts["tie"] + counts["order_only"] > 0


@pytest.mark.parametrize("fault,code", [("sha256", "pin_mismatch"), ("identity", "identity_mismatch"),
                                       ("ref", "entry_ref_not_commit"), ("pack", "pack_hash_mismatch"),
                                       ("tier", "pack_not_t1")])
def test_refusals_write_nothing(source, packs, tmp_path, monkeypatch, capsys, fault, code):
    entry = deepcopy(source[1])
    if fault == "sha256":
        entry["artifact"]["sha256"] = "0" * 64
    elif fault == "identity":
        entry["recipe"]["provider"] = "other-provider"
    elif fault == "ref":
        entry["recipe"]["archive_tree"]["ref"] = "HEAD"
    elif fault == "tier":
        # A correctly hashed pack of another tier passes verify; only the T1 check refuses it.
        verified = receipt.verify
        monkeypatch.setattr(receipt, "verify", lambda *a, **k: dict(verified(*a, **k), tier="T2"))
    else:
        packs = packs[0], "0" * 64
    monkeypatch.setattr(receipt, "receipt", lambda *a: pytest.fail("receipt work began before refusal"))
    status, out = invoke(tmp_path, source, packs, entry)
    assert status == 3 and not out.exists()
    assert capsys.readouterr().err == code + "\n"


@pytest.mark.parametrize("fault", ["crash", "unwritable"])
def test_tool_failure_writes_nothing(source, packs, tmp_path, monkeypatch, capsys, fault):
    # Exit 1 means a written receipt with a defect, so a crash must exit 70 instead.
    if fault == "crash":
        def crash(*args):
            raise RuntimeError("planted")
        monkeypatch.setattr(receipt, "receipt", crash)
        name = "receipt.json"
    else:
        monkeypatch.setattr(receipt, "receipt", lambda *a: {"pass": True})
        name = "missing/receipt.json"
    status, out = invoke(tmp_path, source, packs, name=name)
    err = capsys.readouterr().err
    assert status == 70 and not out.exists()
    assert err.startswith("tool_failure\n") and "Traceback" in err


def test_compiled_write_texts_match_responder(source, packs, monkeypatch):
    entry = source[1]
    original = receipt.compile_script
    for rel in receipt.load_json(packs[0] / "index.json")["packs"]:
        compiled_branches = []

        def capture(*args, compiled_branches=compiled_branches, **kwargs):
            compiled = original(*args, **kwargs)
            compiled_branches.append((compiled, args[0], args[1], args[2]))
            return compiled

        with monkeypatch.context() as patcher:
            patcher.setattr(receipt, "compile_script", capture)
            corpora = receipt.compiled_corpora(packs[0] / rel, entry)
        assert corpora and len(compiled_branches) == 2
        responder = ScriptedResponder(entry)
        for compiled, life_dir, branch, schedule in compiled_branches:
            expected, origins = {}, {}
            rows = [json.loads(line) for line in
                    (life_dir / f"stream.{branch}.jsonl").read_bytes().splitlines()]
            probes = {p.index: p.item_ids for p in compiled.probes}
            for session in compiled.script["sessions"]:
                if session["kind"] == "probe":
                    for iid in probes[session["index"]]:
                        assert corpora[iid] == (expected, origins)
                    continue
                plan = schedule.sessions[session["index"] - 1]
                for turn in session["turns"]:
                    messages = [dict(role="user", content=turn["user"])]
                    body = dict(messages=messages, tools=[dict(type="function", function=dict(
                        name="naive_rag_add", parameters={}))])
                    call = Call("write_turn", "write_turn", "chat", body, "scripted", None, "fixture")
                    writes = responder._write(call, messages)
                    assert len(writes) == 1
                    mid = f"m{len(expected) + 1:06d}"
                    expected[mid] = json.loads(writes[0]["arguments"])["content"]
                    origins[mid] = sorted({r["event_id"] for r in rows if "text" in r and
                        r["turn_key"] == f"{plan.session_id}/t{turn['n']}"})
            assert expected


def test_byte_identical_without_paths(source, packs, tmp_path):
    status, first = invoke(tmp_path, source, packs, name="first.json")
    second_status, second = invoke(tmp_path, source, packs, name="second.json")
    assert status == second_status == 0
    assert first.read_bytes() == second.read_bytes() == canon(read(first))
    assert str(tmp_path).encode() not in first.read_bytes()
    assert str(ROOT).encode() not in first.read_bytes()
    # Includes paths outside the test root, such as the extraction directory.
    def strings(value):
        if isinstance(value, dict):
            return [s for k, v in value.items() for s in [k, *strings(v)]]
        if isinstance(value, list):
            return [s for v in value for s in strings(v)]
        return [value] if isinstance(value, str) else []
    assert not any(Path(s).is_absolute() for s in strings(read(first)))


def test_comparison_classes():
    expected = [(Fraction(1), f"e{n}", 0, "alpha") for n in range(7)]
    def classify(actual, top=None):
        return receipt.compare_rows(expected, actual, control.TOP_K,
            receipt.pairs(actual[:5]) if top is None else top)["classification"]

    assert classify(expected) == "equal"
    for actual, kind in (([expected[1], expected[0], *expected[2:]], "order_only"),
                         (list(reversed(expected)), "tie"), (expected[:-1], "defect")):
        assert classify(actual) == kind
    top = receipt.pairs(expected[:5])
    for invalid in (top[:-1], top + [top[-1]], [top[0]] * 5,
                    [["unscored", 0], *top[1:]]):
        assert classify(expected, invalid) == "defect"
    expected[0] = (Fraction(2), "e0", 0, "alpha")
    assert classify(expected, [top[1], top[0], *top[2:]]) == "defect"
    assert classify(expected, receipt.pairs(expected[1:6])) == "defect"
    assert receipt.jaccard(set(), set()) == "1"
    assert receipt.jaccard({"a", "b"}, {"b", "c"}) == "1/3"


def test_rebuilt_jaccards_and_mismatch_disclose(source, tmp_path):
    folder = tmp_path / "archive"
    folder.mkdir()
    with receipt.load_baseline(receipt.load_archive(source[1], source[0], folder)) as baseline:
        check_rebuilt_jaccards(baseline)


def check_rebuilt_jaccards(baseline):
    inp = synthetic_input()
    iid = inp.keys[0]["item_id"]
    corpora = {iid: ({"m000001": "alpha", "m000002": "alpha"},
                     {"m000001": ["a", "b"], "m000002": ["c"]})}
    disclosure = receipt.part2(inp, baseline, {iid: [["b", 0], ["d", 0]]}, corpora)
    assert disclosure["items"] == [dict(item_id=iid, control="1/4", same_corpus="1")]
    assert disclosure["counts"] == dict(control={"1/4": 1}, same_corpus={"1": 1})
    assert disclosure["corpus_check_mismatch"] == []
    baseline.TOP_K = 1
    disclosure = receipt.part2(inp, baseline, {iid: [["b", 0], ["d", 0]]}, corpora)
    assert disclosure["items"] == [dict(item_id=iid, control="1/3", same_corpus="2/3")]
    assert disclosure["corpus_check_mismatch"][0]["comparison"]["classification"] == "defect"


def test_control_top_k_is_independent(monkeypatch, tmp_path, source, packs):
    monkeypatch.setattr(control, "TOP_K", 4)
    status, out = synthetic_run(monkeypatch, tmp_path, source, packs)
    assert status == 1 and not read(out)["pass"]


def test_usage_exits_two(source):
    with pytest.raises(SystemExit) as caught:
        receipt.main([])
    assert caught.value.code == 2
