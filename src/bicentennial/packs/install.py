"""Read-only pack installation and pin verification."""

import argparse
import json
import os
import shutil
import stat
import sys
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.controls.cache import (
    CONTROL_FILES,
    PACKAGE_ROOT,
    READER_FILES,
    ControlsTampered,
    code_sha256,
)
from bicentennial.packs.manifest import PinnedArtifactChanged, tree_sha256
from bicentennial.packs.scoring import SCORING_FILES
from bicentennial.runner.lock import LockMismatch, verify_lock


def _inventory(root):
    """Take one inventory, descending only into lstat-confirmed directories."""
    modes, files, payloads = {}, {}, {}
    pending = [root]
    while pending:
        path = pending.pop()
        rel = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        modes[rel] = mode
        try:
            if stat.S_ISDIR(mode):
                pending.extend(reversed(sorted(path.iterdir())))
            elif stat.S_ISREG(mode):
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                    data = stream.read()
                files[rel] = dict(size=len(data), sha256=sha256(data).hexdigest())
                if path.suffix == ".json":
                    payloads[rel] = data
        except OSError:
            if stat.S_ISREG(mode):
                files[rel] = dict(size=None, sha256=None)
    return modes, files, payloads


def _remove(root):
    for path in [root, *sorted(root.rglob("*"))]:
        path.chmod(path.lstat().st_mode | stat.S_IWUSR)
    shutil.rmtree(root)


def install(src, dest) -> str:
    src, dest = Path(src), Path(dest)
    if os.path.lexists(dest):
        raise FileExistsError(dest)
    modes, _, _ = _inventory(src)
    if not stat.S_ISDIR(modes["."]):
        raise ValueError("tree_root")
    for rel in sorted(modes):
        if not (stat.S_ISDIR(modes[rel]) or stat.S_ISREG(modes[rel])):
            raise ValueError(rel)
    dest.mkdir()
    try:
        for rel in sorted(modes):
            if rel == ".":
                continue
            if stat.S_ISDIR(modes[rel]):
                (dest / rel).mkdir()
            else:
                shutil.copyfile(src / rel, dest / rel)
        for rel in sorted(modes, key=lambda r: (len(Path(r).parts), r), reverse=True):
            (dest / rel).chmod(0o555 if stat.S_ISDIR(modes[rel]) else 0o444)
        digest = tree_sha256(dest)
        if digest != tree_sha256(src):
            raise PinnedArtifactChanged(("pack_hash",))
        return digest
    except BaseException:
        _remove(dest)
        raise


def verify(root, *, pack_hash, package_root=PACKAGE_ROOT, lock=None, expected_lock=None) -> dict:
    modes, files, payloads = _inventory(Path(root))
    failures = set()
    for rel in sorted(modes):
        mode = modes[rel]
        expected = 0o444 if stat.S_ISREG(mode) else 0o555 if stat.S_ISDIR(mode) else None
        if stat.S_IMODE(mode) != expected:
            failures.add(f"mode:{rel}")

    def load(rel):
        try:
            value = json.loads(payloads[rel])
            canon(value)
            if isinstance(value, dict):
                return value
        except (KeyError, ValueError, TypeError, RecursionError):
            pass
        failures.add(rel)
        return {}

    def mapping(obj, key, rel):
        value = obj.get(key, {})
        if not isinstance(value, dict):
            failures.add(rel)
            return {}
        return value

    index = load("index.json")
    manifests = []
    for rel in sorted(mapping(index, "packs", "index.json")):
        manifest = load(f"{rel}/manifest.json")
        expected = mapping(manifest, "files", f"{rel}/manifest.json")
        actual = {p[len(rel) + 1:]: files[p] for p in sorted(files)
                  if p.startswith(rel + "/") and p != f"{rel}/manifest.json"}
        for name in sorted(actual.keys() | expected.keys()):
            if actual.get(name) != expected.get(name):
                failures.add(f"{rel}/{name}")
        manifests.append((rel, manifest))
    digest = sha256_canon([[p, files[p]["size"], files[p]["sha256"]] for p in sorted(files)])
    if digest != pack_hash or any(not (stat.S_ISREG(modes[p]) or stat.S_ISDIR(modes[p]))
                                  for p in sorted(modes)):
        failures.add("pack_hash")
    for rel, manifest in manifests:
        scoring = load(f"{rel}/sealed/scoring.json")
        if sha256_canon(scoring) != mapping(manifest, "pins", f"{rel}/manifest.json").get("scoring_sha256"):
            failures.add("scoring_sha256")
    package_root = Path(package_root)
    scorer = [p.relative_to(package_root).as_posix()
              for p in sorted((package_root / "score").glob("*.py"))]
    pins = mapping(index, "pins", "index.json")
    for name, paths in (("scorer_sha256", scorer), ("controls_sha256", CONTROL_FILES),
                        ("reader_sha256", READER_FILES), ("scoring_code_sha256", SCORING_FILES)):
        try:
            if code_sha256(paths, root=package_root) == pins.get(name):
                continue
        except OSError:
            pass
        failures.add(name)
    if sha256_canon(index.get("harness_artifacts")) != pins.get("harness_pin"):
        failures.add("harness_pin")
    if lock is not None:
        verify_lock(expected_lock, lock)
        if lock.get("pack_hash") != pack_hash:
            failures.add("pack_hash")
        if sha256_canon(lock.get("harness_artifacts")) != pins.get("harness_pin"):
            failures.add("harness_pin")
    if failures:
        raise PinnedArtifactChanged(failures)
    return index


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(3, f"{self.prog}: error: {message}\n")


def main(argv=None):
    if os.environ.get("PYTHONHASHSEED") != "0":
        print("hashseed", file=sys.stderr)
        return 3
    parser = _Parser()
    commands = parser.add_subparsers(dest="command", required=True)
    copying = commands.add_parser("install")
    copying.add_argument("src")
    copying.add_argument("dest")
    checking = commands.add_parser("verify")
    checking.add_argument("root")
    checking.add_argument("--pack-hash", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            print(install(args.src, args.dest))
        else:
            verify(args.root, pack_hash=args.pack_hash)
    except (PinnedArtifactChanged, LockMismatch, ControlsTampered) as error:
        print(error.code, file=sys.stderr)
        return 3
    except (OSError, ValueError):
        print("refused", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
