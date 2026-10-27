"""Schema-stable masked digest; non-request records are excluded."""

import json
import re
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS

_SCHEMA = json.loads((SCHEMAS / "ledger-record.schema.json").read_bytes())
_MASKS = json.loads((Path(__file__).parents[1] / "contracts/masks.json").read_bytes())


def _visit(obj, tokens, entry):
    if not tokens:
        if isinstance(obj, str) and obj.startswith(entry.get("except_prefix", "\0")):
            return obj
        return entry["placeholder"]
    op, name = tokens[0]
    if isinstance(obj, dict):
        return {k: _visit(v, tokens[1:], entry) if k == name else
                _visit(v, tokens, entry) if op == ".." else v for k, v in obj.items()}
    if isinstance(obj, list):
        return [_visit(v, tokens[1:] if op == "[*]" else tokens, entry)
                if op in ("[*]", "..") else v for v in obj]
    return obj


def apply_masks(obj, run_values: dict[str, str]):
    """Return a canonical copy masked by K13; use before hashing request/response bodies."""
    if set(run_values) != {"sandbox_root", "director_port"} or any(
            not isinstance(v, str) or not v for v in run_values.values()):
        raise ValueError("run_values requires nonempty sandbox_root and director_port strings")
    obj = json.loads(canon(obj))
    for entry in _MASKS:
        if entry["kind"] == "jsonpath":
            tokens = [(op or "[*]", name) for op, name in
                      re.findall(r"(\.\.?)([A-Za-z_][A-Za-z0-9_]*)|\[\*\]", entry["target"])]
            obj = _visit(obj, tokens, entry)
    replacements = {run_values[e["target"]]: e["placeholder"]
                    for e in _MASKS if e["kind"] == "run_value"}
    pattern = re.compile("|".join(re.escape(v) for v in sorted(replacements, key=lambda v: (-len(v), v))))

    def replace(value):
        if isinstance(value, str):
            return pattern.sub(lambda m: replacements[m[0]], value)
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        return [replace(v) for v in value] if isinstance(value, list) else value

    return replace(obj)


def stable_digest(records: list[dict], run_values: dict[str, str]) -> str:
    stable = {k for k, p in _SCHEMA["properties"].items() if p["x-stability"] == "stable"}
    # The sha256 fields already cover masked bodies; masking them again would let a run value
    # (the port, say) that happens to occur inside a hex digest rewrite it.
    digests = {k for k in stable if _SCHEMA["properties"][k].get("pattern") == "^[0-9a-f]{64}$"}
    projected = [dict(apply_masks({k: v for k, v in rec.items() if k in stable - digests}, run_values),
                      **{k: rec[k] for k in digests if k in rec})
                 for rec in records if rec.get("type") == "request"]

    def order(rec):
        cursor = rec["cursor"]
        return (rec["life"], rec["branch"], (0, 0) if cursor is None else
                (cursor["session"], cursor["turn"]), rec["role"], rec["served_by"],
                rec["served"], sha256(canon(rec)).hexdigest())

    return sha256(canon(sorted(projected, key=order))).hexdigest()
