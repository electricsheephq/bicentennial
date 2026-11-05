"""Offline operator exclusions under synthetic login homes and policy checks."""

import json
from unittest.mock import Mock

import pytest
import test_outside_entry

from bicentennial.runner import t1, t2, t2lite
from bicentennial.systems import registry

outside = test_outside_entry.outside


@pytest.fixture
def marker_run(outside, tmp_path, monkeypatch):
    monkeypatch.delenv("BICENTENNIAL_OPERATOR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    out = tmp_path / "out"
    prepared = Mock(side_effect=t1.T1Refused("synthetic_stop"))
    monkeypatch.setattr(t1, "prepare", prepared)

    def run(module, *, flag, marked):
        outside["benchmark_operator_runs"] = flag
        assert not registry.operator_forbidden(outside)
        if marked:
            (home / ".bicentennial-operator").touch()
        monkeypatch.setattr(module, "LIVE_ENV", ())
        runner = module.run_t2lite if module is t2lite else module.run_t2
        assert runner(system=outside["name"], entry=outside, packs_dir=tmp_path / "packs",
                      pack_hash="1" * 64, out=out, login_home=home, max_sends=0) == 3
        return json.loads((out / "refusal.json").read_bytes())["code"]

    return run, prepared


@pytest.mark.parametrize("module", [t2lite, t2], ids=["t2lite", "t2"])
def test_marker_refuses_own_flag(module, marker_run):
    run, prepared = marker_run
    assert run(module, flag=False, marked=True) == "operator_identity"
    prepared.assert_not_called()


@pytest.mark.parametrize("module", [t2lite, t2], ids=["t2lite", "t2"])
@pytest.mark.parametrize("flag,marked", [(True, True), (False, False)],
                         ids=["permitted-under-marker", "excluded-without-marker"])
def test_marker_reaches_prepare(module, flag, marked, marker_run, outside):
    run, prepared = marker_run
    assert run(module, flag=flag, marked=marked) == "synthetic_stop"
    prepared.assert_called_once()
    assert prepared.call_args.kwargs["entry"] is outside


@pytest.mark.parametrize("forbidden", [False, True], ids=["ordinary", "forbidden"])
@pytest.mark.parametrize("flag", [False, True, None], ids=["flag-false", "flag-true", "no-flag"])
def test_operator_excluded_combines_flag_and_identity(flag, forbidden):
    entry = {"name": "lcm-copy" if forbidden else "outside-memory"}
    if flag is not None:
        entry["benchmark_operator_runs"] = flag
    assert registry.operator_forbidden(entry) is forbidden
    assert registry.operator_excluded(entry) is (flag is False or forbidden)


def test_policy_refuses_own_flag(outside):
    assert not registry.operator_forbidden(outside)
    outside["benchmark_operator_runs"] = False
    assert registry.outside_reasons(outside, operator="benchmark") == ["benchmark_operator_forbidden"]
    assert registry.outside_reasons(outside, operator="owner") == []
    outside["benchmark_operator_runs"] = True
    assert registry.outside_reasons(outside, operator="benchmark") == []
