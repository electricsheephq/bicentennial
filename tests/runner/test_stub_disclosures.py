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
    assert {name: actual[name] for name in names if name in actual} == expected


def test_t1_stub_disclosures_both_gated_arms_only(tmp_path, monkeypatch):
    for system in ("mem0-oss", "hermes-native", "holographic"):
        with monkeypatch.context() as patch:
            props = prepared("t1", tmp_path / system, patch, system)
            entry = load(REGISTRY / f"{system}.toml")
            arm = NS(outcomes={}, bundles=(), transforms=(), units=(), verdicts=())
            run = NS(ctx=NS(entry=entry, worker_properties=props), arms={a: arm for a in
                ("system", "wiped", "no_memory")}, not_exercised=(), singleton_lives={}, duty_items=())
            patch.setattr(compare, "_finals", lambda *a: [])
            expected = {"t1.embeddings": EMBEDDINGS, "t1.extraction": EXTRACTION} if system == "mem0-oss" else {}
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
    for system in ("mem0-oss", "hermes-native", "holographic"):
        with monkeypatch.context() as patch:
            props = prepared("t0", tmp_path / system, patch, system)
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
            check_properties(ET.fromstring(report["junit"])[0], "t0", expected)
