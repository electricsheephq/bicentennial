"""Black-box fault and forgetting checks; only text misses certify absence."""

import codecs
import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from bicentennial.api.contract import shape
from bicentennial.audit.readback import calls_in, results
from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.probe.scripted_reader import ReaderResult, api_task, read_api
from bicentennial.sandbox.spansearch import span_search

INVARIANTS = ("INV-VERB", "INV-NEW", "INV-PAIR", "INV-FORGET")
STATUSES = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_EXERCISED", "INFRA_FAILURE")
GATED_T1 = INVARIANTS[:3]
CONFORMANCE_PEER = dict(zip(INVARIANTS, ("maintain_lossless", "supersession_current",
                                       "tool_grouping", "forget_removes"), strict=True))
NEW_CELLS = ("DRIFT-CUR", "DRIFT-PART", "DRIFT-PROC", "FAULT-NEWEST")
VERBATIM = "verbatim retention"
STRESSES = ("compaction", "crash")
_REASONS = ("absent_after_fault", "not_newest", "orphan_result", "surfaced", "store_hit",
            "opaque_store", "no_snapshot", "system_failure", "blocked", "infra", "host_kept")


class SystemFault(Exception):
    """An adapter violated its contract; never holds adapter output."""


@dataclass(frozen=True)
class Verdict:
    invariant: str
    status: str
    members: int
    uninformative: int
    failed: tuple[str, ...]
    inconclusive: tuple[str, ...]
    infra: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self):
        if self.invariant not in INVARIANTS or self.status not in STATUSES:
            raise ValueError("invalid verdict")
        for field in ("failed", "inconclusive", "infra", "reasons"):
            object.__setattr__(self, field, tuple(sorted(set(getattr(self, field)))))
        if any(r not in _REASONS for r in self.reasons):
            raise ValueError("invalid reason")

    def to_obj(self):
        return json.loads(canon({k: getattr(self, k) for k in self.__dataclass_fields__}))


def _verdict(invariant, rows):
    counted = [row for row in rows if row[2] != "host_kept"]  # host_kept only adds a reason (RING0 E22)
    members = sum(status != "uninformative" for _, status, _ in counted)
    uninformative = len(counted) - members
    groups = [tuple(sorted({i for i, status, _ in rows if status == target}))
              for target in ("FAIL", "INCONCLUSIVE", "INFRA_FAILURE")]
    failed, inconclusive, infra = groups
    status = ("NOT_EXERCISED" if not rows else "FAIL" if failed else
              "INFRA_FAILURE" if infra else "INCONCLUSIVE" if inconclusive or not members else "PASS")
    return Verdict(invariant, status, members, uninformative, failed, inconclusive, infra,
                   tuple(sorted({r for _, _, r in rows if r})))


def searchable_bytes(data) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8", "strict")
        return True
    except UnicodeDecodeError:
        return False


def searchable(path) -> bool:
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        return False
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if b"\x00" in chunk:
                    return False
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return True
    except UnicodeDecodeError:
        return False


@dataclass(frozen=True)
class StoreSearch:
    verdict: str
    hit_paths: tuple[str, ...]
    opaque_paths: tuple[str, ...]


def search_store(root, needles) -> StoreSearch:
    root = Path(root)
    hits = span_search(root, list(needles))
    opaque = []

    def fail(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        dirs.sort()
        for name in sorted(files):
            path = Path(directory) / name
            if stat.S_ISREG(path.lstat().st_mode) and not searchable(path):
                opaque.append(path.relative_to(root).as_posix())
    paths = tuple(sorted({p for group in hits.values() for p in group}))
    return StoreSearch("found" if paths else "inconclusive" if opaque else "absent",
                       paths, tuple(sorted(opaque)))


def needles_for(tokens) -> tuple[bytes, ...]:
    normalized = [unicodedata.normalize("NFC", t) for t in tokens]
    return tuple(sorted({v.encode() for t in normalized for v in (t, t.casefold())}))


def _host_kept(texts, needles):
    return any(n in text.encode() for text in texts for n in needles)


def _call(fn, *args):
    try:
        return fn(*args)
    except Exception:
        raise SystemFault() from None


def _settle(adapter, bound):
    if _call(adapter.settle, bound) is not True:
        raise SystemFault()


def _checkpoint(adapter, bound):
    _settle(adapter, bound)
    data = _call(adapter.checkpoint)
    if type(data) is not bytes:
        raise SystemFault()
    return data


class _Query:
    def __init__(self, adapter):
        self.adapter = adapter

    def query(self, *args):
        answer = _call(self.adapter.query, *args)
        try:
            shape(answer, dict(output=str, citations=list, confidence_milli=int))
            if any(type(c) is not str for c in answer["citations"]) or not 0 <= answer["confidence_milli"] <= 1000:
                raise ValueError()
        except (ValueError, TypeError):
            raise SystemFault() from None
        return answer


def _restart(holder, factory, bound):
    data = _checkpoint(holder[0], bound)
    holder.clear()  # Drop the only adapter reference before constructing its replacement.
    holder.append(_call(factory))
    _call(holder[0].restore, data)


def _event(i, t, text, kind="message", **extra):
    return dict(event_id=i, t_sim=t, kind=kind,
                actor={"message": "user", "tool_call": "assistant", "tool_result": "tool"}[kind], text=text, **extra)


def _probe(adapter, bound, i, query, token, *, old=None, forbidden=False, spans=()):
    def option(name, value):
        return dict(option_id=name, tokens=[value] if value else [], envelope=dict(
            type="entity" if value else "unknown", value=value, confidence_milli=1000 if value else 0))
    prefix = i.removeprefix("new-")
    options = [option(prefix + "-new" if old else "f-leak", token)]
    if old:
        options.append(option(prefix + "-old", old))
    options.append(option(prefix + "-unknown" if old else "f-none", None))
    keys = dict(item_id=i, life="s05-api", branch="B0", required=[] if forbidden else [token],
                forbidden=[token] if forbidden else [], oracle_spans=list(spans), recall_query=query,
                competing=[dict(kind="stale", token=old)] if old else [],
                canary=json.loads((SCHEMAS / "reader_keys.schema.json").read_bytes())["properties"]["canary"]["enum"][0])
    validate("reader_keys", keys)
    view = dict(item_id=i, prompt=query, options=options)
    _settle(adapter, bound)
    injected = _call(adapter.probe, api_task(view, keys), 100) if hasattr(adapter, "probe") else ()
    return read_api(_Query(adapter), view, keys, 100, injected=tuple(injected))


def _api_script(factory, invariant, bound, snapshot):
    holder = [_call(factory)]
    _call(holder[0].reset)

    def ingest(events):
        for e in events:
            _call(holder[0].ingest, e)

    def probe(i, q, token, **kw):
        return _probe(holder[0], bound, i, q, token, **kw)

    if invariant == "INV-VERB":
        planted = [_event("v1", 1, "Archive locker code is LOCK-4417."),
                   _event("v2", 2, "Nightly backup host is HOST-8823."),
                   _event("v3", 3, "Release signing owner is OWNR-3391.")]
        fillers = [_event(f"w{n}", n, f"Weather remark {word}.")
                   for n, word in enumerate(("four", "five", "six", "seven"), 4)]
        probes = [(f"verb-{n}", q, token) for n, (q, token) in enumerate((
            ("archive locker code", "LOCK-4417"), ("nightly backup host", "HOST-8823"),
            ("release signing owner", "OWNR-3391")), 1)]
        ingest(planted + fillers)
        twin = [probe(*p, spans=[f"v{n}"]).in_context for n, p in enumerate(probes, 1)]
        holder.clear()
        holder.append(_call(factory))
        _call(holder[0].reset)
        ingest(planted)
        _call(holder[0].maintain)
        ingest(fillers)
        _call(holder[0].maintain)
        _restart(holder, factory, bound)
        faulted = [probe(*p, spans=[f"v{n}"]) for n, p in enumerate(probes, 1)]
        yield from ((p[0], "uninformative" if not base else "PASS" if r.in_context is True else "FAIL",
                 "absent_after_fault" if base and r.in_context is not True else "")
                for p, base, r in zip(probes, twin, faulted, strict=True))
        return
    if invariant == "INV-NEW":
        ingest([_event("a1", 1, "Deploy window preference was SLOT-1101."),
                _event("a2", 2, "Deploy window preference now SLOT-2202."),
                _event("b2", 4, "Backup region choice now ZONE-4404."),
                _event("b1", 3, "Backup region choice was ZONE-3303.")])
        _restart(holder, factory, bound)
        yield from ((i, "PASS" if probe(i, q, token, old=old).selected_option == i[-1] + "-new" else "FAIL", "")
                for i, q, token, old in (("new-a", "deploy window preference", "SLOT-2202", "SLOT-1101"),
                                         ("new-b", "backup region choice", "ZONE-4404", "ZONE-3303")))
        return
    if invariant == "INV-PAIR":
        ingest([_event("p1", 1, "Please check the orchid pipeline."),
                _event("p2", 2, "fetch_status request PING-5150", "tool_call"),
                _event("p3", 3, "status green ACK-6262", "tool_result", call_id="p2")])
        _restart(holder, factory, bound)
        yield from ((i, "PASS" if probe(i, q, token).in_context is True else "FAIL", "")
                for i, q, token in (("pair-result", "status green", "ACK-6262"),
                                     ("pair-call", "fetch_status request", "PING-5150")))
        return
    ingest([_event("g1", 1, "Gate code for the loading yard is GATE-4410."),
            _event("g2", 2, "Please forget the gate code."), _event("g3", 3, "Yard opening hours are posted.")])
    _call(holder[0].forget, {"event_ids": ["g1"]})
    kept_texts = tuple(getattr(holder[0], "forget_kept_texts", {}).values())
    yield from ((i, "FAIL" if probe(i, q, "GATE-4410", forbidden=True).forbidden_in_context is True else "PASS", "")
                for i, q in (("forget-1", "yard gate code"), ("forget-2", "loading")))
    data = _checkpoint(holder[0], bound)
    needles = needles_for(["GATE-4410"])
    if any(n in data for n in needles):
        yield ("forget-store", "FAIL", "store_hit")
        if _host_kept(kept_texts, needles):
            yield ("forget-store", "FAIL", "host_kept")
        return
    scans = []
    if snapshot:
        for root in snapshot(holder[0]):
            scan = search_store(root, needles).verdict
            if scan == "found":
                yield ("forget-store", "FAIL", "store_hit")
                if _host_kept(kept_texts, needles):
                    yield ("forget-store", "FAIL", "host_kept")
                return
            scans.append(scan)
    opaque = not searchable_bytes(data) or "inconclusive" in scans
    yield ("forget-store", "INCONCLUSIVE" if opaque else "PASS",
           "opaque_store" if opaque else "")


def adapter_invariant(factory, invariant, *, bound_s: int, snapshot=None) -> Verdict:
    """Run one API-mode invariant against an adapter factory."""
    ids, reason = {
        "INV-VERB": (("verb-1", "verb-2", "verb-3"), "absent_after_fault"),
        "INV-NEW": (("new-a", "new-b"), "not_newest"),
        "INV-PAIR": (("pair-call", "pair-result"), "absent_after_fault"),
        "INV-FORGET": (("forget-1", "forget-2", "forget-store"), "surfaced"),
    }[invariant]
    rows = []
    try:
        for i, s, r in _api_script(factory, invariant, bound_s, snapshot):
            rows.append((i, s, r or (reason if s == "FAIL" else "")))
    except SystemFault:
        rows = [(i, "FAIL", "system_failure") for i in ids]
    except Exception:
        rows.extend((i, "INFRA_FAILURE", "infra") for i in ids if i not in {row[0] for row in rows})
    return _verdict(invariant, rows)


def adapter_invariants(factory, *, bound_s: int, snapshot=None) -> dict[str, Verdict]:
    """Run API-mode invariants against an adapter factory.

    API-mode INV-PAIR certifies that the call and its result both survive the crash;
    Answer exposes only output, citations and confidence_milli, not result call_id.
    Call/result linkage is certified in Hermes mode, where the requests' call and
    output ids are observable.
    """
    return {inv: adapter_invariant(factory, inv, bound_s=bound_s, snapshot=snapshot)
            for inv in INVARIANTS}


@dataclass(frozen=True)
class ItemEvidence:
    item: dict
    record: dict
    keys: dict
    result: ReaderResult | None
    failure_class: str | None
    crosses_restart: bool
    baseline_in_context: bool | None = None
    roots: tuple | None = None
    kept_texts: tuple[str, ...] = ()


def run_invariants(evidence, *, tier, requests=None, expected_call_ids=()) -> dict[str, Verdict]:
    if tier not in ("T0", "T1"):
        raise ValueError("invalid tier")
    rows, seen = {inv: [] for inv in INVARIANTS}, set()
    for e in evidence:
        for name, value in (("item", e.item), ("item_record", e.record), ("reader_keys", e.keys)):
            validate(name, value)
        i, r = e.item["item_id"], e.result
        if i in seen or any(value["item_id"] != i for value in (e.record, e.keys)) or r is not None and r.item_id != i:
            raise ValueError("duplicate or differing item ids")
        seen.add(i)
        if e.failure_class not in (None, "FAIL_TASK", "SYSTEM_FAILURE", "BLOCKED", "N/A_EXPOSURE", "N/A_CLOCK"):
            raise ValueError("invalid failure class")
        if r is None and e.failure_class in (None, "FAIL_TASK"):
            raise ValueError("missing reader result")
        if e.failure_class in ("N/A_EXPOSURE", "N/A_CLOCK"):
            continue
        verb = e.record["direction"] == VERBATIM and bool(set(e.record["crossed"]) & set(STRESSES)) and bool(e.keys["required"])
        if tier == "T0" and verb and e.baseline_in_context is None:
            raise ValueError("fault-free baseline required")
        memberships = (verb, e.item["cell_id"] in NEW_CELLS and e.crosses_restart and bool(e.keys["required"]),
                       False, tier == "T0" and bool(e.keys["forbidden"]))
        for inv, member in zip(INVARIANTS, memberships, strict=True):
            if not member:
                continue
            status, reason = "PASS", ""
            if e.failure_class in ("SYSTEM_FAILURE", "BLOCKED"):
                status, reason = ("FAIL", "system_failure") if e.failure_class == "SYSTEM_FAILURE" else ("INFRA_FAILURE", "blocked")
            elif inv == "INV-VERB":
                status = "uninformative" if tier == "T0" and e.baseline_in_context is False else "PASS" if r.in_context is True else "FAIL"
                reason = "absent_after_fault" if status == "FAIL" else ""
            elif inv == "INV-NEW":
                if r.in_context is not True or r.selected_option != e.item["gold"]["option_id"]:
                    status, reason = "FAIL", "not_newest"
            elif r.forbidden_in_context is True:
                status, reason = "FAIL", "surfaced"
            elif not e.roots:
                status, reason = "INCONCLUSIVE", "no_snapshot"
            else:
                try:
                    for root in e.roots:
                        scan = search_store(root, needles_for(e.keys["forbidden"])).verdict
                        if scan == "found":
                            status, reason = "FAIL", "store_hit"
                            if _host_kept(e.kept_texts, needles_for(e.keys["forbidden"])):
                                rows[inv].append((i, "FAIL", "host_kept"))
                            break
                        if scan == "inconclusive":
                            status, reason = "INCONCLUSIVE", "opaque_store"
                except Exception:
                    status, reason = "INFRA_FAILURE", "infra"
            rows[inv].append((i, status, reason))
    expected, paired = tuple(sorted(set(expected_call_ids))), set()
    for n, (wire, body) in enumerate(requests if requests is not None else (), 1):
        if wire not in ("chat", "responses"):
            raise ValueError("invalid wire")
        calls = {i for i, _ in sorted(calls_in(body, wire), key=canon)}
        outputs = set(results(body, wire))
        paired.update(sorted(calls & outputs - {None}))
        if calls or outputs:
            broken = None in calls | outputs or calls != outputs
            rows["INV-PAIR"].append((f"req-{n}", "FAIL" if broken else "PASS", "orphan_result" if broken else ""))
    for n, i in enumerate(expected, 1):
        if i not in paired:
            rows["INV-PAIR"].append((f"expected-{n}", "FAIL", "orphan_result"))
    return {inv: _verdict(inv, rows[inv]) for inv in INVARIANTS}
