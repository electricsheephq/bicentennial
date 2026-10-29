"""External allocated-byte accounting, excluding declared volatile subtrees."""

import stat
from pathlib import Path

from bicentennial.contracts.run import validate
from bicentennial.sandbox.surfaces import _directory, _walk

TIERS = {"K100": 100, "K30": 30, "K10": 10, "K3": 3}


def allocated_bytes(root, volatile_paths) -> int:
    """Sum st_blocks * 512 once per regular-file (device, inode)."""
    root, volatile = _directory(root), list(volatile_paths)
    for path in volatile:
        validate("surfaces", [{"path": path, "kind": "dir", "mode": 0}])
    total, seen = 0, set()
    for directory, dirs, files in _walk(root):
        for name in dirs[:] + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if any(relative == v or relative.startswith(v + "/") for v in volatile):
                if name in dirs:
                    dirs.remove(name)
                continue
            info = path.lstat()
            inode = info.st_dev, info.st_ino
            if stat.S_ISREG(info.st_mode) and inode not in seen:
                total += info.st_blocks * 512
                seen.add(inode)
    return total


def store_bytes(root, baseline, volatile_paths) -> int:
    """Subtract the empty-store baseline, floored at zero."""
    return max(0, allocated_bytes(root, volatile_paths) - baseline)


def over_tier(store_bytes, raw_bytes, tier) -> bool:
    """Compare baseline-subtracted store bytes to an exact raw-byte percentage."""
    if tier not in TIERS:
        raise ValueError(f"unknown Keep tier: {tier}")
    return 100 * store_bytes > TIERS[tier] * raw_bytes


def apply_budget(store_bytes, cap_bytes, cap_label):
    """Apply an explicit byte cap for a Keep tier; equality is within the cap."""
    if cap_label not in TIERS:
        raise ValueError(f"unknown Keep tier: {cap_label}")
    return store_bytes > cap_bytes
