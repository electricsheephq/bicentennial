"""Offline equivalence and persistence checks for the developer baseline."""

import ast
import importlib.util
import json
import random
import sys
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bicentennial.controls import naive_rag as control

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "baselines/naive-rag-hermes"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tfidf():
    return load_file("baseline_tfidf", PLUGIN / "tfidf.py")


@pytest.fixture
def provider(tmp_path, monkeypatch):
    agent, base = ModuleType("agent"), ModuleType("agent.memory_provider")
    base.MemoryProvider = object
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", base)
    name = "baseline_naive_rag"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    # Relative imports remain isolated from other tests and need no installed package.
    for child in ("store", "tfidf"):
        monkeypatch.setitem(sys.modules, f"{name}.{child}", load_file(f"{name}.{child}", PLUGIN / f"{child}.py"))
    spec.loader.exec_module(module)
    ctx = SimpleNamespace(register_memory_provider=lambda p: setattr(ctx, "provider", p))
    module.register(ctx)
    p = ctx.provider
    assert p.name == "naive-rag-dev" and p.is_available() and p.unavailable_reason() == ""
    p.initialize("session", hermes_home=tmp_path)
    yield p
    p.shutdown()


def call(provider, tool, **args):
    return json.loads(provider.handle_tool_call("naive_rag_" + tool, args))


def reference(texts, query):
    adapter = control.NaiveRag()
    # Only the scored method is exercised; event ids sort in insertion order.
    adapter.events = {f"e{i:06d}": {"text": text, "t_sim": 0} for i, text in enumerate(texts, 1)}
    return adapter.scored(query, 0)


def assert_equivalent(tfidf, texts, query):
    memories = {f"m{i:06d}": text for i, text in enumerate(texts, 1)}
    actual = tfidf.scored(memories, query)
    expected = [(score, "m" + eid[1:], ordinal, text) for score, eid, ordinal, text in reference(texts, query)]
    assert [(mid, ordinal) for _, mid, ordinal, _ in actual[:tfidf.TOP_K]] == [
        (mid, ordinal) for _, mid, ordinal, _ in expected[:control.TOP_K]]
    assert actual == expected  # Exact scores and the complete ranking also agree.
    return actual


@pytest.mark.parametrize("size", [0, 1, 2, 7, 19])
def test_generated_rankings(tfidf, size):
    rng = random.Random(731 + size)
    vocabulary = ["alpha", "beta", "gamma", "delta", "Café", "猫", "Straße", "İ", "_token", "１２３"]
    texts = [" \t".join(rng.choices(vocabulary, k=rng.choice([0, 1, 3, 25, 70]))) for _ in range(size)]
    if size > 2:
        texts[-1] = texts[0]
    for query in ("", "   !!!", "alpha beta beta", "CAFÉ 猫", "Straße İ", "absent_word"):
        assert_equivalent(tfidf, texts, query)


def test_ties_use_memory_id_then_ordinal(tfidf):
    texts = ["zeta alpha", "alpha zeta"] * 4
    rows = assert_equivalent(tfidf, texts, "zeta alpha")
    assert [(mid, ordinal) for _, mid, ordinal, _ in rows[:5]] == [(f"m{i:06d}", 0) for i in range(1, 6)]
    text = ("alpha " * 40).strip()
    rows = assert_equivalent(tfidf, [text + " " + text, text], "alpha")
    assert [(mid, ordinal) for _, mid, ordinal, _ in rows] == [
        ("m000001", 0), ("m000001", 1), ("m000002", 0)]


def test_idf_counts_chunks(tfidf):
    texts = ["alpha " * 90 + "beta", "alpha beta beta", "beta beta", "gamma"]
    assert len(tfidf.chunks(texts[0])) == 3
    assert_equivalent(tfidf, texts, "alpha beta")


@pytest.mark.parametrize("length", [239, 240, 241])
def test_chunk_boundary(tfidf, length):
    first = "a" * (length - 2) + " b"
    text = " \t" + first + " c \n"
    expected = [first, "c"] if length <= 240 else [first[:-2], "b c"]
    assert tfidf.chunks(text) == control.chunks(text) == expected
    assert_equivalent(tfidf, [text, "b c"], "b")


def test_words_features_fixed_math_and_vectors(tfidf):
    text = "Straße STRASSE İ ẞ café 猫 _x １２３"
    assert tfidf.words(text) == control.words(text)
    assert tfidf.words("ß") != tfidf.words("ss")
    for word in control.words(text):
        assert tfidf.feature(word) == control.feature(word)
    for x in [Fraction(1), Fraction(3, 2), Fraction(2), Fraction(31, 3), Fraction(1024)]:
        assert tfidf.ln_fixed(x) == control.ln_fixed(x)
    for n in (0, 1, 2, 9, 41):
        for df in range(n + 1):
            assert tfidf.idf_fixed(n, df) == control.idf_fixed(n, df)
    ws = control.words(text + " 猫 猫 café")
    idf = {word: control.idf_fixed(9, i % 10) for i, word in enumerate(sorted(set(ws)))}
    assert tfidf.vector(ws, idf) == control.vector(ws, idf)


def test_whitespace_and_long_words(tfidf):
    texts = ["", " \n\t", "!!!", "猫" * 241 + " café", "\n alpha\t\tbeta \n"]
    for text in texts:
        assert tfidf.chunks(text) == control.chunks(text)
    for query in ("", "!!!", "猫" * 241, "café", "alpha beta"):
        assert_equivalent(tfidf, texts, query)


def test_nonpositive_dot_and_zero_norm_are_excluded(tfidf, monkeypatch):
    def collision(word):
        return 1, -1 if word == "negative" else 1
    monkeypatch.setattr(tfidf, "feature", collision)
    monkeypatch.setattr(control, "feature", collision)
    rows = assert_equivalent(tfidf, ["positive", "negative", "positive negative"], "positive")
    assert [(mid, ordinal) for _, mid, ordinal, _ in rows] == [("m000001", 0)]


def test_tools_and_explicit_writes_only(provider):
    p = provider
    assert call(p, "search", query="alpha") == {"results": []}
    assert p.prefetch("alpha", session_id="session") == ""
    p.sync_turn("alpha", "alpha")
    assert call(p, "search", query="alpha") == {"results": []}
    assert not p.store.path.exists()
    schemas = {s["name"]: s["parameters"] for s in p.get_tool_schemas()}
    assert schemas == {
        "naive_rag_add": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
        "naive_rag_search": {"type": "object", "properties": {
            "query": {"type": "string"}, "whole": {"type": "boolean", "default": False}}, "required": ["query"]},
        "naive_rag_delete": {"type": "object", "properties": {
            "memory_id": {"type": "string"}}, "required": ["memory_id"]},
    }
    text = "猫 payload " * 1024 + " tail_token\n"
    assert call(p, "add", content=text) == {"id": "m000001"}
    assert call(p, "search", query="tail_token", whole=True) == {"results": [{"id": "m000001", "content": text}]}
    assert call(p, "search", query="") == {"results": []}
    assert call(p, "search", query="unmatched") == {"results": []}
    assert call(p, "delete", memory_id="missing") == {"deleted": False}
    assert call(p, "delete", memory_id="m000001") == {"deleted": True}
    assert call(p, "delete", memory_id="m000001") == {"deleted": False}
    assert call(p, "search", query="tail_token") == {"results": []}
    with pytest.raises(ValueError, match="unknown naive-RAG tool"):
        p.handle_tool_call("unknown", {})


def test_whole_search_ranks_distinct_memories_by_best_chunk(provider):
    p = provider
    texts = ["\n" + "alpha " * 230 + "\n", "alpha", "alpha beta", "alpha gamma",
             "alpha delta", "alpha epsilon", "alpha zeta"]
    for text in texts:
        call(p, "add", content=text)
    rows = reference(texts, "alpha")
    expected, seen = [], set()
    for _, eid, _, _ in rows:
        mid = "m" + eid[1:]
        if mid not in seen:
            seen.add(mid)
            expected.append({"id": mid, "content": texts[int(eid[1:]) - 1]})
    assert call(p, "search", query="alpha", whole=True) == {"results": expected[:5]}
    chunks = call(p, "search", query="alpha")["results"]
    assert chunks == [{"id": "m" + eid[1:], "ordinal": ordinal, "content": text}
                      for _, eid, ordinal, text in rows[:5]]
    assert len({r["id"] for r in chunks}) == 1


def reload_provider(p):
    p.shutdown()
    fresh = type(p)()
    fresh.initialize("new-session", hermes_home=p.store.path.parents[2])
    return fresh


def test_ids_never_reused_after_delete_and_reload(provider):
    p = provider
    assert call(p, "add", content="alpha") == {"id": "m000001"}
    assert call(p, "add", content="beta") == {"id": "m000002"}
    assert call(p, "delete", memory_id="m000002") == {"deleted": True}
    assert call(p, "add", content="gamma") == {"id": "m000003"}
    for mid in ("m000001", "m000003"):
        assert call(p, "delete", memory_id=mid) == {"deleted": True}
    p = reload_provider(p)
    assert call(p, "add", content="delta") == {"id": "m000004"}
    assert json.loads(p.store.path.read_text().splitlines()[0]) == {"counter": 4}


def test_insertion_order_past_six_digits(provider):
    provider.store.path.write_text(json.dumps({"counter": 999998}) + "\n")
    p = reload_provider(provider)
    ids = [call(p, "add", content="alpha")["id"] for _ in range(3)]
    assert ids == ["m999999", "m1000000", "m1000001"]
    assert [row["id"] for row in call(p, "search", query="alpha")["results"]] == ids


def test_reload_preserves_results_and_jsonl(provider):
    p = provider
    texts = ["猫 café\nalpha " * 40, "alpha beta", "", "alpha", "alpha", "beta"]
    for text in texts:
        call(p, "add", content=text)
    call(p, "delete", memory_id="m000002")
    before = {(query, whole): call(p, "search", query=query, whole=whole)
              for query in ("alpha", "猫", "", "unmatched") for whole in (False, True)}
    fresh = reload_provider(p)
    assert {(query, whole): call(fresh, "search", query=query, whole=whole)
            for query, whole in before} == before
    rows = [json.loads(line) for line in p.store.path.read_text().splitlines()]
    assert rows == [{"counter": 6}, *({"id": f"m{i:06d}", "content": text}
                                    for i, text in enumerate(texts, 1) if i != 2)]
    assert list(p.store.path.parent.iterdir()) == [p.store.path]


@pytest.mark.parametrize("failure", [None, "fsync", "replace"])
def test_atomic_write_order_and_temporary_cleanup(provider, monkeypatch, failure):
    p = provider
    call(p, "add", content="original")
    original = p.store.path.read_bytes()
    module = sys.modules[type(p.store).__module__]
    fsync, replace = module.os.fsync, module.os.replace
    operations = []

    def observed_fsync(fd):
        operations.append("fsync")
        if failure == "fsync":
            raise OSError("simulated fsync failure")
        fsync(fd)

    def observed_replace(source, destination):
        operations.append("replace")
        assert operations == ["fsync", "replace"]
        assert source.parent == destination.parent == p.store.path.parent
        assert destination.read_bytes() == original
        pending = [json.loads(line) for line in source.read_text().splitlines()]
        assert pending[-1] == {"id": "m000002", "content": "next"}
        if failure == "replace":
            raise OSError("simulated replace failure")
        replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", observed_fsync)
        patch.setattr(module.os, "replace", observed_replace)
        if failure:
            with pytest.raises(OSError, match="simulated"):
                call(p, "add", content="next")
        else:
            assert call(p, "add", content="next") == {"id": "m000002"}
    assert list(p.store.path.parent.iterdir()) == [p.store.path]
    if failure:
        assert p.store.path.read_bytes() == original
        assert p.store.memories == {"m000001": "original"} and p.store.counter == 1
        assert reload_provider(p).store.memories == p.store.memories
        assert call(p, "add", content="retry") == {"id": "m000002"}
    else:
        assert operations == ["fsync", "replace"]
        assert reload_provider(p).store.memories == {"m000001": "original", "m000002": "next"}


def test_plugin_metadata_and_import_boundary():
    assert (PLUGIN / "plugin.yaml").read_text().splitlines() == [
        "name: naive-rag-dev", "version: 1.0.0",
        "description: Benchmark-owned naive-RAG developer baseline for Hermes",
        "author: Bicentennial benchmark", "license: Apache-2.0"]
    for path in PLUGIN.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name.partition(".")[0] in sys.stdlib_module_names for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                assert node.module == "agent.memory_provider" or node.module.partition(".")[0] in sys.stdlib_module_names
