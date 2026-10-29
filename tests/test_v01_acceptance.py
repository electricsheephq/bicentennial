"""Offline acceptance evidence, mutation coverage, and producer compatibility."""

import ast
import copy
import importlib.util
import json
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.controls.cache import (
    CONTROL_FILES,
    PACKAGE_ROOT,
    READER_FILES,
    code_sha256,
)
from bicentennial.packs.manifest import file_manifest, tree_sha256
from bicentennial.packs.scoring import SCORING_FILES
from bicentennial.report.card import assemble, finalize
from bicentennial.report.junit import item_suite, junit_xml
from bicentennial.report.receipt import build_receipt, loop_time
from bicentennial.report.t1_gate import INVARIANTS, GateResult
from bicentennial.runner import compare, t0
from bicentennial.score.bundle import make_bundle
from bicentennial.score.invariants import Verdict
from bicentennial.systems import controls
from bicentennial.systems.hermes_plugin import PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/v01_acceptance.py"
C, H0, H1 = "c" * 40, "0" * 64, "1" * 64


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


accept = module("v01_acceptance", SCRIPT)
public_check = module("acceptance_public_check", ROOT / "scripts/public_check.py")


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(value))


def card(system, tier, verdict, arm="system", *, pack_hash=H0):
    source = json.loads((ROOT / "tests/fixtures/aggregate/two_lives.json").read_bytes())
    example = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"]["card_ring0"]
    entry = tomllib.loads((ROOT / "systems/registry/hermes-native.toml").read_text())
    entry["name"] = system
    pins = {k: "a" * len(v) for k, v in example["pins"].items() if k != "masks_hash"}
    pins.update(benchmark_commit=C, pack_hash=pack_hash if tier == "T0" else H1)
    if system in accept.SYSTEMS:
        artifact = tomllib.loads((ROOT / "systems/registry" / f"{system}.toml").read_text())["artifact"]
        pins["system_hash"] = sha256_canon([artifact])
    items = copy.deepcopy(source["items"])
    if arm == "wiped":
        for life in sorted({b["life"] for b in source["bundles"]}):
            ids = {i for b in source["bundles"] if b["life"] == life for i in b["items"]}
            lowest = min((i for i in items if i["item_id"] in ids and type(i["score_milli"]) is int),
                         key=lambda i: (i["score_milli"], i["item_id"]))
            lowest["stage_attribution"] = "retained"
    by_id = {i["item_id"]: i for i in items}
    bundles = [make_bundle({k: b[k] for k in ("bundle_id", "cell_id", "twin_type", "life")},
                           *(by_id[i] for i in b["items"])) for b in source["bundles"]]
    provisional = assemble(tier=tier, mode="api" if tier == "T0" else "hermes", system_entry=entry,
        run_status="COMPLETE", pins=pins, ledger_records=[],
        run_values=dict(sandbox_root="/sandbox/root", director_port="43210"), items=items,
        bundles=bundles, controls=example["controls"] | dict(
        wiped_store="not run at T0" if tier == "T0" else "FAIL"))
    return finalize(provisional, verdict)


def receipt(*, busy=False, ms=1000):
    return build_receipt(run_status="COMPLETE", wall_start_ms=100, wall_end_ms=100 + ms,
        latency_ms=[], load_milli=[0, 0, 0], busy_marker_readings=[busy], tokens_by_role={},
        runtime_by_role={}, spend_micro_usd=0, store_growth_bytes=0, process_ids=[12345],
        ports=[43210], temporary_paths=["/sandbox/transient-run"], raw_body_digest="a" * 64)


def pack_installation(packs, rels):
    """A minimal installation with real manifests, code pins, hash and modes."""
    for rel in rels:
        directory = packs / rel
        dump(directory / "sealed/scoring.json", {})
        (directory / "sealed/example.txt").write_bytes(b"fixture\n")
        dump(directory / "manifest.json", dict(files=file_manifest(directory),
                                               pins=dict(scoring_sha256=sha256_canon({}))))
    scorer = [p.relative_to(PACKAGE_ROOT).as_posix()
              for p in sorted((PACKAGE_ROOT / "score").glob("*.py"))]
    pins = {name: code_sha256(paths) for name, paths in (
        ("scorer_sha256", scorer), ("controls_sha256", CONTROL_FILES),
        ("reader_sha256", READER_FILES), ("scoring_code_sha256", SCORING_FILES))}
    dump(packs / "index.json", dict(tier="T0", packs={p: {} for p in rels},
                                   harness_artifacts=[], pins=pins | dict(harness_pin=sha256_canon([]))))
    for path in [packs, *packs.rglob("*")]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    return tree_sha256(packs)


def writable(root):
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    runs, packs = tmp_path / "runs", tmp_path / "packs/T0"
    rels = ("pack/G2/a/example/6101", "pack/G2/b/example/6102")
    pack_hash = pack_installation(packs, rels)
    inv = [Verdict(n, "NOT_EXERCISED" if n == "INV-FORGET" else "PASS", 1, 0, (), (), (), ()).to_obj()
           for n in INVARIANTS]
    control = dict(canary=source_canary(), label=controls.WIPED_LABEL, wipes=[], floor_mismatches=[])
    for system in sorted((*accept.SYSTEMS, accept.REFERENCE)):
        for tier in (("t0",) if system == accept.REFERENCE else ("t0", "t1")):
            baseline = None
            for name in accept.RUNS[tier]:
                directory = runs / system / tier / name
                directory.mkdir(parents=True)
                directory.with_suffix(".exit").write_text("0\n")
                units = rels if tier == "t0" else ("system", "wiped")
                for unit in units:
                    arm = "system" if tier == "t0" else unit
                    verdict = "PASS" if tier == "t0" or (arm == "system" and name != "base") else (
                        "CONFORMANCE_PASS" if arm == "system" else "FAIL")
                    data = card(system, tier.upper(), verdict, arm, pack_hash=pack_hash)
                    d = directory / unit
                    d.mkdir(parents=True)
                    (d / "card.json").write_bytes(data)
                    if tier == "t1" and name == "base" and arm == "system":
                        baseline = sha256(data).hexdigest()
                    dump(d / "receipt.json", receipt(busy=tier == "t1" and name == "run2"))
                    dump(d / "invariants.json", inv)
                    dump(d / "controls.json", control)
                    props = [("honeypot.hits", "0")]
                    if tier == "t0":
                        props += [("t0.fixture", "producer-built fixture")]
                    else:
                        dump(d / "corpus.json", [dict(case_id="r1.wipe_on_restart", status="PASS",
                                                      first_diff=None, reason="")])
                        gate = GateResult(arm, verdict, 1 if arm == "wiped" else 0, "COMPLETE",
                            None if name == "base" else baseline, (), (), (), (), (), ())
                        props += [*compare.DISCLOSURES,
                            *(compare.PLUGIN_DISCLOSURES if system in accept.PLUGINS else ()),
                            *[(n, "0") for n in accept.WITNESSES],
                            ("controls.floor_mismatches", "[]"), ("controls.wiped_store", "FAIL"),
                            ("gate", canon(gate.to_obj()).decode()), ("gate.final", verdict)]
                        if arm == "wiped":
                            props.append(("wiped.label", controls.WIPED_LABEL))
                    (d / "junit.xml").write_bytes(junit_xml([item_suite(json.loads(data), arm, props)]))
                if tier == "t0":
                    dump(directory / "adapter_invariants.json", inv)
                    dump(directory / "relations.json", {})
                    (directory / "relations.xml").write_bytes(junit_xml([]))
    try:
        yield SimpleNamespace(runs=runs, t0_packs=packs, t0_pack_hash=pack_hash, t1_pack_hash=H1,
                              commit=C, out=tmp_path / "out", rels=rels)
    finally:
        writable(packs)


def source_canary():
    return (ROOT / "CANARY").read_text().strip()


def argv(tree, out=None):
    return [value for name in ("runs", "t0_packs", "t0_pack_hash", "t1_pack_hash", "commit", "out")
            for value in ("--" + name.replace("_", "-"), str(out if name == "out" and out else getattr(tree, name)))]


def load_result(tree):
    return json.loads((tree.out / "RESULT-MANIFEST.json").read_bytes())


def codes(result):
    return {code for check in result["checks"] for code, _ in check["failures"]}


def unit_path(tree, *, system="hermes-native", tier="t1", name="run2", unit="system"):
    return tree.runs / system / tier / name / unit


def rewrite_card(path, **changes):
    target = path / "card.json"
    dump(target, json.loads(target.read_bytes()) | changes)


def prop(path, name, value):
    target = path / "junit.xml"
    root = ET.fromstring(target.read_bytes())
    parent = root.find("testsuite/properties")
    old = next((p for p in parent if p.get("name") == name), None)
    if old is not None:
        parent.remove(old)
    if value is not None:
        ET.SubElement(parent, "property", name=name, value=value)
    ET.indent(root, space="  ")
    target.write_bytes(ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n")


def rewrite_receipt(path, **changes):
    target = path / "receipt.json"
    dump(target, json.loads(target.read_bytes()) | changes)


def test_pass_and_repeat(tree, tmp_path, capsys, monkeypatch):
    before = file_manifest(tree.t0_packs), {p: p.stat().st_mode for p in
                                         [tree.t0_packs, *tree.t0_packs.rglob("*")]}
    assert accept.main(argv(tree)) == 0
    assert capsys.readouterr().out.endswith("accepted\n")
    m = load_result(tree)
    assert m["accepted"] and all(c["holds"] for c in m["checks"])
    assert m["target_misses"] == []
    kit = dict(m["disclosures"]["kit"])
    assert "kit.busy.T0" in kit and "kit.busy.T1" not in kit
    assert m["loop_time"]["T1"]["idle_n"] == 6
    assert m["loop_time"]["T1"]["busy_n"] == 3
    other = tmp_path / "second"
    assert accept.main(argv(tree, other)) == 0
    assert {p.name for p in tree.out.iterdir()} == {"RESULT.md", "RESULT-MANIFEST.json"}
    for p in sorted(tree.out.iterdir()):
        data = p.read_bytes()
        assert data == (other / p.name).read_bytes()
        assert not public_check.PATHS.search(data.decode())
        assert str(tmp_path).encode() not in data
        assert b"43210" not in data and b"12345" not in data and b"transient-run" not in data
    md = (tree.out / "RESULT.md").read_text()
    headings = re.findall(r"^## .+$", md, re.M)
    assert headings == ["## " + n for n in ("Results", "Loop time", "Target misses", "Disclosures",
                                           "Acceptance checks", "What this does not prove")]
    assert md.endswith(accept.LIMITS + "\n")
    assert accept.render(m, accept.contracts()) == md
    # A redundant guard: on valid inputs the structure and pack-hash checks pass, so skipping them
    # must give the same manifest bytes. The mode and manifest comparison below is the real check
    # that verifying the installation leaves it untouched.
    unchecked = tmp_path / "unchecked"
    with monkeypatch.context() as patch:
        patch.setattr(accept, "verify_t0_packs", lambda *args: None)
        patch.setattr(accept, "xml_structure", lambda *args: None)
        assert accept.main(argv(tree, unchecked)) == 0
    assert (tree.out / "RESULT-MANIFEST.json").read_bytes() == (unchecked / "RESULT-MANIFEST.json").read_bytes()
    assert before == (file_manifest(tree.t0_packs), {p: p.stat().st_mode for p in
                                                  [tree.t0_packs, *tree.t0_packs.rglob("*")]})


@pytest.mark.parametrize("tier,unit", [("t0", None), ("t1", "system"), ("t1", "wiped")])
@pytest.mark.parametrize("element,attribute", [
    (".", "tests"), ("testsuite", "skipped"), ("testsuite/testcase", "classname"),
    ("testsuite/properties/property", "value"),
])
def test_junit_required_attributes(tree, tier, unit, element, attribute):
    target = unit_path(tree, tier=tier, unit=unit or tree.rels[0]) / "junit.xml"
    root = ET.fromstring(target.read_bytes())
    del root.find(element).attrib[attribute]
    target.write_bytes(ET.tostring(root))
    assert accept.main(argv(tree)) == 1
    failures = next(c["failures"] for c in load_result(tree)["checks"] if c["name"] == "schema")
    where = target.relative_to(tree.runs).as_posix()
    assert [(code, rule) for code, rule in failures if code == "junit_structure"] == [
        ("junit_structure", where + ":/testsuites" + {
            ".": "", "testsuite": "/testsuite[1]", "testsuite/testcase": "/testsuite[1]/testcase[1]",
            "testsuite/properties/property": "/testsuite[1]/properties[1]/property[1]",
        }[element] + f"/@{attribute}:required")]


@pytest.mark.parametrize("mutation", [
    "root", "count", "element", "attribute", "property", "order", "choice", "detail", "text", "leaf_text",
])
def test_junit_structure_rules(tree, mutation):
    target = unit_path(tree) / "junit.xml"
    root = ET.fromstring(target.read_bytes())
    suite = root.find("testsuite")
    if mutation == "root":
        root.tag = "report"
    elif mutation == "count":
        suite.set("tests", "-1")
    elif mutation == "element":
        ET.SubElement(suite, "unknown")
    elif mutation == "attribute":
        suite.find("testcase").set("unexpected", "value")
    elif mutation == "property":
        suite.find("properties").clear()
    elif mutation == "order":
        props = suite.find("properties")
        suite.remove(props)
        suite.append(props)
    elif mutation in ("choice", "detail"):
        case = suite.find("testcase")
        for child in list(case):
            case.remove(child)
        ET.SubElement(case, "failure", type="QA", message="failure")
        if mutation == "choice":
            ET.SubElement(case, "error", type="SYSTEM_FAILURE", message="error")
        else:
            del case[0].attrib["type"]
    elif mutation == "text":
        suite.text = "unexpected text"
    else:
        suite.find("properties/property").text = " "
    target.write_bytes(ET.tostring(root))
    assert accept.main(argv(tree)) == 1
    assert "junit_structure" in codes(load_result(tree))


@pytest.mark.parametrize("attribute", ["name", "tests", "failures", "errors"])
def test_relations_required_attributes(tree, attribute):
    target = unit_path(tree, tier="t0", unit="relations.xml")
    root = ET.fromstring(target.read_bytes())
    del root.attrib[attribute]
    target.write_bytes(ET.tostring(root))
    assert accept.main(argv(tree)) == 1
    check = next(c for c in load_result(tree)["checks"] if c["name"] == "schema")
    assert check["failures"] == [["relations_structure",
        target.relative_to(tree.runs).as_posix() + f":/testsuites/@{attribute}:required"]]


@pytest.mark.parametrize("mutation", ["removed", "narrowed_index", "byte"])
def test_t0_pack_hash_verified_before_index_and_per_pack_checks(tree, monkeypatch, capsys, mutation):
    directory = tree.t0_packs / tree.rels[0]
    if mutation == "byte":
        target = directory / "sealed/example.txt"
        target.chmod(0o644)
        target.write_bytes(b"Fixture\n")
        target.chmod(0o444)
    else:
        writable(directory)
        directory.parent.chmod(0o755)
        shutil.rmtree(directory)
        directory.parent.chmod(0o555)
        if mutation == "narrowed_index":
            target = tree.t0_packs / "index.json"
            value = json.loads(target.read_bytes())
            del value["packs"][tree.rels[0]]
            target.chmod(0o644)
            dump(target, value)
            target.chmod(0o444)
    called = []

    def observe(name, function):
        def wrapped(*args):
            called.append(name)
            return function(*args)
        return wrapped

    monkeypatch.setattr(accept, "read_index", observe("index", accept.read_index))
    monkeypatch.setattr(accept.Predicates, "t0_packs", observe("packs", accept.Predicates.t0_packs))
    assert accept.main(argv(tree)) == 3
    assert capsys.readouterr() == ("", "t0_pack_hash_mismatch --t0-packs\n")
    assert called == []
    assert not tree.out.exists()


# Each row declares all primary and secondary failure codes, not only its intended finding.
MUTATIONS = [
    ("run_refused", {"run_refused"}),
    ("refused_absent", {"run_refused"}),
    ("run_incomplete", {"run_incomplete"}),
    ("run_layout", {"run_layout"}),
    ("exit_mismatch", {"exit_mismatch", "t1_exit"}),
    ("t0_exit", {"t0_exit", "t0_not_identical"}),
    ("t1_exit", {"t1_exit", "run_status", "t1_system_gate", "t1_not_identical"}),
    ("schema_invalid", {"schema_invalid"}),
    ("t0_pack_set", {"t0_pack_set"}),
    ("run_status", {"run_status", "t1_not_identical"}),
    ("t0_not_identical", {"t0_not_identical"}),
    ("t1_system_gate", {"t1_system_gate"}),
    ("t1_baseline", {"t1_baseline", "t1_not_identical"}),
    ("t1_not_identical", {"t1_not_identical"}),
    ("t1_base_differs", {"t1_base_differs", "t1_baseline"}),
    ("wiped_not_fail", {"wiped_not_fail", "t1_not_identical"}),
    ("wiped_store", {"wiped_store", "t1_not_identical"}),
    ("t1_lives", {"t1_lives", "t1_not_identical"}),
    ("wiped_stage", {"wiped_stage", "t1_not_identical"}),
    ("isolation_unknown", {"isolation_unknown", "t1_not_identical"}),
    ("isolation_forwarded", {"isolation_forwarded", "t1_not_identical"}),
    ("no_memory_gold", {"no_memory_gold", "t1_not_identical"}),
    ("property_missing", {"property_missing", "t1_not_identical"}),
    ("controls", {"controls", "t1_not_identical"}),
    ("floor_mismatches", {"floor_mismatches", "t1_not_identical"}),
    ("honeypot", {"honeypot", "t1_not_identical"}),
    ("invalid_card", {"honeypot", "exit_mismatch", "t1_system_gate", "t1_not_identical"}),
    ("spend", {"spend"}),
    ("pins_commit", {"pins_commit", "t1_not_identical"}),
    ("pins_pack_hash", {"pins_pack_hash", "t1_not_identical"}),
    ("pins_system", {"pins_system", "t1_not_identical"}),
    ("disclosure_missing:t1.window", {"disclosure_missing:t1.window", "t1_not_identical"}),
    ("disclosure_missing:t1.fresh_install_mask",
     {"disclosure_missing:t1.fresh_install_mask", "t1_not_identical"}),
]


def mutate(tree, name):
    p = unit_path(tree)
    if name in ("run_refused", "refused_absent"):
        dump(p.parent / "refusal.json", dict(code="upstream_record", fields=[]))
        p.parent.with_suffix(".exit").write_text("3\n")
        if name == "refused_absent":
            shutil.rmtree(p.parent)
    elif name == "run_incomplete":
        (p / "junit.xml").unlink()
    elif name == "run_layout":
        (p.parent / "work").mkdir()
    elif name == "exit_mismatch":
        p.parent.with_suffix(".exit").write_text("1\n")
    elif name == "t0_exit":
        p = unit_path(tree, system=accept.REFERENCE, tier="t0", unit=tree.rels[0])
        rewrite_card(p, gate_verdict="FAIL")
        tree.runs.joinpath(accept.REFERENCE, "t0/run2.exit").write_text("1\n")
    elif name == "t1_exit":
        rewrite_card(p, gate_verdict="BLOCKED", run_status="BLOCKED")
        prop(p, "gate.final", "BLOCKED")
        p.parent.with_suffix(".exit").write_text("2\n")
    elif name == "schema_invalid":
        target = p / "card.json"
        target.write_bytes(target.read_bytes() + b" ")
    elif name == "t0_pack_set":
        for run in ("run1", "run2"):
            shutil.rmtree(unit_path(tree, tier="t0", name=run, unit=tree.rels[0]))
    elif name == "run_status":
        rewrite_card(p.parent / "wiped", run_status="BLOCKED")
    elif name == "t0_not_identical":
        rewrite_card(unit_path(tree, tier="t0", unit=tree.rels[0]), masked_ledger_digest="b" * 64)
    elif name == "t1_system_gate":
        prop(p, "gate.final", "FAIL")
        # Apply the same stable change to run1 to isolate the gate predicate.
        prop(unit_path(tree, name="run1"), "gate.final", "FAIL")
    elif name == "t1_baseline":
        root = ET.fromstring((p / "junit.xml").read_bytes())
        gate = json.loads(next(n.get("value") for n in root.findall("testsuite/properties/property")
                               if n.get("name") == "gate"))
        gate["baseline_sha256"] = "f" * 64
        prop(p, "gate", canon(gate).decode())
    elif name == "t1_not_identical":
        rewrite_card(p, masked_ledger_digest="b" * 64)
    elif name == "t1_base_differs":
        rewrite_card(unit_path(tree, name="base"), masked_ledger_digest="b" * 64)
    elif name == "wiped_not_fail":
        rewrite_card(p.parent / "wiped", gate_verdict="PASS")
    elif name == "wiped_store":
        prop(p, "controls.wiped_store", "uninformative")
    elif name == "t1_lives":
        p = p.parent / "wiped"
        value = json.loads((p / "card.json").read_bytes())
        entry = tomllib.loads((ROOT / "systems/registry/hermes-native.toml").read_text())
        updated = assemble(tier="T1", mode="hermes", system_entry=entry, run_status="COMPLETE",
            pins={k: v for k, v in value["pins"].items() if k != "masks_hash"}, ledger_records=[],
            run_values=dict(sandbox_root="/sandbox/root", director_port="43210"),
            items=value["items"], bundles=[b | dict(life="one-life") for b in value["bundles"]],
            controls=value["controls"])
        (p / "card.json").write_bytes(finalize(updated, "FAIL"))
    elif name == "wiped_stage":
        p = p.parent / "wiped"
        value = json.loads((p / "card.json").read_bytes())
        ids = {i for b in value["bundles"] if b["life"] == "life-g1" for i in b["items"]}
        rewrite_card(p, items=[i | dict(stage_attribution=None) if i["item_id"] in ids else i
                              for i in value["items"]])
    elif name in ("isolation_unknown", "isolation_forwarded", "no_memory_gold", "property_missing"):
        witness = {"isolation_unknown": "isolation.unknown_requests",
                   "isolation_forwarded": "isolation.forwarded", "no_memory_gold": "no_memory.gold_in_context",
                   "property_missing": "isolation.forwarded"}[name]
        prop(p, witness, None if name == "property_missing" else "1")
    elif name == "controls":
        target = p.parent / "wiped/controls.json"
        dump(target, json.loads(target.read_bytes()) | dict(label="another label"))
    elif name == "floor_mismatches":
        for arm in ("system", "wiped"):
            target = p.parent / arm / "controls.json"
            dump(target, json.loads(target.read_bytes()) | dict(floor_mismatches=["b1"]))
        prop(p, "controls.floor_mismatches", '["b1"]')
    elif name == "honeypot":
        prop(p, "honeypot.hits", "1")
    elif name == "invalid_card":
        rewrite_card(p, gate_verdict="INVALID")
    elif name == "spend":
        rewrite_receipt(p, spend_micro_usd=1)
    elif name.startswith("pins_"):
        field = {"pins_commit": "benchmark_commit", "pins_pack_hash": "pack_hash",
                 "pins_system": "system_hash"}[name]
        pins = json.loads((p / "card.json").read_bytes())["pins"]
        rewrite_card(p, pins=pins | {field: "b" * len(pins[field])})
    elif name.startswith("disclosure_missing:"):
        if name.endswith("fresh_install_mask"):
            p = unit_path(tree, system="holographic")
        prop(p, name.split(":", 1)[1], None)
    else:
        raise AssertionError(name)


@pytest.mark.parametrize("name,expected", MUTATIONS)
def test_mutations(tree, capsys, name, expected):
    mutate(tree, name)
    assert accept.main(argv(tree)) == 1
    output = capsys.readouterr().out
    m = load_result(tree)
    assert codes(m) == expected
    assert not m["accepted"]
    for check in m["checks"]:
        for code, where in check["failures"]:
            assert f"FAIL {check['name']} {code} {where}" in output
    if name == "t0_not_identical":
        assert any(where.endswith("card.masked_ledger_digest") for c in m["checks"]
                   for code, where in c["failures"] if code == "t0_not_identical")


@pytest.mark.parametrize("name,expected", [
    ("missing_flag", "usage"), ("bad_commit", "usage"), ("out_exists", "out_exists"),
    ("runs_missing", "runs_missing"), ("extra_system", "layout"), ("missing_tier", "layout"),
    ("exit_file", "exit_file"), ("truncated", "unreadable"), ("index", "index")])
def test_input_errors(tree, capsys, name, expected):
    args = argv(tree)
    if name == "missing_flag":
        args = args[:-2]
    elif name == "bad_commit":
        args[args.index("--commit") + 1] = "a" * 39
    elif name == "out_exists":
        tree.out.mkdir()
    elif name == "runs_missing":
        shutil.rmtree(tree.runs)
    elif name == "extra_system":
        (tree.runs / "other").mkdir()
    elif name == "missing_tier":
        shutil.rmtree(tree.runs / "mem0-oss/t1")
    elif name == "exit_file":
        (tree.runs / "hermes-native/t0/run1.exit").write_text("0")
    elif name == "truncated":
        (unit_path(tree) / "card.json").write_text("{")
    elif name == "index":
        target = tree.t0_packs / "index.json"
        value = json.loads(target.read_bytes()) | dict(tier="T1", packs={})
        target.chmod(0o644)
        dump(target, value)
        target.chmod(0o444)
        # Keep installation verification valid to exercise read_index's tier check.
        args[args.index("--t0-pack-hash") + 1] = tree_sha256(tree.t0_packs)
    assert accept.main(args) == 3
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1].startswith(expected + " ")
    assert captured.out == ""
    assert not tree.out.exists() or (name == "out_exists" and not list(tree.out.iterdir()))


@pytest.mark.parametrize("args", [("-h",), ("--help",), ("valid", "--help")])
def test_help_is_usage_refusal(tree, args):
    args = [*argv(tree), args[-1]] if args[0] == "valid" else list(args)
    result = subprocess.run([sys.executable, str(SCRIPT), *args],
                            capture_output=True, text=True)
    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr.startswith("usage: ")
    assert result.stderr.endswith("usage arguments\n")
    assert not tree.out.exists()


@pytest.mark.parametrize("status", [0, 2])
def test_parser_exit_is_usage_refusal(tree, monkeypatch, capsys, status):
    def exit_during_parse(parser, args):
        parser.exit(status, "parser exit\n")

    monkeypatch.setattr(accept.Parser, "parse_args", exit_during_parse)
    assert accept.main(argv(tree)) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("usage: ")
    assert captured.err.endswith("usage arguments\n")
    assert not tree.out.exists()


def test_hashseed_subprocess(tree):
    result = subprocess.run([sys.executable, str(SCRIPT), *argv(tree)], capture_output=True, text=True,
                            env=dict(os.environ, PYTHONHASHSEED="random"))
    assert result.returncode == 3 and result.stderr == "hashseed PYTHONHASHSEED\n"
    assert not tree.out.exists()


def test_loop_targets_are_disclosures(tree):
    p = unit_path(tree, tier="t0", unit=tree.rels[0])
    rewrite_receipt(p, wall_end_ms=61_100)
    rewrite_receipt(unit_path(tree), wall_end_ms=700_100, busy_marker_readings=[True])
    assert accept.main(argv(tree)) == 0
    m = load_result(tree)
    assert len(m["target_misses"]) == 2
    assert m["loop_time"]["T1"]["busy_max_ms"] == 700_000
    assert "kit.busy.T1" not in dict(m["disclosures"]["kit"])
    markdown = (tree.out / "RESULT.md").read_text()
    assert "61000 ms against 60000 ms (idle)" in markdown
    assert "700000 ms against 600000 ms (busy)" in markdown


def test_predicate_order_and_tuple_results(tree, monkeypatch):
    called = []

    def observe(name, original):
        def wrapped(*args):
            called.append(name)
            result = original(*args)
            assert isinstance(result, tuple)
            return result
        return wrapped

    for name in accept.CHECKS[:-1]:
        monkeypatch.setattr(accept.Predicates, name, observe(name, getattr(accept.Predicates, name)))
    monkeypatch.setattr(accept, "loop_time_measured",
                        observe("loop_time_measured", accept.loop_time_measured))
    assert accept.main(argv(tree)) == 0
    assert tuple(called) == accept.CHECKS


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_invalid_card_keeps_other_artifact_checks(tree, tier):
    p = unit_path(tree, tier=tier, unit=tree.rels[0] if tier == "t0" else "system")
    target = p / "card.json"
    target.write_bytes(target.read_bytes() + b" ")
    invariant = p / "invariants.json"
    value = json.loads(invariant.read_bytes())
    value[0]["status"] = "FAIL"
    dump(invariant, value)
    assert accept.main(argv(tree)) == 1
    assert codes(load_result(tree)) == {"schema_invalid", f"{tier}_not_identical"}


@pytest.mark.parametrize("value", [None, "[]", "{", "{}"])
def test_t1_gate_property_shape(tree, value):
    prop(unit_path(tree), "gate", value)
    assert accept.main(argv(tree)) == 1
    assert codes(load_result(tree)) == {"schema_invalid"}


@pytest.mark.parametrize("side,busy", [("busy", False), ("idle", True)])
def test_loop_side_required(tree, side, busy):
    for system in accept.SYSTEMS:
        for run in accept.RUNS["t1"]:
            rewrite_receipt(unit_path(tree, system=system, name=run), busy_marker_readings=[busy])
    assert accept.main(argv(tree)) == 1
    assert codes(load_result(tree)) == {f"loop_time_unmeasured:{side}"}


@pytest.mark.parametrize("status", ["BLOCKED", "INFRA_FAILURE"])
@pytest.mark.parametrize("tier,arm", [("t0", None), ("t1", "system"), ("t1", "wiped")])
def test_receipt_run_status_must_match_complete_card(tree, status, tier, arm):
    path = unit_path(tree, tier=tier, unit=arm or tree.rels[0])
    rewrite_receipt(path, run_status=status)
    assert accept.main(argv(tree)) == 1
    result = load_result(tree)
    assert not result["accepted"]
    assert codes(result) == {"run_status"}
    check = next(c for c in result["checks"] if c["name"] == "run_status")
    assert check["failures"] == [["run_status", (path / "receipt.json").relative_to(tree.runs).as_posix()]]


def test_empty_marker_readings_are_unmeasured(tree, capsys):
    for system in accept.SYSTEMS:
        for run in accept.RUNS["t1"]:
            rewrite_receipt(unit_path(tree, system=system, name=run), busy_marker_readings=[])
    rewrite_receipt(unit_path(tree), busy_marker_readings=[True])
    assert accept.main(argv(tree)) == 1
    result = load_result(tree)
    assert not result["accepted"]
    assert codes(result) == {"loop_time_unmeasured:idle"}
    assert "loop_time_unmeasured:idle" in capsys.readouterr().out
    assert result["loop_time"]["T1"]["idle_n"] == 0
    assert result["loop_time"]["T1"]["idle_max_ms"] is None
    assert result["loop_time"]["T1"]["busy_n"] == 1


def test_junit_structure_pinned_to_xsd():
    xs = "{http://www.w3.org/2001/XMLSchema}"
    schema = ET.parse(ROOT / "schemas/junit.xsd").getroot()
    assert [e.get("name") for e in schema.findall(xs + "element")] == [accept.JUNIT_ROOT]
    groups = {g.get("name"): g for g in schema.findall(xs + "attributeGroup")}
    types = {t.get("name"): t for t in schema.findall(xs + "complexType")}

    def attributes(container):
        result = []
        for node in container:
            if node.tag == xs + "attributeGroup":
                assert set(node.attrib) == {"ref"}
                result.extend(attributes(groups[node.get("ref")]))
            elif node.tag == xs + "attribute":
                assert set(node.attrib) == {"name", "type", "use"}
                assert node.get("use") == "required"
                assert node.get("type") in ("xs:string", "xs:nonNegativeInteger")
                result.append((node.get("name"), node.get("type")))
            else:
                assert node.tag in (xs + "sequence", xs + "choice")
        return tuple(sorted(result))

    def occurs(node):
        maximum = node.get("maxOccurs", "1")
        return int(node.get("minOccurs", "1")), None if maximum == "unbounded" else int(maximum)

    actual = {}
    for element in schema.iter(xs + "element"):
        assert set(element.attrib) <= {"name", "type", "minOccurs", "maxOccurs"}
        assert element.get("name") not in actual
        if element.get("type"):
            assert not list(element)
            container = types[element.get("type")]
        else:
            assert [n.tag for n in element] == [xs + "complexType"]
            container = element[0]
        assert not (set(container.attrib) - {"name"})  # mixed content needs a new rule.
        models = [n for n in container if n.tag in (xs + "sequence", xs + "choice")]
        assert len(models) <= 1
        content = None
        if models:
            model = models[0]
            assert set(model.attrib) <= {"minOccurs", "maxOccurs"}
            assert all(n.tag == xs + "element" for n in model)
            content = (model.tag.removeprefix(xs), *occurs(model),
                       tuple((n.get("name"), *occurs(n)) for n in model))
        actual[element.get("name")] = attributes(container), content
    assert accept.JUNIT_STRUCTURE == actual
    assert accept.RELATIONS_STRUCTURE == actual


def test_constants():
    assert accept.T1_DISCLOSURES == tuple(n for n, _ in compare.DISCLOSURES)
    assert accept.PLUGIN_T1_DISCLOSURES == tuple(n for n, _ in compare.PLUGIN_DISCLOSURES)
    assert accept.WIPED_LABEL == controls.WIPED_LABEL
    assert accept.PLUGINS == tuple(sorted(PROVIDERS))
    schema = json.loads((ROOT / "schemas/card_ring0.schema.json").read_bytes())
    assert schema["properties"]["labels"]["properties"]["signal"]["enum"] == [accept.SIGNAL]
    parsed = ast.parse(Path(compare.__file__).read_text())
    assignment = next(n for n in ast.walk(parsed) if isinstance(n, ast.Assign) and
                      any(isinstance(t, ast.Name) and t.id == "witnesses" for t in n.targets))
    assert tuple(sorted(e.elts[0].value for e in assignment.value.elts)) == accept.WITNESSES


def test_purity_ast():
    source = SCRIPT.read_text()
    parsed = ast.parse(source)
    allowed = {"argparse", "hashlib", "json", "os", "re", "sys", "tomllib", "pathlib",
               "dataclasses", "xml.etree.ElementTree", "bicentennial.canon",
               "bicentennial.contracts.run", "bicentennial.report.receipt",
               "bicentennial.report.determinism", "bicentennial.report.t1_gate",
               "bicentennial.packs.install"}
    for n in ast.walk(parsed):
        if isinstance(n, ast.Import):
            assert all(a.name in allowed for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            assert n.module in allowed
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os":
            assert n.attr == "environ"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and ast.unparse(n.func).startswith("os."):
            assert ast.unparse(n.func) == "os.environ.get"
            assert len(n.args) == 1 and n.args[0].value == "PYTHONHASHSEED"
    assert "l" + "cm" not in source.lower()


def test_purity_import_graph(tree):
    # The mandatory verifier imports read-only helpers from packs, runner.lock,
    # adapters and scoring. Allow only that dependency closure through the old ban.
    program = ("import runpy,sys,json; import bicentennial.packs.install; "
               "verifier_modules=set(sys.modules); m=runpy.run_path(sys.argv[1]); "
               "code=m['main'](sys.argv[2:]); print(json.dumps(dict(modules=sorted(sys.modules), "
               "verifier_modules=sorted(verifier_modules)))); sys.exit(code)")
    result = subprocess.run([sys.executable, "-c", program, str(SCRIPT), *argv(tree)],
                            capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED="0"))
    assert result.returncode == 0, result.stderr + result.stdout
    modules = json.loads(result.stdout.splitlines()[-1])
    denied = ("harness", "runner", "systems", "director", "api", "sandbox", "probe", "packs")
    assert not [n for n in set(modules["modules"]) - set(modules["verifier_modules"])
                if n.startswith(tuple("bicentennial." + p for p in denied))]


def test_seeded_receipt_properties(tree):
    rng = random.Random(3107)
    for _ in range(20):
        ms, busy = rng.randrange(0, 1_200_001), bool(rng.randrange(2))
        r = receipt(ms=ms, busy=busy)
        assert loop_time(r) == (ms, busy)
        args = copy.copy(tree)
        p = unit_path(tree)
        dump(p / "receipt.json", r)
        m = accept.evaluate(args)
        assert m["accepted"]
        row = next(r for r in m["runs"] if (r["system"], r["tier"], r["run"]) ==
                   ("hermes-native", "T1", "run2"))
        assert row["loop"] == [dict(unit="system", ms=ms, busy=busy)]
        assert any(r["system"] == "hermes-native" and r["run"] == "run2" for r in m["target_misses"]) == (ms > 600_000)


def test_real_t0_layout(tmp_path, monkeypatch, capsys):
    from bicentennial.packs import build
    from bicentennial.packs.catalogue import load_catalogue
    from bicentennial.packs.install import install

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    catalogue = load_catalogue(ROOT / "packs/catalogue-v0.toml", c7_path=ROOT / "specs/ring0/c7-partial.json",
                               tier_path=ROOT / "tiers/life_specs/t0.toml")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build, "check_distribution", lambda packs, **kwargs:
                      SimpleNamespace(ok=True, to_obj=lambda: {}))
        built = build.build_tier("T0", tmp_path / "build", harness_artifacts=[
            tomllib.loads((ROOT / "systems/registry/hermes-native.toml").read_text())["artifact"]],
            rows=[catalogue.by_id()["g2-recall-count-mft-1"]])
    installed = tmp_path / "installed"
    try:
        pack_hash = install(tmp_path / "build/T0", installed)
        assert pack_hash == built["pack_hash"]
        runs = tmp_path / "runs"
        for name in ("run1", "run2"):
            out = runs / accept.REFERENCE / "t0" / name
            out.parent.mkdir(parents=True, exist_ok=True)
            code = t0.run_t0(system=accept.REFERENCE, packs=["all"], packs_dir=installed,
                             pack_hash=pack_hash, out=out)
            out.with_suffix(".exit").write_text(f"{code}\n")
            assert code == 0
        rel = sorted(built["index"]["packs"])[0]
        card_path = runs / accept.REFERENCE / "t0/run1" / rel / "card.json"
        commit = json.loads(card_path.read_bytes())["pins"]["benchmark_commit"]
        args = SimpleNamespace(runs=runs, t0_packs=installed, t0_pack_hash=pack_hash,
                               t1_pack_hash=H1, commit=commit)
        result = accept.evaluate(args, systems=())
        assert all(c["holds"] for c in result["checks"]), result["checks"]
        evidence = dict(card_sha256=sha256(card_path.read_bytes()).hexdigest(),
            loop=[r["loop"] for r in result["runs"]])
        # Stored outside the repository only when the lane supplies an evidence destination.
        target = os.environ.get("V01_ACCEPTANCE_EVIDENCE")
        if target:
            dump(Path(target), evidence)
        with capsys.disabled():
            print("producer_evidence=" + canon(evidence).decode())
    finally:
        if installed.exists():
            for path in [installed, *sorted(installed.rglob("*"))]:
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
