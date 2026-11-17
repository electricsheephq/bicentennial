"""docs/invariants.md: every rule has an id, a status and real tests (#593, part 4)."""

import ast
import fnmatch
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "invariants.md"
HEADER = "| ID | Rule | Source | Enforced by | Proved by | Status |"
SEPARATOR = "|---|---|---|---|---|---|"
ROW_ID = re.compile(r"V[1-9]\d*")
CELL = re.compile(r"(?<!\\)\|")
TEST = re.compile(r"`([\w./-]+\.py)::(\w+)`")
PROOF = re.compile(rf"{TEST.pattern}(?:; {TEST.pattern})*")
SKIPPERS = {"skip", "skipif", "importorskip", "xfail"}
COLLECTED = ("test_*.py", "*_test.py")
STATUSES = {"proved", "partly", "open"}


def rows(text):
    """Every data line of every catalogue table as (line number, cells or None), and the table lines outside a table."""
    found, stray, inside = [], [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line == HEADER:
            inside = True
        elif not line.strip():
            inside = False
        elif not inside:
            if line.lstrip().startswith("|"):
                stray.append(number)
        elif line != SEPARATOR:
            body = line.strip()
            whole = len(body) > 1 and body.startswith("|") and body.endswith("|") and not body.endswith("\\|")
            found.append((number, [cell.strip() for cell in CELL.split(body[1:-1])] if whole else None))
    return found, stray


def top_level_tests(path):
    """The module's syntax tree and its top-level test functions, the ones pytest collects, by name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tree, {node.name: node for node in tree.body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")}


def _skips(node):
    return any(isinstance(sub, ast.Attribute) and sub.attr in SKIPPERS or isinstance(sub, ast.Name) and sub.id in SKIPPERS
               for sub in ast.walk(node))


def can_skip(tree, node):
    """A skip or xfail mark or call in the test, a module-level skip or pytestmark, or an async test (no async test
    plugin is installed); fixtures and conftest hooks are not read."""
    if isinstance(node, ast.AsyncFunctionDef) or _skips(node):
        return True
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target] if isinstance(statement, ast.AnnAssign) else [])
        if _skips(statement) or any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            return True
    return False


def collected(path):
    """A path CI collects: under tests/ once normalised, in a file that pytest's default patterns match."""
    norm = posixpath.normpath(path)
    return norm.startswith("tests/") and any(fnmatch.fnmatchcase(posixpath.basename(norm), pattern)
                                             for pattern in COLLECTED)


def problems(text, root):
    """Every way the catalogue breaks its own rules, one line each."""
    out = []
    found, stray = rows(text)
    for number in stray:
        out.append(f"line {number}: a table line outside a catalogue table; each table starts with {HEADER!r}")
    ids = []
    for number, cells in found:
        if cells is None or len(cells) != 6:
            out.append(f"line {number}: {'not delimited by |' if cells is None else f'{len(cells)} cells'}, "
                       "expected 6 cells")
            continue
        rule, named, status = cells[0], cells[4], cells[5]
        ids.append(rule)
        if not ROW_ID.fullmatch(rule):
            out.append(f"line {number}: row id {rule!r} is not Vn")
        if status not in STATUSES:
            out.append(f"{rule}: status {status!r} is not one of {sorted(STATUSES)}")
        if named != "none" and not PROOF.fullmatch(named):
            out.append(f"{rule}: Proved by must be 'none' or `path.py::test_name` spans joined by '; ', not {named!r}")
            continue
        runs = False
        for path, name in TEST.findall(named):
            file = root / path
            if not file.is_file():
                out.append(f"{rule}: {path} does not exist")
                continue
            tree, tests = top_level_tests(file)
            if name not in tests:
                out.append(f"{rule}: {path} defines no top-level test {name}")
            elif collected(path) and not can_skip(tree, tests[name]):
                runs = True
        if status == "proved" and not runs:
            out.append(f"{rule}: proved, but no named test is a CI-collected test under tests/ that cannot skip")
    if ids != [f"V{n}" for n in range(1, len(ids) + 1)]:
        out.append(f"ids are not V1..V{len(ids)} in order: {ids}")
    return out


def test_catalogue_holds():
    text = DOC.read_text(encoding="utf-8")
    assert rows(text)[0], "no catalogue rows found"
    assert problems(text, ROOT) == []


def test_problems_catch_each_break(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "import pytest\n\n\ndef test_real():\n    pass\n\n\ndef outer():\n    \"\"\"\ndef test_doc():\n    \"\"\"\n\n"
        "    def test_nested():\n        pass\n\n\n@pytest.mark.skipif(True, reason='opt-in')\ndef test_marked():\n    pass\n\n\n"
        "def test_called():\n    pytest.skip('no')\n\n\n@pytest.mark.xfail\ndef test_xf():\n    pass\n\n\n"
        "class TestK:\n    @pytest.mark.skip\n    def test_method(self):\n        pass\n\n\n"
        "async def test_async():\n    pass\n\n\nasync def later():\n    pytest.skip('x')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import pytest\n\npytestmark = pytest.mark.skip(reason='all')\n\n\ndef test_module():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "x_test.py").write_text("def test_suffix():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_n.py").write_text(
        "import pytest\n\npytestmark = pytest.mark.slow\n\n\ndef test_plain_mark():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_p.py").write_text(
        "import pytest\n\npytestmark: object = pytest.mark.slow\n\n\ndef test_annotated_mark():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "import pytest\nfrom pytest import skip\n\n\ndef test_bare():\n    skip('x')\n\n\n"
        "def test_imp():\n    pytest.importorskip('nothing')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_q.py").write_text(
        "import pytest\n\nnp = pytest.importorskip('numpy')\n\n\ndef test_needs_np():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "helper.py").write_text("def test_helper():\n    pass\n", encoding="utf-8")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "test_y.py").write_text("def test_outside():\n    pass\n", encoding="utf-8")
    table = HEADER + "\n" + SEPARATOR + "\n"
    good = table + ("| V1 | a | s | c | `tests/test_x.py::test_real` | proved |\n"
                    "| V2 | b \\| e | s | c | none | open |\n"
                    "| V3 | c | s | c | `results/test_y.py::test_outside` | partly |\n"
                    "| V4 | d | s | c | `tests/x_test.py::test_suffix`; `tests/test_x.py::test_marked` | proved |\n"
                    "| V5 | e | s | c | `tests/test_x.py::test_async` | partly |\n")
    assert problems(good, tmp_path) == []
    must = "Proved by must be"
    unrun = "proved, but no named test is a CI-collected test"
    cases = {
        "| V1 | a | s | c | `tests/test_x.py::test_gone` | proved |\n": "defines no top-level test test_gone",
        "| V1 | a | s | c | `tests/test_x.py::test_doc` | partly |\n": "defines no top-level test test_doc",
        "| V1 | a | s | c | `tests/test_x.py::test_nested` | partly |\n": "defines no top-level test test_nested",
        "| V1 | a | s | c | `tests/missing.py::test_real` | partly |\n": "does not exist",
        "| V1 | a | s | c | none | proved |\n": unrun,
        "| V1 | a | s | c | `results/test_y.py::test_outside` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/helper.py::test_helper` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/../results/test_y.py::test_outside` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_x.py::test_marked` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_x.py::test_called` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_x.py::test_xf` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_m.py::test_module` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_n.py::test_plain_mark` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_p.py::test_annotated_mark` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_b.py::test_bare` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_b.py::test_imp` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_q.py::test_needs_np` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_x.py::test_async` | proved |\n": unrun,
        "| V1 | a | s | c | `tests/test_x.py::outer` | partly |\n": "defines no top-level test outer",
        "| V1 | a | s | c | `tests/test_x.py::test_method` | partly |\n": "defines no top-level test test_method",
        "| V1 | a | s | c | `tests/test_x.py::TestK::test_real` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py::test_real[a]` | partly |\n": must,
        "| V1 | a | s | c | tests/test_x.py::test_real | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py`::`test_real` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py :: test_real` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x::test_real` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py::test_real`; tests/test_x.py (test_gone) | partly |\n": must,
        "| V1 | a | s | c | [test_gone](../tests/test_x.py) | partly |\n": must,
        "| V1 | a | s | c | `TestGone` | partly |\n": must,
        "| V1 | a | s | c | `tests/test_x.py::test_real`, `tests/x_test.py::test_suffix` | partly |\n": must,
        "| V1 | a | s | c | none | maybe |\n": "is not one of",
        "| V2 | a | s | c | none | open |\n": "ids are not",
        "| V1 | a | s | none | open |\n": "5 cells",
        "| V1 | a | s | c | none | open ||\n": "7 cells",
        "| V1 | a | s | c | none | open\n": "not delimited",
        "| V1 | a | s | c | none | open \\|\n": "not delimited",
        "|\n": "not delimited",
        "| V1x | a | s | c | none | open |\n": "is not Vn",
        "| VX1 | a | s | c | none | open |\n": "is not Vn",
        "| v1 | a | s | c | none | open |\n": "is not Vn",
    }
    for row, expected in cases.items():
        found = problems(table + row, tmp_path)
        assert any(expected in line for line in found), (row, found)
    for gap in ("\n", "\n  "):
        stray = table + "| V1 | a | s | c | none | open |\n" + gap + "| V2 | b | s | c | none | open |\n"
        assert any("outside a catalogue table" in line for line in problems(stray, tmp_path)), gap
