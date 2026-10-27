"""Module-only build-time tool-call check."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.harness.hermes.adapter import PinMismatch
from bicentennial.systems.registry import SystemRefused, load

from .check import check_compile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check-compile"])
    parser.add_argument("life_dir", type=Path)
    for flag in ("checkout", "harness-pin", "entry", "route-table", "scratch"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--step-s", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        report = check_compile(args.life_dir, entry=load(args.entry),
            route_table=json.loads(args.route_table.read_bytes()), harness_pin=json.loads(args.harness_pin.read_bytes()),
            checkout=args.checkout, scratch=args.scratch, step_s=args.step_s)
    except PinMismatch:
        return 3
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, SystemRefused):
        return 2
    sys.stdout.buffer.write(canon(report) + b"\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
