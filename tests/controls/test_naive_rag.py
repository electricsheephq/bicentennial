"""S09 exact retrieval, hand tables, quote recall and cache acceptance."""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.api import conformance
from bicentennial.api.adapters import bm25
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.controls import cache
from bicentennial.controls import naive_rag as rag
from bicentennial.keyed import shuffle, uniform_int
from bicentennial.probe import scripted_reader

SPEC = importlib.util.spec_from_file_location("s07_fixture", Path(__file__).with_name("test_controls.py"))
s07 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s07)
fixture_input, PIN, copy = s07.fixture_input, s07.PIN, s07.copy
ROOT = Path(__file__).resolve().parents[2]
S = "Which seat does the note say she now wants?"
G = "gate code"


def case_input(case="B"):
    inp, score = fixture_input()
    if case == "A":
        return inp, score
    keys = list(inp.keys)
    for b in range(2):
        source, target = f"qf{b}", f"qg{b}"
        item = next(i for i in inp.pack["items"] if i["item_id"] == source)
        cloned = json.loads(canon(copy(item)).decode().replace(source, target))
        cloned["prompt"] = item["prompt"]
        inp.pack["items"].append(cloned)
        key = copy(next(k for k in keys if k["item_id"] == source))
        key["item_id"] = target
        keys.append(key)
        inp.now[target] = 1000
    inp.pack["bundles"].append(dict(canary=s07.CANARY, bundle_id="qa-fork-2", cell_id="WAKE-PREF",
                                     twin_type="fork", items=["qg0", "qg1"], decisive_fact_id="fact-qa-fork-2"))
    inp.pack["qa_order"] = sorted(i["item_id"] for i in inp.pack["items"] if i["stage"] != "act")
    for key in keys:
        iid = key["item_id"]
        if iid in ("qf0", "qf1") or case == "C" and iid in ("qg0", "qg1"):
            key["recall_query"] = S
        elif iid in ("kf0", "kf1"):
            key["recall_query"] = G
    return replace(inp, keys=tuple(keys)), score


def computed(case="B"):
    inp, score = case_input(case)
    controls = cache.compute(inp, score=score, harness_pin=PIN, window=16384)
    return rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls, window=16384)


def event(eid, text, t=0):
    return dict(event_id=eid, text=text, t_sim=t, kind="message", actor="fixture")


def query(adapter, prompt, now=1000, iid="probe"):
    return adapter.query(dict(task_id=iid, prompt=prompt), now)


def adapter_for(events):
    adapter = rag.NaiveRag()
    for e in events:
        adapter.ingest(e)
    return adapter


def test_chunk_boundaries():
    text = " ".join(f"W{i:03d}x" for i in range(60))
    assert [len(c) for c in rag.chunks(text)] == [239, 119]
    assert rag.chunks("  " + "y" * 300 + " z  ") == ["y" * 300, "z"]
    assert rag.chunks("") == rag.chunks(" \n ") == []
    adapter = adapter_for([event("L", text), event("M", "nothing here")])
    assert query(adapter, "w045x") == dict(output=rag.chunks(text)[1], citations=["L"], confidence_milli=1000)
    assert adapter.retrievals == {"probe": [["L", 1]]}
    assert rag.chunks("a\t b\n c") == ["a\t b\n c"]


def test_exact_ranking_ties_depth_and_future():
    adapter = adapter_for([event("e1", "alpha beta"), event("e2", "alpha"), event("e3", "gamma")])
    assert query(adapter, "Alpha") == dict(output="alpha\nalpha beta", citations=["e2", "e1"], confidence_milli=1000)
    tied = adapter_for([event(f"x{i}", "same text") for i in reversed(range(7))])
    assert query(tied, "text")["citations"] == [f"x{i}" for i in range(5)]
    future = adapter_for([event("present", "alpha", 1), event("future", "alpha", 9)])
    assert query(future, "alpha", 5)["citations"] == ["present"]
    assert rag.TOP_K == scripted_reader.K == 5
    assert query(adapter, "absent")["output"] == "UNKNOWN"
    assert query(adapter, "")["citations"] == []


def test_features_vectors_and_collisions(monkeypatch):
    assert rag.words("AbC _X １２!") == ["abc", "_x", "１２"]
    d = sha256(b"alpha").digest()
    assert rag.feature("alpha") == (int.from_bytes(d[:8], "big"), -1 if d[8] & 1 else 1)
    assert rag.idf_fixed(10, 10) > 0
    coordinate, sign = rag.feature("alpha")
    assert rag.vector(["alpha"] * 3, {"alpha": 7}) == {coordinate: sign * 21}
    monkeypatch.setattr(rag, "feature", lambda w: (1, 1 if w == "a" else -1))
    assert rag.vector(["a", "b"], {"a": 3, "b": 3}) == {1: 0}
    assert rag.vector([], {}) == {}
    assert query(adapter_for([event("zero", "a b")]), "a")["citations"] == []


def test_conformance():
    assert conformance.run(rag.NaiveRag) == {
        n: n != "supersession_current" for n in conformance.CHECKS}


def test_log_fixed_keyed_property():
    for c in range(200):
        unit = ("s09", "ln_fixed", str(c))
        a = uniform_int("s09", unit, 0, "a", 0, 10**6)
        b = uniform_int("s09", unit, 0, "b", 1, 1000)
        x = 1 + Fraction(a, b)
        assert rag.ln_fixed(x) == bm25.log_fixed(x)
    assert rag.ln_fixed(Fraction(1)) == 0


def test_retrieval_keyed_properties():
    vocabulary = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    for c in range(200):
        unit = ("s09", "retrieval", str(c))

        def draw(name, lo, hi, unit=unit):
            return uniform_int("s09", unit, 0, name, lo, hi)

        events = [event(f"e{i}", " ".join(vocabulary[draw(f"w{i}-{j}", 0, 5)]
                  for j in range(draw(f"length{i}", 1, 10))), draw(f"time{i}", 0, 9))
                  for i in range(draw("events", 1, 12))]
        now = draw("now", 0, 9)
        prompt = " ".join(vocabulary[draw(f"q{j}", 0, 5)] for j in range(draw("qlength", 1, 3)))
        adapter = adapter_for(events)
        result = query(adapter, prompt, now)
        assert len(result["citations"]) <= rag.TOP_K
        assert all(next(e for e in events if e["event_id"] == eid)["t_sim"] <= now
                   for eid in result["citations"])
        assert result == query(adapter_for([e for e in events if e["t_sim"] <= now]), prompt, now)
        assert result == query(adapter_for(shuffle("s09", unit, 0, "ingest", events)), prompt, now)
        ranked = adapter.scored(prompt, now)
        assert ranked == sorted(ranked, key=lambda r: (-r[0], r[1], r[2]))


@pytest.mark.parametrize("case,values,flag", [
    ("A", [0, 0, 0, 1000, 0], True), ("B", [0, 0, 1000, 1000, 500], False),
    ("C", [0, 0, 1000, 1000, 1000], True)])
def test_hand_table(case, values, flag):
    inp, score = case_input(case)
    controls = cache.compute(inp, score=score, harness_pin=PIN, window=16384)
    assert [r["score_milli"] for r in controls["arms"]["no_memory"]["aggregates"]] == [0, 0, 0, 1000, 0]
    assert [r["score_milli"] for r in controls["arms"]["oracle_evidence"]["aggregates"]] == [1000] * 5
    arm = rag.run(inp, score=score)
    entry = rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)
    assert {k: v for k, v in entry["arm"].items() if k != "aggregates"} == arm
    assert [r["score_milli"] for r in entry["arm"]["aggregates"]] == values
    assert entry["flagged"] is flag
    if case == "A":
        assert all(v == [] for v in arm["retrieved"].values())
    if case == "C":
        assert tuple(entry["rows"][-1][p] for p in ("between", "rag_near_solved", "floor_near_solved")) == (
            False, True, False)
    if case != "B":
        return
    assert {i["item_id"]: i["score_milli"] for i in arm["items"]} == dict(
        af0=0, af1=0, al0=0, al1=1000, kf0=1000, kf1=1000, na=1000, qf0=1000, qf1=1000, qg0=0, qg1=0)
    expected = dict.fromkeys((i["item_id"] for i in arm["items"]), [])
    expected.update(kf0=[["e-gate", 0], ["e-request", 0]], kf1=[["e-gate", 0]],
                    qf0=[["e-new0", 0], ["e-request", 0], ["e-old", 0]],
                    qf1=[["e-new1", 0], ["e-old", 0]])
    assert arm["retrieved"] == expected
    report = next(r for r in arm["reports"] if r["item_id"] == "kf0")
    assert report["forget"] == dict(in_context=True, in_store=None, held=False)
    assert report["recall"] == dict(k=5, hits=1, of=1, milli=1000)
    assert report["recall_basis"] == "chunk_quote"
    assert [tuple(r[p] for p in ("between", "rag_near_solved", "floor_near_solved"))
            for r in entry["rows"]] == [(False, False, False), (False, False, False),
            (False, True, False), (False, True, True), (True, False, False)]


def test_quote_recall_uses_one_chunk_and_exact_tokens():
    inp, score = fixture_input(("qf0", "qf1"))
    key = next(k for k in inp.keys if k["item_id"] == "qf0")
    e = next(e for e in inp.events["life-s04"]["B0"] if e["event_id"] == "e-new0")
    e["text"] = " ".join(["leftchunk"] * 24) + " WINDOW-7401"
    assert len(rag.chunks(e["text"])) == 2
    for prompt, expected in (("leftchunk", 0), ("WINDOW", 1)):
        key["recall_query"] = prompt
        arm = rag.run(inp, score=score)
        report = next(r for r in arm["reports"] if r["item_id"] == "qf0")
        assert arm["retrieved"]["qf0"] == [["e-new0", expected]]
        assert report["recall"]["hits"] == expected
        assert report["recall"]["milli"] == expected * 1000
        assert report["recall_basis"] == "chunk_quote"
    key["required"] = sorted(["leftchunk", "WINDOW-7401"])
    assert next(r for r in rag.run(inp, score=score)["reports"] if r["item_id"] == "qf0")["recall"]["hits"] == 0
    key["required"] = ["window-7401"]  # Exact matching: no matching token, so event-id basis.
    report = next(r for r in rag.run(inp, score=score)["reports"] if r["item_id"] == "qf0")
    assert report["recall_event_id_basis"] == dict(hits=1, of=1)
    key["required"] = ["non-ascii-é"]
    with pytest.raises(AssertionError, match="non-ASCII required token"):
        rag.run(inp, score=score)


def test_whitespace_token_is_not_repaired():
    inp, score = fixture_input(("qf0", "qf1"))
    key = next(k for k in inp.keys if k["item_id"] == "qf0")
    key["required"], key["recall_query"] = ["CHUNKLEFT CHUNKRIGHT"], "CHUNKRIGHT then CHUNKLEFT"
    e = next(e for e in inp.events["life-s04"]["B0"] if e["event_id"] == "e-new0")
    e["text"] = "x" * 230 + " CHUNKLEFT CHUNKRIGHT"
    arm = rag.run(inp, score=score)
    assert arm["retrieved"]["qf0"] == [["e-new0", 1], ["e-new0", 0]]
    report = next(r for r in arm["reports"] if r["item_id"] == "qf0")
    assert report["recall"]["hits"] == 0


def test_near_rows_missing_inputs_and_boundaries():
    def row(track, value, stage="remember"):
        return dict(stage=stage, track=track, score_milli=value)

    rows = rag.near_rows([row("x", 0), row("y", 700)], [row("x", 700)],
                         [row("x", 1000), row("y", 1000), row("x", 1000, "act")])
    assert [(r["stage"], r["track"]) for r in rows] == [("act", "x"), ("remember", "x"), ("remember", "y")]
    assert rows[0]["between"] is rows[0]["rag_near_solved"] is rows[0]["floor_near_solved"] is None
    assert rows[1]["between"] is rows[1]["rag_near_solved"] is True
    assert rows[2]["between"] is rows[2]["rag_near_solved"] is None
    assert rows[2]["floor_near_solved"] is True
    assert rag.flagged([]) is True


def test_projections(tmp_path):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    entry = rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)
    assert rag.card_controls(controls, entry) == dict(no_memory_floor=None, oracle_evidence=None,
                                                    full_history=None, naive_rag=None)
    single, score_single = fixture_input(("af0", "af1"))
    gate_single = cache.compute(single, score=score_single, harness_pin=PIN)
    rag_single = rag.compute(single, score=score_single, harness_pin=PIN, controls_entry=gate_single)
    projected = rag.card_controls(gate_single, rag_single)
    assert projected == dict(no_memory_floor=0, oracle_evidence=1000, full_history=1000, naive_rag=0)
    card = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"]["card_ring0"]
    card["controls"] = dict(projected, wiped_store="FAIL")
    validate("card_ring0", card)
    digest = cache.write_entry(tmp_path / "naive_rag.json", entry)
    pack = copy(inp.pack)
    pack["controls"] = rag.pack_controls(controls, entry, digest)
    validate("pack", pack)
    assert cache.cache_key(replace(inp, pack=pack), harness_pin=PIN) == cache.cache_key(inp, harness_pin=PIN)
    assert pack["hashes"] == {}
    assert pack["controls"]["naive_rag"] == dict(aggregates=entry["arm"]["aggregates"], rows=entry["rows"],
        flagged=False, embedder="hashed-tfidf-v1", embedder_sha256=entry["key"]["embedder_sha256"], entry_sha256=digest)
    assert rag.disclosures(entry) == [("naive_rag.chunk_chars", "240"),
        ("naive_rag.embedder", "hashed-tfidf-v1"), ("naive_rag.embedder_sha256", entry["key"]["embedder_sha256"]),
        ("naive_rag.flagged", "false"), ("naive_rag.label", "cached, API mode"), ("naive_rag.top_k", "5")]
    assert cache.display_rows(controls, entry["arm"]["aggregates"])[-1]["normalised_milli"] == 500
    for invalid in ("z" * 64, "A" * 64, "a" * 63, 1, None):
        with pytest.raises(ValueError):
            rag.pack_controls(controls, entry, invalid)


def test_cache_hit(tmp_path):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    calls = []

    def counted(item, result):
        calls.append(item["item_id"])
        return score(item, result)

    path = tmp_path / "naive_rag.json"
    first = rag.ensure(inp, path, score=counted, harness_pin=PIN, controls_entry=controls)
    assert len(calls) == 11
    calls.clear()
    assert rag.ensure(inp, path, score=counted, harness_pin=PIN, controls_entry=controls) == first
    assert calls == []
    assert path.read_bytes() == canon(first)
    assert rag.read_entry(path, first["key"], controls_entry=controls,
                          expected_sha256=sha256(path.read_bytes()).hexdigest()) == first


@pytest.mark.parametrize("change", ["pin", "scoring", "text", "window", "depth-up", "depth-down", "chunk", "name"])
def test_cache_one_change_misses(tmp_path, monkeypatch, change):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    path = tmp_path / "naive_rag.json"
    original = rag.ensure(inp, path, score=score, harness_pin=PIN, controls_entry=controls)
    pin, window = PIN, 16384
    if change == "pin":
        pin = "b" + PIN[1:]
    elif change == "scoring":
        inp = replace(inp, scoring_sha256="1" + inp.scoring_sha256[1:])
    elif change == "text":
        inp.events["life-s04"]["B0"][0]["text"] += " "
    elif change == "window":
        window += 1
    elif change.startswith("depth"):
        monkeypatch.setattr(rag, "TOP_K", 6 if change == "depth-up" else 4)
    elif change == "chunk":
        monkeypatch.setattr(rag, "CHUNK_CHARS", 241)
    else:
        monkeypatch.setattr(rag, "EMBEDDER_NAME", "changed")
    controls = cache.compute(inp, score=score, harness_pin=pin, window=window)
    key = rag.rag_key(inp, harness_pin=pin, window=window)
    if change in ("depth-up", "depth-down", "chunk", "name"):
        assert key["embedder_sha256"] != original["key"]["embedder_sha256"]
    assert rag.read_entry(path, key, controls_entry=controls) is None
    calls = []

    def counted(item, result):
        calls.append(item["item_id"])
        return score(item, result)

    new = rag.ensure(inp, path, score=counted, harness_pin=pin, controls_entry=controls, window=window)
    assert len(calls) == 11
    assert new["key"] == key
    assert rag.read_entry(path, key, controls_entry=controls) == new


def test_depth_decrease_validates_stored_depth_before_recomputation(tmp_path, monkeypatch):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    entry = rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)
    entry["arm"]["retrieved"]["qf0"] = [["e-new0", 0]] * 5
    reseal(entry)
    path = tmp_path / "naive_rag.json"
    cache.write_entry(path, entry)
    monkeypatch.setattr(rag, "TOP_K", 4)
    key = rag.rag_key(inp, harness_pin=PIN)
    with monkeypatch.context() as patch:
        patch.setattr(rag, "reduce", lambda *a, **kw: pytest.fail("recomputed stale entry"))
        assert rag.read_entry(path, key, controls_entry=controls) is None
    assert rag.ensure(inp, path, score=score, harness_pin=PIN, controls_entry=controls)["embedder"]["top_k"] == 4


def test_code_edit_changes_both_hashes(tmp_path, monkeypatch):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    entry = rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)
    path = tmp_path / "naive_rag.json"
    cache.write_entry(path, entry)
    root = tmp_path / "package"
    shutil.copytree(cache.PACKAGE_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    key = rag.rag_key(inp, harness_pin=PIN, root=root)
    assert key == entry["key"]
    source = root / "controls/naive_rag.py"
    source.write_bytes(source.read_bytes() + b" ")
    changed = rag.rag_key(inp, harness_pin=PIN, root=root)
    assert {k for k in key if key[k] != changed[k]} == {"controls_sha256", "embedder_sha256"}
    changed_base = cache.cache_key(inp, harness_pin=PIN, root=root)
    with monkeypatch.context() as patch:
        patch.setattr(cache, "cache_key", lambda *args, **kwargs: changed_base)
        matching_controls = cache.compute(inp, score=score, harness_pin=PIN)
    assert rag.read_entry(path, changed, controls_entry=matching_controls) is None


def reseal(entry):
    entry["digest"] = sha256_canon({k: v for k, v in entry.items() if k != "digest"})


@pytest.mark.parametrize("change", ["score", "resealed-score", "retrieved", "rows", "newline", "pretty",
    "expected", "stale", "json", "canary", "key-digest", "shape", "arm-shape", "bundle", "item", "identities",
    "ordinal", "params", "embedder-pin", "flag", "gate-columns"])
def test_tampering(tmp_path, change):
    inp, score = case_input()
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    entry = rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)
    key, expected = entry["key"], None
    if change in ("score", "resealed-score", "stale"):
        entry["arm"]["aggregates"][0]["score_milli"] = 1
        if change == "stale":
            key = dict(key, harness_pin="b" * 64)
            controls = dict(controls, key=rag.base_key(key))
    elif change == "retrieved":
        entry["arm"]["retrieved"]["qf0"] = [["e-new0", 0]] * 6
    elif change == "rows":
        entry["rows"][0]["between"] = not entry["rows"][0]["between"]
    elif change == "expected":
        expected = "f" * 64
    elif change == "canary":
        entry["canary"] = "wrong"
    elif change == "key-digest":
        entry["key_sha256"] = "f" * 64
    elif change == "shape":
        entry["extra"] = None
    elif change == "arm-shape":
        entry["arm"]["extra"] = None
    elif change == "bundle":
        entry["arm"]["bundles"][0]["score_milli"] = 1
    elif change == "item":
        entry["arm"]["items"][0]["score_milli"] = "0"
    elif change == "identities":
        del entry["arm"]["retrieved"]["qf0"]
    elif change == "ordinal":
        entry["arm"]["retrieved"]["qf0"] = [["e-new0", True]]
    elif change == "params":
        entry["embedder"]["top_k"] = True
    elif change == "embedder-pin":
        entry["key"]["embedder_sha256"] = "bad"
        entry["key_sha256"] = sha256_canon(entry["key"])
    elif change == "flag":
        entry["flagged"] = True
    elif change == "gate-columns":
        entry["rows"] = rag.near_rows([dict(r, score_milli=1) for r in controls["arms"]["no_memory"]["aggregates"]],
            entry["arm"]["aggregates"], controls["arms"]["oracle_evidence"]["aggregates"])
        entry["flagged"] = rag.flagged(entry["rows"])
    if change != "score":
        reseal(entry)
    data = canon(entry)
    if change == "newline":
        data += b"\n"
    elif change == "pretty":
        data = json.dumps(entry, indent=2).encode()
    elif change == "json":
        data = b"{"
    path = tmp_path / "naive_rag.json"
    path.write_bytes(data)
    with pytest.raises(cache.ControlsTampered) as caught:
        rag.read_entry(path, key, controls_entry=controls, expected_sha256=expected)
    assert caught.value.code == "pinned_artifact_changed"


def test_gate_identity_and_singletons_refused(tmp_path):
    inp, score = case_input()
    other = cache.compute(inp, score=score, harness_pin="b" * 64)
    with pytest.raises(ValueError, match="controls entry is keyed differently"):
        rag.compute(inp, score=score, harness_pin=PIN, controls_entry=other)
    with pytest.raises(ValueError, match="controls entry is keyed differently"):
        rag.read_entry(tmp_path / "missing", rag.rag_key(inp, harness_pin=PIN), controls_entry=other)
    controls = cache.compute(inp, score=score, harness_pin=PIN)
    assert rag.read_entry(tmp_path / "missing", rag.rag_key(inp, harness_pin=PIN), controls_entry=controls) is None
    controls["arms"]["no_memory"]["singleton_lives"] = {}
    with pytest.raises(ValueError, match="singleton lives differ"):
        rag.compute(inp, score=score, harness_pin=PIN, controls_entry=controls)


def test_deterministic_process_bytes():
    outputs = [subprocess.check_output([sys.executable, __file__], cwd=ROOT,
               env=dict(os.environ, PYTHONHASHSEED=seed)) for seed in ("0", "random")]
    assert outputs[0] == outputs[1] == canon(computed())


def test_purity_and_public_doc():
    path = cache.PACKAGE_ROOT / "controls/naive_rag.py"
    tree = ast.parse(path.read_text())
    s07.assert_pure(tree)
    allowed = {"re", "hashlib", "fractions", "json", "bicentennial.canon", "bicentennial.contracts.run",
        "bicentennial.api.contract", "bicentennial.api.adapters.reference_store", "bicentennial.score.aggregate",
        "bicentennial.world.scale"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(n.name in allowed for n in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed if node.level == 0 else node.level == 1 and node.module in (None, "common", "cache")
        for field in ("id", "attr", "name", "arg", "asname"):
            value = getattr(node, field, None)
            if isinstance(value, str):
                assert "lcm" not in value.lower()
    doc = (ROOT / "specs/controls/naive_rag.md").read_text()
    assert len(doc.splitlines()) <= 80
    assert all(line in doc for line in ('TOP_K = 5', 'CHUNK_CHARS = 240',
                                       'EMBEDDER_NAME = "hashed-tfidf-v1"', 'cached, API mode'))
    assert "/" + "Users/" not in doc and "/" + "home/" not in doc
    assert len(path.read_text().splitlines()) <= 340


if __name__ == "__main__":
    sys.stdout.buffer.write(canon(computed()))
