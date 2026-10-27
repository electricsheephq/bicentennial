"""Command line entry point for offline developer runs."""

import argparse
import os
import sys

from bicentennial.runner.compare import run_t1
from bicentennial.runner.guard import reexec_niced
from bicentennial.runner.t0 import run_t0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(3, f"usage: {message}\n")


def _workers(value):
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("workers must be an integer") from None
    if result < 1:
        raise argparse.ArgumentTypeError("workers must be positive")
    return result


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _Parser(prog="bicentennial")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("t0")
    command.add_argument("--system", required=True)
    command.add_argument("--pack", dest="packs", action="append", required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    command.add_argument("--pack-hash", required=True)
    command.add_argument("--out", required=True)
    command.add_argument("--mode", choices=("api", "hermes"), default="api")
    command.add_argument("--workers", type=_workers, default=1)
    for name in ("hermes", "plugin-source", "cache"):
        command.add_argument("--" + name)
    command = commands.add_parser("t1")
    for name in ("system", "pack-hash", "out"):
        command.add_argument("--" + name, required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    for name in ("baseline", "hermes", "plugin-source", "cache"):
        command.add_argument("--" + name)
    args = vars(parser.parse_args(argv))
    selected = args.pop("command")
    if os.environ.get("PYTHONHASHSEED") != "0":
        print("hashseed", file=sys.stderr)
        return 3
    reexec_niced(["-m", "bicentennial.cli", *argv])
    return run_t0(**args) if selected == "t0" else run_t1(**args)


if __name__ == "__main__":
    raise SystemExit(main())
