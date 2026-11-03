"""Frozen T1 bytes from the starting generator, without repository history."""

import json

from bicentennial.canon import sha256_canon
from bicentennial.packs.build import build_tier

A = [dict(name="hermes", version="test", sha256="a" * 64)]


def test_t1_pack_byte_goldens(tmp_path):
    result = build_tier("T1", tmp_path, harness_artifacts=A)
    manifests = {}
    for rel in result["index"]["packs"]:
        meta = json.loads((tmp_path / "T1" / rel / "sealed/meta.json").read_bytes())
        manifests[meta["life"]] = sha256_canon(meta["generator"])
    assert manifests == {
        "t1-g1": "71b50442b18c977febe8af8a59222e9638a175c1871de9590145ef156850c635",
        "t1-g2": "fb82438e39bec7dc36121fe9bde391d1b08ac73311841f93c7d73b85606ff2c3",
    }
    assert sha256_canon(result["index"]) == "3841db7d8bd56e301b675cd2e09bfe5c76bd80c52cbd17e24b8d9f44640b1198"
    assert result["pack_hash"] == "9421da459b27019a4d72d6e5e18f4d967818fc1a74ae1470b3ddeb6cd3a79012"
