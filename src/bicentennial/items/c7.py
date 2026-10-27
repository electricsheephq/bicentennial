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

GENRES = ("g1", "g2")
FREEZE = "specs/ring0/c7-partial.json"
_CELL_ROW = re.compile(r"\| ([A-Z]+-[A-Z]+) \| (\w+) \|[^|]*\| ([A-Z])(?: \([^|)]*\))? \|[^|]*\|[^|]*\| ([^|]+) \|")
_CELL_ID = re.compile(r"\| [A-Z]+-[A-Z]+ \|")


def cells(root) -> dict:
    """Each cell's track, stage and primary lever, from docs/inventory/CELLS-v0.md."""
    rows = {}
    for line in (Path(root) / "docs/inventory/CELLS-v0.md").read_text(encoding="utf-8").splitlines():
        if m := _CELL_ROW.match(line):
            rows[m[1]] = {"track": m[2], "stage": m[3], "primary_lever": m[4].strip()}
        elif _CELL_ID.match(line):
            raise ValueError(f"unparsed cell row: {line[:40]}")
    return rows


def entry(template, genre, cell_rows) -> dict:
    """One template's entry, with entry_sha256 over the canonical entry without that field."""
    cell = cell_rows[template.cell_id]
    body = json.loads(json.dumps({
        "ref": template.ref, "genre": genre, "cell_id": template.cell_id,
        "direction": template.direction, "kind": template.kind,
        "decision_tables": list(template.decision_tables),
        "template": {f.name: getattr(template, f.name) for f in dataclasses.fields(template)},
        "class": f"{type(template).__module__}.{type(template).__qualname__}",
        "class_source_sha256": sha256(Path(inspect.getsourcefile(type(template))).read_bytes()).hexdigest(),
        "cell": cell,
        "lever_mix": {"primary": cell["primary_lever"], "value": "uncalibrated (v0.2)",
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
