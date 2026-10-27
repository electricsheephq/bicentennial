"""Pinned integer hashed TF-IDF control, cached in API mode."""

import json
import re
from fractions import Fraction as F
from hashlib import sha256

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.contract import answer, task_ids
from bicentennial.canon import canon, milli, sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.score.aggregate import reduce
from bicentennial.world.scale import DEV_WINDOW

from . import cache
from .common import check, run_arm

TOP_K = 5
CHUNK_CHARS = 240
EMBEDDER_NAME = "hashed-tfidf-v1"
EMBEDDER_FILES = ("api/adapters/reference_store.py", "api/contract.py", "controls/naive_rag.py")
PACKAGE_ROOT = cache.PACKAGE_ROOT


def words(text):
    return re.findall(r"\w+", text.lower())


def feature(word):
    d = sha256(word.encode()).digest()
    return int.from_bytes(d[:8], "big"), -1 if d[8] & 1 else 1


def ln_fixed(x):
    shifts = 0
    while x >= 2:
        x /= 2
        shifts += 1

    def series(z):
        return 2 * sum((z ** (2 * k + 1) / (2 * k + 1) for k in range(24)), F(0))

    return int(1_000_000 * (shifts * series(F(1, 3)) + series((x - 1) / (x + 1))))


def idf_fixed(n, df):
    return ln_fixed(1 + F(2 * (n - df) + 1, 2 * df + 1))


def vector(word_list, idf):
    result = {}
    for word in sorted(set(word_list)):
        coordinate, sign = feature(word)
        result[coordinate] = result.get(coordinate, 0) + sign * word_list.count(word) * idf[word]
    return {j: result[j] for j in sorted(result)}


def chunks(text):
    result, start, end = [], None, 0
    for word in re.finditer(r"\S+", text):
        if start is not None and word.end() - start > CHUNK_CHARS:
            result.append(text[start:end])
            start = None
        if start is None:
            start = word.start()
        end = word.end()
    if start is not None:
        result.append(text[start:end])
    return result


class NaiveRag(ReferenceStore):
    def reset(self):
        super().reset()
        self.retrievals = {}

    def scored(self, prompt, now):
        visible = [(eid, ordinal, text, words(text)) for eid in sorted(self.events)
                   if self.events[eid]["t_sim"] <= now
                   for ordinal, text in enumerate(chunks(self.events[eid]["text"]))]
        vocabulary = sorted(set(words(prompt)) | {w for _, _, _, ws in visible for w in ws})
        idf = {w: idf_fixed(len(visible), sum(w in ws for _, _, _, ws in visible)) for w in vocabulary}
        q, ranked = vector(words(prompt), idf), []
        for eid, ordinal, text, ws in visible:
            c = vector(ws, idf)
            norm = sum(c[j] ** 2 for j in sorted(c))
            dot = sum(q[j] * c.get(j, 0) for j in sorted(q))
            if norm > 0 and dot > 0:
                ranked.append((F(dot * dot, norm), eid, ordinal, text))
        return sorted(ranked, key=lambda r: (-r[0], r[1], r[2]))

    def query(self, task, now):
        task_ids(task, now)
        top = self.scored(task["prompt"], now)[:TOP_K]
        self.retrievals[task["task_id"]] = [[eid, ordinal] for _, eid, ordinal, _ in top]
        return dict(output="\n".join(r[3] for r in top), citations=[r[1] for r in top],
                    confidence_milli=1000) if top else answer()


def run(inp, *, score):
    adapters = []
    keys = {k["item_id"]: k for k in sorted(inp.keys, key=lambda k: k["item_id"])}
    assert all(t.isascii() for i in sorted(keys) for t in keys[i]["required"]), "non-ASCII required token"

    def factory():
        adapter = NaiveRag()
        adapters.append(adapter)
        return adapter

    arm = run_arm(inp, factory, score=score)
    owners = {i: a for a in adapters for i in sorted(a.retrievals)}
    ids = sorted(i["item_id"] for i in arm["items"])
    arm["retrieved"] = {i: owners[i].retrievals[i] for i in ids}
    for report in arm["reports"]:
        iid = report["item_id"]
        key, adapter = keys[iid], owners[iid]
        hits, fallback, fallback_hits = 0, 0, 0
        for eid in key["oracle_spans"]:
            event = adapter.events.get(eid)
            if event is None:
                continue
            required = [t for t in key["required"] if t in event["text"]]
            recalled = any(e == eid and all(t in chunks(event["text"])[ordinal] for t in required)
                           for e, ordinal in arm["retrieved"][iid][:TOP_K])
            hits += recalled
            fallback += not required
            fallback_hits += recalled and not required
        total = len(key["oracle_spans"])
        report["recall"] = dict(k=TOP_K, hits=hits, of=total, milli=milli(F(hits, total))) if total else None
        report["recall_basis"] = "chunk_quote"
        report["recall_event_id_basis"] = dict(hits=fallback_hits, of=fallback)
    return arm


def embedder_params():
    return dict(name=EMBEDDER_NAME, top_k=TOP_K, chunk_chars=CHUNK_CHARS,
                words="\\w+ over str.lower()", feature="sha256[0:8] big-endian, sign sha256[8] & 1",
                tf="raw count", idf="floor(1e6 ln(1 + (N - df + 1/2) / (df + 1/2)))",
                score="cosine, dot > 0", ties="event_id, then chunk ordinal")


def embedder_sha256(*, root=PACKAGE_ROOT):
    return sha256_canon(dict(params=embedder_params(), code=cache.code_sha256(EMBEDDER_FILES, root=root)))


def rag_key(inp, *, harness_pin, window=DEV_WINDOW, root=PACKAGE_ROOT):
    return dict(cache.cache_key(inp, harness_pin=harness_pin, window=window, root=root),
                embedder_sha256=embedder_sha256(root=root))


def base_key(key):
    return {k: key[k] for k in sorted(key) if k != "embedder_sha256"}


def near_rows(floor_rows, rag_rows, ceiling_rows):
    tables = [{(r["stage"], r["track"]): r["score_milli"] for r in rows}
              for rows in (floor_rows, rag_rows, ceiling_rows)]
    result = []
    for stage, track in sorted(set().union(*(sorted(table) for table in tables))):
        f, r, c = (table.get((stage, track)) for table in tables)
        complete = None not in (f, r, c)
        result.append(dict(stage=stage, track=track, floor_milli=f, naive_rag_milli=r, ceiling_milli=c,
                           between=f < r < c if complete else None,
                           rag_near_solved=10 * r >= 10 * f + 7 * (c - f) if complete else None,
                           floor_near_solved=10 * f >= 7 * c if f is not None and c is not None else None))
    return result


def flagged(rows):
    return not any(r["between"] is True for r in rows)


def compute(inp, *, score, harness_pin, controls_entry, window=DEV_WINDOW):
    check(inp)
    key = rag_key(inp, harness_pin=harness_pin, window=window)
    if controls_entry["key"] != base_key(key):
        raise ValueError("controls entry is keyed differently")
    arm = run(inp, score=score)
    if arm["singleton_lives"] != controls_entry["arms"]["no_memory"]["singleton_lives"]:
        raise ValueError("controls singleton lives differ")
    arm["aggregates"] = reduce(arm["items"], arm["bundles"], singleton_lives=arm["singleton_lives"])["aggregates"]
    rows = near_rows(controls_entry["arms"]["no_memory"]["aggregates"], arm["aggregates"],
                     controls_entry["arms"]["oracle_evidence"]["aggregates"])
    entry = dict(canary=cache._canary(), key=key, key_sha256=sha256_canon(key), embedder=embedder_params(),
                 arm=arm, rows=rows, flagged=flagged(rows))
    return dict(entry, digest=sha256_canon(entry))


def _columns(rows, column):
    return [dict(stage=r["stage"], track=r["track"], score_milli=r[column]) for r in rows]


def read_entry(path, key, *, controls_entry, expected_sha256=None):
    if controls_entry["key"] != base_key(key):
        raise ValueError("controls entry is keyed differently")
    try:
        data = cache.Path(path).read_bytes()
    except FileNotFoundError:
        return None
    try:
        if expected_sha256 is not None and sha256(data).hexdigest() != expected_sha256:
            raise ValueError("file hash mismatch")
        entry = json.loads(data)
        if canon(entry) != data or set(entry) != {
                "canary", "key", "key_sha256", "embedder", "arm", "rows", "flagged", "digest"}:
            raise ValueError("noncanonical entry shape")
        arm, params = entry["arm"], entry["embedder"]
        if set(arm) != {"items", "bundles", "reports", "singleton_lives", "retrieved", "aggregates"}:
            raise ValueError("invalid arm shape")
        if (entry["canary"] != cache._canary() or entry["digest"] != sha256_canon(
                {k: entry[k] for k in sorted(entry) if k != "digest"})
                or entry["key_sha256"] != sha256_canon(entry["key"])):
            raise ValueError("entry hash mismatch")
        if set(params) != set(embedder_params()) or any(
                type(params[p]) is not (int if p in ("top_k", "chunk_chars") else str) for p in sorted(params)):
            raise ValueError("invalid embedder parameters")
        if params["top_k"] < 1 or params["chunk_chars"] < 1 or not re.fullmatch(
                r"[0-9a-f]{64}", entry["key"]["embedder_sha256"]):
            raise ValueError("invalid embedder pin")
        retrieved = arm["retrieved"]
        if set(retrieved) != {i["item_id"] for i in arm["items"]}:
            raise ValueError("retrieved identities differ")
        for iid in sorted(retrieved):
            pairs = retrieved[iid]
            if type(pairs) is not list or len(pairs) > params["top_k"] or any(
                    type(p) is not list or len(p) != 2 or type(p[0]) is not str
                    or type(p[1]) is not int or p[1] < 0 for p in pairs):
                raise ValueError("invalid retrieved chunks")
        if (params != embedder_params() or entry["key"]["embedder_sha256"] != key["embedder_sha256"]
                or any(entry["key"][p] != key[p] for p in
                       ("reader_sha256", "scorer_sha256", "controls_sha256"))):
            return None  # Old algorithms must not be recomputed with current code.
        for item in arm["items"]:
            validate("item_outcome", item)
        aggregates = reduce(arm["items"], arm["bundles"], singleton_lives=arm["singleton_lives"])["aggregates"]
        floor, ceiling = (_columns(entry["rows"], p) for p in ("floor_milli", "ceiling_milli"))
        rows = near_rows(floor, aggregates, ceiling)
        if (arm["aggregates"] != aggregates or entry["rows"] != rows
                or type(entry["flagged"]) is not bool or entry["flagged"] != flagged(rows)):
            raise ValueError("cached projections differ")
        if entry["key"] != key:
            return None
        expected = near_rows(controls_entry["arms"]["no_memory"]["aggregates"], aggregates,
                             controls_entry["arms"]["oracle_evidence"]["aggregates"])
        if rows != expected:
            raise ValueError("gate columns differ")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise cache.ControlsTampered("cached naive RAG failed verification") from error
    return entry


def ensure(inp, path, *, score, harness_pin, controls_entry, window=DEV_WINDOW):
    key = rag_key(inp, harness_pin=harness_pin, window=window)
    entry = read_entry(path, key, controls_entry=controls_entry)
    if entry is None:
        entry = compute(inp, score=score, harness_pin=harness_pin, controls_entry=controls_entry, window=window)
        cache.write_entry(path, entry)
    return entry


def card_value(controls_entry, rag_entry):
    tracks = {r["track"] for n in ("no_memory", "oracle_evidence")
              for r in controls_entry["arms"][n]["aggregates"]}
    rows = rag_entry["arm"]["aggregates"]
    chosen = next((r for r in rows if r["stage"] == "act"), rows[0] if len(rows) == 1 else None)
    return chosen["score_milli"] if len(tracks) == 1 and chosen is not None else None


def card_controls(controls_entry, rag_entry):
    return dict(cache.card_controls(controls_entry), naive_rag=card_value(controls_entry, rag_entry))


def pack_controls(controls_entry, rag_entry, rag_sha256):
    if type(rag_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", rag_sha256):
        raise ValueError("invalid naive RAG file digest")
    return dict(cache.pack_controls(controls_entry), naive_rag=dict(
        aggregates=rag_entry["arm"]["aggregates"], rows=rag_entry["rows"], flagged=rag_entry["flagged"],
        embedder=EMBEDDER_NAME, embedder_sha256=rag_entry["key"]["embedder_sha256"], entry_sha256=rag_sha256))


def disclosures(rag_entry):
    params = rag_entry["embedder"]
    return [("naive_rag.chunk_chars", str(params["chunk_chars"])), ("naive_rag.embedder", params["name"]),
            ("naive_rag.embedder_sha256", rag_entry["key"]["embedder_sha256"]),
            ("naive_rag.flagged", "true" if rag_entry["flagged"] else "false"),
            ("naive_rag.label", "cached, API mode"), ("naive_rag.top_k", str(params["top_k"]))]
