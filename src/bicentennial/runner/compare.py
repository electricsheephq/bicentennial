"""Offline T1 comparison, ordered controls and all-or-refusal publication."""

import json
import os
import shutil
import time
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import SCHEMAS
from bicentennial.controls.cache import (
    cache_key,
    card_controls,
    ensure,
    read_entry,
)
from bicentennial.corpus.format import CORPUS_PATH, load_corpus
from bicentennial.corpus.run import corpus_suite, run_case
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.harness.hermes.plugin_host import GateRefused, HermesMemoryHost
from bicentennial.ledger import LedgerBusy, apply_masks
from bicentennial.packs.catalogue import load_catalogue
from bicentennial.packs.install import verify
from bicentennial.packs.scoring import control_input, make_score
from bicentennial.report.card import assemble, finalize
from bicentennial.report.junit import (
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
    raw_body_digest,
    write_run,
)
from bicentennial.report.t1_gate import BaselineMismatch, check_baseline, t1_gate
from bicentennial.runner import life, t0, t1
from bicentennial.runner.guard import read_marker
from bicentennial.runner.lock import lock_hash
from bicentennial.runner.t0 import SYSTEM_CAUSES
from bicentennial.runner.t1 import REPO, T1Refused, run_arms
from bicentennial.runtime.clock import SimClock
from bicentennial.score.aggregate import reduce
from bicentennial.systems.controls import (
    WIPED_LABEL,
    control_report,
    control_status,
    floor_mismatches,
)
from bicentennial.systems.hermes_plugin import PROVIDERS
from bicentennial.world.scale import ANCHOR_T
from bicentennial.world.tokens import ESTIMATOR

GATED = t1.GATED_ARMS
KNOWN = ("corpus_fail", "invariant_fail", "regression")
CATALOGUE = ("packs/catalogue-v0.toml", "specs/ring0/c7-partial.json", "tiers/life_specs/t0.toml")
DISCLOSURES = (
    ("t1.assistant_turns", "scripted assistant turns: fixed placeholder"),
    ("t1.baselines", "naive RAG not run in v0.1; the baseline set is incomplete"),
    ("t1.corpus", "corpus: memory-layer mode"),
    ("t1.corpus_crash", "API-mode crash equals restart"),
    ("t1.estimator", canon(ESTIMATOR).decode()),
    ("t1.fresh_install", "fresh-install hash compared within the run"),
    ("t1.isolation", "probe isolation is per checkpoint, not per item"),
    ("t1.key_matching", "G2 action predicates key on the planned key and first_execution_t takes the first "
     "call of any step tool; safe at T0/T1 scripted replay only"),
    ("t1.receipt", "receipt tokens_by_role, store_growth_bytes and process_ids are not measured at T1 v0.1"),
    ("t1.terminal", life.TERMINAL_DISCLOSURE),
    ("t1.tuesday", "Tuesday timing is not exercised at T1"),
    ("t1.unsettled", "unsettled checkpoints still run their probes; every item of such a checkpoint is "
     "SYSTEM_FAILURE (unsettled)"),
    ("t1.verdicts", "INVALID: the wiped control passed or a honeypot was read (exit 1); BLOCKED: "
     "infrastructure failed after its reruns with no known failure (exit 2); a known failure wins"),
    ("t1.verified_empty", "verified empty: before configuration; configuration is benchmark-written"),
    ("t1.window", "context_length 65536; compression.threshold_tokens 16384 = W"),
)
PLUGIN_DISCLOSURES = (
    ("t1.a4", "A4 not audited for plug-in providers at v0.1"),
    ("t1.plugin_snapshot", "a plug-in's verified-empty listing is its install snapshot, taken after the "
     "plug-in's own install-time files are written"),
    ("t1.reclassify", "plug-in end_timeout, final_mismatch, resume_failed and turn_timeout stops are "
     "INFRA_FAILURE when the no-memory floor stops identically; probe sessions only"),
    ("t1.fresh_install_mask", "fresh-install hash: director port masked in config.yaml and mem0.json"),
)


class CorpusInfra(RuntimeError):
    """A benchmark-owned corpus fault, never charged to the system."""


INFRA = (*t1.REFUSALS, HarnessFailed, LedgerBusy, CorpusInfra)


class _Host:
    def __init__(self, host, held):
        self.host, self.held = host, held

    def __getattr__(self, name):
        value = getattr(self.host, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            try:
                return value(*args, **kwargs)
            except t1.REFUSALS as error:
                self.held.append(error)
                raise
            except HarnessFailed as error:
                if str(error) in SYSTEM_CAUSES:
                    raise RuntimeError(str(error)) from error
                raise
            except (LedgerBusy, CorpusInfra):
                raise
            except Exception as error:
                raise CorpusInfra(type(error).__name__) from error

        return call


class _WipedHost(_Host):
    def __getattr__(self, name):
        if name == "restore":
            reset = super().__getattr__("reset")
            return lambda data: reset()
        value = super().__getattr__(name)
        if name == "begin_session":
            def begin(index):
                value(index)
                super(_WipedHost, self).__getattr__("reset")()
            return begin
        return value


class CorpusFactory:
    def __init__(self, ctx, arm, case, unit, held, hosts, overrides):
        self.ctx, self.arm, self.case, self.unit = ctx, arm, case, unit
        self.held, self.hosts, self.overrides = held, hosts, overrides

    def __call__(self):
        try:
            ctx = self.ctx
            root = self.unit / "hosts" / f"h{len(self.hosts)}"
            root.mkdir(parents=True)
            kw = dict(route_table=RouteTable.load(ctx.table), responder=ScriptedResponder(ctx.entry),
                clock=SimClock(root / "clock.json", ANCHOR_T, life.STEP_S), root=root,
                scratch=self.unit / "hosts", life=self.case.case_id, branch="corpus", run=ctx.run_id,
                lock_hash=lock_hash(ctx.lock), checkout=ctx.hermes, harness_pin=ctx.harness_pin,
                plugin_source=ctx.plugin_source, sim_epoch_s=0)
            kw.update(self.overrides or {})
            host = HermesMemoryHost(ctx.entry, **kw)
            self.hosts.append(host)
            return (_Host if self.arm == "system" else _WipedHost)(host, self.held)
        except t1.REFUSALS as error:
            self.held.append(error)
            raise
        except Exception as error:
            raise CorpusInfra(type(error).__name__) from error


def _isolated(records, egress):
    return not egress.get("non_loopback", []) and all(
        r.get("served_by") in (None, "scripted") and all(
            (a.get("served_by") == "scripted" or "error" in a) and not a.get("diagnostics")
            for a in r.get("upstream", ())) for r in records)


def corpus(ctx, arm, cases, *, catalogue, work, host=None, audit=None):
    """Retry corpus infrastructure faults, retaining isolation evidence before cleanup."""
    results = []
    for case in sorted(cases, key=lambda c: c.case_id):
        for attempt in range(3):
            unit = Path(work) / case.case_id / f"a{attempt}"
            unit.mkdir(parents=True)
            held, hosts = [], []
            result = run_case(case, CorpusFactory(ctx, arm, case, unit, held, hosts, host),
                root=unit / "life", catalogue=catalogue, bound_s=ctx.entry["settle"]["bound_s"],
                infra=INFRA)
            for h in hosts:
                if hasattr(h, "records") and hasattr(h, "egress"):
                    rows = h.records()
                    if not _isolated(rows, h.egress.summary()):
                        raise T1Refused("upstream_record")
                    if audit is not None:
                        audit.extend(rows)
            if held:
                raise held[0]
            shutil.rmtree(unit)
            if result.status != "INFRA_FAILURE":
                break
        results.append(result)
    return tuple(results)


def _controls(ctx, cache):
    entries = []
    pin = sha256_canon(ctx.index["harness_artifacts"])
    for pack in ctx.packs:
        inp = control_input(pack.dir)
        entry = read_entry(pack.dir / "sealed/controls.json", cache_key(inp, harness_pin=pin),
                           expected_sha256=pack.pack["hashes"]["controls"])
        if entry is None:
            cache.mkdir(parents=True, exist_ok=True)
            entry = ensure(inp, cache / f"{pack.pack['pack_id']}.controls.json",
                           score=make_score(pack.scoring), harness_pin=pin)
        entries.append(entry)
    values = [card_controls(e) for e in entries]
    return {k: values[0][k] if all(v[k] == values[0][k] for v in values) else None
            for k in sorted(values[0])}


def _finals(arm):
    return [u.runs[-1] for u in arm.units]


def _runs(run, arms):
    return [r for arm in arms for u in run.arms[arm].units for r in u.runs]


def _masked(records, values):
    # Mirror stable_digest's schema rule: SHA-256 fields already hash masked bodies.
    props = json.loads((SCHEMAS / "ledger-record.schema.json").read_bytes())["properties"]
    digests = {k for k, p in props.items()
               if p["x-stability"] == "stable" and p.get("pattern") == "^[0-9a-f]{64}$"}
    return [dict(apply_masks({k: v for k, v in r.items() if k not in digests}, values),
                 **{k: r[k] for k in sorted(digests) if k in r}) for r in records]


def _provisional(run, arm, wiped_store, *, base, out):
    a = run.arms[arm]
    finals = _finals(a)
    assert all(f.run_values or not f.records for f in finals)
    ledger = [r for f in finals if f.run_values for r in _masked(f.records, f.run_values)]
    values = next((f.run_values for f in finals if f.run_values),
                  dict(sandbox_root=str(out), director_port="0"))
    return assemble(tier="T1", mode="hermes", system_entry=run.ctx.entry,
        run_status="BLOCKED" if any(i["failure_class"] == "BLOCKED" for i in a.outcomes.values())
        else "COMPLETE", pins=run.ctx.pins, ledger_records=ledger, run_values=values,
        items=list(a.outcomes.values()), bundles=list(a.bundles), singleton_lives=run.singleton_lives,
        duty_items=frozenset(run.duty_items), controls=base | {"wiped_store": wiped_store}, voids=a.voids)


def _receipt(run, arm, status, start, end):
    runs = _runs(run, (arm, "no_memory") if arm == "system" else (arm,))
    rows = [r for f in runs for r in f.records]
    runtime = {}
    for r in rows:
        if r.get("type") == "request":
            runtime[r["role"]] = runtime.get(r["role"], 0) + r["t_ms"]
    return build_receipt(run_status=status, wall_start_ms=start, wall_end_ms=end,
        latency_ms=ledger_latencies(rows), load_milli=load_milli(os.getloadavg()),
        busy_marker_readings=[busy(run.ctx.marker),
            *(g["exit"] != 0 for r in runs for s in r.sessions for g in s.gate), busy(read_marker())],
        tokens_by_role={}, runtime_by_role=runtime, spend_micro_usd=0, store_growth_bytes=0,
        process_ids=[], ports=[int(r.run_values["director_port"]) for r in runs if r.run_values],
        temporary_paths=[r.run_values["sandbox_root"] for r in runs if r.run_values],
        raw_body_digest=raw_body_digest(rows))


def _invariants(run, arm):
    return [v.to_obj() for v in run.arms[arm].verdicts]


def _junit(run, arm, card, gate, final, cases, results, fm, hits, witnesses):
    a, name = run.arms[arm], run.ctx.entry["name"]
    extra = [*DISCLOSURES, *(PLUGIN_DISCLOSURES if name in PROVIDERS else ()),
        ("t1.not_exercised", canon(list(run.not_exercised)).decode()),
        ("t1.transforms", canon(list(a.transforms)).decode()),
        ("t1.reclassified", canon(sorted({i for u in a.units for i in u.reclassified})).decode()),
        ("honeypot.hits", str(hits)), *witnesses,
        ("controls.floor_mismatches", canon(list(fm)).decode()),
        ("controls.wiped_store", json.loads(card)["controls"]["wiped_store"]),
        ("gate", canon(gate.to_obj()).decode()), ("gate.final", final)]
    if arm == "wiped":
        extra.append(("wiped.label", WIPED_LABEL))
        gaps = [f.audit["a4_gaps"] for f in _finals(a) if f.audit.get("a4_gaps")]
        if gaps:
            extra.append(("t1.a4_gaps", gaps[0]))
    suites = [item_suite(json.loads(card), arm, run_properties(reduce(list(a.outcomes.values()),
        list(a.bundles), singleton_lives=run.singleton_lives, duty_items=frozenset(run.duty_items)), extra)),
        (f"ring0.T1.{name}.{arm}.invariants", [], junit_cases_from_invariants(_invariants(run, arm))),
        corpus_suite(cases, results, tier="T1", system=name, arm=arm)]
    if arm == "system":
        floor = run.arms["no_memory"].outcomes
        suites.append(item_suite(dict(tier="T1", system=name, items=[floor[i] for i in sorted(floor)]),
                                 "no_memory"))
    return junit_xml(suites)


def _execute(ctx, *, out, packs_dir, pack_hash, baseline, cache, corpus_host, start):
    run = run_arms(ctx, scratch=out / "work")
    rows = []
    for f in _runs(run, tuple(sorted(run.arms))):
        if not _isolated(f.records, f.egress):
            raise T1Refused("upstream_record")
        rows.extend(f.records)
    cases = load_corpus(CORPUS_PATH)
    catalogue = load_catalogue(REPO / CATALOGUE[0], c7_path=REPO / CATALOGUE[1],
                               tier_path=REPO / CATALOGUE[2])
    try:
        results = {arm: corpus(ctx, arm, cases, catalogue=catalogue,
            work=out / "corpus-work" / arm, host=corpus_host, audit=rows) for arm in GATED}
    finally:
        if (out / "corpus-work").exists():
            shutil.rmtree(out / "corpus-work")
    base = _controls(ctx, Path(cache) if cache is not None else out / "cache")
    corpus_objs = {arm: [r.to_obj() for r in results[arm]] for arm in GATED}
    wiped = _provisional(run, "wiped", "FAIL", base=base, out=out)
    w = t1_gate(wiped, baseline, corpus_objs["wiped"], invariants=_invariants(run, "wiped"),
                crossing=run.crossing, arm="wiped")
    store = "uninformative" if w.verdict == "BLOCKED" else control_status(
        w.verdict, run.arms["system"].recall)
    system = _provisional(run, "system", store, base=base, out=out)
    s = t1_gate(system, baseline, corpus_objs["system"], invariants=_invariants(run, "system"),
                crossing=run.crossing)
    hits = sum(a.honeypot_hits for a in run.arms.values())
    vw, rw = "INVALID" if hits else w.verdict, w.run_status
    vs, rs = s.verdict, s.run_status
    if w.verdict == "BLOCKED":
        vs, rs = "FAIL" if set(s.reasons) & set(KNOWN) else "BLOCKED", "BLOCKED"
    if hits:
        vs = "INVALID"
    cards = dict(system=finalize(dict(system, run_status=rs), vs),
                 wiped=finalize(dict(wiped, run_status=rw), vw))
    end = time.time_ns() // 1_000_000
    receipts = {arm: _receipt(run, arm, rs if arm == "system" else rw, start, end) for arm in GATED}
    fm = floor_mismatches(list(run.arms["wiped"].bundles), list(run.arms["no_memory"].bundles), run.crossing)
    controls = canon(control_report(tuple(h for u in run.arms["wiped"].units for h in u.runs[-1].hooks), fm))
    witnesses = (("isolation.unknown_requests", str(sum(r.get("role") == "unknown" for r in rows))),
        ("isolation.forwarded", str(sum(a.get("served_by") != "scripted"
            for r in rows for a in r.get("upstream", ())))),
        ("no_memory.gold_in_context", str(sum(r.in_context is True
            for f in _finals(run.arms["no_memory"]) for r in f.results.values()))))
    junit = {arm: _junit(run, arm, cards[arm], s if arm == "system" else w,
        vs if arm == "system" else vw, cases, results[arm], fm, hits, witnesses) for arm in GATED}
    for arm in GATED:
        if receipts[arm]["spend_micro_usd"] > 0:
            raise SpendRefused(receipts[arm]["spend_micro_usd"])
    verify(packs_dir, pack_hash=pack_hash, lock=ctx.current_lock(), expected_lock=ctx.lock)
    for arm in GATED:
        directory = out / arm
        directory.mkdir(parents=True)
        for name, data in (("invariants", canon(_invariants(run, arm))),
                           ("corpus", canon(corpus_objs[arm])), ("controls", controls)):
            (directory / f"{name}.json").write_bytes(data)
        write_run(directory, card=cards[arm], receipt=receipts[arm], junit=junit[arm])
    return 1 if vs in ("FAIL", "INVALID") else 2 if vs == "BLOCKED" else 0


def run_t1(*, system, packs_dir, pack_hash, out, baseline=None, hermes=None,
           plugin_source=None, cache=None, entry=None, worker_argv=None, corpus_host=None) -> int:
    """Run the two-life comparison, returning the Ring 0 exit code."""
    start = time.time_ns() // 1_000_000
    out, created = Path(out), False
    try:
        if os.environ.get("PYTHONHASHSEED") != "0":
            raise T1Refused("hashseed")
        if out.exists() or out.is_symlink():
            raise T1Refused("out_exists")
        ctx = t1.prepare(system=system, packs=packs_dir, pack_hash=pack_hash, hermes=hermes,
            plugin_source=plugin_source, entry=entry, worker_argv=worker_argv)
        data = None
        if baseline is not None:
            try:
                data = Path(baseline).read_bytes()
            except OSError:
                raise T1Refused("baseline_unreadable") from None
            try:
                check_baseline(data, system=ctx.entry["name"], pins=ctx.pins)
            except BaselineMismatch:
                raise
            except ValueError:
                raise T1Refused("baseline_invalid") from None
        out.mkdir(parents=True)
        created = True
        return _execute(ctx, out=out, packs_dir=packs_dir, pack_hash=pack_hash, baseline=data,
                        cache=cache, corpus_host=corpus_host, start=start)
    except (*t1.REFUSALS, BaselineMismatch, SpendRefused) as error:
        reasons = getattr(error, "reasons", ())
        code = ("baseline_mismatch" if isinstance(error, BaselineMismatch) else
            getattr(error, "code", None) or (",".join(sorted(reasons)) if reasons else
            "SpendRefused" if isinstance(error, SpendRefused) else
            "gate_refused" if isinstance(error, GateRefused) else "pin_mismatch"))
        fields = [error.field] if isinstance(error, BaselineMismatch) else sorted(getattr(error, "fields", ()))
        print(code, file=t0.sys.stderr)
        if created:
            (out / "refusal.json").write_bytes(canon(dict(code=code, fields=fields)))
        return 3
