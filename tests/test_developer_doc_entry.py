"""Check the guide's own outside entry and its fresh-clone offline proof."""

import re
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.gitenv import git_env
from bicentennial.systems.mapping import check_mapping, resolve_mapping
from bicentennial.systems.pins import archive_hash
from bicentennial.systems.registry import check, load_entry, outside_reasons

REPO = Path(__file__).resolve().parents[1]
SHARED = runpy.run_path(str(REPO / "tests/test_developer_doc.py"))
GUIDE = REPO / "docs/developers/entry.md"
N = 37


def test_ci_block_matches_doc(tmp_path):
    block = SHARED["doc_block"](GUIDE.read_text(), "entry-offline")
    assert block == SHARED["workflow_run"](
        SHARED["WORKFLOW"].read_text(), "Run the developer guide's outside-entry offline path")
    assert len(block) == 7
    assert block[:5] == ["set -e", "python3 -m venv .venv", ". .venv/bin/activate",
                         "python -m pip install -e .[dev]", "export PYTHONHASHSEED=0"]
    assert shlex.split(block[-2]) == [
        "python", "-m", "pytest", "-q",
        "tests/test_developer_doc_entry.py::test_ci_block_matches_doc",
        "tests/test_developer_doc_entry.py::test_entry_example_admitted",
        "tests/test_developer_doc_entry.py::test_entry_archive_pin",
        "tests/test_naive_rag_top5.py",
        "tests/runner/test_entry_write_life.py::test_outside_scripted_write_life",
        "--junitxml=build/entry-offline.xml"]
    guard = shlex.split(block[-1])
    # Exactly the interpreter, -c and the check: nothing after it, such as `|| true`, can mask its exit status.
    assert len(guard) == 3 and guard[:2] == ["python", "-c"]
    report = tmp_path / "build/entry-offline.xml"
    report.parent.mkdir()
    for cases, expected in (("<testcase/>" * N, 0),
                            ("<testcase/>" * (N - 1) + "<testcase><skipped/></testcase>", 1),
                            ("<testcase/>" * (N - 1), 1),
                            ("<testcase/>" * (N + 1), 1)):
        report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
        result = subprocess.run([sys.executable, *guard[1:]], cwd=tmp_path, capture_output=True)
        assert result.returncode == expected


def _example(tmp_path):
    text = GUIDE.read_text()
    assert text.count("<!-- entry-example:") == 1
    blocks = re.findall(r"^<!-- entry-example: naive-rag-dev-v1 -->\n```toml\n(.*?)\n```$",
                        text, re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1
    path = tmp_path / "entry.toml"
    path.write_text(blocks[0] + "\n")
    return load_entry(path)


def test_entry_example_admitted(tmp_path):
    entry = _example(tmp_path)
    assert not outside_reasons(entry)
    assert not check(entry)
    assert check_mapping(entry, resolve_mapping(entry)) is None
    assert entry["name"] == entry["artifact"]["name"] == entry["recipe"]["provider"] == "naive-rag-dev"
    assert re.fullmatch(r"[0-9a-f]{40}", entry["recipe"]["archive_tree"]["ref"])


def test_entry_archive_pin(tmp_path):
    entry = _example(tmp_path)
    tree = entry["recipe"]["archive_tree"]
    present = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", tree["ref"] + "^{commit}"],
                             capture_output=True, env=git_env()).returncode == 0
    if not present:
        pytest.skip("v1 archive commit is absent in this shallow clone")
    assert archive_hash(REPO, (tree["ref"], tree["subdirectory"])) == entry["artifact"]["sha256"]
