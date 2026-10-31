"""#282 path text regressions, including owner-run socket-backed evidence."""

import json
import os
import re
import runpy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_compare as acceptance

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.director.compiler.check import Voids, check_compile
from bicentennial.harness.hermes import adapter, plugin_host
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.ledger import BlobStore, Guard, apply_masks
from bicentennial.runner import compare, life, t0, t1
from bicentennial.sandbox import fixedroot

installed = acceptance.installed
cases = acceptance.cases
policy = acceptance.policy
replay = acceptance.replay
synth = acceptance.synth


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(fixedroot, "PARENT", os.path.realpath(tmp_path))
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    monkeypatch.setattr(plugin_host, "assert_niced", lambda pid: None)
    monkeypatch.setattr(t1, "check_compile", lambda *a, **kw: {"ok": True})
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)


def test_fixed_scratch(synth, installed, tmp_path, monkeypatch):
    scratches, works, hosts = [], [], []
    original = compare.corpus

    class Host(ReferenceStore):
        write_clipped, write_max_length = 0, None

        def __init__(self, entry, **kwargs):
            super().__init__()
            hosts.append(kwargs["root"])

        def fields(self):
            return {"actor": "not_delivered", "text": "full", "time": "session_clock"}

    def case(case, factory, **kwargs):
        factory()
        factory()
        return acceptance.fake_case(case, factory, **kwargs)

    def arms(ctx, *, scratch):
        scratches.append(scratch)
        return replace(synth, ctx=ctx)

    def corpus(ctx, arm, cases, **kwargs):
        works.append((arm, kwargs["work"]))
        return original(ctx, arm, cases, **kwargs)

    monkeypatch.setattr(compare, "run_arms", arms)
    monkeypatch.setattr(compare, "corpus", corpus)
    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    monkeypatch.setattr(compare, "run_case", case)
    for name in ("short", "long-" + "x" * 70):
        out = tmp_path / name
        assert acceptance.invoke(installed, out) == 0
        assert acceptance.properties(out, "system")["t1.sandbox_slot"] == "0"
    sandbox = Path(fixedroot.PARENT) / "bicentennial-0"
    assert scratches == [sandbox / "t1"] * 2
    assert works == [(a, sandbox / "corpus") for _ in range(2) for a in compare.GATED]
    assert hosts == [sandbox / "corpus" / "hosts" / f"h{n}"
                     for _ in range(2 * len(compare.GATED) * 2) for n in range(2)]


def test_unit_and_compile_scratch(synth, policy, installed, tmp_path, monkeypatch):
    checks, units = [], []

    def check(life_dir, **kw):
        checks.append((life_dir, kw["scratch"]))
        return {"ok": True}

    def drive(**kw):
        name = json.loads((kw["life_dir"] / "life.json").read_bytes())["life"]
        units.append((kw["arm"], kw["branch"], kw["scratch"]))
        return replace(policy.cache[name, kw["arm"], kw["branch"]],
                       stored_roots={}, retained_roots={}, _root=None)

    monkeypatch.setattr(t1, "check_compile", check)
    monkeypatch.setattr(t1, "run_life", drive)
    monkeypatch.setattr(compare, "run_arms", t1.run_arms)
    sandbox = Path(fixedroot.PARENT) / "bicentennial-0"
    for name in ("short", "long-" + "x" * 70):
        assert acceptance.invoke(installed, tmp_path / name) in (0, 1, 2)
    assert len(units) == 24
    assert {scratch for _, _, scratch in units} == {sandbox / "t1"}
    assert checks == [(p.life_dir, sandbox / "t1" / "check" / p.life)
                      for _ in range(2) for p in policy.ctx.packs]


def test_worker_passes_lease_fd(tmp_path, monkeypatch):
    original, calls = subprocess.Popen, []
    protocol = Path(__file__).parents[1] / "harness/fake_protocol_worker.py"

    def spawn(argv, **kwargs):
        calls.append(kwargs["pass_fds"])
        assert kwargs["pass_fds"] == fixedroot.held() and fixedroot.held()
        # The existing harness tests use this same scheduling double for protocol workers.
        return original(argv[argv.index(str(protocol)) - 1:], **kwargs)

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    with fixedroot.lease(0, t1.T1Refused):
        worker = adapter._Worker([sys.executable, str(protocol), "normal", str(tmp_path)],
                                 {"PATH": os.defpath}, tmp_path, tmp_path / "stderr")
        try:
            assert calls == [fixedroot.held()]
        finally:
            worker.proc.terminate()
            worker.proc.wait(timeout=10)


def test_busy_run_preserves_holder(synth, installed, tmp_path):
    with fixedroot.lease(0, t1.T1Refused) as sandbox:
        sentinel = sandbox / "holder"
        sentinel.write_text("alive")
        out = tmp_path / "busy"
        assert acceptance.invoke(installed, out) == 3
        refusal = json.loads((out / "refusal.json").read_bytes())
        assert refusal == dict(code="sandbox_busy", fields=[], detail=[f"holder_pid={os.getpid()}"])
        assert sentinel.read_text() == "alive"
        assert not (Path(fixedroot.PARENT) / "bicentennial-1").exists()


@pytest.mark.parametrize("runner", ["t0", "t1"])
def test_slot_validation_before_execution(synth, installed, tmp_path, monkeypatch, runner):
    # T0 uses a reference preparation and must still validate without taking a lease.
    if runner == "t0":
        monkeypatch.setattr(t0, "_preflight", lambda **kw: ())
        def invoke(out):
            return t0.run_t0(system="reference", packs=[], packs_dir="unused",
                             pack_hash="unused", out=out, sandbox_slot=10)
    else:
        def invoke(out):
            return acceptance.invoke(installed, out, sandbox_slot=10)
    out = tmp_path / runner
    assert invoke(out) == 3
    assert json.loads((out / "refusal.json").read_bytes())["code"] == "sandbox_slot"
    assert not list(tmp_path.glob("bicentennial-*"))


def test_leaked_branch_refused(policy, tmp_path, monkeypatch):
    pack, ctx = policy.ctx.packs[0], policy.ctx
    scratch = tmp_path / "t1"
    (scratch / "B0").mkdir(parents=True)

    def unexpected(*args, **kwargs):
        pytest.fail("leaked branch reached the adapter")

    monkeypatch.setattr(life, "HermesAdapter", unexpected)
    with pytest.raises(FileExistsError):
        life.run_life(arm="system", entry=ctx.entry, life_dir=pack.life_dir, branch="B0",
            items=pack.items["B0"], records=pack.records_b["B0"], keys=pack.keys,
            scratch=scratch, run=ctx.run_id, attempt=0, gate=ctx.gate,
            current_lock=ctx.current_lock, voids=Voids(), harness_pin=ctx.harness_pin)


def test_compile_roots(policy, tmp_path, monkeypatch):
    seen = []

    def construct(*args, **kwargs):
        seen.append((kwargs["branch"], kwargs["root"]))
        raise HarnessFailed("worker_start")

    monkeypatch.setattr(adapter, "HermesAdapter", construct)
    pack = next(p for p in policy.ctx.packs if p.genre == "G1")
    scratch = tmp_path / "check" / pack.life
    check_compile(pack.life_dir, entry=policy.ctx.entry, route_table=t1._routes("hermes-native"),
                  harness_pin=policy.ctx.harness_pin, checkout=None, scratch=scratch)
    for branch in ("B0", "B1"):
        roots = [root for b, root in seen if b == branch]
        assert roots
        assert roots == [scratch / f"check-{branch}-{k}" for k in range(len(roots))]
    assert not list(scratch.glob("check-*"))
    seen.clear()
    check_compile(pack.life_dir, entry=policy.ctx.entry, route_table=t1._routes("hermes-native"),
                  harness_pin=policy.ctx.harness_pin, checkout=None, scratch=scratch)
    assert seen


def test_fake_worker_roots(installed, cases, tmp_path, monkeypatch):
    """Owner-run: sockets are required; keep failed socket setup visible in the lane."""
    monkeypatch.setattr(t1, "check_compile", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(compare, "load_corpus", lambda path: cases)
    write_tree = runpy.run_path(str(compare.REPO / "tests/harness/hermes_stub.py"))["write_tree"]
    hermes = write_tree(tmp_path / "hermes-checkout", log=tmp_path / "stub-calls.jsonl")

    def case(case, factory, **kwargs):
        host = factory()
        host.close()
        return acceptance.fake_case(case, factory, **kwargs)

    monkeypatch.setattr(compare, "run_case", case)
    source = tmp_path / "provider"
    source.mkdir()
    (source / "provider.py").write_text("# synthetic provider\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=test",
            "-c", "user.email=test@example.invalid", "commit", "-qm", "synthetic pin"]):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", "HEAD"],
                             check=True, capture_output=True).stdout
    plugin = acceptance.measured("holographic")
    plugin["artifact"]["sha256"] = acceptance.sha256(archive).hexdigest()
    roots, runs, current, bodies = [], [], {}, []
    real_life, real_layout, host_layout = t1.run_life, adapter.layout, plugin_host.layout

    def layout(root, scratch):
        roots.append(("adapter", Path(root)))
        return real_layout(root, scratch)

    def host(root, scratch):
        roots.append(("host", Path(root)))
        return host_layout(root, scratch)

    def drive(**kw):
        result = real_life(**kw)
        assert result.stopped is None, result.stopped
        root = result._root / "run"
        assert result.run_values["sandbox_root"] == str(root)
        store = BlobStore(root / "ledger/blobs", Guard([]))
        offsets = [(iid, envelope["citation"]["context_offset"])
                   for iid, envelope in sorted(result.envelopes.items())
                   if envelope is not None and envelope["citation"] is not None]
        getcwds = []
        for row in result.records:
            for key in ("req", "resp"):
                if key not in row:
                    continue
                text = store.get(row[key]).decode()
                bodies.append(json.dumps(apply_masks(json.loads(text), result.run_values)))
                getcwds.extend(re.findall(r"getcwd ([^;]+);", text))
        assert getcwds and set(getcwds) == {str(root / "workspace")}
        runs.append(SimpleNamespace(entry=current["entry"], out=current["out"], arm=kw["arm"],
            life=result.life, branch=kw["branch"], root=root, digest=result.stable_digest,
            offsets=offsets))
        return result

    monkeypatch.setattr(adapter, "layout", layout)
    monkeypatch.setattr(plugin_host, "layout", host)
    monkeypatch.setattr(t1, "run_life", drive)
    for entry in (acceptance.measured(), plugin):
        for n, name in enumerate(("short", "long-" + "x" * 70)):
            current.update(entry=entry["name"], out=n)
            out = tmp_path / entry["name"] / name
            code = acceptance.invoke(installed, out, system=entry["name"], entry=entry,
                hermes=hermes, plugin_source=source if entry is plugin else None,
                corpus_host=dict(checkout=hermes, worker_argv=[sys.executable, str(plugin_host.WORKER)]))
            assert code in (0, 1, 2)
        for arm in compare.GATED:
            cards = [acceptance.read(tmp_path / entry["name"] / name, arm)
                     for name in ("short", "long-" + "x" * 70)]
            assert cards[0]["masked_ledger_digest"] == cards[1]["masked_ledger_digest"]
            assert cards[0] == cards[1]
    sandbox = Path(fixedroot.PARENT) / "bicentennial-0"
    for branch in ("B0", "B1"):
        assert {r.root for r in runs if r.branch == branch} == {sandbox / "t1" / branch / "run"}
    assert len({len(str(r.root)) for r in runs}) == 1
    assert {kind for kind, _ in roots} == {"adapter", "host"}
    assert roots and all(root.is_relative_to(sandbox / "t1") or
                         root.is_relative_to(sandbox / "corpus") for _, root in roots)
    for entry in ("hermes-native", "holographic"):
        for arm in t1.UNIT_ORDER:
            for name in {r.life for r in runs}:
                for branch in ("B0", "B1"):
                    pair = [r for r in runs if (r.entry, r.arm, r.life, r.branch) ==
                            (entry, arm, name, branch)]
                    assert len(pair) == 2
                    assert pair[0].digest == pair[1].digest
                    assert pair[0].offsets == pair[1].offsets
    # #282's checkout-path check is diagnostic only; no masking fix is authorized.
    checkouts = {"benchmark": str(compare.REPO.resolve()),
                 "hermes": str(hermes.resolve())}
    for label, checkout in checkouts.items():
        print(f"checkout-path {label} count={sum(text.count(checkout) for text in bodies)}", flush=True)
