"""Hermes exposure and probe presence; raw ledger/report hashes are volatile.

This reader returns identifiers and observations only. Card provenance must use
R02's stable_digest instead of these wall-time-sensitive ledger/report hashes.
"""

import json
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.ledger.blobs import BlobStore
from bicentennial.ledger.verify import verify
from bicentennial.render.stream import verify_branch


@dataclass(frozen=True)
class Span:
    event_id: str
    session: int
    turn: int
    needles: tuple[str, ...]


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def _needles(values):
    values = tuple(_nfc(value) for value in values)
    if not values or any(not value or "\x00" in value for value in values):
        raise ValueError("invalid presence needle")
    return values


def locked_tokens(db) -> dict[str, tuple[str, ...]]:
    """Read fact tokens in token-id order, preserving duplicates."""
    result = {}
    for fact_id, value in db.execute("SELECT fact_id, value FROM locked_token ORDER BY token_id"):
        result.setdefault(fact_id, []).append(_nfc(value))
    return {fact_id: tuple(values) for fact_id, values in result.items()}


def spans(rows, session_ids, tokens, wanted) -> dict[str, Span]:
    """Resolve decisive event ids against the sealed stream's session order."""
    wanted, seen, result = set(wanted), set(), {}
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("duplicate session id")
    for row in rows:
        eid = row["event_id"]
        if eid in seen:
            raise ValueError("duplicate event id")
        seen.add(eid)
        if eid not in wanted:
            continue
        sid, key = row["session_id"], row["turn_key"]
        if sid not in session_ids:
            raise ValueError("unknown session id")
        prefix = f"{sid}/t"
        suffix = key[len(prefix):] if key.startswith(prefix) else ""
        if not suffix or any(c not in "0123456789" for c in suffix):
            raise ValueError("malformed turn key")
        turn = int(suffix)
        if turn < 1 or key != f"{sid}/t{turn}":
            raise ValueError("malformed turn key")
        needles = sorted({_nfc(value) for fid in row["fact_ids"]
                          for value in tokens.get(fid, ())})
        if not needles:
            if "text" not in row:
                raise ValueError("token-less payload span")
            needles = [row["text"]]
        result[eid] = Span(eid, session_ids.index(sid) + 1, turn, _needles(needles))
    if wanted - result.keys():
        raise ValueError("missing wanted span")
    return {eid: result[eid] for eid in sorted(result)}


def load_spans(out_dir, branch, tokens, wanted) -> dict[str, Span]:
    manifest = verify_branch(out_dir, branch)
    with (Path(out_dir) / f"stream.{branch}.jsonl").open(encoding="utf-8") as stream:
        return spans((json.loads(line) for line in stream), manifest["session_ids"], tokens, wanted)


def context_text(obj) -> str:
    """Join NFC string values, never keys; NUL prevents cross-value matches."""
    def strings(value):
        if isinstance(value, str):
            yield _nfc(value)
        elif isinstance(value, dict):
            for key in sorted(value):
                yield from strings(value[key])
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)

    return "\x00".join(strings(obj))


def present(needles, text) -> bool:
    return all(needle in text for needle in _needles(needles))


def _cursor(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2 or any(
            type(n) is not int or n < 1 for n in value):
        raise ValueError("invalid probe cursor")
    return tuple(value)


def exposure(roots, *, life, branch, system, spans, items, probes, recall, attempt_id=None) -> dict:
    """Read one attempt in run order without retaining request bodies."""
    needles = {eid: _needles(span.needles) for eid, span in spans.items()}
    roots = tuple(Path(root) for root in roots)
    if not roots:
        raise ValueError("empty ledger roots")
    indexed = {}
    for item in items:
        validate("item", item)
        iid = item["item_id"]
        if iid in indexed:
            raise ValueError("duplicate item id")
        for eid in item["gold_spans"]:
            if eid not in spans or spans[eid].session > item["probe_point"]:
                raise ValueError("unknown or future gold span")
        indexed[iid] = item
    if probes.keys() != indexed.keys():
        raise ValueError("probe keys differ from item ids")
    positions = {iid: _cursor(probes[iid]) for iid in sorted(indexed)}
    at_probe = {}
    for iid, cursor in positions.items():
        at_probe.setdefault(cursor, []).append(iid)
    hits = {eid: set() for eid in sorted(spans)}
    observed, digests, lock_hash = {}, [], None
    subroles = ("tool_results",) if recall else ("cursor", "retry")
    attempts = set()
    for root in roots:
        counts = verify(root)
        if counts["records"] < 1 or any(counts[key] for key in (
                "chain_breaks", "truncated_tail", "bad_blobs", "missing_lock_fields")):
            raise ValueError("invalid ledger integrity")
        raw = (root / "ledger.jsonl").read_bytes()
        digests.append(sha256(raw).hexdigest())
        store = BlobStore(root / "blobs", None)
        for line in raw.split(b"\n")[:-1]:
            rec = json.loads(line)
            if rec["type"] != "request":
                continue
            if attempt_id is not None and rec["attempt_id"] != attempt_id:
                continue
            attempts.add(rec["attempt_id"])
            if len(attempts) > 1:
                raise ValueError("mixed attempts")
            if any(rec[key] != value for key, value in (
                    ("life", life), ("branch", branch), ("system", system))):
                raise ValueError("foreign request identity")
            if lock_hash is None:
                lock_hash = rec["lock_hash"]
            elif lock_hash != rec["lock_hash"]:
                raise ValueError("mixed lock hashes")
            if rec["status"] != 200 or rec["cursor"] is None:
                continue
            cursor = (rec["cursor"]["session"], rec["cursor"]["turn"])
            history = rec["role"] in ("replay_main", "write_turn")
            probe = (rec["role"] == "probe_main" and rec["subrole"] in subroles
                     and cursor in at_probe and cursor not in observed)
            if not history and not probe:
                continue
            text = context_text(json.loads(store.get(rec["req"])))
            if history:
                for eid in hits:
                    if all(needle in text for needle in needles[eid]):
                        hits[eid].add(cursor)
            if probe:
                observed[cursor] = {
                    iid: sorted({eid for eid in indexed[iid]["gold_spans"]
                                 if not all(needle in text for needle in needles[eid])})
                    for iid in at_probe[cursor]}
            del text
    span_report = {}
    for eid, cursors in hits.items():
        span = spans[eid]
        ordered = sorted(cursors)
        first = next((c for c in ordered if c >= (span.session, span.turn)), None)
        span_report[eid] = {"delivered": [span.session, span.turn],
                            "present": [list(c) for c in ordered],
                            "first": list(first) if first is not None else None}
    item_report = {}
    for iid in sorted(indexed):
        item, cursor = indexed[iid], positions[iid]
        unexposed = sorted({eid for eid in item["gold_spans"]
                            if span_report[eid]["first"] is None or
                            span_report[eid]["first"][0] > item["probe_point"]})
        known = cursor in observed and bool(item["gold_spans"])
        missing = observed[cursor][iid] if known else []
        item_report[iid] = {"probe": list(cursor),
                            "cause": "N/A_EXPOSURE" if unexposed else None,
                            "unexposed": unexposed, "in_context": not missing if known else None,
                            "missing": missing}
    return {"life": life, "branch": branch, "system": system, "lock_hash": lock_hash,
            "ledgers": digests, "spans": span_report, "items": item_report,
            "volatile": ["ledgers", "report_hash"]}


def report_bytes(report) -> bytes:
    return canon(report)
