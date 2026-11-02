"""Keep the T2-lite guide aligned with its parser, refusals and offline outputs."""

import ast
import re
import runpy
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial import cli
from bicentennial.runner import t2lite
from bicentennial.runner.spend import Price, Spend

REPO = Path(__file__).resolve().parents[1]
SHARED = runpy.run_path(str(REPO / "tests/test_developer_doc.py"))
RUNNER = runpy.run_path(str(REPO / "tests/runner/test_t2lite.py"))
scenario = RUNNER["scenario"]
live_settings = RUNNER["live_settings"]
GUIDE = REPO / "docs/developers/t2lite.md"


def test_doc_commands_exist(monkeypatch, capsys):
    text = GUIDE.read_text()
    flags = [span.split()[0] for span in re.findall(r"`([^`\n]+)`", text) if span.startswith("--")]
    SHARED["_flags_in_help"](cli.main, "t2lite", flags, capsys)
    calls = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "run_t2lite", lambda **kwargs: calls.append(kwargs) or 0)
    for line in SHARED["_shell_lines"](text):
        tokens = shlex.split(line)
        if tokens[:2] == ["bicentennial", "t2lite"]:
            SHARED["_flags_in_help"](cli.main, "t2lite", tokens[2:], capsys)
            assert cli.main(tokens[1:]) == 0
    assert len(calls) == 3
    a, prime, b = calls
    assert prime["aa_of"] == prime["baseline"] == a["out"]
    assert b["baseline"] == a["out"] and b["aa_prime"] == prime["out"]
    assert "A′'s flips are noise, and its q₀ is the noise rate" in text


def _calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def _evaluate(node, **values):
    return eval(compile(ast.Expression(node), "<refusal expression>", "eval"), {"__builtins__": {}}, values)


def _mapped_literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.IfExp):
        yield from _mapped_literals(node.body)
        yield from _mapped_literals(node.orelse)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _mapped_literals(value)


def _code_refusals():
    tree = ast.parse((REPO / "src/bicentennial/runner/t2lite.py").read_text())
    codes = SHARED["_code_refusals"]()
    for call in _calls(tree, "T1Refused"):
        arg = call.args[0]
        if isinstance(arg, ast.Constant):
            codes.add(arg.value)
        elif isinstance(arg, ast.BinOp):
            codes.update(_evaluate(arg, role=role) for role in t2lite.ROLES.values())
    # run_life's own refusals reach refusal.json as their sorted, comma-joined reasons.
    life = ast.parse((REPO / "src/bicentennial/runner/life.py").read_text())
    for call in _calls(life, "SystemRefused"):
        codes.update(n.value for n in ast.walk(call.args[0])
                     if isinstance(n, ast.Constant) and isinstance(n.value, str))
    # Literal branches of the runner's code mapping and tool-failure publication.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "code" for t in node.targets):
            codes.update(_mapped_literals(node.value))
        if isinstance(node, ast.keyword) and node.arg == "code" and isinstance(node.value, ast.Constant):
            codes.add(node.value.value)
    flips = ast.parse((REPO / "src/bicentennial/report/t2lite_flips.py").read_text())
    comparison = None
    invalid = None
    for call in _calls(flips, "BaselineRefused"):
        arg = call.args[0]
        if isinstance(arg, ast.Constant):
            codes.add(arg.value)
        elif isinstance(arg, ast.JoinedStr):
            codes.add("".join(part.value if isinstance(part, ast.Constant) else
                              "<" + part.value.id + ">" for part in arg.values))
            if any(isinstance(p, ast.Constant) and p.value == "invalid_card:" for p in arg.values):
                invalid = arg
        elif isinstance(arg, ast.BinOp):
            comparison = arg
            codes.update(_evaluate(arg, prefix=c.args[2].value, field="<field>")
                         for c in _calls(flips, "_compare"))
    # Evaluate _references' actual renaming expression for each non-baseline role.
    references = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_references")
    rename = next(n.value for n in ast.walk(references) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "reason" for t in n.targets))
    for role in set(t2lite.ROLES.values()) - {t2lite.ROLES["baseline"]}:
        for reason in (_evaluate(invalid, side=t2lite.ROLES["baseline"]),
                       _evaluate(comparison, prefix="", field="<field>")):
            codes.add(_evaluate(rename, role=role, error=SimpleNamespace(reason=reason)))
    return codes


def test_doc_codes():
    table = GUIDE.read_text().split("| Code | Cause |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
    rows = re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE)
    assert len(rows) == len(set(rows))
    assert set(rows) == _code_refusals()


@pytest.mark.parametrize("mode", [None, "credential"])
def test_doc_outputs(scenario, monkeypatch, mode):
    build = t2lite.build_live_stack
    def with_spend(path, **kwargs):
        Spend(path, 0, Price(0, 0))  # The real live stack creates this; the reused fake does not.
        return build(path, **kwargs)
    monkeypatch.setattr(t2lite, "build_live_stack", with_spend)
    scenario.mode = mode
    if mode is None:
        assert scenario.invoke("A") == 0
        assert scenario.invoke("prime", aa_of=scenario.out.parent / "A", baseline=scenario.out.parent / "A") == 0
        prime = t2lite._read(scenario.out.parent / "prime", "flips.json")
        assert prime["q0"]["milli"] == 0 and "no A/A′ band" not in prime["labels"]
        assert scenario.invoke(baseline=scenario.out.parent / "A", aa_prime=scenario.out.parent / "prime") == 0
    else:
        assert scenario.invoke() == 3
    name = "Complete" if mode is None else "Credential stop"
    table = GUIDE.read_text().split(f"### {name}\n", 1)[1].strip().split("\n\n", 1)[0]
    listed = set(re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE))
    actual = {re.sub(r"/(t1-g[12])/B[01]/", "/<life>/<branch>/", p.relative_to(scenario.out).as_posix())
              for p in scenario.out.rglob("*") if p.is_file()}
    assert actual == listed
    if mode is None:
        assert "`live.holds` (`waits`, `held_ms`, sorted `reasons`)" in table
        assert t2lite._read(scenario.out, "disclosures.json")["live"]["holds"] == {
            "waits": 0, "held_ms": 0, "reasons": []}


def test_ci_block_matches_doc(tmp_path):
    text = GUIDE.read_text()
    assert text.count("<!-- ci-block:") == 1
    block = SHARED["doc_block"](text, "t2lite-offline")
    assert block == SHARED["workflow_run"](SHARED["WORKFLOW"].read_text(),
                                         "Run the developer guide's T2-lite offline path")
    assert "export PYTHONHASHSEED=0" in block
    assert "python -m pip install -e .[dev]" in block
    assert any("tests/runner/test_t2lite.py::test_full_fake_worker_and_rerun_store_hashes" in line for line in block)
    assert block[0] == "set -e"
    command = shlex.split(block[-2])
    assert command == ["python", "-m", "pytest", "-q",
                       "tests/runner/test_t2lite.py::test_full_fake_worker_and_rerun_store_hashes",
                       "--junitxml=build/t2lite-offline.xml"]
    guard = shlex.split(block[-1])
    assert guard[:2] == ["python", "-c"]
    report = tmp_path / "build/t2lite-offline.xml"
    report.parent.mkdir()
    for case, expected in (("<testcase/>", 0), ("<testcase><skipped/></testcase>", 1), ("", 1)):
        report.write_text(f"<testsuites><testsuite>{case}</testsuite></testsuites>")
        result = subprocess.run([sys.executable, *guard[1:]], cwd=tmp_path, capture_output=True)
        assert result.returncode == expected


def test_doc_public_text():
    paths = runpy.run_path(str(REPO / "scripts/public_check.py"))["PATHS"]
    assert not paths.search(GUIDE.read_text())
