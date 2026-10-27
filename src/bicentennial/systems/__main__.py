"""Check declarations without installing or running a system."""

import argparse

from .registry import REGISTRY, _read, check, unmeasured


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    paths = args.paths or sorted(REGISTRY.glob("*.toml"))
    if not paths:
        print("registry: REFUSED registry_empty")
        return 1
    refused = False
    for path in paths:
        try:
            entry = _read(path)
        except (OSError, ValueError):
            print("entry: REFUSED entry_unreadable")
            refused = True
            continue
        reasons = check(entry)
        pending = [] if reasons else unmeasured(entry)
        status = ("REFUSED " + " ".join(reasons) if reasons else
                  "UNMEASURED " + " ".join(pending) if pending else "ok")
        print(f"{entry.get('name', 'entry')}: {status}")
        refused |= bool(reasons)
    return int(refused)


if __name__ == "__main__":
    raise SystemExit(main())
