"""Exact, reversible row swaps and independently compiled twin lives."""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.items.bundle import Compiled, compile_life
from bicentennial.items.compile import compile_branch
from bicentennial.items.protocol import TWIN_TYPES
from bicentennial.keyed import shuffle
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import (
    history_set_hash,
    stream_bytes,
    verify_branch,
    write_branch,
)

from . import db as writers
from . import unit
from .export import export_jsonl
from .lineage import closure
from .processes import (
    LOW_SALIENCE,
    NUMBER,
    SOFT,
    check_tokens,
    check_values,
    mint,
    pair,
    slot,
    token_value,
)
from .processes.forget import forget_request, verify
from .processes.plants import plant
from .scale import TURNS


@dataclass(frozen=True)
class Flip:
    key: tuple[str, str]
    twin_type: str
    kind: str
    decisive_fact_id: str
    out: tuple[bytes, ...]
    into: tuple[bytes, ...]
    facts: frozenset[str]
    events: frozenset[str]


class IndependenceError(ValueError):
    def __init__(self, rejected, item_ids):
        self.rejected = tuple(sorted(rejected))
        super().__init__(" ".join(sorted(item_ids[key] for key in self.rejected)))


@dataclass(frozen=True)
class TwinLife:
    flips: tuple[Flip, ...]
    b1: sqlite3.Connection
    cuts: tuple
    manifests: tuple
    history_set_hash: str
    compiled: Compiled
    differing: frozenset[str]
    prefix: int


def _line(table, row):
    return canon({"table": table, "row": row})


def _rows(db):
    return [json.loads(line) for line in export_jsonl(db).splitlines()]


def plan_flip(db, schedule, *, key, twin_type, decisive_fact_id, principal_id) -> Flip:
    """Plan one bundle against B0; refusal messages contain only the decisive id."""
    rows, out, into = _rows(db), [], []

    def find(table, **fields):
        return [r["row"] for r in rows if r["table"] == table
                and all(r["row"].get(k) == v for k, v in fields.items())]

    def swap(table, row, replacement=None):
        out.append(_line(table, row))
        if replacement is not None:
            into.append(_line(table, replacement))

    def correction_rows():
        try:
            link, = links
            event, = find("event", id=link["event_id"])
            retract, = find("link", event_id=event["id"], role="retract")
            previous, = find("fact", id=retract["fact_id"])
            ah, = find("attr", entity_id=f["subject_id"], key=f["predicate"], value=f["object"],
                       valid_from_t=event["t_sim"], valid_to_t=None, recorded_t=event["t_sim"], source_event_id=event["id"])
            ap, = find("attr", entity_id=previous["subject_id"], key=previous["predicate"],
                       value=previous["object"], valid_to_t=event["t_sim"])
            if (f["speech_act"] == "assert" and link["role"] == "assert" and not find("fact_surface", fact_id=decisive_fact_id)
                    and all(previous[k] == f[k] for k in ("subject_id", "predicate"))):
                return retract, ah, ap
        except ValueError:
            pass
        return None

    try:
        if twin_type not in TWIN_TYPES:
            raise ValueError
        f, = find("fact", id=decisive_fact_id)
        links = find("link", fact_id=decisive_fact_id)
        requests = [r for r in find("forget_request") if decisive_fact_id in r["covered_fact_ids_json"]]
        if twin_type == "fork":
            kind = "value"
            token, = find("locked_token", fact_id=decisive_fact_id)
            stem, _ = re.fullmatch(r"([A-Z]{2,12})-([0-9]{6})", token["value"]).groups()
            if (f["object"] != token["value"] or f["predicate"] in ("forget", "forget_ref")
                    or find("commitment", fact_id=decisive_fact_id) or find("plant", fact_id=decisive_fact_id)
                    or any(find("event", id=link["event_id"])[0]["payload_json"] for link in links)):
                raise ValueError
            attrs = find("attr", entity_id=f["subject_id"], key=f["predicate"], value=f["object"])
            allowed = {_line("fact", f), _line("locked_token", token), *(_line("attr", a) for a in attrs)}
            if any(token["value"].encode() in canon(r) for r in rows if canon(r) not in allowed):
                raise ValueError
            values = [r["value"] for r in find("locked_token") if r != token]
            for n in range(8):
                alternate = token_value(db, schedule, "twin", decisive_fact_id, "value", n, stem, containment=False)
                try:
                    check_values([*values, alternate])
                    break
                except ValueError:
                    continue
            else:
                raise ValueError
            swap("fact", f, f | {"object": alternate})
            swap("locked_token", token, token | {"value": alternate})
            for a in attrs:
                swap("attr", a, a | {"value": alternate})
        elif twin_type == "lure":
            kind = "cancel"
            made, = find("locked_token", fact_id=decisive_fact_id)
            stem, number = re.fullmatch(r"([A-Z]{2,12})-([0-9]{6})", made["value"]).groups()
            retract, = [link for link in links if link["role"] == "retract"]
            event, = find("event", id=retract["event_id"])
            asserted, = [link for link in find("link", event_id=event["id"]) if link["role"] == "assert"]
            fx, = find("fact", id=asserted["fact_id"])
            token, = find("locked_token", fact_id=fx["id"])
            if (not find("commitment", fact_id=decisive_fact_id)
                    or len(find("link", event_id=event["id"])) != 2 or find("link", fact_id=fx["id"]) != [asserted]
                    or any(fx[k] != f[k] for k in ("subject_id", "predicate")) or fx["polarity"] != "negate"
                    or token["value"] != f"{stem}-{pair(schedule, int(number))}"):
                raise ValueError
            for table, row in [("event", event), ("link", retract), ("link", asserted), ("fact", fx),
                               ("locked_token", token), *[("fact_surface", r) for r in find("fact_surface", fact_id=fx["id"])]]:
                swap(table, row)
        elif twin_type == "trigger" and requests:
            kind = "forget"
            request, = requests
            fr = forget_request(db, request["event_id"])
            if correction_rows() is not None:
                raise ValueError
            marker, = find("locked_token", fact_id=fr.marker_fact_id)
            if marker["value"] != find("fact", id=fr.marker_fact_id)[0]["object"]:
                raise ValueError
            swap("locked_token", marker)
            request_facts = (*fr.request_fact_ids, fr.marker_fact_id)
            for fid in request_facts:
                if (fid in fr.request_fact_ids and find("locked_token", fact_id=fid)
                        or any(link["event_id"] != fr.event_id for link in find("link", fact_id=fid))):
                    raise ValueError
                swap("fact", find("fact", id=fid)[0])
                for surface in find("fact_surface", fact_id=fid):
                    swap("fact_surface", surface)
            for link in find("link", event_id=fr.event_id):
                if link["fact_id"] not in request_facts:
                    raise ValueError
                swap("link", link)
            swap("event", find("event", id=fr.event_id)[0])
            swap("forget_request", request)
        elif twin_type == "trigger":
            kind = "correction"
            pattern = correction_rows()
            if pattern is None:
                raise ValueError
            retract, ah, ap = pattern
            swap("fact", f, f | {"speech_act": "hedge", "strength": SOFT})
            swap("link", retract)
            swap("attr", ah)
            swap("attr", ap, ap | {"valid_to_t": None})
        else:
            kind = "source"
            tw = plant(db, decisive_fact_id).twin
            carrier, = find("event", id=tw.carrier_event_id)
            if tw.actor_id == carrier["actor_id"] and tw.evidence_fact_id is None:
                raise ValueError
            swap("fact", f, f | {"modality": "stated"})
            swap("plant", find("plant", fact_id=decisive_fact_id)[0])
            if tw.actor_id != carrier["actor_id"]:
                swap("event", carrier, carrier | {"actor_id": tw.actor_id})
            if tw.evidence_fact_id is not None:
                evidence_links = find("link", fact_id=tw.evidence_fact_id)
                if any(find("event", id=link["event_id"])[0]["payload_json"] for link in evidence_links):
                    raise ValueError
                evidence, = find("fact", id=tw.evidence_fact_id)
                if find("attr", entity_id=evidence["subject_id"], key=evidence["predicate"], value=evidence["object"]):
                    raise ValueError
                swap("fact", evidence, evidence | {"object": tw.evidence_object, "polarity": tw.evidence_polarity})
        removed = [json.loads(line) for line in out]
        added = [json.loads(line) for line in into]
        retained = [r for r in rows if canon(r) not in out]
        missing = {(r["table"], r["row"]["id"]) for r in removed if r["table"] in ("event", "fact")}
        missing -= {(r["table"], r["row"]["id"]) for r in added if r["table"] in ("event", "fact")}
        if any(canon(fid) in canon(r) for _, fid in sorted(missing) for r in retained):
            raise ValueError
        occupied = {r["row"]["t_sim"] for r in retained + added if r["table"] == "event"}
        vacated = {r["row"]["t_sim"] for r in removed if r["table"] == "event"} - occupied
        for k in range(1, len(schedule.sessions) + 1):
            for n in range(1, TURNS + 1):
                if slot(schedule, k, n) in vacated:
                    eid = mint(schedule, "filler", "slots", "event", "event", (k - 1) * TURNS + n)
                    if find("event", id=eid):
                        raise ValueError
                    into.append(_line("event", dict(id=eid, t_sim=slot(schedule, k, n), kind="filler", channel="chat",
                        actor_id=principal_id, audience_json=["agent"], visibility="shared", salience=LOW_SALIENCE, payload_json={})))
        changed = [json.loads(line) for line in sorted(out + into)]
        facts = {decisive_fact_id} | {r["id"] for r in find("fact") if any(canon(r["id"]) in canon(c) for c in changed)}
        events = {r["row"]["id"] for r in changed if r["table"] == "event"}
        events |= {r["row"]["event_id"] for r in changed if r["table"] in ("link", "forget_request")}
        events |= {r["row"]["carrier_event_id"] for r in changed if r["table"] == "plant"}
        rendered = {r["row"].get("fact_id", r["row"].get("id")) for r in changed
                    if r["table"] in ("fact", "locked_token", "commitment", "plant")}
        events |= {r["row"]["event_id"] for r in retained + changed if r["table"] == "link" and r["row"]["fact_id"] in rendered}
        if not out:
            raise ValueError
        return Flip(key, twin_type, kind, decisive_fact_id, tuple(sorted(out)), tuple(sorted(into)), frozenset(facts), frozenset(events))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ValueError(decisive_fact_id) from None


def guard(db, item, decisive_fact_id) -> frozenset[str]:
    spans = set(item["gold_spans"])
    evidence = {decisive_fact_id} | {r["fact_id"] for r in db.execute("SELECT * FROM link") if r["event_id"] in spans}
    evidence.update(closure(db, sorted(evidence)).facts)
    lineage = db.execute("SELECT * FROM lineage ORDER BY artifact_kind, artifact_id, source_fact_id").fetchall()
    while True:
        expanded = evidence | {r["source_fact_id"] for r in lineage if
            r["artifact_kind"] == "fact" and r["artifact_id"] in evidence or
            r["artifact_kind"] == "event" and r["artifact_id"] in spans}
        if expanded == evidence:
            return frozenset(evidence)
        evidence = expanded


def independent(db, schedule, flips, guards):
    """Return accepted swaps and rejected keys in the keyed greedy order."""
    by_key = {f.key: f for f in flips}
    if len(by_key) != len(flips):
        raise ValueError("duplicate flip key")
    order = shuffle(schedule.seed, unit(schedule.life, "twin", "order"), 0, "order",
                    sorted(canon(list(key)).decode() for key in by_key))
    accepted, rejected = [], []
    times = {f.key: {json.loads(line)["row"]["t_sim"] for line in f.out if json.loads(line)["table"] == "event"} for f in flips}
    for encoded in order:
        f = by_key[tuple(json.loads(encoded))]
        spans, facts = guards[f.key]
        if any(f.facts & guards[a.key][1] or a.facts & facts or f.events & guards[a.key][0]
               or a.events & spans or set(f.out + f.into) & set(a.out + a.into) or times[f.key] & times[a.key] for a in accepted):
            rejected.append(f.key)
        else:
            accepted.append(f)
    return tuple(accepted), tuple(sorted(rejected))


def plan(db0, schedule, b0, *, principal_id):
    flips, guards, ids, refused = [], {}, {}, []
    for item, meta in b0.entries:
        if meta["twin_type"] is None:
            continue
        key = meta["template_id"], meta["instance_key"]
        try:
            flips.append(plan_flip(db0, schedule, key=key, twin_type=meta["twin_type"],
                                   decisive_fact_id=meta["decisive_fact_id"], principal_id=principal_id))
        except ValueError:
            refused.append(key)
        guards[key] = frozenset(item["gold_spans"]), guard(db0, item, meta["decisive_fact_id"])
        ids[key] = item["item_id"]
    accepted, rejected = independent(db0, schedule, flips, guards)
    rejected = [*refused, *rejected]
    values = dict(db0.execute("SELECT token_id, value FROM locked_token"))
    for f in accepted:
        if f.kind != "value":
            continue
        replacements = {r["row"]["token_id"]: r["row"]["value"] for line in f.into
                        if (r := json.loads(line))["table"] == "locked_token"}
        candidate = values | replacements
        try:
            check_values(list(candidate.values()))
            numbers = [n for value in candidate.values() for n in NUMBER.findall(value)]
            if len(set(numbers)) != len(numbers):
                raise ValueError
        except ValueError:
            rejected.append(f.key)
        else:
            values = candidate
    if rejected:
        raise IndependenceError(rejected, ids)
    return tuple(sorted(accepted, key=lambda f: f.key))


def apply(db, flips, path) -> sqlite3.Connection:
    """Write either direction of each exact swap, deleting partial outputs on failure."""
    path, lines, seen, removed, added = Path(path), set(export_jsonl(db).splitlines()), set(), set(), set()
    if path.exists():
        raise ValueError("existing world")
    for f in flips:
        out, into = set(f.out), set(f.into)
        if not out or seen & (out | into):
            raise ValueError(f.decisive_fact_id)
        seen.update(out | into)
        if out <= lines and not into & lines:
            take, put = out, into
        elif into <= lines and not out & lines:
            take, put = into, out
        else:
            raise ValueError(f.decisive_fact_id)
        removed.update(take)
        added.update(put)
    result = sorted((lines - removed) | added)
    rows = [json.loads(line) for line in result]
    meta, = [r["row"] for r in rows if r["table"] == "meta"]
    db1 = writers.create_world(path, meta)
    try:
        for table in writers.TABLES[1:]:
            for row in rows:
                if row["table"] == table:
                    getattr(writers, f"insert_{table}")(db1, **row["row"])
        check_tokens(db1)
        verify(db1)
        if export_jsonl(db1) != b"\n".join(result) + b"\n":
            raise ValueError("export mismatch")
        db1.commit()
        db1.close()
        return writers.open_world(path)
    except Exception:
        db1.close()
        path.unlink(missing_ok=True)
        raise ValueError("invalid twin world") from None


def twin_life(db0, schedule, templates, *, world_path, out_dir, principal_id, expected_state, bank=None) -> TwinLife:
    """Compile both worlds, prove their independence and stream diff, then publish branches."""
    world_path, out_dir = Path(world_path), Path(out_dir)
    files = [out_dir / f"{name}.{branch}.{suffix}" for branch in ("B0", "B1")
             for name, suffix in (("stream", "jsonl"), ("sessions", "jsonl"), ("history", "json"))]
    if world_path.exists() or any(path.exists() for path in files):
        raise ValueError("existing twin output")
    templates, state0 = tuple(templates), expected_state(db0)
    pre = cut(db0, schedule, branch="B0", principal_id=principal_id, expected_state=state0, bank=bank)
    flips = plan(db0, schedule, compile_branch(db0, schedule, pre, templates), principal_id=principal_id)
    db1 = None
    try:
        db1 = apply(db0, flips, world_path)
        excluded = frozenset(r[0] for db in (db0, db1) for r in db.execute("SELECT value FROM locked_token ORDER BY value"))
        cuts = tuple(cut(db, schedule, branch=branch, principal_id=principal_id, expected_state=state,
                         bank=bank, exclude_tokens=excluded) for db, branch, state in
                     ((db0, "B0", state0), (db1, "B1", expected_state(db1))))
        branches = tuple(compile_branch(db, schedule, c, templates) for db, c in zip((db0, db1), cuts, strict=True))
        compiled = compile_life(*branches)
        guards, ids = {}, {}
        for db, branch in zip((db0, db1), branches, strict=True):
            for item, meta in branch.entries:
                if meta["twin_type"] is not None:
                    key = meta["template_id"], meta["instance_key"]
                    spans, facts = guards.get(key, (frozenset(), frozenset()))
                    guards[key] = spans | frozenset(item["gold_spans"]), facts | guard(db, item, meta["decisive_fact_id"])
                    ids.setdefault(key, item["item_id"])
        _, rejected = independent(db0, schedule, flips, guards)
        if rejected:
            raise IndependenceError(rejected, ids)
        streams = [{r["event_id"]: {k: v for k, v in r.items() if k not in ("seq", "sha256")} for r in c.rows} for c in cuts]
        differing = frozenset(eid for eid in sorted(streams[0].keys() | streams[1].keys()) if streams[0].get(eid) != streams[1].get(eid))
        if not differing <= frozenset(eid for f in flips for eid in f.events) or any(not differing & f.events for f in flips):
            raise ValueError("event footprint mismatch")
        prefix = min((i for c in cuts for i, r in enumerate(c.rows) if r["event_id"] in differing), default=len(cuts[0].rows))
        raw = [stream_bytes(c.rows).splitlines(keepends=True) for c in cuts]
        if raw[0][:prefix] != raw[1][:prefix] or differing and raw[0][prefix:prefix + 1] == raw[1][prefix:prefix + 1]:
            raise ValueError("prefix mismatch")
        out_dir.mkdir(parents=True, exist_ok=True)
        manifests = tuple(write_branch(out_dir, c) for c in cuts)
        for branch in ("B0", "B1"):
            verify_branch(out_dir, branch)
        return TwinLife(flips, db1, cuts, manifests, history_set_hash(manifests), compiled, differing, prefix)
    except Exception:
        if db1 is not None:
            db1.close()
            world_path.unlink(missing_ok=True)
        for path in files:
            path.unlink(missing_ok=True)
        raise
