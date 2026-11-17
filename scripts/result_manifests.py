#!/usr/bin/env python3
"""Derive result manifests from published pages and check their artifact bytes."""

import argparse
import json
import os
import re
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "RESULT-MANIFEST.json"
SCHEMA = "bicentennial-result-manifest/1"
LEGACY = frozenset({"bicentennial-v0.1-result/1"})  # The v0.1 kit's own manifests, kept byte for byte.
INDEX = "results/MANIFEST-INDEX.json"
# Generated files the repository's .gitignore keeps out of git; running a page's own tests can create them.
GENERATED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})
GENERATED_FILES = frozenset({".DS_Store"})
GENERATED_SUFFIXES = (".pyc", ".pyo")


def generated(name):
    return name in GENERATED_FILES or name.endswith(GENERATED_SUFFIXES)


def byte_order(path):
    return path.as_posix().encode("utf-8")


def collapsed(text):
    return " ".join(text.split())


def page_fields(page):
    lines = page.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("page must start with a title beginning '# '")
    start = next((i for i, line in enumerate(lines) if line.startswith("Claim class:")), None)
    if start is None:
        raise ValueError("page lacks a line starting 'Claim class:'")
    claim = [lines[start][len("Claim class:"):]]
    for line in lines[start + 1:]:
        if not line.strip() or re.match(r"^#{1,6}(?:\s|$)", line):
            break
        claim.append(line)
    items = []
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("## What this does not prove")), None)
    if start is not None:
        for line in lines[start + 1:]:
            if re.match(r"^#{1,2}(?:\s|$)", line):
                break
            if not line.strip():
                continue
            bullet = re.match(r"^[-*+]\s+(.+)$", line)
            if bullet:
                items.append(bullet.group(1))
            elif items and line[:1].isspace():
                items[-1] += " " + line.strip()
            else:
                raise ValueError("'What this does not prove' must be a bullet list")
        if not items:
            raise ValueError("'What this does not prove' must be a bullet list")
    return dict(title=lines[0][2:], claim_class=collapsed(" ".join(claim)),
                does_not_prove=[collapsed(item) for item in items])


def derived(folder):
    """Derive only page/folder fields; backfilled is retained provenance."""
    fields = page_fields(folder / "RESULT.md")
    date = re.match(r"^\d{4}-\d{2}-\d{2}", folder.name)
    if date is None:
        raise ValueError("result folder must start with YYYY-MM-DD")
    paths = []
    for directory, dirs, files in os.walk(folder):
        base = Path(directory)
        dirs[:] = [name for name in dirs
                   if name not in GENERATED_DIRS and not (base / name / "RESULT.md").is_file()]
        paths.extend(base / name for name in files if name != MANIFEST and not generated(name))
    artifacts = []
    for path in sorted(paths, key=lambda p: byte_order(p.relative_to(folder))):
        content = path.read_bytes()
        artifacts.append(dict(path=path.relative_to(folder).as_posix(),
                              sha256=sha256(content).hexdigest(), bytes=len(content)))
    return dict(schema=SCHEMA, page="RESULT.md", **fields, published=date.group(),
                release=folder.parent.name, artifacts=artifacts)


def manifest_paths(root):
    return sorted((root / "results").rglob(MANIFEST), key=lambda p: byte_order(p.relative_to(root)))


def index_bytes(root):
    entries = [dict(path=path.relative_to(root).as_posix(), sha256=sha256(path.read_bytes()).hexdigest())
               for path in manifest_paths(root)]
    lines = "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries)
    return canon(dict(schema="bicentennial-result-index/1", manifests=entries,
                      combined_sha256=sha256(lines.encode("utf-8")).hexdigest()))


def load(path):
    return json.loads(path.read_bytes())


def check(root):
    problems = []
    for page in sorted((root / "results").rglob("RESULT.md"), key=byte_order):
        if not page.with_name(MANIFEST).is_file():
            problems.append(f"{page.relative_to(root)}: missing {MANIFEST}")
    for path in manifest_paths(root):
        label = path.relative_to(root).as_posix()
        if not path.with_name("RESULT.md").is_file():
            problems.append(f"{label}: missing RESULT.md")
        try:
            value = load(path)
            if not isinstance(value, dict):
                problems.append(f"{label}: manifest must be a JSON object")
                continue
            schema = value.get("schema")
            if not isinstance(schema, str) or schema not in LEGACY | {SCHEMA}:
                problems.append(f"{label}: unknown schema {schema!r}")
                continue
            if schema in LEGACY:
                continue  # A legacy kit manifest is indexed without interpreting its page or fields.
            if path.read_bytes() != canon(value):
                problems.append(f"{label}: not canonical JSON; run refresh")
            expected = derived(path.parent)
            different = [key for key, data in expected.items()
                         if key not in value or canon(value[key]) != canon(data)]
            if type(value.get("backfilled")) is not bool:
                different.append("backfilled")
            if different:
                problems.append(f"{label}: derived fields differ: {', '.join(different)}")
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f"{label}: {collapsed(str(exc))}")
    try:
        if (root / INDEX).read_bytes() != index_bytes(root):
            problems.append(f"{INDEX}: stale index")
    except (OSError, ValueError, TypeError) as exc:
        problems.append(f"{INDEX}: {collapsed(str(exc))}")
    return problems


def backfill(root):
    pending = []
    for page in sorted((root / "results").rglob("RESULT.md"), key=byte_order):
        path = page.with_name(MANIFEST)
        if not path.exists():
            pending.append((path, canon(dict(**derived(page.parent), backfilled=True))))
    for path, content in pending:
        with path.open("xb") as stream:
            stream.write(content)


def refresh(root, folder):
    folder = (root / folder).resolve()
    if not folder.is_relative_to((root / "results").resolve()):
        raise ValueError("refresh folder must be under results/")
    path = folder / MANIFEST
    value = load(path)
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("refresh requires an existing v1 manifest; legacy manifests are never rewritten")
    path.write_bytes(canon(value | derived(folder)))


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "backfill", "index"):
        commands.add_parser(name)
    commands.add_parser("refresh").add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            problems = check(root)
            for problem in problems:
                print(problem)
            return int(bool(problems))
        if args.command == "backfill":
            backfill(root)
        elif args.command == "refresh":
            refresh(root, args.folder)
        else:
            (root / INDEX).write_bytes(index_bytes(root))
    except (OSError, ValueError, TypeError) as exc:
        print(collapsed(str(exc)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
