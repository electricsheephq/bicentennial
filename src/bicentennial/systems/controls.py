"""Wiped-store canary and the probe-only Hermes no-memory floor (S10)."""

import json
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.harness.hermes.adapter import HermesAdapter
from bicentennial.sandbox.surfaces import (
    clone_tree,
    surface_hash,
    verify_empty,
    wipe_to_fresh,
)
from bicentennial.systems.registry import REGISTRY, SystemRefused, check, load

CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
WIPED_LABEL = "positive control: must fail"
UNINFORMATIVE = "uninformative"
CONFIG_FILE = "config.yaml"
WAKE_REASONS = ("session_start", "kill", "restart")


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


class WipeOnWake:
    """One hook per arm/life/branch; snapshot before config, verify before every later spawn."""

    label = WIPED_LABEL

    def __init__(self, entry, roots: dict[str, Path], control_dir: Path):
        reasons = check(entry)
        if reasons:
            raise SystemRefused(reasons)
        if not entry["surfaces"]:
            raise ValueError("a wiped arm needs a surface")
        if any(s["root"] not in roots for s in entry["surfaces"]):
            raise ValueError("missing surface root")
        self._surfaces = json.loads(canon(entry["surfaces"]))
        self._dirs = tuple(Path(roots[s["root"]]) / s["relative"] for s in self._surfaces)
        self._control = Path(control_dir)
        self._records = []
        self.fresh_install_hashes = ()

    def _snapshot(self):
        # Validate every path before creating even the control directory.
        paths = [p.resolve() for p in self._dirs] + [self._control.resolve()]
        if self._control.exists() or self._control.is_symlink():
            raise ValueError("control directory already exists")
        if any(_overlap(a, b) for i, a in enumerate(paths) for b in paths[i + 1:]):
            raise ValueError("surfaces and control directory must be disjoint")
        for path, surface in zip(self._dirs, self._surfaces, strict=True):
            marker = path / ".bicentennial-sandbox"
            if path.is_symlink() or not path.is_dir() or marker.is_symlink() or not marker.is_file():
                raise ValueError("a real surface directory and regular sandbox marker are required")
            listing = tree_listing(path, surface["volatile_paths"])
            if surface["root"] == "HERMES_HOME" and surface["relative"] == ".":
                if {r["path"] for r in listing} != {".bicentennial-sandbox"} or (path / CONFIG_FILE).exists():
                    raise ValueError("Hermes must hold only its sandbox marker before the first spawn")
        self._control.mkdir(parents=True)
        hashes = []
        for i, (path, surface) in enumerate(zip(self._dirs, self._surfaces, strict=True)):
            snapshot = self._control / f"fresh-{i}"
            clone_tree(path, snapshot)
            digest = surface_hash(snapshot, surface["volatile_paths"])
            if surface_hash(path, surface["volatile_paths"]) != digest:
                raise ValueError("fresh snapshot differs from surface")
            hashes.append(digest)
        self.fresh_install_hashes = tuple(hashes)

    def __call__(self, reason) -> bool:
        if reason not in WAKE_REASONS:
            raise ValueError("unknown wake reason")
        wake = bool(self._records)
        if not wake:
            if reason != "session_start":
                raise ValueError("the first call must start a session")
            self._snapshot()
        rows = []
        for i, (path, surface) in enumerate(zip(self._dirs, self._surfaces, strict=True)):
            fresh = self.fresh_install_hashes[i]
            if wake:
                wipe_to_fresh(path, self._control / f"fresh-{i}")
                verify_empty(path, surface["volatile_paths"], fresh)
            rows.append({"root": surface["root"], "relative": surface["relative"],
                         "fresh_install_hash": fresh,
                         "post_wipe_hash": surface_hash(path, surface["volatile_paths"]) if wake else None})
        record = {"call": len(self._records) + 1, "reason": reason, "wake": wake, "surfaces": rows}
        canon(record)
        self._records.append(record)
        return wake

    def records(self) -> tuple:
        """Detached diagnostics for controls.json; never card.json or receipt.json."""
        return tuple(json.loads(canon(self._records)))


def no_memory_cell(**adapter_kwargs) -> HermesAdapter:
    """Build the Hermes floor; X02 caches its probe-only results once per pack."""
    if any(s["kind"] != "probe" for s in adapter_kwargs["script"]["sessions"]):
        raise ValueError("the no-memory cell is probe-only")
    return HermesAdapter(load(REGISTRY / "hermes-native.toml"), memory=False, before_spawn=None, **adapter_kwargs)


def control_status(wiped_gate: str, system_recall) -> str:
    if wiped_gate not in ("PASS", "CONFORMANCE_PASS", "FAIL"):
        raise ValueError("unknown wiped gate")
    if wiped_gate in ("PASS", "CONFORMANCE_PASS"):
        return "PASS"
    return "FAIL" if any(system_recall) else UNINFORMATIVE


def floor_mismatches(wiped, floor, crossing) -> tuple[str, ...]:
    def index(rows):
        result = {}
        for row in rows:
            validate("bundle_outcome", row)
            bid = row["bundle_id"]
            if bid in result:
                raise ValueError("duplicate bundle id")
            result[bid] = (row["score_milli"], row["failure_class"])
        return result

    wiped, floor, crossing = index(wiped), index(floor), set(crossing)
    if crossing - wiped.keys() or crossing - floor.keys():
        raise ValueError("crossing bundle missing from an arm")
    return tuple(sorted(bid for bid in crossing if wiped[bid] != floor[bid]))


def control_report(hooks, floor_mismatches) -> dict:
    report = {"canary": CANARY, "label": WIPED_LABEL, "wipes": [hook.records() for hook in hooks],
              "floor_mismatches": list(floor_mismatches)}
    canon(report)
    return report
