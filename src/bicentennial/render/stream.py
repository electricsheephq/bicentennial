"""Canonical stream seals, closed-world lint and immutable branch cache records."""

import json
import unicodedata
from functools import cache
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.world.tokens import ESTIMATOR


@cache
def _canary():
    return json.loads((SCHEMAS / "stream.schema.json").read_bytes())["properties"]["canary"]["enum"][0]


def event_sha256(row):
    return sha256_canon({k: v for k, v in row.items() if k != "sha256"})


def seal(row):
    row["sha256"] = event_sha256(row)
    validate("stream", row)
    return row


def _strings(value, keys=False):
    if isinstance(value, dict):
        for key in sorted(value):
            if keys:
                yield key
            yield from _strings(value[key], keys)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child, keys)
    elif isinstance(value, str):
        yield value


def content(row):
    return row["text"] if "text" in row else "".join(_strings(row["payload"]))


def _lint_form(row):
    parts = [row["text"]] if "text" in row else [canon(row["payload"]).decode(),
                                                *_strings([row["payload"], row["tool"]], keys=True)]
    return tuple(unicodedata.normalize("NFC", part) for part in parts)


def _present(token, form):
    """A token is present only inside one part of the form, never across a join."""
    return any(token in part for part in form)


def lint(db, rows):
    tokens = [(r["token_id"], r["fact_id"], unicodedata.normalize("NFC", r["value"]))
              for r in db.execute("SELECT * FROM locked_token ORDER BY token_id")]
    links = {(r["event_id"], r["fact_id"]) for r in db.execute("SELECT * FROM link")}
    violations = set()
    for row in rows:
        form, eid = _lint_form(row), row["event_id"]
        violations.update((eid, tid) for tid, fid, token in tokens
                          if _present(token, form) and (eid, fid) not in links)
        if _present(_canary(), form):
            violations.add((eid, "canary"))
    return sorted(violations)


def stream_bytes(rows):
    return b"".join(canon(row) + b"\n" for row in rows)


def stream_hash(rows):
    return sha256(stream_bytes(rows)).hexdigest()


sessions_bytes = stream_bytes
sessions_hash = stream_hash


def render_key(cut, meta):
    return sha256_canon({"meta": {k: meta[k] for k in ("generator_version", "genre", "seed", "scale")},
                         **{k: getattr(cut, k) for k in
                            ("life", "branch", "world_hash", "schedule_sha256", "bank_sha256",
                             "exclude_sha256")},
                         "lane": "template", "estimator": ESTIMATOR})


def _branch(branch):
    if branch not in ("B0", "B1"):
        raise ValueError("invalid branch")


def write_branch(out_dir, cut):
    _branch(cut.branch)
    manifest = {"canary": _canary(), **{k: getattr(cut, k) for k in
                ("life", "branch", "world_hash", "schedule_sha256", "exclude_sha256", "render_key")},
                "stream_hash": stream_hash(cut.rows), "sessions_hash": sessions_hash(cut.sessions),
                "bank": {"bank_id": cut.bank_id, "sha256": cut.bank_sha256,
                         "calibrated": cut.bank_calibrated}, "estimator": ESTIMATOR,
                "session_ids": list(dict.fromkeys(row["session_id"] for row in cut.rows))}
    for name, data in (("stream", stream_bytes(cut.rows)), ("sessions", sessions_bytes(cut.sessions)),
                       ("history", canon(manifest))):
        suffix = "json" if name == "history" else "jsonl"
        with (Path(out_dir) / f"{name}.{cut.branch}.{suffix}").open("xb") as file:
            file.write(data)
    return manifest


def verify_branch(out_dir, branch):
    _branch(branch)
    try:
        raw = (Path(out_dir) / f"history.{branch}.json").read_bytes()
        manifest = json.loads(raw)
        if canon(manifest) != raw or manifest["branch"] != branch or manifest["canary"] != _canary():
            raise ValueError("invalid history manifest")
        for name in ("stream", "sessions"):
            raw = (Path(out_dir) / f"{name}.{branch}.jsonl").read_bytes()
            if sha256(raw).hexdigest() != manifest[f"{name}_hash"]:
                raise ValueError(f"{name} hash mismatch")
            for line in raw.splitlines(keepends=True):
                row = json.loads(line)
                validate("stream" if name == "stream" else "session", row)
                if canon(row) + b"\n" != line or (name == "stream" and
                                                        row["sha256"] != event_sha256(row)):
                    raise ValueError(f"invalid {name} row")
        return manifest
    except (OSError, KeyError, TypeError, UnicodeError) as error:
        raise ValueError("invalid branch cache") from error


def history_set_hash(manifests):
    history = {}
    for manifest in manifests:
        life, branch = manifest["life"], manifest["branch"]
        _branch(branch)
        branches = history.setdefault(life, {})
        if branch in branches:
            raise ValueError("duplicate life and branch")
        branches[branch] = {k: manifest[k] for k in
                            ("world_hash", "schedule_sha256", "stream_hash", "sessions_hash", "render_key")}
    for life in sorted(history):
        branches = history[life]
        if set(branches) != {"B0", "B1"} or (
                branches["B0"]["schedule_sha256"] != branches["B1"]["schedule_sha256"]):
            raise ValueError("incomplete twins or schedule mismatch")
    return sha256_canon({"history_set": history})
