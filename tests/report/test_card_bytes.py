"""S11 offline reporting acceptance, including seeded byte-identity properties."""

import ast
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.ledger import stable_digest
from bicentennial.report.card import assemble, finalize
from bicentennial.report.junit import (
    Case,
    item_cases,
    item_suite,
    junit_cases_from_invariants,
    junit_xml,
    run_properties,
)
from bicentennial.report.receipt import (
    SpendRefused,
    build_receipt,
    busy,
    ledger_latencies,
    load_milli,
    loop_time,
    percentiles,
    raw_body_digest,
    write_run,
)
from bicentennial.runner.guard import REFUSED_EXIT, Marker
from bicentennial.score.aggregate import reduce
from bicentennial.score.bundle import make_bundle
from bicentennial.systems.registry import load

ROOT = Path(__file__).resolve().parents[2]
RUN_VALUES = dict(sandbox_root="/sandbox/root", director_port="43210")


def example(name):
    return json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"][name]


def fixture():
    return json.loads((ROOT / "tests/fixtures/aggregate/two_lives.json").read_bytes())


def ledger():
    records = []
    for n, role in enumerate(("replay_main", "probe_main", "write_turn"), 1):
        record = dict(type="request", seq=n, t=100 + n, t_ms=10 * n, load=[0, 100, 200],
                      run="run-1", hash="a" * 64, prev_hash="b" * 64,
                      req=str(n) * 64, resp=str(n + 3) * 64, req_chars=10,
                      n_messages=1, n_tools=0, method="POST", path="/v1/chat/completions",
                      subrole="", model_in="bicentennial-main", life="life-g1", branch="B0",
                      system="hermes-native", attempt_id=f"attempt-{n}", role=role,
                      cursor=dict(session=1, turn=n), status=200, served="script",
                      served_by="scripted", lock_hash="c" * 64, req_masked_sha256=str(n) * 64,
                      resp_masked_sha256=str(n + 3) * 64, sim_now=1000 + n, upstream=[],
                      incoming_auth_dropped=True, write_calls=0, write_turn_failed="",
                      write_turn_readback=True)
        validate("ledger-record", record)
        records.append(record)
    return records


def inputs():
    f = fixture()
    pins = example("card_ring0")["pins"]
    del pins["masks_hash"]
    return dict(tier="T1", mode="hermes", system_entry=load(ROOT / "systems/registry/hermes-native.toml"),
                run_status="COMPLETE", pins=pins, ledger_records=ledger(), run_values=RUN_VALUES,
                items=f["items"], bundles=f["bundles"], controls=example("card_ring0")["controls"])


def card_bytes(**changes):
    return finalize(assemble(**dict(inputs(), **changes)), "PASS")


def receipt_inputs(records=None):
    return dict(run_status="COMPLETE", wall_start_ms=100, wall_end_ms=200,
                latency_ms=ledger_latencies(records if records is not None else ledger()),
                load_milli=[0, 100, 250], busy_marker_readings=[False],
                tokens_by_role={"replay_main": (10, 5), "probe_main": (3, 2)},
                runtime_by_role={"replay_main": 100, "probe_main": 20}, spend_micro_usd=0,
                store_growth_bytes=32, process_ids=[123, 123, 12], ports=[8080, 8000, 8080],
                temporary_paths=["/sandbox/tmp-b", "/sandbox/tmp-a", "/sandbox/tmp-a"],
                raw_body_digest=raw_body_digest(records if records is not None else ledger()))


def test_fixture_values_and_fresh_copies():
    args = inputs()
    before = copy.deepcopy(args)
    f = fixture()
    assert reduce(f["items"], f["bundles"]) == f["expected"]
    provisional = assemble(**args)
    assert "gate_verdict" not in provisional
    raw = finalize(provisional, "PASS")
    assert "gate_verdict" not in provisional
    assert raw == card_bytes() == canon(json.loads(raw))
    card = json.loads(raw)
    for key in ("aggregates", "sensitivity", "worst_case", "twin_consistency", "violations"):
        assert card[key] == f["expected"][key]
    assert card["per_item_accuracy"] == f["expected"]["accuracy"]["cells"]
    assert card["coverage"] == dict(assigned=12, scored=10, blocked=1, na_exposure=0,
                                    na_clock=1, coverage_milli=833)
    assert card["singletons"] == []
    assert card["volatile_surface_paths"] == [dict(surface="HERMES_HOME", path=p)
                                               for p in (".mcp-discovery.lock", "logs")]
    assert card["voids"] == dict(checked=0, voided=0, void_milli=None)
    masks = ROOT / "src/bicentennial/contracts/masks.json"
    assert card["pins"]["masks_hash"] == sha256(masks.read_bytes()).hexdigest()
    assert card["masked_ledger_digest"] == stable_digest(args["ledger_records"], RUN_VALUES)
    assert stable_digest([], RUN_VALUES) == sha256(b"[]").hexdigest()
    assert card["competing_milli"] == card["carry_over_milli"] == 0
    assert card["diagnostics"] == [dict(track=t, competing_milli=0, carry_over_milli=0)
                                    for t in ("Recall", "Tuesday", "Wake")]
    assert args == before
    provisional["items"][0]["item_id"] = "changed"
    provisional["controls"]["full_history"] = 0
    assert args == before


def test_shares():
    args = inputs()
    item = next(i for i in args["items"] if i["item_id"] == "g1-recall-1-a")
    item.update(competing_present=["opt-aisle"], carry_over=True)
    card = json.loads(finalize(assemble(**args), "PASS"))
    assert (card["competing_milli"], card["carry_over_milli"]) == (42, 250)
    assert card["diagnostics"] == [dict(track=t, competing_milli=250 if t == "Recall" else 0,
                                       carry_over_milli=250 if t == "Recall" else 0)
                                    for t in ("Recall", "Tuesday", "Wake")]


def test_seeded_order_property_200_cases():
    rng = random.Random(1101)
    args = inputs()
    expected = finalize(assemble(**args), "PASS")
    for _ in range(200):
        shuffled = copy.deepcopy(args)
        for key in ("items", "bundles", "ledger_records"):
            rng.shuffle(shuffled[key])
        rng.shuffle(shuffled["system_entry"]["surfaces"])
        for surface in shuffled["system_entry"]["surfaces"]:
            rng.shuffle(surface["volatile_paths"])
        assert finalize(assemble(**shuffled), "PASS") == expected


def test_hashseed_subprocesses():
    code = """
import json
from hashlib import sha256
from tests.report.test_card_bytes import card_bytes
from bicentennial.report.junit import item_suite, junit_xml
raw = card_bytes()
xml = junit_xml([item_suite(json.loads(raw), 'system')])
print(json.dumps([sha256(raw).hexdigest(), sha256(xml).hexdigest()]))
"""
    outputs = [subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True,
                              capture_output=True, text=True,
                              env=dict(os.environ, PYTHONHASHSEED=seed)).stdout
               for seed in ("0", "random")]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])[0] == sha256(card_bytes()).hexdigest()


def test_timing_changes_only_affect_represented_receipt_inputs():
    original = ledger()
    baseline_card = card_bytes(ledger_records=original)
    baseline = canon(build_receipt(**receipt_inputs(original)))
    for key, value in (("t", 999), ("load", [4, 5, 6]), ("t_ms", 77), ("seq", None)):
        changed = copy.deepcopy(original)
        if key == "seq":
            changed[0][key], changed[1][key] = changed[1][key], changed[0][key]
        else:
            for r in changed:
                r[key] = value
        assert card_bytes(ledger_records=changed) == baseline_card
        current = canon(build_receipt(**receipt_inputs(changed)))
        assert (current == baseline) == (key in ("t", "load"))
    changes = dict(wall_end_ms=300, latency_ms=[99], load_milli=[8, 9, 10],
                   process_ids=[456], ports=[9090])
    for key, value in changes.items():
        assert canon(build_receipt(**dict(receipt_inputs(), **{key: value}))) != baseline
    changed = copy.deepcopy(original)
    for r in changed:
        r.update(t=555, t_ms=77, load=[7, 8, 9])
    changed[0]["seq"], changed[1]["seq"] = changed[1]["seq"], changed[0]["seq"]
    assert card_bytes(ledger_records=changed) == baseline_card
    assert canon(build_receipt(**dict(receipt_inputs(changed), **changes))) != baseline


def test_stable_changes_change_card():
    args = inputs()
    before = card_bytes()
    args["ledger_records"][0]["resp_masked_sha256"] = "f" * 64
    changed = finalize(assemble(**args), "PASS")
    assert json.loads(before)["masked_ledger_digest"] != json.loads(changed)["masked_ledger_digest"]
    args = inputs()
    item = args["items"][0]
    item["envelope"]["confidence_milli"] = 400
    item.update(score_milli=500, worst_case_milli=500)
    indexed = {i["item_id"]: i for i in args["items"]}
    args["bundles"] = [make_bundle({k: b[k] for k in ("bundle_id", "cell_id", "twin_type", "life")},
                                  *(indexed[i] for i in b["items"])) for b in args["bundles"]]
    assert finalize(assemble(**args), "PASS") != before


def test_void_disclosure_never_changes_other_fields_or_denominators():
    card = json.loads(card_bytes(voids=dict(checked=3, voided=1, void_milli=333)))
    plain = json.loads(card_bytes())
    assert card.pop("voids") == dict(checked=3, voided=1, void_milli=333)
    plain.pop("voids")
    assert canon(card) == canon(plain)
    blocked = next(i for i in card["items"] if i["item_id"] == "g2-wake-3-b")
    assert (blocked["failure_class"], blocked["infra_reruns"]) == ("BLOCKED", 2)
    assert card["coverage"]["assigned"] == 12 and card["coverage"]["blocked"] == 1


@pytest.mark.parametrize("voids", [dict(checked=3, voided=1, void_milli=334),
                                   dict(checked=3, voided=4, void_milli=1000),
                                   dict(checked=0, voided=0, void_milli=0)])
def test_validator_refuses_bad_voids(voids):
    card = json.loads(card_bytes())
    card["voids"] = voids
    with pytest.raises(ValueError):
        validate("card_ring0", card)


@pytest.mark.parametrize("voids", [dict(checked=0, voided=0, void_milli=None),
                                   dict(checked=3, voided=1, void_milli=333, extra=1)])
def test_assembler_refuses_bad_void_summary_shape(voids):
    with pytest.raises(ValueError):
        assemble(**inputs(), voids=voids)


def test_labels_t0_and_singleton_pass():
    assert "scripted_model" in json.loads(card_bytes())["labels"]
    for mode in ("api", "hermes"):
        args = inputs()
        args.update(tier="T0", mode=mode, ledger_records=[])
        args["controls"]["wiped_store"] = "not run at T0"
        provisional = assemble(**args)
        assert ("scripted_model" in provisional["labels"]) == (mode == "hermes")
        validate("card_ring0", json.loads(finalize(provisional, "PASS")))
    args["items"] = [i for i in args["items"] if i["stage"] != "act"]
    args["bundles"] = []
    args["singleton_lives"] = {i["item_id"]: "life-g1" for i in args["items"]}
    singleton = json.loads(finalize(assemble(**args), "PASS"))
    assert singleton["bundles"] == [] and len(singleton["singletons"]) == 4
    for tier, status, gate in (("T1", "COMPLETE", "PASS"), ("T0", "BLOCKED", "PASS")):
        invalid = copy.deepcopy(singleton)
        invalid.update(tier=tier, run_status=status, gate_verdict=gate)
        invalid["labels"]["scripted_model"] = "scripted model: wiring-only"
        with pytest.raises(ValueError):
            validate("card_ring0", invalid)
    args.update(items=[], singleton_lives={})
    with pytest.raises(ValueError):
        finalize(assemble(**args), "PASS")
    empty = json.loads(finalize(assemble(**args), "FAIL"))
    assert empty["competing_milli"] == empty["carry_over_milli"] == 0
    assert empty["diagnostics"] == []


@pytest.mark.parametrize("change", [dict(tier="T2"), dict(mode="live"), dict(pins={}),
                                    dict(controls={})])
def test_assembler_rejects_bad_inputs(change):
    with pytest.raises(ValueError):
        assemble(**dict(inputs(), **change))


def test_duplicate_volatile_paths_and_relative_surface():
    args = inputs()
    surface = args["system_entry"]["surfaces"][0]
    surface["relative"] = "nested"
    assert all(p["surface"] == "HERMES_HOME/nested"
               for p in assemble(**args)["volatile_surface_paths"])
    surface["volatile_paths"].append(surface["volatile_paths"][0])
    with pytest.raises(ValueError, match="duplicate"):
        assemble(**args)


@pytest.mark.parametrize("xs,expected", [([], (0, None, None, None, None)),
                                        ([5], (1, 5, 5, 5, 5)),
                                        (list(range(1, 11)), (10, 5, 9, 10, 10)),
                                        (list(range(1, 21)), (20, 11, 18, 19, 20)),
                                        ([3, 1, 2, 2], (4, 2, 3, 3, 3))])
def test_percentile_goldens(xs, expected):
    assert percentiles(xs) == dict(zip(("n", "p50", "p90", "p95", "max"), expected, strict=True))


@pytest.mark.parametrize("xs", [[True], [-1], [1.0], (1, 2)])
def test_percentiles_refuse_non_integer_lists(xs):
    with pytest.raises(ValueError):
        percentiles(xs)


def test_seeded_percentile_property_200_cases():
    rng = random.Random(1102)
    for _ in range(200):
        xs = [rng.randrange(10000) for _ in range(rng.randint(1, 50))]
        s, result = sorted(xs), percentiles(xs)
        for p in (50, 90, 95):
            assert result[f"p{p}"] == s[min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))]
        assert result["max"] == max(xs)


def test_receipt_helpers_and_sorting():
    records = ledger()
    assert ledger_latencies([records[2], dict(type="close"), records[0], records[1]]) == [10, 20, 30]
    assert raw_body_digest(records) == sha256_canon([[r["seq"], r["req"], r["resp"]]
                                                  for r in records])
    assert load_milli(["0.0015", Fraction(5, 2000), 2]) == [2, 2, 2000]
    with pytest.raises(ValueError):
        load_milli([1, 2])
    assert not busy(Marker(0, False, "idle"))
    assert busy(Marker(10, True, "busy")) and busy(Marker(None, None, "unreadable"))
    assert loop_time(example("receipt")) == (100, False)
    assert loop_time(dict(example("receipt"), busy_marker_readings=[False, True])) == (100, True)
    args = receipt_inputs()
    before = copy.deepcopy(args)
    receipt = build_receipt(**args)
    assert receipt["tokens"] == dict(input=13, output=7)
    assert [r["role"] for r in receipt["tokens_by_role"]] == ["probe_main", "replay_main"]
    assert receipt["runtime_by_role"] == [dict(role="probe_main", ms=20),
                                          dict(role="replay_main", ms=100)]
    assert receipt["process_ids"] == [12, 123] and receipt["ports"] == [8000, 8080]
    assert receipt["temporary_paths"] == ["/sandbox/tmp-a", "/sandbox/tmp-b"]
    assert args == before


@pytest.mark.parametrize("bad", ["unsorted", "duplicate", "unknown", "sum", "summary",
                                 "runtime_order", "runtime_role", "runtime_negative"])
def test_receipt_contract_refusals(bad):
    receipt = build_receipt(**receipt_inputs())
    if bad == "unsorted":
        receipt["tokens_by_role"].reverse()
    elif bad == "duplicate":
        receipt["tokens_by_role"].append(copy.deepcopy(receipt["tokens_by_role"][-1]))
    elif bad == "unknown":
        receipt["tokens_by_role"][0]["role"] = "not-a-role"
    elif bad == "sum":
        receipt["tokens"]["input"] += 1
    elif bad == "summary":
        receipt["latency_summary"]["p50"] += 1
    elif bad == "runtime_order":
        receipt["runtime_by_role"].reverse()
    elif bad == "runtime_role":
        receipt["runtime_by_role"][0]["role"] = "not-a-role"
    else:
        receipt["runtime_by_role"][0]["ms"] = -1
    with pytest.raises(ValueError):
        validate("receipt", receipt)


def test_spend_refusal_and_zero_spend_write(tmp_path, monkeypatch):
    card = card_bytes()
    xml = junit_xml([item_suite(json.loads(card), "system")])
    receipt = build_receipt(**dict(receipt_inputs(), spend_micro_usd=1))
    with pytest.raises(SpendRefused) as raised:
        write_run(tmp_path, card=b"bad", receipt=receipt, junit=xml)
    assert raised.value.exit_code == REFUSED_EXIT == 3
    assert raised.value.spend_micro_usd == 1
    assert list(tmp_path.iterdir()) == []
    receipt["spend_micro_usd"] = 0
    replaced = []
    replace = os.replace

    def observe(source, dest):
        replaced.append(Path(dest).name)
        replace(source, dest)

    monkeypatch.setattr("bicentennial.report.receipt.os.replace", observe)
    write_run(tmp_path, card=card, receipt=receipt, junit=xml)
    assert replaced == ["junit.xml", "receipt.json", "card.json"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {
        "card.json": card, "receipt.json": canon(receipt), "junit.xml": xml}


@pytest.mark.parametrize("bad", ["status", "newline", "invalid", "float"])
def test_write_refuses_bad_card_before_files(tmp_path, bad):
    card, receipt = card_bytes(), build_receipt(**receipt_inputs())
    if bad == "status":
        receipt["run_status"] = "BLOCKED"
    elif bad == "newline":
        card += b"\n"
    elif bad == "invalid":
        value = json.loads(card)
        del value["labels"]
        card = canon(value)
    else:
        card = b'{"bad":0.1}'
    with pytest.raises(ValueError):
        write_run(tmp_path, card=card, receipt=receipt, junit=b"xml")
    assert list(tmp_path.iterdir()) == []


def assert_xml_structure(raw):
    root = ET.fromstring(raw)
    assert root.tag == "testsuites"
    assert set(root.attrib) == {"name", "tests", "failures", "errors"}
    for suite in root:
        assert suite.tag == "testsuite"
        assert set(suite.attrib) == {"name", "tests", "failures", "errors", "skipped"}
        children = list(suite)
        if children and children[0].tag == "properties":
            properties = children.pop(0)
            assert not properties.attrib
            for prop in properties:
                assert prop.tag == "property" and set(prop.attrib) == {"name", "value"}
                assert len(prop) == 0
        for case in children:
            assert case.tag == "testcase" and set(case.attrib) == {"name", "classname"}
            assert len(case) <= 1
            for detail in case:
                assert detail.tag in ("failure", "error", "skipped")
                assert set(detail.attrib) == {"type", "message"} and len(detail) == 0
    return root


def test_junit_fixture_counts_names_and_details():
    card = json.loads(card_bytes())
    reduced = reduce(card["items"], card["bundles"])
    props = run_properties(reduced, [("control_report.label", "wiped"), ("disclosure", "v0.1")])
    root = assert_xml_structure(junit_xml([item_suite(card, "system", props)]))
    assert root.attrib == dict(name="bicentennial", tests="24", failures="8", errors="1")
    suite = root[0]
    assert suite.attrib == dict(name="ring0.T1.hermes-native.system", tests="24", failures="8",
                                errors="1", skipped="2")
    cases = suite.findall("testcase")
    assert [c.get("name") for c in cases] == sorted(i["item_id"] for i in card["items"])
    assert {c.get("name") for c in cases if c.find("failure") is not None} == {
        "g1-recall-1-b", "g1-tue-1-b", "g1-tue-2-a", "g1-tue-2-b", "g1-wake-2-b",
        "g1-wake-3-a", "g2-recall-1-a", "g2-recall-1-b"}
    assert {c.get("name") for c in cases if c.find("error") is not None} == {"g2-wake-4-b"}
    assert {c.get("name"): c[0].get("type") for c in cases if c.find("skipped") is not None} == {
        "g2-tue-2-a": "N/A_CLOCK", "g2-wake-3-b": "BLOCKED"}
    assert props == sorted(props)
    assert dict(props)["accuracy.figure_milli"] == "700"
    assert dict(props)["accuracy.incomplete"] == "true"
    assert dict(props)["coverage.incomplete"] == "true"
    assert dict(props)["single_item.act.Wake"] == "625"
    assert dict(props)["accuracy.label"] == reduced["accuracy"]["label"]
    assert all(c.get("classname").count(".") == 2 for c in cases)
    details = {c.get("name"): c[0].attrib for c in cases if len(c)}
    assert details["g2-wake-4-b"]["message"] == "score_milli=0 worst_case_milli=-1000"
    assert details["g1-recall-1-b"] == dict(type="QA", message="score_milli=-500")
    assert "tuesday_class=" in details["g1-tue-1-b"]["message"]


def test_xmllint_schema(tmp_path):
    xmllint = shutil.which("xmllint")
    if xmllint is None:
        pytest.skip("xmllint unavailable; stdlib structure test remains active")
    card = json.loads(card_bytes())
    path = tmp_path / "junit.xml"
    path.write_bytes(junit_xml([item_suite(card, "system", [("escaped", '<&"\t\n')]),
                                ("invariants", (), junit_cases_from_invariants([
                                    dict(invariant="INV-NEW", status="FAIL")]))]))
    result = subprocess.run([xmllint, "--noout", "--schema", str(SCHEMAS / "junit.xsd"), str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_invariant_statuses_and_multiple_suite_totals():
    statuses = ["PASS", "FAIL", "INFRA_FAILURE", "INCONCLUSIVE", "NOT_EXERCISED"]
    rows = [dict(invariant=f"INV-{n}", status=s) for n, s in enumerate(statuses)]
    cases = junit_cases_from_invariants(rows)
    assert [c.outcome for c in cases] == ["passed", "failure", "error", "skipped", "skipped"]
    assert [c.message for c in cases] == [None, *statuses[1:]]
    card = json.loads(card_bytes())
    root = assert_xml_structure(junit_xml([item_suite(card, "system"), ("invariants", (), cases)]))
    assert root.attrib == dict(name="bicentennial", tests="29", failures="9", errors="2")
    assert root[1].get("skipped") == "2"
    assert [s.get("name") for s in root] == ["ring0.T1.hermes-native.system", "invariants"]


@pytest.mark.parametrize("bad", ["case", "suite", "property", "control", "surrogate", "nonchar",
                                 "property_control", "detail_control"])
def test_junit_refusals(bad):
    case = Case("probe-1", "remember.Recall.cell", "passed")
    suites = [("suite", (), [case])]
    if bad == "case":
        suites[0][2].append(case)
    elif bad == "suite":
        suites.append(suites[0])
    elif bad == "property":
        suites = [("suite", [("x", 1), ("x", 2)], [])]
    elif bad == "property_control":
        suites = [("suite", [("x", "\x00")], [])]
    elif bad == "detail_control":
        suites = [("suite", (), [Case("p", "c", "failure", "FAIL", "\x00")])]
    else:
        suites = [({"control": "\x01", "surrogate": "\ud800", "nonchar": "\ufffe"}[bad], (), [])]
    with pytest.raises(ValueError):
        junit_xml(suites)


def test_junit_properties_outcomes_and_escaping():
    reduced = fixture()["expected"]
    with pytest.raises(ValueError, match="duplicate"):
        run_properties(reduced, [("accuracy.label", "duplicate")])
    for args in [("p", "c", "unknown"), ("p", "c", "passed", "bad")]:
        with pytest.raises(ValueError):
            Case(*args)
    case = Case("p<&", "c", "passed")
    with pytest.raises(FrozenInstanceError):
        case.name = "changed"
    raw = junit_xml([("suite", [("json", {"n": 1}), ("literal", '<&"\t\n😀')], [case])])
    root = assert_xml_structure(raw)
    assert root[0][0][1].get("value") == '<&"\t\n😀'
    assert root[0][1].get("name") == "p<&"
    assert raw.endswith(b"\n") and raw.startswith(b"<?xml")
    assert "time" not in root.attrib
    with pytest.raises(ValueError):
        item_suite(json.loads(card_bytes()), "unknown")
    item = fixture()["items"][0]
    item.update(score_milli=0, base_verdict="OMISSION", benign_extra=True)
    assert item_cases([item])[0].message == "score_milli=0 benign_extra"
    assert ET.fromstring(junit_xml([])).get("tests") == "0"


def test_report_import_boundary():
    forbidden = {"world", "genres", "items", "director", "harness", "sandbox", "probe",
                 "systems", "runner", "time", "random", "socket", "subprocess"}
    allowed_stdlib = {"json", "os", "hashlib", "fractions", "dataclasses", "pathlib", "xml"}
    for path in (ROOT / "src/bicentennial/report").glob("*.py"):
        source = path.read_text()
        assert "lcm" not in source.lower()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                for module in modules:
                    parts = module.split(".")
                    assert not forbidden.intersection(parts)
                    assert parts[0] in allowed_stdlib | {"bicentennial"}
