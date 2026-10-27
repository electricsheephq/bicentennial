"""Offline system selection; unmeasured pins are declarations, never runnable."""

import os
import re
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath

from bicentennial.contracts.run import validate

# Provisional OSI allow-list for C-9 selection (pending), not a final roster decision.
PROVISIONAL_OSI_LICENCES = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "MPL-2.0", "ISC",
    "GPL-2.0-only", "GPL-3.0-only", "LGPL-2.1-only", "LGPL-3.0-only", "AGPL-3.0-only",
})
REGISTRY = Path(__file__).resolve().parents[3] / "systems" / "registry"
ZERO_HASH = "0" * 64
_ENV_OPERATOR = object()
_TAG = re.compile(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z.-]+)?")
_ALIAS = re.compile(r"bicentennial-[a-z0-9-]+")


class SystemRefused(ValueError):
    """A declaration failed the runner gate; reasons are stable machine labels."""

    def __init__(self, reasons):
        self.reasons = tuple(reasons)
        super().__init__(", ".join(self.reasons))


def _read(path):
    with open(path, "rb") as stream:
        entry = tomllib.load(stream)
    for key in ("recall", "embedding_dim"):
        entry.setdefault(key, None)
    return entry


def load(path) -> dict:
    """Read TOML, supply absent nullable keys, and enforce K13's system contract."""
    entry = _read(path)
    validate("system", entry)
    return entry


def _placeholder(value):
    if isinstance(value, str):
        remaining = value.replace("{prompt}", "")
        return "{" in remaining or "}" in remaining
    if isinstance(value, dict):
        return any(_placeholder(k) or _placeholder(v) for k, v in value.items())
    return isinstance(value, list) and any(_placeholder(v) for v in value)


def check(entry) -> list[str]:
    """Return ordered, deduplicated policy refusals, or schema_invalid as fallback."""
    if not isinstance(entry, dict):
        return ["schema_invalid"]
    reasons = []
    artifact = entry.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    if not isinstance(entry.get("licence"), str) or entry["licence"] not in PROVISIONAL_OSI_LICENCES:
        reasons.append("licence_not_osi")
    version, digest = artifact.get("version"), artifact.get("sha256")
    if (not isinstance(version, str) or not _TAG.fullmatch(version)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        reasons.append("artifact_unpinned")
    routes = entry.get("own_model_routes", [])
    if isinstance(routes, list) and any(
        not isinstance(r, dict) or not isinstance(r.get("alias"), str)
        or not _ALIAS.fullmatch(r["alias"]) for r in routes
    ):
        reasons.append("route_unroutable")
    surfaces = entry.get("surfaces", [])
    bad_path = False
    if isinstance(surfaces, list):
        for surface in surfaces:
            path = surface.get("relative") if isinstance(surface, dict) else None
            if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                    or PureWindowsPath(path).is_absolute() or "\\" in path
                    or ".." in PurePosixPath(path).parts):
                bad_path = True
    if bad_path or ((entry.get("write_tools") or routes) and not surfaces):
        reasons.append("state_path_undeclared")
    recall = entry.get("recall")
    if isinstance(recall, dict) and _placeholder(recall.get("argument_template")):
        reasons.append("recall_placeholder")
    try:
        validate("system", entry)
    except ValueError:
        if not reasons:
            reasons.append("schema_invalid")
    return reasons


def unmeasured(entry) -> list[str]:
    """Name pins that still need measurement, in stable display order."""
    return [field for field, value in (
        ("artifact.sha256", entry.get("artifact", {}).get("sha256")),
        ("fresh_install_hash", entry.get("fresh_install_hash")),
    ) if value == ZERO_HASH]


def admit_system(entry, operator=_ENV_OPERATOR) -> None:
    """Refuse before running; an omitted operator is read from the current environment."""
    if operator is _ENV_OPERATOR:
        operator = os.environ.get("BICENTENNIAL_OPERATOR")
    reasons = check(entry)
    if isinstance(entry, dict):
        if entry.get("benchmark_operator_runs") is False and operator == "benchmark":
            reasons.append("benchmark_operator_forbidden")
        if "schema_invalid" not in reasons and isinstance(entry.get("artifact"), dict):
            reasons.extend("unmeasured:" + field for field in unmeasured(entry))
    if reasons:
        raise SystemRefused(reasons)
