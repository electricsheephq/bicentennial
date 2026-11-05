"""Offline kept-probe restoration, strict input comparison and mutation checks."""

import copy
import json
import runpy
import shutil
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.director import core
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.harness.hermes import adapter
from bicentennial.render.stream import content
from bicentennial.runner import repro
from bicentennial.runner.kept import PreProbe
from bicentennial.runner.lock import SessionGate, attempt_id
from bicentennial.runner.units import T2_SPEC, _score_run
from bicentennial.sandbox.surfaces import install_hash
from bicentennial.world.db import open_world

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_per_item_kept.py")))
lives = HELPERS["lives"]
harness = HELPERS["harness"]
unit_sessions = HELPERS["unit_sessions"]
observed = HELPERS["observed"]
drive = HELPERS["drive"]
FakeLive = HELPERS["HELPERS"]["FakeLive"]
ENTRY = HELPERS["HELPERS"]["ENTRY"]


def score(case, run):
    stream = [json.loads(line) for line in
              (case["t"].out_dir / f"stream.{case['branch']}.jsonl").read_bytes().splitlines()]
    evidence = {i["item_id"]: [content(r) for r in stream if r["event_id"] in i["gold_spans"]]
                for i in case["items"]}
    pack = SimpleNamespace(life=case["t"].life, genre=case["t"].genre,
        items={case["branch"]: case["items"]}, cases=case["cases"], keys=case["keys"], scoring={"evidence": evidence})
    return _score_run(SimpleNamespace(entry=ENTRY), pack, case["branch"], "system", run, run.attempt)[0]


@pytest.fixture
def kept_probe(observed, tmp_path, monkeypatch):
    case = observed[0]
    # A later item exercises the full compilation and cursor, with the kill in a skipped replay.
    target = [i for i in case["items"] if i["stage"] != "act"][-1]["item_id"]
    session = adapter.HermesAdapter.run_session

    def planted(self, index, **kwargs):
        spec = next(s for s in self.script["sessions"] if s["index"] == index)
        if spec["kind"] != "probe":
            for name in ("config.yaml", "mem0.json"):
                (self.paths["hermes_home"] / name).write_text(
                    f"endpoint=127.0.0.1:{self.server.port}\nnear=127.0.0.1:{self.server.port}5\nvalue=stable\n")
        return session(self, index, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", planted)
    scratch = tmp_path / "attempt"
    original = HELPERS["run_observed"](observed, scratch, run="t2-0123456789abcdef", attempt=2,
                                        pre_probe_attribution=T2_SPEC.pre_probe_attribution)
    scores = score(case, original)
    # FakeLive plants UNKNOWN instead of the required answer, giving a scored miss.
    assert scores[target]["score_milli"] < 1000
    record = original.pre_probe[target]
    digests = [r["req_masked_sha256"] for r in original.records
               if r.get("role") == "probe_main" and r.get("cursor", {}).get("session") == record.fields["probe_session_index"]]
    out = tmp_path / "out"
    HELPERS["publish"](original, [scores[target]], out)
    directory = out / "kept" / original.life / original.branch / target
    before = tree_listing(directory, [])
    shutil.rmtree(scratch)

    def serve(director, port):
        director.run_values["director_port"] = "1235"
        return SimpleNamespace(port=1235)

    monkeypatch.setattr(adapter, "serve", serve)
    return SimpleNamespace(case=case, target=target, scratch=scratch, directory=directory,
                           before=before, digests=digests)


def repeat(sample, restore, **kwargs):
    identity = restore.records["attempt_identity"]
    options = dict(probe_mode="per_item", keep_pre_probe=True,
                pre_probe_attribution=T2_SPEC.pre_probe_attribution, live=FakeLive(), repro=restore,
                stop_after_target=True, run=identity["run"], attempt=identity["attempt"])
    run = drive(sample.case, sample.scratch, **(options | kwargs))
    # Compare before scoring: compilation mutations must fail here, never in a score lookup.
    assert restore.compare_run(run) == "identical"
    return run


def test_restored_probe_three_of_three(kept_probe):
    sample = kept_probe
    restore = repro.load_bundle(sample.directory)
    for _ in range(3):
        run = repeat(sample, restore)
        assert run.audit["status"] == "OK"
        assert run.stopped is None
        assert len(run.pre_probe) == len(run.sessions) == 1
        assert run.expected_call_ids == run.post_restart_requests == ()
        assert not run.stored_roots
        assert all(run.classes[i["item_id"]] == ("INFRA_FAILURE", "not_restored")
                   for i in sample.case["items"] if i["item_id"] != sample.target)
        assert sample.target not in run.classes
        actual = repro.load_context(run.pre_probe[sample.target].directory, run.pre_probe[sample.target].fields)
        assert actual["attempt_identity"] == restore.records["attempt_identity"]
        assert [r["req_masked_sha256"] for r in run.records if r.get("role") == "probe_main"] == sample.digests
        home = run.pre_probe[sample.target].roots[0]
        for name in ("config.yaml", "mem0.json"):
            assert "endpoint=127.0.0.1:1235\nnear=127.0.0.1:12345" in (home / name).read_text()
        assert install_hash(home, restore.surfaces[0]["volatile_paths"], 1235) == restore.bundle["surface_hashes"]["HERMES_HOME/."]
        assert restore.foreign_port_refs == ()
        result = score(sample.case, run)[sample.target]
        assert (result["score_milli"], result["failure_class"]) == (
            restore.bundle["identity"]["score_milli"], restore.bundle["identity"]["failure_class"])
        shutil.rmtree(sample.scratch)
    restore.check_snapshot()
    assert tree_listing(sample.directory, []) == sample.before


@pytest.mark.parametrize("mutation", ["restore", "config.yaml", "mem0.json", "kept_byte", "items", "attempt",
                                       "mem0_byte", "cursor"])
def test_restore_mutants(kept_probe, monkeypatch, mutation):
    sample = kept_probe
    restore = repro.load_bundle(sample.directory)
    kwargs = {}
    if mutation == "restore":
        monkeypatch.setattr(restore, "restore", lambda *args: None)
    elif mutation in ("config.yaml", "mem0.json"):
        rewrite = repro.rewrite_port

        def skip_one(root, old, new):
            path = Path(root) / mutation
            data = path.read_bytes() if path.exists() else None
            rewrite(root, old, new)
            if data is not None:
                path.write_bytes(data)
        monkeypatch.setattr(repro, "rewrite_port", skip_one)
    elif mutation == "kept_byte":
        (sample.directory / "surfaces/0/replay-state").write_text("changed")
        with pytest.raises(repro.ReproRefused, match="^snapshot_changed$"):
            restore.check_snapshot()
        return
    elif mutation == "items":
        kwargs["items"] = [i for i in sample.case["items"] if i["item_id"] == sample.target]
    elif mutation == "attempt":
        kwargs["attempt"] = 3
    elif mutation == "mem0_byte":
        restore_tree = restore.restore

        def changed(*args):
            restore_tree(*args)
            path = args[0][0][1] / "mem0.json"
            path.write_text(path.read_text().replace("stable", "mutant"))
        monkeypatch.setattr(restore, "restore", changed)
    elif mutation == "cursor":
        def assign(self, index):
            self.ctx.cursor = 1
        monkeypatch.setattr(adapter.Director, "skip_session", assign)
    with pytest.raises((AssertionError, repro.ReproRefused)):
        repeat(sample, restore, **kwargs)


def test_foreign_port_scan_and_snapshot_after_run(kept_probe):
    restore = repro.load_bundle(kept_probe.directory)
    source = kept_probe.directory / "surfaces/0/foreign"
    source.write_bytes(b"127.0.0.1:1234 127.0.0.1:12345")
    with pytest.raises(repro.ReproRefused, match="snapshot_changed"):
        restore.check_snapshot()
    assert repro.foreign_port_refs([("surface", source.parent)], 1234) == ("surface/foreign",)


def test_malformed_surface_metadata_refuses(kept_probe):
    # Digests that agree do not make a kept entry well formed: a bad shape refuses and never crashes.
    directory = kept_probe.directory
    original = json.loads((directory / "bundle.json").read_bytes())
    bindings = json.loads((directory / "context" / f"{original['replay_context']['director_bindings']}.json").read_bytes())
    entry = bindings["probe_config"]["entry"]
    surface = entry["surfaces"][0]

    def load(entry):
        record = copy.deepcopy(bindings)
        record["probe_config"]["entry"] = entry
        digest = sha256_canon(record)
        (directory / "context" / f"{digest}.json").write_bytes(canon(record))
        bundle = copy.deepcopy(original)
        bundle["replay_context"]["director_bindings"] = digest
        bundle["probe_config_sha256"] = sha256_canon(record["probe_config"])
        (directory / "bundle.json").write_bytes(canon(bundle))
        return repro.load_bundle(directory)

    # The same rewrite of a well-formed entry loads, so each refusal below is the shape's.
    assert load(dict(entry, unlisted=True)).surfaces == entry["surfaces"]
    for malformed in ({}, [], {"surfaces": {}}, {"surfaces": 5}, {"surfaces": [5]},
                      {"surfaces": [{k: v for k, v in surface.items() if k != "root"}]},
                      {"surfaces": [dict(surface, relative=5)]},
                      {"surfaces": [dict(surface, volatile_paths="x")]},
                      {"surfaces": [dict(surface, volatile_paths=[5])]}):
        with pytest.raises(repro.ReproRefused, match="^bundle_invalid$"):
            load(malformed)


def test_restore_failure_is_not_a_repetition(kept_probe, monkeypatch):
    restore = repro.load_bundle(kept_probe.directory)
    def broken(*args):
        raise OSError("synthetic clone failure")
    monkeypatch.setattr(repro, "clone_tree", broken)
    with pytest.raises(repro.ReproRefused, match="^probe_not_run$"):
        repeat(kept_probe, restore)


def test_target_stop_leaves_other_items_not_restored(kept_probe, monkeypatch):
    # A stop in the target's session gives its cause to the target only: no other item was restored.
    restore = repro.load_bundle(kept_probe.directory)
    session = adapter.HermesAdapter.run_session

    def crash(self, index, **kwargs):
        if index == restore.bundle["probe_session_index"]:
            raise RuntimeError("planted target failure")
        return session(self, index, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", crash)
    identity = restore.records["attempt_identity"]
    run = drive(kept_probe.case, kept_probe.scratch, probe_mode="per_item", keep_pre_probe=True,
                pre_probe_attribution=T2_SPEC.pre_probe_attribution, live=FakeLive(), repro=restore,
                stop_after_target=True, run=identity["run"], attempt=identity["attempt"])
    assert run.stopped is not None and run.stopped[2] == restore.bundle["probe_session_index"]
    assert run.classes[kept_probe.target] == run.stopped[:2]
    others = [i["item_id"] for i in kept_probe.case["items"] if i["item_id"] != kept_probe.target]
    assert others and all(run.classes[i] == ("INFRA_FAILURE", "not_restored") for i in others)


def test_entry_surface_mismatch_refuses_before_running(kept_probe):
    restore = repro.load_bundle(kept_probe.directory)
    restore.records = copy.deepcopy(restore.records)
    restore.records["director_bindings"]["probe_config"]["entry"]["surfaces"].append(
        dict(root="HERMES_HOME", relative="other", volatile_paths=[]))
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:director_bindings$"):
        repeat(kept_probe, restore)
    # Nothing ran: no gate session, no scratch tree.
    assert not kept_probe.scratch.exists()


def test_restore_forces_capture_and_skips_in_script_order(kept_probe, monkeypatch):
    restore = repro.load_bundle(kept_probe.directory)
    skipped, gated = [], []
    skip = adapter.Director.skip_session

    def track(self, index):
        skipped.append(index)
        return skip(self, index)

    start = SessionGate.start_session

    def gate(self, lock, arm, life, branch, index, attempt):
        gated.append(index)
        return start(self, lock, arm, life, branch, index, attempt)

    monkeypatch.setattr(adapter.Director, "skip_session", track)
    monkeypatch.setattr(SessionGate, "start_session", gate)
    run = repeat(kept_probe, restore, keep_pre_probe=False, stop_after_target=False)
    actual = repro.load_context(run.pre_probe[restore.item_id].directory, run.pre_probe[restore.item_id].fields)
    assert gated == [restore.bundle["probe_session_index"]]
    # compile_script interleaves probe sessions in checkpoint order, rather than index order.
    case = kept_probe.case
    with closing(open_world(case["t"].out_dir / "world.B0.db", readonly=True)) as db:
        compiled = compile_script(case["t"].out_dir, "B0", case["t"].schedule, db,
                                  items=case["items"], step_s=60, probe_mode="per_item")
    assert skipped == [s["index"] for s in compiled.script["sessions"] if s["index"] not in gated]
    assert actual["attempt_identity"]["cursor"] == restore.records["attempt_identity"]["cursor"]
    assert run.stopped is None


def test_explicit_none_matches_default(lives, unit_sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "time", SimpleNamespace(time=lambda: 1, monotonic=lambda: 1))
    monkeypatch.setattr(core, "os", SimpleNamespace(getloadavg=lambda: (0, 0, 0)))
    case = lives["t1-g1", "B0"]
    scratch = tmp_path / "attempt"
    first = drive(case, scratch, live=FakeLive())
    rows = first.records
    probes = (first._root / "t2lite_probes.json").read_bytes()
    store = tree_listing(first._root / "run/hermes-home", [])
    scores = score(case, first)
    shutil.rmtree(scratch)
    second = drive(case, scratch, live=FakeLive(), repro=None)
    assert second.records == rows
    assert (second._root / "t2lite_probes.json").read_bytes() == probes
    assert tree_listing(second._root / "run/hermes-home", []) == store
    assert score(case, second) == scores


def inputs():
    identity = dict(run="recorded", life="life", branch="B0", attempt=2, lock_hash="a" * 64, cursor=8)
    identity["attempt_id"] = attempt_id(identity["lock_hash"], "system", "life", "B0", 21, 2)
    records = dict(canonical_paths=dict(root="/slot/run", home="/slot/run/home"),
        director_bindings=dict(run_values=dict(director_port="1234", sandbox_root="/slot"),
            probe_config=dict(checkout="/checkout", entry={}, live_probe={}), route_table={}),
        attempt_identity=identity, resolved_route=dict(alias="alias"), replay_segment=dict(segment=1),
        clock_cadence=dict(sim_t_s=60, step_s=60, clock_path="/slot/clock.json",
                           published=dict(sim_start=60, wall_anchor=1, rate=0)),
        compiled_probe=dict(index=21, turns=[]), workspace_inputs=dict(cwd="/slot/workspace", copy="workspace"),
        environment_inputs=dict(seed={}, envwire_root="/slot/envwire", worker_argv=["/checkout/worker.py"],
            worker_env=dict(PYTHONPATH="/checkout:/code/bicentennial/harness/hermes/clockshim", PATH="/bin", LANG="C",
                LC_ALL="C", HERMES_HOME="/slot/store", HOME="/slot/home", TMPDIR="/slot/tmp",
                BICENTENNIAL_CLOCK_FILE="/slot/clock.json", HTTP_PROXY="http://127.0.0.1:1234")))
    fields = dict(surface_hashes={}, workspace_hash="a" * 64, environment_hash="a" * 64, sim_t_s=60,
        probe_session_index=21, probe_slot=0, route_table_sha256=sha256_canon({}),
        probe_config_sha256=sha256_canon(records["director_bindings"]["probe_config"]),
        replay_context={k: sha256_canon(v) for k, v in records.items()})
    return fields, records


def comparison(change):
    fields, records = inputs()
    other, actual = copy.deepcopy(fields), copy.deepcopy(records)
    change(actual)
    other["probe_config_sha256"] = sha256_canon(actual["director_bindings"]["probe_config"])
    return repro.compare_records(fields, records, other, actual)


@pytest.mark.parametrize("record", sorted(repro.CONTEXT_RECORDS))
def test_unlisted_record_change_refuses(record):
    with pytest.raises(repro.ReproRefused, match=f"^starting_state_changed:{record}$"):
        comparison(lambda records: records[record].update(unlisted=True))


@pytest.mark.parametrize("field", sorted(repro.FIELDS - {"replay_context", "probe_config_sha256"}))
def test_unlisted_field_change_refuses(field):
    fields, records = inputs()
    other = dict(fields, **{field: "changed"})
    with pytest.raises(repro.ReproRefused, match=f"^starting_state_changed:{field}$"):
        repro.compare_records(fields, records, other, records)


@pytest.mark.parametrize("record,key,reason", [
    ("canonical_paths", "home", "canonical_paths"), ("workspace_inputs", "cwd", "canonical_paths"),
    ("clock_cadence", "clock_path", "canonical_paths"), ("environment_inputs", "envwire_root", "canonical_paths")])
def test_path_relocations(record, key, reason):
    assert comparison(lambda r: r[record].update(**{key: "/new/path"})) == f"relocated({reason})"


@pytest.mark.parametrize("key", ["HERMES_HOME", "HOME", "TMPDIR", "BICENTENNIAL_CLOCK_FILE", "PATH", "LANG", "LC_ALL", "LC_TIME"])
def test_environment_relocations(key):
    reason = "canonical_paths" if key in ("HERMES_HOME", "HOME", "TMPDIR", "BICENTENNIAL_CLOCK_FILE") else key
    assert comparison(lambda r: r["environment_inputs"]["worker_env"].update(**{key: "/new/value"})) == f"relocated({reason})"


def test_checkout_and_sandbox_relocations():
    def change(records):
        records["director_bindings"]["probe_config"]["checkout"] = "/new-checkout"
        records["director_bindings"]["run_values"]["sandbox_root"] = "/new-slot"
        records["environment_inputs"]["worker_argv"] = ["/new-checkout/worker.py"]
        records["environment_inputs"]["worker_env"]["PYTHONPATH"] = "/new-checkout:/new-code/bicentennial/harness/hermes/clockshim"
    assert comparison(change) == "relocated(canonical_paths,checkout)"


# move, slots (A: argv, P: PYTHONPATH), the kept value, the new value, the result (None: refused).
PREFIX_ROWS = [
    # A value that only contains a moved directory, or extends its last name, is not under it: it must match exactly.
    ("checkout", "AP", "/u/checkout/w.py", "/u/checkout/w.py", "relocated(checkout)"),
    ("checkout", "AP", "/u/checkout/w.py", "/u/new-checkout/w.py", None),
    ("checkout", "AP", "/checkout-old/x", "/checkout-old/x", "relocated(checkout)"),
    ("checkout", "AP", "/checkout-old/x", "/new-checkout-old/x", None),
    ("benchmark", "AP", "/u/code/lib", "/u/code/lib", "relocated(checkout)"),
    ("benchmark", "AP", "/u/code/lib", "/u/new-code/lib", None),
    ("sandbox", "AP", "/u/slot/x", "/u/slot/x", "relocated(canonical_paths)"),
    ("sandbox", "AP", "/u/slot/x", "/u/new-slot/x", None),
    # A '=' inside a path belongs to it; only an option's value after its first '=' is a path of its own.
    ("checkout", "AP", "/u/name=/checkout/x", "/u/name=/checkout/x", "relocated(checkout)"),
    ("checkout", "AP", "/u/name=/checkout/x", "/u/name=/new-checkout/x", None),
    ("checkout", "A", "--config=/checkout/c.yaml", "--config=/new-checkout/c.yaml", "relocated(checkout)"),
    ("checkout", "A", "--config=/checkout/c.yaml", "--config=/checkout/c.yaml", None),
    # An option with no '=' is not the same option with an empty value.
    ("checkout", "A", "-x", "-x=", None),
    # A literal never reads as a placeholder, with or without a relocation beside it.
    ("none", "AP", "/slot/x", "{SANDBOX_ROOT}/x", None),
    ("checkout", "AP", "{SANDBOX_ROOT}/x", "/slot/x", None),
    ("none", "A", "--config=/slot/x", "--config={SANDBOX_ROOT}/x", None),
]


@pytest.mark.parametrize("move,slot,before,after,result",
                         [(m, s, b, a, r) for m, slots, b, a, r in PREFIX_ROWS for s in slots])
def test_relocation_masks_path_prefixes_only(move, slot, before, after, result):
    fields, records = inputs()
    env = records["environment_inputs"]
    if slot == "A":
        env["worker_argv"].append(before)
    else:
        env["worker_env"]["PYTHONPATH"] += ":" + before
    actual = copy.deepcopy(records)
    checkout = "/new-checkout" if move == "checkout" else "/checkout"
    code = "/new-code" if move == "benchmark" else "/code"
    actual["director_bindings"]["probe_config"]["checkout"] = checkout
    if move == "sandbox":
        actual["director_bindings"]["run_values"]["sandbox_root"] = "/new-slot"
    env = actual["environment_inputs"]
    env["worker_argv"] = [checkout + "/worker.py"] + ([after] if slot == "A" else [])
    env["worker_env"]["PYTHONPATH"] = f"{checkout}:{code}/bicentennial/harness/hermes/clockshim" + (f":{after}" if slot == "P" else "")
    if result is None:
        with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
            repro.compare_records(fields, records, fields, actual)
    else:
        assert repro.compare_records(fields, records, fields, actual) == result


def test_reordered_benchmark_roots_never_compare_identical():
    # One placeholder for two directories hides their order: a start that differs is never identical.
    shim = "/bicentennial/harness/hermes/clockshim"
    fields, records = inputs()
    records["environment_inputs"]["worker_env"]["PYTHONPATH"] = f"/a{shim}:/b{shim}"
    actual = copy.deepcopy(records)
    actual["environment_inputs"]["worker_env"]["PYTHONPATH"] = f"/b{shim}:/a{shim}"
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
        repro.compare_records(fields, records, fields, actual)


def test_braces_in_moved_directories_still_relocate():
    # A brace is part of a directory's name: the checkout and the benchmark root match as recorded.
    shim = "/bicentennial/harness/hermes/clockshim"
    fields, records = inputs()

    def place(target, checkout, code):
        target["director_bindings"]["probe_config"]["checkout"] = checkout
        env = target["environment_inputs"]
        env["worker_argv"] = [checkout + "/worker.py"]
        env["worker_env"]["PYTHONPATH"] = f"{checkout}:{code}{shim}"
    place(records, "/u/{x}/checkout", "/u/{x}/code")
    actual = copy.deepcopy(records)
    place(actual, "/u/{x}/new-checkout", "/u/{x}/new-code")
    assert repro.compare_records(fields, records, fields, actual) == "relocated(checkout)"


def test_checkout_nested_under_the_sandbox_root_relocates():
    # The longest listed directory wins, whichever record lists it; the argv and PYTHONPATH shapes are the adapter's.
    fields, records = inputs()
    records["director_bindings"]["probe_config"]["checkout"] = "/slot/checkout"
    env = records["environment_inputs"]
    env["worker_argv"] = ["/slot/checkout/.venv/bin/python", "/code/bicentennial/harness/hermes/worker.py"]
    env["worker_env"]["PYTHONPATH"] = "/code/bicentennial/harness/hermes/clockshim:/slot/checkout"
    actual = copy.deepcopy(records)
    actual["director_bindings"]["probe_config"]["checkout"] = "/slot/new-checkout"
    env = actual["environment_inputs"]
    env["worker_argv"][0] = "/slot/new-checkout/.venv/bin/python"
    env["worker_env"]["PYTHONPATH"] = "/code/bicentennial/harness/hermes/clockshim:/slot/new-checkout"
    assert repro.compare_records(fields, records, fields, actual) == "relocated(checkout)"


def test_lock_relocation_requires_derived_attempt_id():
    def change(records):
        identity = records["attempt_identity"]
        identity["lock_hash"] = "b" * 64
        identity["attempt_id"] = attempt_id("b" * 64, "system", "life", "B0", 21, 2)
    assert comparison(change) == "relocated(lock_hash)"
    with pytest.raises(repro.ReproRefused, match="starting_state_changed:attempt_identity"):
        comparison(lambda r: r["attempt_identity"].update(lock_hash="b" * 64))


def test_clock_and_port_normalization():
    def change(records):
        records["clock_cadence"]["published"]["wall_anchor"] = 999
        records["director_bindings"]["run_values"]["director_port"] = "1235"
        records["environment_inputs"]["worker_env"]["HTTP_PROXY"] = "http://127.0.0.1:1235"
    assert comparison(change) == "identical"
    for key in ("rate", "sim_start"):
        with pytest.raises(repro.ReproRefused, match="starting_state_changed:clock_cadence"):
            comparison(lambda r, key=key: r["clock_cadence"]["published"].update(**{key: 1}))
    with pytest.raises(repro.ReproRefused, match="starting_state_changed:clock_cadence"):
        comparison(lambda r: r["clock_cadence"].update(step_s=1))
    # A literal never reads as the port's placeholder, with or without a relocation beside it.
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
        comparison(lambda r: r["environment_inputs"]["worker_env"].update(HTTP_PROXY="http://127.0.0.1:{DIRECTOR_PORT}"))

    def literal_beside_a_move(records):
        records["director_bindings"]["probe_config"]["checkout"] = "/new-checkout"
        env = records["environment_inputs"]
        env["worker_argv"] = ["/new-checkout/worker.py"]
        env["worker_env"].update(PYTHONPATH="/new-checkout:/code/bicentennial/harness/hermes/clockshim",
                                 HTTP_PROXY="http://127.0.0.1:{DIRECTOR_PORT}")
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
        comparison(literal_beside_a_move)


@pytest.mark.parametrize("record,path", [
    ("attempt_identity", ("cursor",)), ("attempt_identity", ("run",)),
    ("director_bindings", ("probe_config", "live_probe")),
    ("director_bindings", ("route_table",)),
    ("environment_inputs", ("seed",)), ("environment_inputs", ("worker_argv",)),
    ("environment_inputs", ("worker_env", "UNLISTED")),
    ("environment_inputs", ("worker_env", "PYTHONPATH")),
])
def test_executor_inputs_refuse(record, path):
    def change(records):
        value = records[record]
        for key in path[:-1]:
            value = value[key]
        value[path[-1]] = "different"
    with pytest.raises(repro.ReproRefused, match=f"^starting_state_changed:{record}$"):
        comparison(change)


def test_exact_json_types_and_canonical_paths_in_argv():
    with pytest.raises(repro.ReproRefused, match="bundle_invalid"):
        comparison(lambda r: r["clock_cadence"].update(step_s=60.0))
    # Malformed environment values refuse; they never crash the comparison.
    for change in (lambda r: r["environment_inputs"]["worker_env"].update(PATH=5),
                   lambda r: r["environment_inputs"]["worker_env"].update(PYTHONPATH=["/checkout"])):
        with pytest.raises(repro.ReproRefused, match="^bundle_invalid$"):
            comparison(change)
    # An argv that is not a list of strings is compared exactly: a dict keyed by the list's elements still differs,
    # and an equal one with a number in it is still identical.
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
        comparison(lambda r: r["environment_inputs"].update(worker_argv=dict.fromkeys(r["environment_inputs"]["worker_argv"], 1)))

    # Beside a real move as well: only a recorded list is masked, so a dict never reads as a relocation.
    def dict_beside_a_move(r):
        r["director_bindings"]["probe_config"]["checkout"] = "/new-checkout"
        r["environment_inputs"]["worker_argv"] = dict.fromkeys(["/new-checkout/worker.py"], 1)
        r["environment_inputs"]["worker_env"]["PYTHONPATH"] = "/new-checkout:/code/bicentennial/harness/hermes/clockshim"
    with pytest.raises(repro.ReproRefused, match="^starting_state_changed:environment_inputs$"):
        comparison(dict_beside_a_move)
    fields, records = inputs()
    records["environment_inputs"]["worker_argv"].append(5)
    assert repro.compare_records(fields, records, fields, copy.deepcopy(records)) == "identical"
    fields, records = inputs()
    with pytest.raises(repro.ReproRefused, match="starting_state_changed:probe_slot"):
        repro.compare_records(fields, records, dict(fields, probe_slot=False), records)
    fields, records = inputs()
    records["environment_inputs"]["worker_argv"] = ["worker", "/slot/run/home/settings"]
    actual = copy.deepcopy(records)
    actual["canonical_paths"]["home"] = "/new-home"
    actual["environment_inputs"]["worker_argv"] = ["worker", "/new-home/settings"]
    assert repro.compare_records(fields, records, fields, actual) == "relocated(canonical_paths)"


def test_port_rewrite_hash_identity_and_scope(tmp_path):
    old, new = 1234, 1235
    for name in ("config.yaml", "mem0.json", "other"):
        (tmp_path / name).write_text("127.0.0.1:1234 127.0.0.1:12345")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/config.yaml").write_text("127.0.0.1:1234")
    (tmp_path / "target").write_text("127.0.0.1:1234")
    # The port helper must leave a symlink untouched even when its name is a port file.
    before = install_hash(tmp_path, [], old)
    repro.rewrite_port(tmp_path, old, new)
    assert install_hash(tmp_path, [], new) == before
    assert (tmp_path / "config.yaml").read_text() == "127.0.0.1:1235 127.0.0.1:12345"
    assert repro.foreign_port_refs([("surface", tmp_path)], old) == (
        "surface/nested/config.yaml", "surface/other", "surface/target")
    (tmp_path / "config.yaml").unlink()
    (tmp_path / "config.yaml").symlink_to("target")
    repro.rewrite_port(tmp_path, old, new)
    assert (tmp_path / "target").read_text() == "127.0.0.1:1234"


@pytest.mark.parametrize("damage", ["digest", "missing", "reference", "config_hash", "record_set"])
def test_context_bundle_invalid(tmp_path, damage):
    fields, records = inputs()
    context = tmp_path / "context"
    context.mkdir()
    for name, value in records.items():
        (context / f"{fields['replay_context'][name]}.json").write_bytes(canon(value))
    assert repro.load_context(tmp_path, fields) == records
    path = context / f"{fields['replay_context']['compiled_probe']}.json"
    if damage == "digest":
        path.write_bytes(canon({}))
    elif damage == "missing":
        path.unlink()
    elif damage == "reference":
        fields["replay_context"]["compiled_probe"] = "pack:probe.json"
    elif damage == "config_hash":
        fields["probe_config_sha256"] = "b" * 64
    else:
        fields["replay_context"].pop("compiled_probe")
    with pytest.raises(repro.ReproRefused, match="^bundle_invalid$"):
        repro.load_context(tmp_path, fields)


def test_bad_bundle_refuses(tmp_path):
    (tmp_path / "bundle.json").write_bytes(canon({}))
    with pytest.raises(repro.ReproRefused, match="^bundle_invalid$"):
        repro.load_bundle(tmp_path)


def test_missing_target_is_not_a_repetition():
    restore = repro.Restore(Path("unused"), dict(identity=dict(item_id="target")), {})
    with pytest.raises(repro.ReproRefused, match="^probe_not_run$"):
        restore.compare_run(SimpleNamespace(pre_probe={}))


def test_digest_is_checked_on_both_sides(tmp_path):
    fields, records = inputs()
    for side in ("expected", "actual"):
        directory = tmp_path / side
        (directory / "context").mkdir(parents=True)
        for name, value in records.items():
            (directory / "context" / f"{fields['replay_context'][name]}.json").write_bytes(canon(value))
    restore = repro.Restore(tmp_path / "expected", dict(identity=dict(item_id="target"), **fields), records)
    record = PreProbe(tmp_path / "actual", (), 10, fields)
    run = SimpleNamespace(pre_probe={"target": record})
    assert restore.compare_run(run) == "identical"
    for side in ("expected", "actual"):
        path = tmp_path / side / "context" / f"{fields['replay_context']['resolved_route']}.json"
        saved = path.read_bytes()
        path.write_bytes(canon({}))
        with pytest.raises(repro.ReproRefused, match="^bundle_invalid$"):
            restore.compare_run(run)
        path.write_bytes(saved)
