"""The partial C-7 freeze: each v0.1 template's frozen entry, built from the template build.

``python -m bicentennial.items.c7 REPO_ROOT`` prints ``specs/ring0/c7-partial.json``.
"""

import dataclasses
import importlib
import inspect
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import sha256_canon
from bicentennial.items.protocol import CANARY
from bicentennial.items.templates.g1.common import PRIMARY_LEVER

GENRES = ("g1", "g2")
FREEZE = "specs/ring0/c7-partial.json"
_CELL_ROW = re.compile(r"\| ([A-Z]+-[A-Z]+) \| (\w+) \|[^|]*\| ([A-Z])(?: \([^|)]*\))? \|[^|]*\|[^|]*\| ([^|]+) \|")
_CELL_ID = re.compile(r"\| [A-Z]+-[A-Z]+ \|")
# The levers.LEVERS key of each v0.1 cell's primary lever; G1's own map, extended to the G2 cells.
PRIMARY_KEY = {**PRIMARY_LEVER, "DRIFT-ASOF": "chain_depth", "KEEP-FORGET": "distance_sessions",
               "KEEP-INC": "salience", "KEEP-NEIGH": "interference", "RECALL-AGG": None}
PACKAGE = Path(__file__).resolve().parents[1]


def cells(root) -> dict:
    """Each cell's track, stage and primary lever, from docs/inventory/CELLS-v0.md."""
    rows = {}
    for line in (Path(root) / "docs/inventory/CELLS-v0.md").read_text(encoding="utf-8").splitlines():
        if m := _CELL_ROW.match(line):
            rows[m[1]] = {"track": m[2], "stage": m[3], "primary_lever": m[4].strip()}
        elif _CELL_ID.match(line):
            raise ValueError(f"unparsed cell row: {line[:40]}")
    return rows


def source_sha256(path) -> str:
    """sha256 of a source file with CRLF line endings read as LF, so a checkout's line endings never change it."""
    return sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sources(cls) -> dict:
    """The sha256 of every package source file that defines a class in the template's MRO."""
    files = {Path(inspect.getsourcefile(c)).resolve() for c in cls.__mro__ if c.__module__.startswith("bicentennial.")}
    return {f.relative_to(PACKAGE).as_posix(): source_sha256(f) for f in sorted(files)}


def entry(template, genre, cell_rows) -> dict:
    """One template's entry, with entry_sha256 over the canonical entry without that field."""
    cell = cell_rows[template.cell_id]
    body = json.loads(json.dumps({
        "ref": template.ref, "genre": genre, "cell_id": template.cell_id,
        "direction": template.direction, "kind": template.kind,
        "decision_tables": list(template.decision_tables),
        "template": {f.name: getattr(template, f.name) for f in dataclasses.fields(template)},
        "class": f"{type(template).__module__}.{type(template).__qualname__}",
        "class_source_sha256": source_sha256(Path(inspect.getsourcefile(type(template)))),
        "source_sha256": sources(type(template)),
        "cell": cell,
        "lever_mix": {"primary": cell["primary_lever"], "primary_key": PRIMARY_KEY[template.cell_id],
                      "value": "uncalibrated (v0.2)", "template": getattr(template, "lever_mix", None),
                      "other_levers": "not neutralised at v0.1; computed per item into each item's levers"},
    }))
    return {**body, "entry_sha256": sha256_canon(body)}


def freeze(root) -> dict:
    """The whole freeze object for every template of every genre, keyed by template ref."""
    cell_rows, entries = cells(root), {}
    for genre in GENRES:
        for template in importlib.import_module(f"bicentennial.items.templates.{genre}").TEMPLATES:
            if template.ref in entries:
                raise ValueError(f"duplicate template ref {template.ref}")
            entries[template.ref] = entry(template, genre, cell_rows)
    entries = dict(sorted(entries.items()))
    return {"canary": CANARY, "slot": "C-7", "status": "partial, provisional (Ring 0 v0.1)",
            "keyed_by": "template ref (template_id-vN)",
            "entry_hash": "sha256 of the canonical JSON (sorted keys, no spaces) of the entry without entry_sha256",
            "entries": entries, "file_sha256_of_entries": sha256_canon(entries)}


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    sys.stdout.write(dumps(freeze(sys.argv[1] if len(sys.argv) > 1 else ".")))
