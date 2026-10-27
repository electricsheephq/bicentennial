"""Keep the runnable developer guide aligned with its CI proof and public API."""

import ast
import importlib
import json
import re
import runpy
import shlex
from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.packs import install
from bicentennial.runner import compare

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "docs/developers/ring0.md"
WORKFLOW = REPO / ".github/workflows/ring0-doc.yml"
STEP = "Run the developer guide's T0 commands"


def doc_block(text, name):
    lines = text.splitlines()
    positions = [i for i, line in enumerate(lines) if line == f"<!-- ci-block: {name} -->"]
    assert len(positions) == 1
    start = positions[0] + 1
    assert lines[start] == "```sh"
    end = lines.index("```", start + 1)
    return lines[start + 1:end]


def workflow_run(text, step):
    lines = text.splitlines()
    positions = [i for i, line in enumerate(lines) if line == f"      - name: {step}"]
    assert len(positions) == 1
    start = positions[0] + 1
    assert lines[start:start + 2] == ["        shell: bash", "        run: |"]
    result = []
    for line in lines[start + 2:]:
        if line and not line.startswith(" " * 10):
            break
        result.append(line[10:] if line else "")
    while result and not result[-1]:
        result.pop()
    return result


def test_ci_block_matches_doc():
    doc = GUIDE.read_text()
    assert doc.count("<!-- ci-block:") == 1
    block = doc_block(doc, "ring0-t0-reference")
    assert len(block) == 10
    assert block == workflow_run(WORKFLOW.read_text(), STEP)


def _on_block(text):
    lines = text.splitlines()
    start = lines.index("on:")
    end = next(i for i in range(start + 1, len(lines))
               if lines[i] and not lines[i].startswith(" "))
    return lines[start:end]


def test_workflow_shape():
    text = WORKFLOW.read_text()
    ci = (REPO / ".github/workflows/ci.yml").read_text()
    assert len(re.findall(r"^      - ", text, re.MULTILINE)) == 3
    assert set(re.findall(r"uses: (\S+)", text)) == set(re.findall(r"uses: (\S+)", ci))
    assert not re.search(r"^\s*env:", text, re.MULTILINE)
    assert len(re.findall(r"^\s*(?:- )?run:", text, re.MULTILINE)) == 1
    assert _on_block(text) == _on_block(ci)
    assert "persist-credentials: false" in text
    assert 'python-version: "3.14"' in text
    assert "timeout-minutes: 30" in text
    assert "contents: read" in text


def _shell_lines(text):
    active = False
    for line in text.splitlines():
        if line == "```sh":
            assert not active
            active = True
        elif line == "```":
            active = False
        elif active:
            yield line
    assert not active


def _flags_in_help(main, sub, tokens, capsys):
    capsys.readouterr()
    with pytest.raises(SystemExit) as caught:
        main([sub, "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    flags = set(re.findall(r"--[a-z][a-z-]*", help_text))
    for token in tokens:
        if token.startswith("--"):
            assert token.split("=", 1)[0] in flags


def test_doc_commands_exist(capsys):
    for line in _shell_lines(GUIDE.read_text()):
        tokens = shlex.split(line)
        assert "lcm-x" not in tokens
        if tokens[:1] == ["bicentennial"]:
            _flags_in_help(cli.main, tokens[1], tokens[2:], capsys)
        elif tokens[:3] == ["python", "-m", "bicentennial.packs.install"]:
            _flags_in_help(install.main, tokens[3], tokens[4:], capsys)
        elif tokens[:3] == ["python", "-m", "bicentennial.report.determinism"]:
            assert callable(importlib.import_module(tokens[2]).main)
        elif tokens[:2] == ["python", "-c"]:
            compile(tokens[2], "<guide command>", "exec")
            for node in ast.walk(ast.parse(tokens[2])):
                if isinstance(node, ast.ImportFrom):
                    module = importlib.import_module(node.module)
                    for alias in node.names:
                        assert hasattr(module, alias.name)


def _refusal_codes(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"T0Refused", "T1Refused"} and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield arg.value
            elif (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add)
                  and isinstance(arg.left, ast.Constant) and arg.left.value == "mode_unavailable:"):
                yield "mode_unavailable:hermes"


def test_doc_codes():
    text = GUIDE.read_text()
    codes = set()
    for name in ("t0", "t1", "compare"):
        codes.update(_refusal_codes(REPO / f"src/bicentennial/runner/{name}.py"))
    tree = ast.parse((REPO / "src/bicentennial/systems/registry.py").read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "reasons"
                and node.func.attr == "append" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            codes.add(node.args[0].value)
    codes.update(("unmeasured:artifact.sha256", "unmeasured:fresh_install_hash", "hashseed",
                  "usage", "source_checkout_required", "pinned_artifact_changed", "lock_mismatch",
                  "gate_refused", "pin_mismatch", "SpendRefused", "baseline_mismatch"))
    codes.update(name for name, _ in (*compare.DISCLOSURES, *compare.PLUGIN_DISCLOSURES))
    schema = json.loads((REPO / "schemas/card_ring0.schema.json").read_text())
    for label in schema["properties"]["labels"]["properties"].values():
        codes.update(label["enum"])
    assert not sorted(code for code in codes if code not in text)


def test_doc_public_text():
    paths = runpy.run_path(str(REPO / "scripts/public_check.py"))["PATHS"]
    for path in (GUIDE, REPO / "README.md"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            assert not paths.search(line), (path.relative_to(REPO), number)
