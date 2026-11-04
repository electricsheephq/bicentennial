"""Temporary probe for #458, not for merge: what a T1 pack build writes on this platform."""

import json
import os
import platform
import sqlite3
import sys
from hashlib import sha256

from bicentennial.packs import build, manifest
from bicentennial.systems.registry import REGISTRY, load


def _dump(tag, value):
    print(f"platform_probe {tag}=" + json.dumps(value, sort_keys=True))


def _tree(root):
    files = manifest.file_manifest(root)
    return {rel: files[rel]["sha256"] for rel in sorted(files)}


def _db(root):
    out = {}
    for path in sorted(root.rglob("*.db")):
        raw = path.read_bytes()
        pages = [sha256(raw[i:i + 4096]).hexdigest()[:16] for i in range(0, len(raw), 4096)]
        out[path.relative_to(root).as_posix()] = dict(size=len(raw), header=raw[:100].hex(), pages=pages)
    return out


def test_platform_probe(tmp_path):
    mask = os.umask(0)
    os.umask(mask)
    _dump("env", dict(platform=sys.platform, python=sys.version, sqlite=sqlite3.sqlite_version,
                      machine=platform.machine(), umask=oct(mask), fsenc=sys.getfilesystemencoding(),
                      lang=os.environ.get("LANG"), tz=os.environ.get("TZ")))
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    runs = []
    for n in (1, 2):
        result = build.build_tier("T1", tmp_path / f"b{n}", harness_artifacts=[artifact])
        root = tmp_path / f"b{n}" / "T1"
        runs.append(dict(index=result["index"],
                         trees={rel: _tree(root / rel) for rel in result["index"]["packs"]}))
    _dump("t1_index", runs[0]["index"])
    _dump("t1_trees", runs[0]["trees"])
    _dump("t1_same_twice", runs[0] == runs[1])
    root = tmp_path / "b1" / "T1"
    _dump("t1_db", {rel: _db(root / rel) for rel in runs[0]["index"]["packs"]})
    raise AssertionError("probe output is printed above")


def test_zz_secure_delete_off(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def off(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.execute("PRAGMA secure_delete=OFF")
        return db

    monkeypatch.setattr(sqlite3, "connect", off)
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    result = build.build_tier("T1", tmp_path / "off", harness_artifacts=[artifact])
    print("secure_delete_off_t1=" + result["pack_hash"])
    raise AssertionError("printed above")
