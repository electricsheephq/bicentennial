"""Read repository configuration."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
