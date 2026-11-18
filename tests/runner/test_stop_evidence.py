"""#618: a run that stops keeps the relay's refusal evidence of every attempt before the stop, in refusals.json."""

import json
import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401
from test_units_characterization import _digests

from bicentennial.canon import canon
from bicentennial.runner import units
from bicentennial.runner.life import _refusals

CORE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "director" / "test_core.py"))
# Lines the director could never write: a float canon() refuses, and a key outside its key set.
INVALID = b'{"status": 0.5}\n{"served": "refused_float", "planted": "planted-user-618a"}\n'
# Each stop's files and bytes at 5922a71, the commit before #618, on these fakes with no refusal. A T2-lite
# receipt names its fake life by the test's own temporary folder, so these hold for test_stop_bytes only.
CUSTODY = "862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8"
NO_REFUSAL = {
    ("t2lite", "credential"): {"custody.json": CUSTODY,
        "receipt.json": "a6efa3130be8b4ef34cad814530eb607ca649195ede9790d502f4b6993aac494",
        "refusal.json": "d9d95e0003ac25eb2d91f7b9106159c28f8778097621c0c8173dcf33d2c4b006"},
    ("t2lite", "live_stop"): {"custody.json": CUSTODY,
        "receipt.json": "a6efa3130be8b4ef34cad814530eb607ca649195ede9790d502f4b6993aac494",
        "refusal.json": "7e520d30c948360890420b9c35949c6b52d3bcc612bd0a3d8da20743892a7558"},
    ("t2lite", "spend"): {"custody.json": CUSTODY,
        "receipt.json": "8d77d5b2dfad07c93e3043b4948d19a615de24f35c06458f2df0f4b55a36b131",
        "refusal.json": "5478d0f1454586658dae3001324e5de5ad7f39379f82fdbc4a20ca9db7ed8317"},
    ("t2", "credential"): {"attempts.json": "a187489eb5a7beb14f66d2e7dc2c84291ef1b4d46976104f0a6b8fe16fbcfd28",
        "custody.json": CUSTODY,
        "receipt.json": "a46a41ab1b1fde79601d6216f135635c23af53b410b78b7b983793c7e220fd36",
        "refusal.json": "d9d95e0003ac25eb2d91f7b9106159c28f8778097621c0c8173dcf33d2c4b006"},
    ("t2", "live_stop"): {"attempts.json": "a187489eb5a7beb14f66d2e7dc2c84291ef1b4d46976104f0a6b8fe16fbcfd28",
        "custody.json": CUSTODY,
        "receipt.json": "a46a41ab1b1fde79601d6216f135635c23af53b410b78b7b983793c7e220fd36",
        "refusal.json": "7e520d30c948360890420b9c35949c6b52d3bcc612bd0a3d8da20743892a7558"},
    ("t2", "spend"): {"attempts.json": "0a05755fc5fa2791c3ef64a514eaebc461bfc3443fb66d6c7b3e7fe577d89bca",
        "custody.json": CUSTODY,
        "receipt.json": "7f8fb646ae38bfb054d61765f6d23f026432af3778c5de8d69c490421efefd04",
        "refusal.json": "5478d0f1454586658dae3001324e5de5ad7f39379f82fdbc4a20ca9db7ed8317"},
}


def evidence(tmp):
    """The relay's own evidence file for one refused_float request, from tests/director/test_core.py's fakes."""
    tmp.mkdir()
    d = CORE["make"](tmp, CORE["Fake"]())
    CORE["start"](d, tmp)
    try:
        body = CORE["turn_body"](tools=("todo",)) | {"temperature": 0.5}
        assert CORE["post"](d, "/main/v1/chat/completions", body)[0] == 400
    finally:
        d.close()
    data = (tmp / "ledger" / "refusals.jsonl").read_bytes()
    (row,) = [json.loads(line) for line in data.splitlines()]
    assert row["served"] == "refused_float"
    return data, row


@pytest.fixture(params=["t2lite", "t2"])
def tier(request):
    """Either tier's offline fakes; T2 runs one slot, so its first unit is the one that stops."""
    s = request.getfixturevalue("t2_scenario" if request.param == "t2" else "scenario")
    s.tier, s.first = request.param, None
    s.stop = (lambda name="out": s.invoke(name, slots=1)) if request.param == "t2" else s.invoke
    return s


def control(s, stop):
    """The same stop with no refusal, beside the run under test: the digests of its files."""
    s.mode = stop
    assert s.stop("control") == 3
    s.mode = None
    return _digests(s.out.with_name("control"))


def plant(kw, data):
    ledger = kw["scratch"] / kw["branch"] / "run/ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    with (ledger / "refusals.jsonl").open("ab") as f:
        f.write(data)
    return ledger


def refuse_then(s, monkeypatch, data, stop, *, stop_in_next=False, rows=None):
    """The first attempt to run keeps `data` as the relay's evidence; `stop` then stops that attempt, or with
    stop_in_next the first attempt finishes and the next one stops. A finished attempt's rows are read as run_life
    reads them at its end (or are `rows`, when given)."""
    drive = units.run_life

    def life(**kw):
        first = s.first is None
        if first:
            # A stopped attempt's partial run is named by its pack; a finished fake one by its life_dir.
            pack = next(p.life for p in s.ctx.packs if p.items[kw["branch"]] == kw["items"])
            s.first = (kw["arm"], pack, kw["branch"], kw["attempt"])
        s.mode = stop if not first or not stop_in_next else None
        if first and s.mode in ("credential", "live_stop"):
            plant(kw, data)  # the stop is raised inside the attempt, before it returns
        run = drive(**kw)
        if first:
            ledger = plant(kw, data)
            run = replace(run, refusals=_refusals(ledger) if rows is None else rows)
            s.first = (kw["arm"], run.life, kw["branch"], kw["attempt"])
        return run

    monkeypatch.setattr(units, "run_life", life)


def kept(s, before, row):
    """refusals.json holds the first attempt's validated row, and every other file is as the stop wrote it before."""
    digests = _digests(s.out)
    assert digests.pop("refusals.json", None) is not None, sorted(p.name for p in s.out.iterdir())
    assert digests == before
    data = (s.out / "refusals.json").read_bytes()
    record = json.loads(data)
    assert data == canon(record)
    arm, life, branch, attempt = s.first
    assert record == dict(attempts=[dict(arm=arm, life=life, branch=branch, attempt=attempt, refusals=[row])])


@pytest.mark.parametrize("stop", ["credential", "live_stop", "spend"])
def test_stop_bytes(tier, stop):
    """A stopped run with no refusal writes the same files and bytes as before #618."""
    tier.mode = stop
    assert tier.stop() == 3
    assert _digests(tier.out) == NO_REFUSAL[tier.tier, stop], repr((tier.tier, stop, _digests(tier.out)))


def test_a_credential_stop_keeps_the_refusal_evidence_before_it(tier, tmp_path, monkeypatch):
    before = control(tier, "credential")
    data, row = evidence(tmp_path / "relay")
    refuse_then(tier, monkeypatch, data + INVALID, "credential")
    assert tier.stop() == 3
    assert json.loads((tier.out / "refusal.json").read_bytes()) == {"code": "credential_stop"}
    kept(tier, before, row)


def test_a_live_responder_stop_keeps_the_refusal_evidence_before_it(tier, tmp_path, monkeypatch):
    before = control(tier, "live_stop")
    data, row = evidence(tmp_path / "relay")
    refuse_then(tier, monkeypatch, data + INVALID, "live_stop")
    assert tier.stop() == 3
    assert json.loads((tier.out / "refusal.json").read_bytes())["code"] == "live_stop"
    kept(tier, before, row)


def test_the_limit_on_requests_keeps_the_refusal_evidence_before_it(tier, tmp_path, monkeypatch):
    before = control(tier, "spend")
    data, row = evidence(tmp_path / "relay")
    refuse_then(tier, monkeypatch, data + INVALID, "spend")
    assert tier.stop() == 3
    assert json.loads((tier.out / "refusal.json").read_bytes()) == {"code": "spend_stop"}
    kept(tier, before, row)


def test_a_finished_units_evidence_survives_a_later_units_stop(tier, tmp_path, monkeypatch):
    data, row = evidence(tmp_path / "relay")
    refuse_then(tier, monkeypatch, data, "credential", stop_in_next=True)
    assert tier.stop() == 3
    assert json.loads((tier.out / "refusal.json").read_bytes()) == {"code": "credential_stop"}
    names = {"custody.json", "receipt.json", "refusal.json", "refusals.json", *(["attempts.json"] * (tier.tier == "t2"))}
    assert {p.name for p in tier.out.iterdir()} == names
    record = json.loads((tier.out / "refusals.json").read_bytes())
    arm, life, branch, attempt = tier.first
    assert record == dict(attempts=[dict(arm=arm, life=life, branch=branch, attempt=attempt, refusals=[row])])


def test_login_material_in_kept_evidence_is_a_credential_scan(tier, monkeypatch):
    """As on a finished run, whose unit_diagnostics.json the output scan reads: only the refusal remains."""
    refuse_then(tier, monkeypatch, canon({"served": "refused_unknown", "model": "synthetic-access-token"}) + b"\n",
                "credential")
    assert tier.stop() == 3
    assert sorted(p.name for p in tier.out.iterdir()) == ["refusal.json"]
    assert json.loads((tier.out / "refusal.json").read_bytes()) == {"code": "credential_scan"}


def test_evidence_that_cannot_be_written_leaves_the_stop_as_before(tier, monkeypatch):
    """refusals.json is evidence only: rows canon() refuses leave it out, and the stop's own files stay."""
    before = control(tier, "spend")
    refuse_then(tier, monkeypatch, b"", "spend", rows=[{"status": 0.5}])
    assert tier.stop() == 3
    assert json.loads((tier.out / "refusal.json").read_bytes()) == {"code": "spend_stop"}
    assert _digests(tier.out) == before
