"""Stub limitations follow registry capabilities into T0 and both gated T1 arms."""

import runpy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace as NS

from bicentennial.canon import canon
from bicentennial.runner import compare, t0
from bicentennial.systems.registry import REGISTRY, load

shared = runpy.run_path(str(Path(__file__).resolve().parents[1] / "systems/test_plugin_deps.py"))
EMBEDDINGS = ("Hashed-vector stub (RING0 E10): cosine reported as (1 + c)/2 over D-1 hashed token "
              "coordinates; similarity order preserved; hybrid weights and absolute thresholds not validated.")
EXTRACTION = ("Automatic extraction not exercised (RING0 E11, #208): the stub's reply format is not the "
              "one the pinned release reads; results cover explicit-write storage and recall.")


def prepared(tier, root, monkeypatch, system):
    shared["lock"](root, monkeypatch)
    shared["fake_worker"](root, dists=[("demo-pkg", "1.0")])
    return shared["prepared"](tier, root, monkeypatch, system=system)


def check_properties(suite, tier, expected):
    actual = {p.attrib["name"]: p.attrib["value"] for p in suite.findall("properties/property")}
    names = {f"{tier}.embeddings", f"{tier}.extraction"}
    names.update(omega_properties())
    assert {name: actual[name] for name in names if name in actual} == expected


def test_omega_disclosure_order():
    from bicentennial.director.scripted import stub_disclosures
    assert stub_disclosures({"name": "omega"}, "t0") == list(omega_properties().items())


def test_t1_stub_disclosures_both_gated_arms_only(tmp_path, monkeypatch):
    for system in ("mem0-oss", "hermes-native", "holographic", "omega"):
        with monkeypatch.context() as patch:
            props = () if system == "omega" else prepared("t1", tmp_path / system, patch, system)
            entry = load(REGISTRY / f"{system}.toml")
            arm = NS(outcomes={}, bundles=(), transforms=(), units=(), verdicts=())
            run = NS(ctx=NS(entry=entry, worker_properties=props), arms={a: arm for a in
                ("system", "wiped", "no_memory")}, not_exercised=(), singleton_lives={}, duty_items=())
            patch.setattr(compare, "_finals", lambda *a: [])
            expected = {"t1.embeddings": EMBEDDINGS, "t1.extraction": EXTRACTION} if system == "mem0-oss" else {}
            if system == "omega":
                expected = omega_properties()
            for name in ("system", "wiped"):
                xml = compare._junit(run, name, canon(dict(tier="T1", system=system, items=[],
                    controls={"wiped_store": "PASS"})), NS(to_obj=lambda: {}), "PASS", [], [], [], 0, [])
                suites = ET.fromstring(xml)
                check_properties(suites[0], "t1", expected)
                floors = [s for s in suites if s.attrib["name"].endswith(".no_memory")]
                assert len(floors) == (1 if name == "system" else 0)
                for floor in floors:
                    check_properties(floor, "t1", {})


def test_t0_stub_disclosures(tmp_path, monkeypatch):
    for system in ("mem0-oss", "hermes-native", "holographic", "omega"):
        with monkeypatch.context() as patch:
            props = () if system == "omega" else prepared("t0", tmp_path / system, patch, system)
            patch.setattr(t0, "assemble", lambda system=system, **kw: dict(tier="T0", system=system, items=[]))
            patch.setattr(t0, "finalize", lambda card, gate: canon(card))
            patch.setattr(t0, "_pins", lambda *a: {})
            patch.setattr(t0, "card_controls", lambda *a: {})
            patch.setattr(t0, "build_receipt", lambda **kw: {})
            pack = NS(pack={"items": [], "bundles": [], "lives": ["life"]},
                meta=dict(honeypot_token="unused", singleton_lives={}, duty_items=[]), template=NS())
            report = t0._report_pack(pack, load(REGISTRY / f"{system}.toml"), {}, {}, [], [], {},
                t0._audit([]), tmp_path, NS(exit=0), 0, props)
            expected = {"t0.embeddings": EMBEDDINGS, "t0.extraction": EXTRACTION} if system == "mem0-oss" else {}
            if system == "omega":
                expected = omega_properties()
            check_properties(ET.fromstring(report["junit"])[0], "t0", expected)


def omega_properties():
    return {"omega." + key: value for key, value in {
        "adapter": "benchmark-authored Hermes provider over omega-memory 1.5.20's Python API: store, query_structured and delete_memory for the tools, type_stats at start, bridge.reset_memory at shutdown, and the embedding preload and backend checks; OMEGA's maintainers are invited to review it",
        "writes": "omega.store as shipped: event type memory, Jaccard dedup within a session, supersession, 90-day TTL and auto-relate, which the adapter waits up to 30 s for after each write and again before each OMEGA call; a call that still finds a relate running is refused before it reaches OMEGA, Hermes's memory manager returns the refusal as a tool error, and the run scores what follows; the store's exact and canonical-hash dedup never match here, because they check the TTL against SQLite's real clock while the worker's clock is simulated; the result shows the memory id and OMEGA's outcome word",
        "reads": "query_structured as shipped: full content, 10 results by default, memory accesses recorded; OMEGA's query and MCP tool render markdown with 200-character previews by default",
        "query_expansion": "off: no LLM key; matches OMEGA without one",
        "reranker": "off: the shipped default would download the cross-encoder at first query; the benchmark runs offline with every model pinned",
        "query_cache": "as shipped: a repeat of an identical query within 60 s (300 s at high confidence) of elapsed time can come from the cache, but every write that reaches the store, every delete and every non-empty read clears it (a blocked write or a within-session Jaccard dedup does not)",
        "deferred_startup": "as shipped: integrity check, WAL checkpoint, and a backup of a non-empty store when no backup exists (the age check compares the simulated clock with real file times, so an existing backup never counts as stale); initialization waits for it, so a run's first start with memories makes a backup, which keeps them after a delete",
        "ttl": "as shipped (90 days for memory events), on the worker's simulated clock: nothing expires within a run; OMEGA's dedup scope checks the TTL against SQLite's real clock instead (omega.writes)",
        "onnx_threads": "1",
        "telemetry": "off: ORT_DISABLE_TELEMETRY=1; onnxruntime 1.29.0 would otherwise upload usage events to Microsoft, and runs are offline",
        "forget": "omega.delete_memory as shipped; OMEGA's forgetting_log keeps a 200-character preview of each deleted memory",
        "prefetch": "empty: shipped UserPromptSubmit hook captures but does not query"}.items()}
