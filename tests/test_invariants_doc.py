"""docs/invariants.md: every rule has an id, a status and real tests (#593, part 4)."""

import ast
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "invariants.md"
ROW_LIKE = re.compile(r"^\|\s*V\s*\d")
ROW = re.compile(r"^\| (V\d+) \|")
SPAN = re.compile(r"`([^`]*)`")
TEST = re.compile(r"([\w./-]+\.py)::(\w+)")
STATUSES = {"proved", "partly", "open"}


def rows(text):
    """Each catalogue row as (id, cells); any table line whose first cell starts with V and a digit is a row."""
    found = []
    for line in text.splitlines():
        if ROW_LIKE.match(line):
            match = ROW.match(line)
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            found.append((match.group(1) if match else None, cells))
    return found


def top_level_tests(path):
    """The module's top-level test functions, the ones pytest collects."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")}


def collected(path):
    """A path CI collects: under tests/ once normalised, in a file named test_*.py."""
    norm = posixpath.normpath(path)
    return norm.startswith("tests/") and posixpath.basename(norm).startswith("test_") and norm.endswith(".py")


def problems(text, root):
    """Every way the catalogue breaks its own rules, one line each."""
    out = []
    found = rows(text)
    for rule, cells in found:
        if rule is None:
            out.append(f"malformed row id {cells[0]!r}: write '| Vn |'")
    found = [(rule, cells) for rule, cells in found if rule]
    ids = [rule for rule, _ in found]
    if ids != [f"V{n}" for n in range(1, len(ids) + 1)]:
        out.append(f"ids are not V1..V{len(ids)} in order: {ids}")
    for rule, cells in found:
        if len(cells) != 6:
            out.append(f"{rule}: {len(cells)} cells, expected 6")
            continue
        status, named = cells[5], cells[4]
        if "::" in SPAN.sub("", named):
            out.append(f"{rule}: a test reference outside backticks")
        tests = []
        for span in SPAN.findall(named):
            if not (".py" in span or "::" in span or "test" in span):
                continue
            match = TEST.fullmatch(span)
            if match:
                tests.append(match.groups())
            else:
                out.append(f"{rule}: test reference {span!r} is not in the form path.py::test_name")
        if status not in STATUSES:
            out.append(f"{rule}: status {status!r} is not one of {sorted(STATUSES)}")
        if status == "proved" and not any(collected(path) for path, _ in tests):
            out.append(f"{rule}: proved, but no named test is in a tests/test_*.py file, which CI runs")
        for path, name in tests:
            file = root / path
            if not file.is_file():
                out.append(f"{rule}: {path} does not exist")
            elif name not in top_level_tests(file):
                out.append(f"{rule}: {path} defines no top-level test {name}")
    return out


def test_catalogue_holds():
    text = DOC.read_text(encoding="utf-8")
    assert rows(text), "no catalogue rows found"
    assert problems(text, ROOT) == []


def test_problems_catch_each_break(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        'def test_real():\n    pass\n\n\ndef outer():\n    """\ndef test_doc():\n    """\n\n'
        '    def test_nested():\n        pass\n', encoding="utf-8")
    (tmp_path / "tests" / "helper.py").write_text("def test_helper():\n    pass\n", encoding="utf-8")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "test_y.py").write_text("def test_outside():\n    pass\n", encoding="utf-8")
    good = ("| V1 | a | s | c | `tests/test_x.py::test_real` | proved |\n"
            "| V2 | b | s | c | none | open |\n"
            "| V3 | c | s | c | `results/test_y.py::test_outside` | partly |\n"
            "| V4 | d | s | c | none | partly |\n")
    assert problems(good, tmp_path) == []
    cases = {
        "| V1 | a | s | c | `tests/test_x.py::test_gone` | proved |\n": "defines no top-level test test_gone",
        "| V1 | a | s | c | `tests/test_x.py::test_doc` | partly |\n": "defines no top-level test test_doc",
        "| V1 | a | s | c | `tests/test_x.py::test_nested` | partly |\n": "defines no top-level test test_nested",
        "| V1 | a | s | c | `tests/missing.py::test_real` | proved |\n": "does not exist",
        "| V1 | a | s | c | none | proved |\n": "no named test is in a tests/test_*.py file",
        "| V1 | a | s | c | `results/test_y.py::test_outside` | proved |\n": "no named test is in a tests/test_*.py file",
        "| V1 | a | s | c | `tests/helper.py::test_helper` | proved |\n": "no named test is in a tests/test_*.py file",
        "| V1 | a | s | c | `tests/../results/test_y.py::test_outside` | proved |\n": "no named test is in a tests/test_*.py file",
        "| V1 | a | s | c | `tests/test_x.py::TestK::test_real` | partly |\n": "is not in the form",
        "| V1 | a | s | c | `tests/test_x.py::test_real[a]` | partly |\n": "is not in the form",
        "| V1 | a | s | c | tests/test_x.py::test_real | partly |\n": "outside backticks",
        "| V1 | a | s | c | `tests/test_x.py`::`test_real` | partly |\n": "outside backticks",
        "| V1 | a | s | c | `tests/test_x.py` | partly |\n": "is not in the form",
        "| V1 | a | s | c | `tests/test_x.py :: test_real` | partly |\n": "is not in the form",
        "| V1 | a | s | c | `tests/test_x::test_real` | partly |\n": "is not in the form",
        "| V1 | a | s | c | `test_real` in tests/test_x.py | partly |\n": "is not in the form",
        "| V1 | a | s | c | `scripts/check::main` | partly |\n": "is not in the form",
        "| V1 | a | s | c | `scripts/roster.py` | partly |\n": "is not in the form",
        "| V1 | a | s | c | none | maybe |\n": "is not one of",
        "| V2 | a | s | c | none | open |\n": "ids are not",
        "| V1 | a | s | none | open |\n": "5 cells",
        "| V1 | a | s | c | none | open |\n|V2| b | s | c | none | open |\n": "malformed row id",
    }
    for text, expected in cases.items():
        found = problems(text, tmp_path)
        assert any(expected in line for line in found), (text, found)
