"""Check tracked public text for local paths, denied names and canaries."""

import argparse
import os
import re
import subprocess
from pathlib import Path

PATHS = re.compile(r"/(?:Users|home)/[^/\s]+/|/(?:Volumes)/[^/\s]+")  # home dirs and mounted volumes
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DATA_ROOTS = ("packs/", "corpus/", "schemas/fixtures/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", nargs="+", default=[])
    args = parser.parse_args()
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *args.paths],
        check=True, stdout=subprocess.PIPE,
    ).stdout
    paths = [os.fsdecode(path) for path in tracked.split(b"\0") if path]
    deny_file = os.environ.get("BICENTENNIAL_DENY_LIST")
    if deny_file is None:
        print("BICENTENNIAL_DENY_LIST unset; skipping deny-list check.")
        names = []
    else:
        names = [
            line.strip().casefold()
            for line in Path(deny_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    canary = None
    if any(path.startswith(DATA_ROOTS) for path in paths):
        try:
            match = GUID.search(Path("CANARY").read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match is None:
            print("CANARY:1: missing canary GUID")
            return 1
        canary = match.group()
    failed = False
    for path in paths:
        if path == "scripts/public_check.py":
            continue
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if PATHS.search(line):
                print(f"{path}:{number}: local filesystem path")
                failed = True
            if any(name in line.casefold() for name in names):
                print(f"{path}:{number}: deny-list name")
                failed = True
        if path.startswith(DATA_ROOTS) and canary not in text:
            print(f"{path}:1: missing canary GUID")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
