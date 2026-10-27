"""Canonical, pinned and independently recomputed cached-control entries."""

import json
import os
import re
import tempfile
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon, milli, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.score.aggregate import compare, reduce
from bicentennial.world.scale import DEV_WINDOW

from . import full_history, no_memory, oracle_evidence
from .common import check

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
READER_FILES = ("probe/__init__.py", "probe/argtemplate.py", "probe/probe_responder.py",
                "probe/scripted_reader.py")
CONTROL_FILES = ("api/adapters/nomemory.py", "api/adapters/oracle_evidence.py",
                 "api/adapters/reference_store.py", "api/contract.py", "controls/__init__.py",
                 "controls/cache.py", "controls/common.py", "controls/full_history.py",
                 "controls/no_memory.py", "controls/oracle_evidence.py", "world/tokens.py")
MIN_GAP_MILLI = 500


class ControlsTampered(ValueError):
    code = "pinned_artifact_changed"


def code_sha256(paths, *, root=PACKAGE_ROOT):
    return sha256_canon([[p, sha256((root / p).read_bytes()).hexdigest()] for p in sorted(paths)])


def cache_key(inp, *, harness_pin, window=DEV_WINDOW, root=PACKAGE_ROOT):
    if not isinstance(harness_pin, str) or not re.fullmatch(r"[0-9a-f]{64}", harness_pin):
        raise ValueError("invalid harness pin")
    if type(window) is not int or window < 1:
        raise ValueError("invalid window")
    pack = {k: inp.pack[k] for k in sorted(inp.pack) if k != "controls"}
    pack["hashes"] = {k: pack["hashes"][k] for k in sorted(pack["hashes"]) if k != "controls"}
    return dict(lives_sha256=sha256_canon(dict(pack=pack,
                reader_keys=sorted(inp.keys, key=lambda k: k["item_id"]), events=inp.events,
                now=inp.now, scoring_sha256=inp.scoring_sha256)),
                reader_sha256=code_sha256(READER_FILES, root=root), harness_pin=harness_pin,
                scorer_sha256=code_sha256([p.relative_to(root).as_posix()
                    for p in sorted((root / "score").glob("*.py"))], root=root),
                controls_sha256=code_sha256(CONTROL_FILES, root=root), window=window)


def _aggregates(arms):
    names = ("no_memory", "oracle_evidence")
    if arms[names[0]]["singleton_lives"] != arms[names[1]]["singleton_lives"]:
        raise ValueError("gate arms have different singleton lives")
    compared = compare({n: ({i["item_id"]: i for i in arms[n]["items"]}, arms[n]["bundles"])
                        for n in names}, singleton_lives=arms[names[0]]["singleton_lives"])
    diagnostic = arms["full_history"]
    return dict(full_history=reduce(diagnostic["items"], diagnostic["bundles"],
                singleton_lives=diagnostic["singleton_lives"])["aggregates"],
                **{n: compared[n]["aggregates"] for n in names})


def broken_rows(floor_rows, ceiling_rows):
    floor = {(r["stage"], r["track"]): r["score_milli"] for r in floor_rows}
    ceiling = {(r["stage"], r["track"]): r["score_milli"] for r in ceiling_rows}
    return [dict(stage=s, track=t) for s, t in sorted(floor.keys() | ceiling.keys())
            if floor.get((s, t)) is None or ceiling.get((s, t)) is None
            or ceiling[(s, t)] - floor[(s, t)] < MIN_GAP_MILLI]


def _canary():
    return json.loads((SCHEMAS / "pack.schema.json").read_bytes())["properties"]["canary"]["enum"][0]


def compute(inp, *, score, harness_pin, window=DEV_WINDOW):
    check(inp)
    key = cache_key(inp, harness_pin=harness_pin, window=window)
    arms = dict(no_memory=no_memory.run(inp, score=score),
                oracle_evidence=oracle_evidence.run(inp, score=score),
                full_history=full_history.run(inp, score=score, window=window))
    rows = _aggregates(arms)
    for name in sorted(arms):
        arms[name]["aggregates"] = rows[name]
    entry = dict(canary=_canary(), key=key, key_sha256=sha256_canon(key), arms=arms,
                 broken=broken_rows(rows["no_memory"], rows["oracle_evidence"]))
    return dict(entry, digest=sha256_canon(entry))


def write_entry(path, entry):
    path, data = Path(path), canon(entry)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = stream.name
        try:
            stream.write(data)
            stream.close()
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return sha256(data).hexdigest()


def read_entry(path, key, *, expected_sha256=None):
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    try:
        if expected_sha256 is not None and sha256(data).hexdigest() != expected_sha256:
            raise ValueError("file hash mismatch")
        entry = json.loads(data)
        if canon(entry) != data or set(entry) != {"canary", "key", "key_sha256", "arms", "broken", "digest"}:
            raise ValueError("noncanonical entry shape")
        payload = {k: entry[k] for k in sorted(entry) if k != "digest"}
        if (entry["canary"] != _canary() or entry["digest"] != sha256_canon(payload)
                or entry["key_sha256"] != sha256_canon(entry["key"])):
            raise ValueError("entry hash mismatch")
        arms = entry["arms"]
        if set(arms) != {"no_memory", "oracle_evidence", "full_history"}:
            raise ValueError("invalid arms")
        for name in sorted(arms):
            for item in arms[name]["items"]:
                validate("item_outcome", item)
        rows = _aggregates(arms)  # S06 validates items and rebuilds every bundle.
        if any(arms[n]["aggregates"] != rows[n] for n in sorted(arms)) or entry["broken"] != broken_rows(
                rows["no_memory"], rows["oracle_evidence"]):
            raise ValueError("cached projections differ")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise ControlsTampered("cached controls failed verification") from error
    return entry if entry["key"] == key else None


def ensure(inp, path, *, score, harness_pin, window=DEV_WINDOW):
    key = cache_key(inp, harness_pin=harness_pin, window=window)
    entry = read_entry(path, key)
    if entry is None:
        entry = compute(inp, score=score, harness_pin=harness_pin, window=window)
        write_entry(path, entry)
    return entry


def normalised_milli(a, floor, ceiling):
    if a is None or floor is None or ceiling is None:
        return None
    return "n/a" if ceiling <= floor else milli(Fraction(a - floor, ceiling - floor))


def display_rows(entry, aggregates):
    rows = [{(r["stage"], r["track"]): r["score_milli"] for r in entry["arms"][n]["aggregates"]}
            for n in ("no_memory", "oracle_evidence")]
    return [dict(stage=r["stage"], track=r["track"], normalised_milli=normalised_milli(
                r["score_milli"], *(table.get((r["stage"], r["track"])) for table in rows)))
            for r in sorted(aggregates, key=lambda r: (r["stage"], r["track"]))]


def card_controls(entry):
    arms = entry["arms"]
    tracks = {r["track"] for n in ("no_memory", "oracle_evidence") for r in arms[n]["aggregates"]}
    result = {}
    for name, label in (("no_memory", "no_memory_floor"), ("oracle_evidence", "oracle_evidence"),
                        ("full_history", "full_history")):
        rows = arms[name]["aggregates"]
        chosen = next((r for r in rows if r["stage"] == "act"), rows[0] if len(rows) == 1 else None)
        result[label] = chosen["score_milli"] if len(tracks) == 1 and chosen is not None else None
    return dict(result, naive_rag="not run in v0.1")


def pack_controls(entry):
    return dict({n: {k: entry["arms"][n][k] for k in
                (("aggregates", "fits") if n == "full_history" else ("aggregates",))}
                for n in ("full_history", "no_memory", "oracle_evidence")}, naive_rag="not run in v0.1")
