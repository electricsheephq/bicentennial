"""Memory-layer corpus replay primitives for controls and reference stubs."""

import argparse
import bisect
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from bicentennial.api.adapters import mutants
from bicentennial.api.adapters.bm25 import BM25
from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.contract import shape
from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.items.reader_keys import life_keys
from bicentennial.packs.build import api_events
from bicentennial.packs.catalogue import (
    TEMPLATES_BY_GENRE,
    c7_entries,
    generate,
    load_catalogue,
)
from bicentennial.probe.scripted_reader import read_api
from bicentennial.report.junit import Case as JUnitCase
from bicentennial.world import open_world

from .format import (
    ADAPTER_NAMES,
    CONTROLS,
    CORPUS_PATH,
    MUTANTS,
    OUTCOME_KEYS,
    PASS_ORACLE,
    REPO,
    check_case,
    dump_corpus,
    load_corpus,
)

FACTORIES = dict(sorted({
    "no_memory": NoMemory,
    "oracle_evidence": OracleEvidence,
    "reference_store": ReferenceStore,
    "bm25": BM25,
    **{name: getattr(mutants, name) for name in MUTANTS},
}.items()))
SETTLE_BOUND_S = 5
STATUSES = ("PASS", "FAIL", "INFRA_FAILURE")
REASONS = ("", "mismatch", "system_failure", "stale_case", "infra")
C7 = REPO / "specs/ring0/c7-partial.json"


class SystemFault(ValueError):
    """An adapter violated the memory-layer call or answer contract."""


class StaleCase(ValueError):
    """A pinned recipe input or regenerated artifact changed."""

    def __init__(self, field):
        self.field = field
        super().__init__(field)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    status: str
    reason: str
    first_diff: str | None

    def __post_init__(self):
        if type(self.case_id) is not str or not self.case_id:
            raise ValueError("case_id")
        if self.status not in STATUSES:
            raise ValueError("status")
        if self.reason not in REASONS:
            raise ValueError("reason")
        if self.first_diff is not None and type(self.first_diff) is not str:
            raise ValueError("first_diff")
        if self.status == "PASS" and (self.reason != "" or self.first_diff is not None):
            raise ValueError("status")
        if self.status == "FAIL" and self.reason not in ("mismatch", "system_failure"):
            raise ValueError("reason")
        if self.status == "INFRA_FAILURE" and self.reason not in ("stale_case", "infra"):
            raise ValueError("reason")

    def to_obj(self):
        return asdict(self)


def outcome(result) -> dict:
    """Keep reader ids, counts and flags; omit token-bearing payloads."""
    obj = {field: getattr(result, field) for field in OUTCOME_KEYS}
    obj["competing_present"] = sorted(obj["competing_present"])
    obj["competing"] = {field: obj["competing"][field] for field in sorted(obj["competing"])}
    if obj["recall"] is not None:
        obj["recall"] = {field: obj["recall"][field] for field in sorted(obj["recall"])}
    return obj


def _factory_names():
    """Check the fixed registry without accepting caller-supplied registrations."""
    if tuple(FACTORIES) != ADAPTER_NAMES:
        raise ValueError("FACTORIES")
    return tuple(FACTORIES)


def _call(adapter, method, *args, infra=()):
    try:
        return getattr(adapter, method)(*args)
    except infra:
        raise
    except Exception:
        raise SystemFault(method) from None


def _settle(adapter, bound_s, infra=()):
    if _call(adapter, "settle", bound_s, infra=infra) is not True:
        raise SystemFault("settle")


class _Guard:
    def __init__(self, adapter, infra=()):
        self.adapter = adapter
        self.infra = infra

    def query(self, task, now):
        answer = _call(self.adapter, "query", task, now, infra=self.infra)
        try:
            shape(answer, dict(output=str, citations=list, confidence_milli=int))
            if any(type(c) is not str for c in answer["citations"]) or not (
                    0 <= answer["confidence_milli"] <= 1000):
                raise ValueError("query")
        except (ValueError, TypeError):
            raise SystemFault("query") from None
        return answer


def _close(adapter, infra=(), error=None):
    if adapter is not None and hasattr(adapter, "close"):
        try:
            _call(adapter, "close", infra=infra)
        except Exception as close_error:
            if error is None:
                raise
            error.add_note(f"close() failed: {close_error!r}")


def drive(life, branch, worlds, keys, items, factory, *, oracle, forget, bound_s, infra=()):
    """Apply session faults, then probe through the guarded memory-layer API."""
    adapter, ingested, error = None, [], None

    def crash():
        nonlocal adapter
        _settle(adapter, bound_s, infra)
        data = _call(adapter, "checkpoint", infra=infra)
        if type(data) is not bytes:
            raise SystemFault("checkpoint")
        old, adapter = adapter, None
        _close(old, infra)
        adapter = _call_factory(factory, infra)
        _call(adapter, "restore", data, infra=infra)

    db, cut = worlds[branch]
    events = api_events(cut)
    sessions = {r["event_id"]: r["session_id"] for r in cut.rows}
    # Preserve every covered token, including requests whose target set is empty.
    requests = {r[0]: [t[0] for t in db.execute(
        "SELECT value FROM locked_token WHERE fact_id IN "
        "(SELECT value FROM json_each(?)) ORDER BY token_id", (r[1],))]
        for r in db.execute("SELECT event_id, covered_fact_ids_json FROM forget_request ORDER BY event_id")}
    try:
        adapter = _call_factory(factory, infra)
        _call(adapter, "reset", infra=infra)
        for plan in life.schedule.sessions:
            if plan.index > 1 and hasattr(adapter, "begin_session"):
                _settle(adapter, bound_s, infra)
                _call(adapter, "begin_session", plan.index, infra=infra)
            faults = [f for f in life.schedule.fault_lite() if f["session"] == plan.index]
            for fault in faults:
                if fault["kind"] == "restart":
                    crash()
                elif fault["kind"] == "compaction":
                    _call(adapter, "maintain", infra=infra)
            kills = [f["turn"] for f in faults if f["kind"] == "kill"]
            for event in (e for e in events if sessions[e["event_id"]] == plan.session_id):
                while kills and bisect.bisect_right(plan.turn_t, event["t_sim"]) > kills[0]:
                    crash()
                    kills.pop(0)
                _call(adapter, "ingest", event, infra=infra)
                ingested.append(event)
                if forget and event["event_id"] in requests:
                    tokens = [unicodedata.normalize("NFC", v) for v in requests[event["event_id"]]]
                    targets = sorted({e["event_id"] for e in ingested if any(
                        v in unicodedata.normalize("NFC", e["text"]) for v in tokens)})
                    _call(adapter, "forget", dict(event_ids=targets), infra=infra)
            for _ in kills:
                crash()
        results = []
        branches = {r["item_id"]: r["branch"] for r in life.twin.compiled.records}
        for item in sorted(items, key=lambda i: i["item_id"]):
            iid = item["item_id"]
            if branches[iid] != branch:
                continue
            _settle(adapter, bound_s, infra)
            now = life.schedule.sessions[item["probe_point"] - 1].t_end
            injected = ()
            if hasattr(adapter, "probe"):
                task = dict(task_id=iid, prompt=keys[iid]["recall_query"])
                if oracle:
                    task["oracle_evidence"] = list(keys[iid]["oracle_spans"])
                injected = _call(adapter, "probe", task, now, infra=infra)
            results.append(outcome(read_api(_Guard(adapter, infra), reader_view(item), keys[iid], now,
                                            oracle=oracle, injected=injected)))
        return results
    except BaseException as caught:
        error = caught
        raise
    finally:
        _close(adapter, infra, error)


def _call_factory(factory, infra=()):
    try:
        return factory()
    except infra:
        raise
    except Exception:
        raise SystemFault("factory") from None


def observe(life, worlds, keys, items, factory, *, oracle=False, forget=True,
            bound_s=SETTLE_BOUND_S, infra=()):
    try:
        return sorted([o for branch in sorted(worlds) for o in drive(
            life, branch, worlds, keys, items, factory, oracle=oracle, forget=forget,
            bound_s=bound_s, infra=infra)],
            key=lambda o: o["item_id"])
    except infra:
        raise
    except SystemFault:
        return "system_failure"


class _Life:
    """Own both generated connections and their disposable recipe directory."""
    def __init__(self, row, out_dir, case=None):
        self.row, self.out_dir, self.case = row, out_dir, case
        self.life, self.db0 = None, None

    def __enter__(self):
        try:
            self.life = generate(self.row, out_dir=self.out_dir)
            life = self.life
            self.db0 = open_world(self.out_dir / "world.B0.db", readonly=True)
            worlds = dict(B0=(self.db0, life.twin.cuts[0]), B1=(life.twin.b1, life.twin.cuts[1]))
            ids = sorted(r["item_id"] for r in life.twin.compiled.records
                         if r["bundle_id"] is not None or r["branch"] == "B0")
            items = sorted((i for i in life.twin.compiled.items if i["item_id"] in ids),
                           key=lambda i: i["item_id"])
            keys = {k["item_id"]: k for k in life_keys(life.twin.compiled, life.schedule, worlds)}
            if self.case is not None:
                for field in ("generator_version", "world_hash_b0", "world_hash_b1", "history_set_hash"):
                    _same(life.manifest[field], getattr(self.case, field), field)
                _same(life.schedule.fault_lite(), self.case.fault_points, "fault_points")
                _same(ids, self.case.items, "items")
            return life, worlds, keys, items
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        if self.db0 is not None:
            self.db0.close()
        if self.life is not None:
            self.life.twin.b1.close()
        if self.out_dir.exists():
            shutil.rmtree(self.out_dir)


def _same(actual, expected, field):
    if actual != expected:
        raise StaleCase(field)


def regenerate(case, *, root, catalogue):
    """Return a context manager yielding life, worlds, reader keys and case items."""
    row = catalogue.by_id().get(case.catalogue_row)
    if row is None:
        raise StaleCase("catalogue_row")
    template = TEMPLATES_BY_GENRE[row.genre][row.template]
    _same(template.ref, case.template, "template")
    _same(c7_entries(C7)[template.ref]["entry_sha256"], case.c7_entry_sha256, "c7_entry_sha256")
    _same(row.micro_spec().to_obj(template), case.levers, "levers")
    return _Life(row, Path(root) / case.case_id, case)


def _observations(life, worlds, keys, items):
    return {name: observe(life, worlds, keys, items, FACTORIES[name],
                          oracle=name == "oracle_evidence", forget=name not in CONTROLS)
            for name in _factory_names()}


def _evaluate(case, root, catalogue, factory=None, bound_s=SETTLE_BOUND_S, infra=()):
    try:
        with regenerate(case, root=root, catalogue=catalogue) as (life, worlds, keys, items):
            if factory is None:
                observed = _observations(life, worlds, keys, items)
                for name in ADAPTER_NAMES:
                    if canon(observed[name]) != canon(case.expected[name]):
                        left, right = observed[name], case.expected[name]
                        iid = case.items[0]
                        if isinstance(left, list) and isinstance(right, list):
                            by_left = {o["item_id"]: o for o in left}
                            by_right = {o["item_id"]: o for o in right}
                            iid = next(i for i in sorted(set(by_left) | set(by_right))
                                       if by_left.get(i) != by_right.get(i))
                        return CaseResult(case.case_id, "FAIL", "mismatch", f"{name}/{iid}")
            else:
                observed = observe(life, worlds, keys, items, factory, bound_s=bound_s, infra=infra)
                if observed == "system_failure":
                    return CaseResult(case.case_id, "FAIL", "system_failure", None)
                actual = [[o["item_id"], o["selected_option"]] for o in observed]
                expected = [[o["item_id"], o["selected_option"]] for o in case.expected[PASS_ORACLE]]
                if canon(actual) != canon(expected):
                    left, right = dict(actual), dict(expected)
                    iid = next(i for i in sorted(set(left) | set(right))
                               if i not in left or i not in right or left[i] != right[i])
                    return CaseResult(case.case_id, "FAIL", "mismatch", iid)
        return CaseResult(case.case_id, "PASS", "", None)
    except infra:
        return CaseResult(case.case_id, "INFRA_FAILURE", "infra", None)
    except StaleCase as error:
        return CaseResult(case.case_id, "INFRA_FAILURE", "stale_case", error.field)
    except Exception:
        return CaseResult(case.case_id, "INFRA_FAILURE", "infra", None)


def replay(case, *, root, catalogue):
    return _evaluate(case, root, catalogue)


def run_case(case, factory, *, root, catalogue, bound_s, infra=()):
    return _evaluate(case, root, catalogue, factory, bound_s, infra)


def run_corpus(cases, factory, *, root, catalogue, bound_s, infra=()):
    return tuple(run_case(c, factory, root=root, catalogue=catalogue, bound_s=bound_s, infra=infra)
                 for c in sorted(cases, key=lambda c: c.case_id))


def stock(catalogue, *, root):
    cases, stocked = [], set()
    entries = c7_entries(C7)
    for row in sorted(catalogue.rows, key=lambda r: r.id):
        if row.gate is not None:
            continue
        template = TEMPLATES_BY_GENRE[row.genre][row.template]
        with _Life(row, Path(root) / row.id) as (life, worlds, keys, items):
            expected = _observations(life, worlds, keys, items)
            if any(expected[n] == "system_failure" for n in (*CONTROLS, PASS_ORACLE)):
                raise ValueError(row.id)
            gold = [reader_view(i)["options"][0]["option_id"] for i in items]
            reference = [o["selected_option"] for o in expected[PASS_ORACLE]]
            if gold != reference:
                continue
            for name in MUTANTS:
                result = expected[name]
                failed = result == "system_failure" or [o["selected_option"] for o in result] != reference
                if not failed or (template.ref, name) in stocked:
                    continue
                manifest = life.manifest
                cases.append(check_case(dict(
                    case_id=f"{row.id}.{name}", source=f"reference_stub:{name}", catalogue_row=row.id,
                    generator_version=manifest["generator_version"], genre=row.genre, seed=row.seed,
                    recipe=row.micro_spec().recipe, template=template.ref,
                    c7_entry_sha256=entries[template.ref]["entry_sha256"],
                    levers=row.micro_spec().to_obj(template), fault_points=life.schedule.fault_lite(),
                    world_hash_b0=manifest["world_hash_b0"], world_hash_b1=manifest["world_hash_b1"],
                    history_set_hash=manifest["history_set_hash"], items=[i["item_id"] for i in items],
                    expected=expected)))
                stocked.add((template.ref, name))
    return tuple(sorted(cases, key=lambda c: c.case_id))


def corpus_suite(cases, results, *, tier, system, arm):
    cases, results = sorted(cases, key=lambda c: c.case_id), sorted(results, key=lambda r: r.case_id)
    if [c.case_id for c in cases] != [r.case_id for r in results]:
        raise ValueError("case_id")
    outcomes = dict(PASS="passed", FAIL="failure", INFRA_FAILURE="error")
    junit_cases = [JUnitCase(name=c.case_id, classname=f"corpus.{c.genre}.{c.template}",
                            outcome=outcomes[r.status], type=r.reason or None,
                            message=(r.first_diff or r.reason) if r.reason else None)
                   for c, r in zip(cases, results, strict=True)]
    return (f"ring0.{tier}.{system}.{arm}.corpus",
            [("corpus.cases", str(len(cases))), ("corpus.version", "v0.1")], junit_cases)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stock").add_argument("--out", type=Path, required=True)
    commands.add_parser("replay").add_argument("--corpus", type=Path, default=CORPUS_PATH)
    args = parser.parse_args(argv)
    if args.command == "stock" and args.out.exists():
        raise ValueError("out")
    catalogue = load_catalogue(REPO / "packs/catalogue-v0.toml", c7_path=C7,
                               tier_path=REPO / "tiers/life_specs/t0.toml")
    with tempfile.TemporaryDirectory() as root:
        if args.command == "stock":
            data = dump_corpus(stock(catalogue, root=Path(root)))
            with args.out.open("xb") as stream:
                stream.write(data)
            return 0
        results = [replay(c, root=Path(root), catalogue=catalogue) for c in load_corpus(args.corpus)]
    sys.stdout.buffer.write(canon([r.to_obj() for r in results]) + b"\n")
    return int(any(r.status != "PASS" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
