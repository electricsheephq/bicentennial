"""Command line entry point for offline developer runs."""

import argparse
import os
import subprocess
import sys
import traceback
from pathlib import Path

from bicentennial.gitenv import git_env

# The runners load schema-backed contracts at import, so they load only after the source-checkout check.
REPO = Path(__file__).resolve().parents[2]


def reexec_niced(argv):
    from bicentennial.runner.guard import reexec_niced as reexec
    return reexec(argv)


def run_t0(**kwargs):
    from bicentennial.runner.t0 import run_t0 as run
    return run(**kwargs)


def run_t1(**kwargs):
    from bicentennial.runner.compare import run_t1 as run
    return run(**kwargs)


def run_t2lite(**kwargs):
    from bicentennial.runner.t2lite import run_t2lite as run
    return run(**kwargs)


def run_t2(**kwargs):
    from bicentennial.runner.t2 import run_t2 as run
    return run(**kwargs)


def _only(value):
    parts = value.split(":")
    if (len(parts) != 3 or not parts[0] or parts[1] not in ("B0", "B1")
            or not parts[2].isdigit() or int(parts[2]) < 1):
        raise argparse.ArgumentTypeError("only must be LIFE:B0|B1:CHECKPOINT")
    return parts[0], parts[1], int(parts[2])


def _turn_wait(value):
    from bicentennial.harness.hermes.adapter import turn_wait_seconds
    return turn_wait_seconds(value)


def _sends(value):
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("max-sends must be non-negative")
    return result


def run_build(*, tier, out):
    try:
        from bicentennial.packs.build import build_tier
        from bicentennial.systems.registry import REGISTRY, load
        result = build_tier(tier, out, harness_artifacts=[load(REGISTRY / "hermes-native.toml")["artifact"]])
        print(f"sqlite_version {result['sqlite_version']}", file=sys.stderr)
    except FileExistsError:
        print("out_exists", file=sys.stderr)
        return 3
    except Exception:
        # Match runner.t0.run_t0's unexpected-failure convention.
        print("tool_failure", file=sys.stderr)
        traceback.print_exc()
        return 70
    return 0


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


def _source_checkout(root) -> bool:
    if not (root / "schemas").is_dir() or not (root / "pyproject.toml").is_file():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, env=git_env(),
        )
        return result.returncode != 0 or os.path.samefile(result.stdout.strip(), root)
    except OSError:
        return True


def _selection(command):
    group = command.add_mutually_exclusive_group(required=True)
    group.add_argument("--system")
    group.add_argument("--entry", type=Path)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not _source_checkout(REPO):
        print("source_checkout_required", file=sys.stderr)
        return 3
    parser = _Parser(prog="bicentennial")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("t0")
    _selection(command)
    command.add_argument("--pack", dest="packs", action="append", required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    command.add_argument("--pack-hash", required=True)
    command.add_argument("--out", required=True)
    command.add_argument("--mode", choices=("api", "hermes"), default="api")
    command.add_argument("--workers", type=_workers, default=1)
    command.add_argument("--sandbox-slot", type=int, default=0)
    for name in ("hermes", "plugin-source", "model-cache", "cache"):
        command.add_argument("--" + name)
    command = commands.add_parser("t1")
    _selection(command)
    for name in ("pack-hash", "out"):
        command.add_argument("--" + name, required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    for name in ("baseline", "hermes", "plugin-source", "model-cache", "cache"):
        command.add_argument("--" + name)
    command.add_argument("--sandbox-slot", type=int, default=0)
    command.add_argument("--turn-wait", dest="turn_wait_s", type=_turn_wait, default=3.0, metavar="SECONDS")
    command = commands.add_parser("t2lite")
    _selection(command)
    for name in ("pack-hash", "out", "login-home"):
        command.add_argument("--" + name, required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    command.add_argument("--max-sends", type=_sends, required=True)
    for name in ("baseline", "aa-of", "aa-prime", "hermes", "plugin-source", "model-cache", "cache"):
        command.add_argument("--" + name)
    command.add_argument("--sandbox-slot", type=int, default=0)
    command.add_argument("--turn-wait", dest="turn_wait_s", type=_turn_wait, default=3.0, metavar="SECONDS")
    command.add_argument("--only", type=_only)
    command.add_argument("--repeat", type=_workers, default=1)
    command = commands.add_parser("t2")
    _selection(command)
    for name in ("pack-hash", "out", "login-home"):
        command.add_argument("--" + name, required=True)
    command.add_argument("--packs", dest="packs_dir", required=True)
    command.add_argument("--max-sends", type=_sends, required=True)
    for name in ("hermes", "plugin-source", "model-cache", "cache"):
        command.add_argument("--" + name)
    command.add_argument("--sandbox-slot", type=int, default=0)
    command.add_argument("--turn-wait", dest="turn_wait_s", type=_turn_wait, default=3.0, metavar="SECONDS")
    command = commands.add_parser("build")
    command.add_argument("--tier", choices=("T0", "T1", "T2"), required=True)
    command.add_argument("--out", required=True)
    command = commands.add_parser("pins")
    _selection(command)
    command.add_argument("--hermes")
    command.add_argument("--plugin-source")
    command.add_argument("--sandbox-slot", type=int, default=0)
    args = vars(parser.parse_args(argv))
    selected = args.pop("command")
    if os.environ.get("PYTHONHASHSEED") != "0":
        print("hashseed", file=sys.stderr)
        return 3
    reexec_niced(["-m", "bicentennial.cli", *argv])
    # Only commands that select a system have --entry; build has neither.
    path = args.pop("entry", None)
    if path is not None:
        from bicentennial.systems.registry import SystemRefused, load_entry

        try:
            entry = load_entry(path)
        except SystemRefused as error:
            print(*error.reasons, file=sys.stderr)
            return 3
        args.update(system=entry["name"], entry=entry)
    if selected == "t0":
        return run_t0(**args)
    if selected == "t1":
        return run_t1(**args)
    if selected == "t2lite":
        return run_t2lite(**args)
    if selected == "t2":
        return run_t2(**args)
    if selected == "pins":
        from bicentennial.systems.pins import run_pins
        return run_pins(**args)
    return run_build(**args)


if __name__ == "__main__":
    raise SystemExit(main())
