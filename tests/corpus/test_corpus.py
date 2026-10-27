import ast
import inspect
import json
import os
import random
import shutil
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from copy import deepcopy
from dataclasses import fields, replace
from hashlib import sha256

import pytest

from bicentennial.canon import canon
from bicentennial.corpus.format import (
    ADAPTER_NAMES,
    CONTROLS,
    CORPUS_PATH,
    MUTANTS,
    OUTCOME_KEYS,
    PASS_ORACLE,
    REFERENCE_STUBS,
    REPO,
    Case,
    check_case,
    check_source,
    dump_corpus,
    load_corpus,
)


def ident(n):
    return f"bcw-{n:016x}"


@pytest.fixture
def obj():
    row, template = "g2-wake-pref-mft-1", "wake-pref-v1"
    result = dict(item_id=ident(1), selected_option=ident(2), competing_present=[],
                  in_context=True, missing_required=0, competing=dict(planted=0, stale=0, twin=0),
                  forbidden_in_context=None, recall=dict(k=5, hits=1, of=1, milli=1000))
    expected = {name: [deepcopy(result)] for name in ADAPTER_NAMES}
    expected["wipe_on_restart"][0].update(selected_option=None, in_context=False, missing_required=1)
    return dict(case_id=f"{row}.wipe_on_restart", source="reference_stub:wipe_on_restart",
                catalogue_row=row, generator_version="v0.1", genre="G2", seed=1,
                recipe=f"catalogue-v0:{template}", template=template, c7_entry_sha256="a" * 64,
                levers=dict(genre="G2", seed=1, sessions=3, distance=1, wake="kill",
                            recipe=f"catalogue-v0:{template}", template=template),
                fault_points=[dict(kind="kill", session=3, turn=1)], world_hash_b0="b" * 64,
                world_hash_b1="c" * 64, history_set_hash="d" * 64, items=[ident(1)], expected=expected)


def test_round_trip_and_copy(obj, tmp_path):
    case = check_case(obj)
    assert set(case.to_obj()) == {f.name for f in fields(Case)}
    assert tuple(sorted(case.expected[PASS_ORACLE][0])) == OUTCOME_KEYS
    data = dump_corpus([case])
    path = tmp_path / "cases.jsonl"
    path.write_bytes(data)
    assert load_corpus(path) == (case,)
    assert dump_corpus(load_corpus(path)) == data
    canary = json.loads((REPO / "schemas/item.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
    assert json.loads(data.splitlines()[0]) == dict(canary=canary, corpus="v0.1", cases=1)
    obj["levers"]["distance"] = 0
    assert case.levers["distance"] == 1
    exported = case.to_obj()
    exported["expected"][PASS_ORACLE][0]["recall"]["hits"] = 0
    assert case.expected[PASS_ORACLE][0]["recall"]["hits"] == 1


def test_registry():
    assert len(ADAPTER_NAMES) == 11
    assert ADAPTER_NAMES == tuple(sorted(CONTROLS + REFERENCE_STUBS))
    assert set(REFERENCE_STUBS) == {"bm25", PASS_ORACLE, *MUTANTS}
    for name in CONTROLS:
        assert check_source(f"control:{name}") == name
    for name in REFERENCE_STUBS:
        if name != PASS_ORACLE:
            assert check_source(f"reference_stub:{name}") == name


@pytest.mark.parametrize("source", ["system:hermes-native", "system:x", "equal_run:r1",
                                    "control:full_history", "reference_stub:reference_store",
                                    "reference_stub:nope", "model:x", None])
def test_source_refusals(source):
    with pytest.raises(ValueError, match="equal_run" if source == "equal_run:r1" else "corpus source"):
        check_source(source)


@pytest.mark.parametrize("mutation", ["no_failure", "missing_adapter", "extra_case", "float_seed",
    "bool_seed", "unsorted_items", "lever_template", "text", "envelope", "float_count",
    "bool_count", "recall_key", "competing_key", "extra_lever", "fault_key", "bool_session",
    "bool_schedule_seed", "bad_hash", "bad_option", "control_fault", "oracle_fault"])
def test_case_refusals(obj, mutation):
    if mutation == "no_failure":
        obj["expected"]["wipe_on_restart"] = deepcopy(obj["expected"][PASS_ORACLE])
    elif mutation == "missing_adapter":
        del obj["expected"]["bm25"]
    elif mutation == "extra_case":
        obj["extra"] = 1
    elif mutation in ("float_seed", "bool_seed"):
        obj["seed"] = 1.5 if mutation == "float_seed" else True
    elif mutation == "unsorted_items":
        obj["items"] = [ident(2), ident(1)]
    elif mutation == "lever_template":
        obj["levers"]["template"] = "wake-pref-v2"
    elif mutation == "text":
        obj["generator_version"] = "a sentence"
    elif mutation == "extra_lever":
        obj["levers"]["extra"] = 1
    elif mutation == "bool_schedule_seed":
        obj["levers"]["schedule_seed"] = True
    elif mutation == "fault_key":
        obj["fault_points"][0]["extra"] = 1
    elif mutation == "bool_session":
        obj["fault_points"][0]["session"] = True
    elif mutation == "bad_hash":
        obj["world_hash_b0"] = "A" * 64
    elif mutation in ("control_fault", "oracle_fault"):
        obj["expected"]["no_memory" if mutation == "control_fault" else PASS_ORACLE] = "system_failure"
    else:
        result = obj["expected"]["bm25"][0]
        if mutation == "envelope":
            result["envelope"] = {}
        elif mutation in ("float_count", "bool_count"):
            result["missing_required"] = 1.5 if mutation == "float_count" else True
        elif mutation == "recall_key":
            result["recall"]["extra"] = 0
        elif mutation == "competing_key":
            result["competing"]["extra"] = 0
        elif mutation == "bad_option":
            result["selected_option"] = "sentence"
    with pytest.raises(ValueError):
        check_case(obj)


def test_optional_schedule_seed(obj):
    assert "schedule_seed" not in check_case(obj).levers
    obj["levers"]["schedule_seed"] = 0
    assert check_case(obj).levers["schedule_seed"] == 0


@pytest.mark.parametrize("mutation", ["noncanonical", "unsorted", "duplicate", "canary", "count",
                                    "extra_header", "missing_newline", "system_source", "float_header"])
def test_file_refusals(obj, mutation, tmp_path):
    first = check_case(obj)
    other = deepcopy(obj)
    other["catalogue_row"] = "g2-wake-pref-mft-2"
    other["case_id"] = f"{other['catalogue_row']}.wipe_on_restart"
    lines = dump_corpus([first, check_case(other)]).splitlines(keepends=True)
    header = json.loads(lines[0])
    if mutation == "noncanonical":
        lines[1] = b" " + lines[1]
    elif mutation == "unsorted":
        lines[1], lines[2] = lines[2], lines[1]
    elif mutation == "duplicate":
        lines[2] = lines[1]
    elif mutation == "canary":
        header["canary"] = "wrong"
    elif mutation == "count":
        header["cases"] += 1
    elif mutation == "extra_header":
        header["extra"] = 0
    elif mutation == "float_header":
        header["cases"] = 2.0
    elif mutation == "missing_newline":
        lines[-1] = lines[-1].rstrip(b"\n")
    elif mutation == "system_source":
        obj.update(source="system:hermes-native", case_id=f"{obj['catalogue_row']}.hermes-native")
        lines[1] = canon(obj) + b"\n"
    lines[0] = (json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
                if mutation == "float_header" else canon(header)) + b"\n"
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b"".join(lines))
    with pytest.raises(ValueError):
        load_corpus(path)


def test_seeded_key_order_invariance(obj):
    rng = random.Random(8241)
    expected = dump_corpus([check_case(obj)])
    for _ in range(30):
        keys = list(obj)
        rng.shuffle(keys)
        shuffled = {key: deepcopy(obj[key]) for key in keys}
        names = list(ADAPTER_NAMES)
        rng.shuffle(names)
        shuffled["expected"] = {name: shuffled["expected"][name] for name in names}
        assert dump_corpus([check_case(shuffled)]) == expected


def test_format_import_boundary():
    path = REPO / "src/bicentennial/corpus/format.py"
    tree = ast.parse(path.read_text())
    allowed = {"json", "re", "dataclasses", "pathlib", "bicentennial.canon", "bicentennial.items.protocol"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed


def test_replay_primitives(obj):
    from types import SimpleNamespace

    from bicentennial.api.adapters import mutants
    from bicentennial.api.adapters.bm25 import BM25
    from bicentennial.api.adapters.nomemory import NoMemory
    from bicentennial.api.adapters.oracle_evidence import OracleEvidence
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import (
        FACTORIES,
        CaseResult,
        StaleCase,
        api_events,
        outcome,
    )
    from bicentennial.packs.build import api_events as shared_projection

    assert tuple(FACTORIES) == ADAPTER_NAMES
    assert FACTORIES == dict(bm25=BM25, no_memory=NoMemory, oracle_evidence=OracleEvidence,
                             reference_store=ReferenceStore,
                             **{name: getattr(mutants, name) for name in MUTANTS})
    result = SimpleNamespace(**obj["expected"][PASS_ORACLE][0], envelope={"secret": "text"}, plan={})
    assert outcome(result) == obj["expected"][PASS_ORACLE][0]
    assert CaseResult(obj["case_id"], "PASS", "", None).to_obj()["status"] == "PASS"
    with pytest.raises(ValueError):
        CaseResult(obj["case_id"], "PASS", "infra", None)
    assert StaleCase("levers").field == "levers"
    assert api_events is shared_projection
    tool = dict(event_id=ident(9), t_sim=1, actor="tool", audience=["agent"],
                payload={"result": "example"})
    assert api_events(SimpleNamespace(rows=[tool])) == shared_projection(SimpleNamespace(rows=[tool]))


@pytest.fixture(scope="module")
def catalogue():
    from bicentennial.packs.catalogue import load_catalogue

    return load_catalogue(REPO / "packs/catalogue-v0.toml",
                          c7_path=REPO / "specs/ring0/c7-partial.json",
                          tier_path=REPO / "tiers/life_specs/t0.toml")


def test_generated_driver(catalogue, tmp_path):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import FACTORIES, _Life, drive

    row = next(r for r in catalogue.rows if r.genre == "G2" and r.wake == "kill")
    with _Life(row, tmp_path / row.id) as (life, worlds, keys, items):
        assert worlds["B1"][0].execute("SELECT count(*) FROM fact").fetchone()[0]
        ref = drive(life, "B0", worlds, keys, items, ReferenceStore,
                    oracle=False, forget=True, bound_s=5)
        wiped = drive(life, "B0", worlds, keys, items, FACTORIES["wipe_on_restart"],
                      oracle=False, forget=True, bound_s=5)
        assert ref and all(o["in_context"] is not False for o in ref)
        assert all(o["in_context"] is False or o["in_context"] is None for o in wiped)
        with pytest.raises(KeyError):
            # Benchmark refusals propagate, and the generated worlds remain managed.
            drive(life, "absent", worlds, keys, items, ReferenceStore,
                  oracle=False, forget=True, bound_s=5)
    assert not list(tmp_path.iterdir())


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(CORPUS_PATH)


def test_stocking_reproducibility(catalogue, corpus, tmp_path, monkeypatch):
    import bicentennial.corpus.run as run
    from bicentennial.contracts.items import reader_view

    generated, unstockable, selections = [], [], {}
    original_generate, original_observations = run.generate, run._observations

    def twice(row, *, out_dir):
        first = original_generate(row, out_dir=out_dir)
        second_dir = out_dir.with_name(out_dir.name + ".again")
        try:
            second = original_generate(row, out_dir=second_dir)
            try:
                for field in ("world_hash_b0", "world_hash_b1", "history_set_hash"):
                    assert first.manifest[field] == second.manifest[field], (row.id, field)
            finally:
                second.twin.b1.close()
                shutil.rmtree(second_dir)
        except BaseException:
            first.twin.b1.close()
            raise
        generated.append(row.id)
        return first

    def record(life, worlds, keys, items):
        observed = original_observations(life, worlds, keys, items)
        row_id = generated[-1]
        assert all(observed[n] != "system_failure" for n in (*CONTROLS, PASS_ORACLE)), row_id
        gold = [reader_view(i)["options"][0]["option_id"] for i in items]
        reference = [o["selected_option"] for o in observed[PASS_ORACLE]]
        selections[row_id] = reference
        if gold != reference:
            unstockable.append(row_id)
        return observed

    monkeypatch.setattr(run, "generate", twice)
    monkeypatch.setattr(run, "_observations", record)
    assert "factory" not in inspect.signature(run.stock).parameters
    assert dump_corpus(run.stock(catalogue, root=tmp_path)) == CORPUS_PATH.read_bytes()
    assert generated == [r.id for r in catalogue.rows if r.gate is None]
    assert any(c.source == "reference_stub:wipe_on_restart" for c in corpus), selections
    assert all(c.source.startswith("reference_stub:") for c in corpus)
    assert len({(c.template, c.source) for c in corpus}) == len(corpus)
    assert not list(tmp_path.iterdir())
    print("STOCKING", json.dumps(dict(
        n=len(corpus), per_mutant={m: Counter(c.source.split(":")[1] for c in corpus)[m] for m in MUTANTS},
        gated=[r.id for r in catalogue.rows if r.gate is not None], unstockable=unstockable,
        sha256=sha256(CORPUS_PATH.read_bytes()).hexdigest()), sort_keys=True))


def test_complete_replay(catalogue, corpus, tmp_path):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import (
        FACTORIES,
        _observations,
        regenerate,
        replay,
        run_case,
        run_corpus,
    )

    start_cpu, start_wall = time.process_time(), time.perf_counter()
    first = tuple(replay(c, root=tmp_path, catalogue=catalogue) for c in corpus)
    replay_timing = dict(cpu=time.process_time() - start_cpu, wall=time.perf_counter() - start_wall)
    assert all(r.status == "PASS" for r in first), first
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    reference = run_corpus(reversed(corpus), ReferenceStore, root=tmp_path, catalogue=catalogue, bound_s=5)
    reference_timing = dict(cpu=time.process_time() - start_cpu, wall=time.perf_counter() - start_wall)
    assert all(r.status == "PASS" for r in reference), reference
    assert [r.case_id for r in reference] == sorted(c.case_id for c in corpus)
    second = tuple(replay(c, root=tmp_path / "fresh", catalogue=catalogue) for c in corpus)
    assert canon([r.to_obj() for r in first]) == canon([r.to_obj() for r in second])
    for case in corpus:
        source = run_case(case, FACTORIES[case.source.split(":")[1]],
                          root=tmp_path, catalogue=catalogue, bound_s=5)
        assert source.status == "FAIL" and source.reason in ("mismatch", "system_failure"), source
        observations = []
        for name in ("one", "two"):
            with regenerate(case, root=tmp_path / name, catalogue=catalogue) as data:
                observations.append(canon(_observations(*data)))
        assert observations[0] == observations[1] == canon(case.expected)
    assert all(not list(p.iterdir()) for p in tmp_path.iterdir())
    print("BUDGET", json.dumps(dict(replay=replay_timing, reference=reference_timing), sort_keys=True))


@pytest.mark.parametrize("field", ["world_hash_b0", "levers", "c7_entry_sha256",
                                  "add_schedule_seed", "remove_schedule_seed"])
def test_stale_pins(catalogue, corpus, tmp_path, field):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import replay, run_case

    case = next(c for c in corpus if ("schedule_seed" in c.levers) == (field == "remove_schedule_seed"))
    obj = case.to_obj()
    if field in ("world_hash_b0", "c7_entry_sha256"):
        obj[field] = ("0" if obj[field][0] != "0" else "1") + obj[field][1:]
    elif field == "levers":
        obj["levers"]["distance"] += 1
    elif field == "add_schedule_seed":
        obj["levers"]["schedule_seed"] = case.seed
    else:
        del obj["levers"]["schedule_seed"]
    # Distance can fall outside the strict stored format; regeneration still identifies the pin.
    stale = Case(**obj)
    expected_field = "levers" if "schedule_seed" in field else field
    for result in (replay(stale, root=tmp_path, catalogue=catalogue),
                   run_case(stale, ReferenceStore, root=tmp_path, catalogue=catalogue, bound_s=5)):
        assert (result.status, result.reason, result.first_diff) == (
            "INFRA_FAILURE", "stale_case", expected_field)
        assert not list(tmp_path.iterdir())


def test_no_text(catalogue, corpus, tmp_path):
    from bicentennial.corpus.run import regenerate
    from bicentennial.render.stream import content

    public = unicodedata.normalize("NFC", CORPUS_PATH.read_text())
    count = 0
    for case in corpus:
        row = catalogue.by_id()[case.catalogue_row]
        if row.test == "INV":
            assert case.levers["schedule_seed"] == catalogue.by_id()[row.base].seed
        else:
            assert "schedule_seed" not in case.levers
        with regenerate(case, root=tmp_path, catalogue=catalogue) as (_, worlds, _, items):
            strings = [i["prompt"] for i in items]
            for branch in sorted(worlds):
                db, cut = worlds[branch]
                strings.extend(r[0] for r in db.execute("SELECT value FROM locked_token ORDER BY token_id"))
                strings.extend(r[0] for r in db.execute("SELECT object FROM fact WHERE length(object)>=4 ORDER BY id"))
                strings.extend(content(r) for r in cut.rows if content(r))
            for text in strings:
                assert unicodedata.normalize("NFC", text) not in public, case.case_id
                count += 1
    assert not list(tmp_path.iterdir())
    print("NO_TEXT", count)


@pytest.mark.parametrize("fault", ["settle", "confidence", "checkpoint", "citation", "exception"])
def test_system_faults(catalogue, corpus, tmp_path, fault):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import run_case

    class Broken(ReferenceStore):
        def settle(self, bound_s):
            return False if fault == "settle" else super().settle(bound_s)

        def checkpoint(self):
            return "invalid" if fault == "checkpoint" else super().checkpoint()

        def query(self, task, now):
            answer = super().query(task, now)
            if fault == "confidence":
                answer["confidence_milli"] = 1.5
            elif fault == "citation":
                answer["citations"] = [1]
            elif fault == "exception":
                raise RuntimeError("query")
            return answer

    case = next(c for c in corpus if any(f["kind"] == "kill" for f in c.fault_points))
    result = run_case(case, Broken, root=tmp_path, catalogue=catalogue, bound_s=5)
    assert (result.status, result.reason) == ("FAIL", "system_failure")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("method", ["factory", "reset", "ingest", "settle", "checkpoint",
                                    "restore", "query", "close"])
@pytest.mark.parametrize("named", [False, True])
def test_infra_attribution(catalogue, corpus, tmp_path, method, named):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import observe, regenerate, run_case, run_corpus

    class BenchmarkFault(RuntimeError):
        pass

    fault, instances = BenchmarkFault(method), []

    class Host(ReferenceStore):
        def __init__(self):
            ReferenceStore.reset(self)
            self.closed = 0
            instances.append(self)

        def close(self):
            self.closed += 1
            if method == "close":
                raise fault

    def fail(*args):
        raise fault

    if method != "factory" and method != "close":
        setattr(Host, method, fail)
    factory = fail if method == "factory" else Host
    infra = (BenchmarkFault,) if named else ()
    case = next(c for c in corpus if any(f["kind"] == "kill" for f in c.fault_points))
    result = run_case(case, factory, root=tmp_path, catalogue=catalogue, bound_s=5, infra=infra)
    expected = ("INFRA_FAILURE", "infra", None) if named else ("FAIL", "system_failure", None)
    assert (result.status, result.reason, result.first_diff) == expected
    results = run_corpus([case], factory, root=tmp_path, catalogue=catalogue, bound_s=5, infra=infra)
    assert results == (result,)
    with regenerate(case, root=tmp_path, catalogue=catalogue) as data:
        if named:
            with pytest.raises(BenchmarkFault) as caught:
                observe(*data, factory, infra=infra)
            assert caught.value is fault
        else:
            assert observe(*data, factory) == "system_failure"
    assert all(h.closed == 1 for h in instances)
    assert bool(instances) == (method != "factory")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("phase", ["probe", "checkpoint", "restore"])
def test_close_preserves_benchmark_exception(catalogue, corpus, tmp_path, monkeypatch, phase):
    import bicentennial.corpus.run as run
    from bicentennial.api.adapters.reference_store import ReferenceStore

    instances = []
    original = IndexError(phase)

    class Host(ReferenceStore):
        def __init__(self):
            super().__init__()
            self.closed = 0
            instances.append(self)

        def close(self):
            self.closed += 1
            raise ValueError("close")

    def fail(*args, **kwargs):
        raise original

    case = next(c for c in corpus if any(f["kind"] == "kill" for f in c.fault_points))
    kwargs = {}
    if phase == "probe":
        monkeypatch.setattr(run, "read_api", fail)
        # Reach the probe before cleanup, without an earlier crash-close failure.
        case = next(c for c in corpus if not c.fault_points)
    else:
        setattr(Host, phase, fail)
        kwargs["infra"] = (IndexError,)
        if phase == "restore":
            # The first adapter closes successfully so the restored one can fail.
            def close(self):
                self.closed += 1
                if instances.index(self) % 2 == 1:
                    raise ValueError("close")
            Host.close = close

    with run.regenerate(case, root=tmp_path, catalogue=catalogue) as data:
        life, worlds, keys, items = data
        with pytest.raises(IndexError) as caught:
            run.drive(life, "B0", worlds, keys, items, Host,
                      oracle=False, forget=True, bound_s=5, **kwargs)
        assert caught.value is original
        assert any("close" in note for note in original.__notes__)
    result = run.run_case(case, Host, root=tmp_path, catalogue=catalogue, bound_s=5, **kwargs)
    assert (result.status, result.reason, result.first_diff) == ("INFRA_FAILURE", "infra", None)
    assert instances and all(h.closed == 1 for h in instances)
    assert not list(tmp_path.iterdir())


def test_close_preserves_system_fault(catalogue, corpus, tmp_path):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import SystemFault, drive, regenerate, run_case

    instances = []

    class Host(ReferenceStore):
        def __init__(self):
            super().__init__()
            self.closed = 0
            instances.append(self)

        def ingest(self, event):
            raise RuntimeError("ingest")

        def close(self):
            self.closed += 1
            raise ValueError("close")

    case = corpus[0]
    with regenerate(case, root=tmp_path, catalogue=catalogue) as (life, worlds, keys, items):
        with pytest.raises(SystemFault) as caught:
            drive(life, "B0", worlds, keys, items, Host, oracle=False, forget=True, bound_s=5)
        assert str(caught.value) == "ingest"
        assert any("close" in note for note in caught.value.__notes__)
    result = run_case(case, Host, root=tmp_path, catalogue=catalogue, bound_s=5)
    assert (result.status, result.reason, result.first_diff) == ("FAIL", "system_failure", None)
    assert instances and all(h.closed == 1 for h in instances)
    assert not list(tmp_path.iterdir())


def test_cli_hash_seeds(corpus, tmp_path):
    outputs = []
    for seed in ("0", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run([sys.executable, "-m", "bicentennial.corpus.run", "replay"],
                                env=env, cwd=REPO, capture_output=True, check=True)
        assert not result.stderr
        assert len(json.loads(result.stdout)) == len(corpus)
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    print("CLI_SHA256", sha256(outputs[0]).hexdigest())
    result = subprocess.run([sys.executable, "-m", "bicentennial.corpus.run", "stock", "--out", str(CORPUS_PATH)],
                            cwd=REPO, capture_output=True)
    assert result.returncode != 0 and b"ValueError: out" in result.stderr


def test_junit(catalogue, corpus, tmp_path):
    from bicentennial.corpus.run import FACTORIES, CaseResult, corpus_suite, run_corpus
    from bicentennial.report.junit import junit_xml

    results = run_corpus(corpus, FACTORIES["wipe_on_restart"], root=tmp_path,
                         catalogue=catalogue, bound_s=5)
    suite = corpus_suite(corpus, results, tier="T1", system="fixture", arm="wiped")
    xml = junit_xml([suite])
    tree = ET.fromstring(xml)
    node = tree.find("testsuite")
    failures = sum(r.status == "FAIL" for r in results)
    assert int(node.attrib["tests"]) == len(corpus)
    assert int(node.attrib["failures"]) == failures
    assert suite[0] == "ring0.T1.fixture.wiped.corpus"
    assert suite[1] == [("corpus.cases", str(len(corpus))), ("corpus.version", "v0.1")]
    assert not list(tmp_path.iterdir())
    xml_path = tmp_path / "corpus.xml"
    xml_path.write_bytes(xml)
    if shutil.which("xmllint"):
        subprocess.run(["xmllint", "--noout", "--schema", str(REPO / "schemas/junit.xsd"), str(xml_path)],
                       check=True, capture_output=True)
        schema = "validated"
    else:
        schema = "skipped: xmllint unavailable"
    print("JUNIT", json.dumps(dict(tests=len(corpus), failures=failures, schema=schema), sort_keys=True))
    with pytest.raises(ValueError, match="case_id"):
        corpus_suite(corpus, results[:-1], tier="T1", system="fixture", arm="wiped")
    cases = (corpus[0],) * 3
    synthetic = (CaseResult(corpus[0].case_id, "PASS", "", None),
                 CaseResult(corpus[0].case_id, "FAIL", "mismatch", corpus[0].items[0]),
                 CaseResult(corpus[0].case_id, "INFRA_FAILURE", "stale_case", "levers"))
    mapped = corpus_suite(cases, synthetic, tier="T1", system="fixture", arm="test")[2]
    assert [c.outcome for c in mapped] == ["passed", "failure", "error"]
    assert mapped[0].type is None and mapped[0].message is None
    assert mapped[2].type == "stale_case" and mapped[2].message == "levers"


def test_package_purity():
    allowed = {"argparse", "bisect", "shutil", "sys", "tempfile", "unicodedata", "dataclasses", "pathlib",
               "json", "re", "bicentennial.api.adapters", "bicentennial.api.adapters.bm25",
               "bicentennial.api.adapters.nomemory", "bicentennial.api.adapters.oracle_evidence",
               "bicentennial.api.adapters.reference_store", "bicentennial.api.contract", "bicentennial.canon",
               "bicentennial.contracts.items", "bicentennial.items.reader_keys", "bicentennial.items.protocol",
               "bicentennial.packs.build", "bicentennial.packs.catalogue", "bicentennial.probe.scripted_reader",
               "bicentennial.report.junit", "bicentennial.world", "format"}
    for path in sorted((REPO / "src/bicentennial/corpus").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(a.name in allowed for a in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed, path
            elif isinstance(node, ast.Constant):
                assert not isinstance(node.value, float)
                if isinstance(node.value, str):
                    assert "l" + "cm" not in node.value.lower()


def test_compaction_and_forgetting(catalogue, tmp_path):
    from bicentennial.corpus.run import FACTORIES, _Life, drive

    class Counting(FACTORIES["truncate_after_compaction"]):
        calls = 0

        def maintain(self):
            type(self).calls += 1
            super().maintain()

    row = replace(next(r for r in catalogue.rows if r.genre == "G2" and r.wake == "kill"),
                  wake="compaction")
    with _Life(row, tmp_path / row.id) as (life, worlds, keys, items):
        drive(life, "B0", worlds, keys, items, Counting, oracle=False, forget=True, bound_s=5)
    assert Counting.calls == 1
    row = next(r for r in catalogue.rows if r.template == "keep-forget")
    with _Life(row, tmp_path / row.id) as (life, worlds, keys, items):
        for name in ("reference_store", "no_memory", "oracle_evidence"):
            calls = []

            class Recording(FACTORIES[name]):
                recorded = calls

                def forget(self, selector):
                    self.recorded.append(deepcopy(selector))
                    super().forget(selector)

            drive(life, "B0", worlds, keys, items, Recording,
                  oracle=name == "oracle_evidence", forget=name not in CONTROLS, bound_s=5)
            count = worlds["B0"][0].execute("SELECT count(*) FROM forget_request").fetchone()[0]
            assert count > 0
            assert len(calls) == (count if name == "reference_store" else 0)
            assert all(c["event_ids"] == sorted(set(c["event_ids"])) for c in calls)
    assert not list(tmp_path.iterdir())


def test_host_lifecycle(catalogue, tmp_path):
    from bicentennial.api.adapters.reference_store import ReferenceStore
    from bicentennial.corpus.run import _Life, drive

    row = replace(next(r for r in catalogue.rows if r.genre == "G2" and r.wake == "kill"),
                  wake="restart", stage="remember")
    instances = []

    class Host(ReferenceStore):
        def __init__(self):
            super().__init__()
            self.closed, self.sessions, self.tasks = 0, [], []
            self.session = 1
            instances.append(self)

        def close(self):
            self.closed += 1

        def begin_session(self, index):
            assert index > self.session
            self.session = index
            self.sessions.append(index)

        def checkpoint(self):
            return canon(dict(session=self.session, events=json.loads(super().checkpoint())))

        def restore(self, data):
            obj = json.loads(data)
            self.session = obj["session"]
            super().restore(canon(obj["events"]))

        def probe(self, task, now):
            assert self.session == len(life.schedule.sessions)
            self.tasks.append((task, now))
            self.cached_answer = dict(output="UNKNOWN", citations=[], confidence_milli=0)
            return list(keys[task["task_id"]]["required"])

        def query(self, task, now):
            assert (task, now) == self.tasks[-1]
            return self.cached_answer

    with _Life(row, tmp_path / row.id) as (life, worlds, keys, items):
        observed = drive(life, "B0", worlds, keys, items, Host,
                         oracle=False, forget=True, bound_s=5)
        assert observed and all(o["in_context"] is True for o in observed)
        assert len(instances) == 2
        assert all(h.closed == 1 for h in instances)
        boundary = next(f["session"] for f in life.schedule.fault_lite() if f["kind"] == "restart")
        assert [k for h in instances for k in h.sessions] == list(range(2, boundary + 1))
        assert instances[-1].session == boundary
        assert instances[-1].tasks
        # A benchmark refusal after construction must also close the host.
        bad_items = [dict(items[0], probe_point=100)]
        with pytest.raises(IndexError):
            drive(life, "B0", worlds, keys, bad_items, Host,
                  oracle=False, forget=True, bound_s=5)
        assert all(h.closed == 1 for h in instances)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", ["metadata", "selection", "missing", "system_failure", "infra"])
def test_result_classification(catalogue, corpus, tmp_path, monkeypatch, change):
    import bicentennial.corpus.run as run

    case = corpus[0]
    name = ADAPTER_NAMES[0]
    observed = deepcopy(case.expected)
    if change == "infra":
        def broken(*args):
            raise RuntimeError("benchmark")
        monkeypatch.setattr(run, "_observations", broken)
    else:
        if change == "system_failure":
            observed[name] = "system_failure"
        elif change == "missing":
            observed[name] = observed[name][1:]
        elif change == "metadata":
            observed[name][0]["missing_required"] += 1
        else:
            observed[name][0]["selected_option"] = ident(999)
        monkeypatch.setattr(run, "_observations", lambda *args: observed)
    result = run.replay(case, root=tmp_path, catalogue=catalogue)
    if change == "infra":
        assert (result.status, result.reason, result.first_diff) == ("INFRA_FAILURE", "infra", None)
    else:
        assert (result.status, result.reason, result.first_diff) == (
            "FAIL", "mismatch", f"{name}/{case.items[0]}")
    if change != "infra":
        # Arms compare selections only; replay compares the entire reader outcome.
        monkeypatch.setattr(run, "observe", lambda *args, **kw: observed[name])
        result = run.run_case(case, run.FACTORIES[PASS_ORACLE], root=tmp_path, catalogue=catalogue, bound_s=5)
        if change == "metadata":
            assert result.status == "PASS"
        elif change == "system_failure":
            assert (result.status, result.reason) == ("FAIL", "system_failure")
        else:
            assert (result.status, result.reason, result.first_diff) == ("FAIL", "mismatch", case.items[0])
    assert not list(tmp_path.iterdir())
