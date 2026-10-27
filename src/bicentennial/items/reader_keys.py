"""Pure runner-sealed evidence keys, derived from branch-local visible rows."""

import unicodedata
from hashlib import sha256

from bicentennial.contracts.run import validate
from bicentennial.render.stream import content
from bicentennial.world import world_hash
from bicentennial.world.processes.forget import forget_request
from bicentennial.world.processes.plants import rejection

from .protocol import CANARY

KINDS = ("stale", "planted", "twin")


def recall_query(item) -> str:
    return item["prompt"]


def query_leaks(query, prompt, texts) -> tuple[str, ...]:
    q, p = (unicodedata.normalize("NFC", s) for s in (query, prompt))
    texts = tuple(unicodedata.normalize("NFC", t) for t in texts)
    leaks = set()
    for i in range(len(q)):
        for j in range(i + 1, len(q) + 1):
            sub = q[i:j]
            if sub not in p:
                if any(sub in text for text in texts):
                    leaks.add(sub)
                break
    return tuple(sorted(leaks))


def reader_keys(db, schedule, cut, item, record, *, twin=None) -> dict:
    iid, d = item["item_id"], record["decisive_fact_id"]
    if (cut.world_hash != world_hash(db) or cut.schedule_sha256 != sha256(schedule.to_json()).hexdigest()
            or cut.life != schedule.life or record["life"] != cut.life
            or record["branch"] != cut.branch or record["item_id"] != iid
            or (twin is None) != (record["bundle_id"] is None)
            or twin is not None and twin["item_id"] == iid):
        raise ValueError(f"reader identity mismatch: {iid}")
    tokens, facts = {}, {}
    for fid, token in db.execute("SELECT fact_id, value FROM locked_token ORDER BY token_id"):
        if fid in tokens or token in facts:
            raise ValueError(f"ambiguous locked token: {fid}")
        tokens[fid], facts[token] = token, fid
    gold = set(item["options"][0]["tokens"])
    required, forbidden, spans = set(gold), set(), set()
    idx = {p.session_id: p.index for p in schedule.sessions}
    visible = [r for r in cut.rows if idx[r["session_id"]] <= item["probe_point"] and "agent" in r["audience"]]
    events = {r["event_id"] for r in visible}
    if not set(item["gold_spans"]) <= events:
        raise ValueError(f"gold span not visible to the agent: {iid}")
    visible_facts = {fid for r in visible for fid in r["fact_ids"]}
    links = list(db.execute("SELECT event_id, fact_id, role FROM link ORDER BY event_id, fact_id, role"))
    retracts = {(eid, fid) for eid, fid, role in links if role == "retract" and eid in events}
    if d is not None and tokens.get(d) not in gold:
        spans.update(eid for eid, fid in sorted(retracts) if fid == d)
        if any(tokens[fid] not in gold for eid, fid, role in links
               if eid in spans and role == "assert" and fid in tokens):
            raise ValueError(f"superseding token absent from gold: {iid}")
    for (eid,) in db.execute("SELECT event_id FROM forget_request ORDER BY event_id"):
        if eid in events:
            request = forget_request(db, eid)
            forbidden.update(request.selector)
            if d in request.covered:
                spans.add(eid)
                required.add(request.marker)
    plants = list(db.execute("SELECT fact_id, carrier_event_id FROM plant ORDER BY fact_id, carrier_event_id, kind"))
    decisive_plants = [eid for fid, eid in plants if fid == d]
    if len(decisive_plants) > 1:
        raise ValueError(f"multiple decisive plants: {d}")
    if decisive_plants and decisive_plants[0] in events:
        rej = rejection(db, d, decisive_plants[0])
        if rej is not None:
            spans.add(rej.evidence_event_id)
            if rej.evidence_fact_id in tokens:
                required.add(tokens[rej.evidence_fact_id])
    if required & forbidden or not spans <= set(item["gold_spans"]):
        raise ValueError(f"conflicting keys or missing required span: {iid}")
    related = set()
    if d is not None:
        subject, predicate = db.execute("SELECT subject_id, predicate FROM fact WHERE id=?", (d,)).fetchone()
        related = {r[0] for r in db.execute("SELECT id FROM fact WHERE subject_id=? AND predicate=? ORDER BY id",
                                          (subject, predicate))}
    stale = {fid for _, fid in sorted(retracts)} & related
    planted = {fid for fid, eid in plants if eid in events} & related
    twins = set(twin["options"][0]["tokens"]) if twin is not None else set()
    competing = []
    for token in sorted(tokens[fid] for fid in sorted(visible_facts) if fid in tokens):
        if token in required | forbidden:
            continue
        fid = facts[token]
        kind = "stale" if fid in stale else "planted" if fid in planted else "twin" if token in twins else None
        if kind is not None:
            competing.append(dict(token=token, kind=kind))
    rows = [r for r in visible if r["event_id"] in item["gold_spans"]]
    oracle = [r for r in rows if not any(tokens.get(fid) in forbidden for fid in r["fact_ids"])]
    oracle_ids = [r["event_id"] for r in oracle]
    oracle_facts = {fid for r in oracle for fid in r["fact_ids"]}
    query = recall_query(item)
    if (not spans <= set(oracle_ids) or any(facts.get(t) not in oracle_facts for t in sorted(required))
            or item["gold_spans"] and not oracle or query_leaks(query, item["prompt"], [content(r) for r in rows])):
        raise ValueError(f"invalid oracle evidence or recall query: {iid}")
    result = dict(canary=CANARY, item_id=iid, life=cut.life, branch=cut.branch, recall_query=query,
                  required=sorted(required), competing=competing, forbidden=sorted(forbidden), oracle_spans=oracle_ids)
    validate("reader_keys", result)
    return result


def life_keys(compiled, schedule, worlds) -> tuple[dict, ...]:
    if (compiled.life != schedule.life or set(worlds) != {"B0", "B1"}
            or any(worlds[b][1].branch != b for b in sorted(worlds))):
        raise ValueError("reader life or branch mismatch")
    items = {i["item_id"]: i for i in compiled.items}
    records = {r["item_id"]: r for r in compiled.records}
    if (len(items) != len(compiled.items) or len(records) != len(compiled.records) or items.keys() != records.keys()):
        raise ValueError("reader item and record mismatch")
    bundles = {b["bundle_id"]: b["items"] for b in compiled.bundles}
    results = []
    for iid in sorted(items):
        record, twin = records[iid], None
        bid = record["bundle_id"]
        if bid is not None:
            pair = bundles.get(bid, [])
            if len(pair) != 2 or iid not in pair or len(set(pair)) != 2 or any(i not in items for i in pair):
                raise ValueError(f"invalid reader bundle: {iid}")
            twin = items[next(i for i in pair if i != iid)]
        db, cut = worlds[record["branch"]]
        results.append(reader_keys(db, schedule, cut, items[iid], record, twin=twin))
    return tuple(results)
