"""Print the system preparation pins without opening a live stack or sending."""

import argparse
import sys
from hashlib import sha256
from pathlib import Path

from bicentennial.runner import t1
from bicentennial.runner.units import T2_SPEC, refusal_code
from bicentennial.systems.registry import REGISTRY


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise t1.T1Refused("usage")


def main(argv=None, *, prepare=t1.prepare):
    parser = Parser(description=__doc__)
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--pack-hash", required=True)
    parser.add_argument("--hermes", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        ctx = prepare(
            system="hermes-native",
            packs=args.packs,
            pack_hash=args.pack_hash,
            hermes=args.hermes,
            spec=T2_SPEC,
            control=False,
            turn_wait_s=3.0,
        )
        registry_hash = sha256(
            (REGISTRY / "hermes-native.toml").read_bytes()
        ).hexdigest()
        lines = [("registry_entry_sha256", registry_hash)]
        lines.extend(
            (name, ctx.pins[name])
            for name in (
                "system_hash",
                "harness_hash",
                "route_table_hash",
                "benchmark_commit",
            )
        )
    except t1.REFUSALS as error:
        print(refusal_code(error))
        return 3
    for name, value in lines:
        print(name, value)
    print("prepared: system run accepted; nothing sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
