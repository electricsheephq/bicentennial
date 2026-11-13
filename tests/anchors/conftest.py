"""One offline public T2 life; builder and all four pins stay unchanged."""

from pathlib import Path

import pytest

from bicentennial.packs import build
from bicentennial.world.targeted import load_tier

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def public_pack(tmp_path_factory):
    out = tmp_path_factory.mktemp("anchor-public-t2")
    spec = load_tier(ROOT / "tiers/life_specs/t2.toml")
    spec["lives"] = spec["lives"][:1]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(build, "load_tier", lambda path: spec)
        result = build.build_tier("T2", out, harness_artifacts=[])
    return out / "T2" / next(iter(result["index"]["packs"]))
