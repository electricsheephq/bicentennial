"""The timing option refuses before execution and stays documented in both guides."""

from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.runner import compare, t1, t2lite


def arguments(command, out="out"):
    args = [command, "--system", "hermes-native", "--packs", "packs", "--pack-hash", "a" * 64, "--out", str(out)]
    if command == "t2lite":
        args += ["--login-home", "login", "--max-sends", "0"]
    return args


@pytest.mark.parametrize("command", ["t1", "t2lite"])
@pytest.mark.parametrize("value", ["0.4", "3.1", "-1", "not-a-number", "nan", "inf"])
def test_turn_wait_usage_precedes_execution(monkeypatch, tmp_path, capsys, command, value):
    def unexpected(*args, **kw):
        pytest.fail("execution started before usage refusal")
    monkeypatch.setattr(cli, "reexec_niced", unexpected)
    monkeypatch.setattr(cli, "run_" + command, unexpected)
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as caught:
        cli.main([*arguments(command, out), "--turn-wait", value])
    assert caught.value.code == 3
    error = capsys.readouterr().err
    assert "usage" in error and "argument --turn-wait:" in error
    assert not out.exists()


@pytest.mark.parametrize("command", ["t1", "t2lite"])
@pytest.mark.parametrize("value", [None, "0.5", "1.0", "3.0"])
def test_turn_wait_cli_default_and_range(monkeypatch, command, value):
    seen = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "run_" + command, lambda **kw: seen.append(kw) or 0)
    assert cli.main(arguments(command) + ([] if value is None else ["--turn-wait", value])) == 0
    assert seen[0]["turn_wait_s"] == (3.0 if value is None else float(value))


@pytest.mark.parametrize("command", ["t1", "t2lite"])
@pytest.mark.parametrize("value", [0.4, 3.1, -1, "not-a-number"])
def test_direct_runner_wait_refusal_precedes_preparation(monkeypatch, tmp_path, capsys, command, value):
    monkeypatch.setattr(t1, "prepare", lambda **kw: pytest.fail("preparation started"))
    out = tmp_path / "out"
    kw = dict(system="hermes-native", packs_dir=tmp_path / "packs", pack_hash="a" * 64,
        out=out, turn_wait_s=value)
    code = (compare.run_t1(**kw) if command == "t1" else
        t2lite.run_t2lite(**kw, login_home=tmp_path / "login", max_sends=0))
    assert code == 3 and capsys.readouterr().err == "usage\n"
    assert not out.exists()


@pytest.mark.parametrize("guide", ["ring0.md", "t2lite.md"])
def test_developer_guides_document_turn_wait(guide):
    text = (Path(__file__).resolve().parents[1] / "docs/developers" / guide).read_text()
    row = next(line for line in text.splitlines() if line.startswith("| `--turn-wait SECONDS` |"))
    for required in ("ordinary scripted turn", "0.5 to 3.0 inclusive", "default 3.0", "Outside the lock",
                     "published setting", "one-commit A/B", "your own", "kill or restart", "exit 3"):
        assert required in row
    assert ("`t1.turn_wait_s`" if guide == "ring0.md" else "`turn_wait_s`") in text
