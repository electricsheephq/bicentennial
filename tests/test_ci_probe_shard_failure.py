"""Temporary CI probe for #315: one failing shard must fail the aggregate test check. Never merged."""


def test_ci_probe_one_shard_fails():
    raise AssertionError("intentional failure: CI probe for #315")
