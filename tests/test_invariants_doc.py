"""docs/invariants.md: every rule has an id, a status and real tests (#593, part 4)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "invariants.md"
ROW = re.compile(r"^\| (V\d+) \|")
TEST = re.compile(r"`([\w./-]+\.py)::(\w+)`")
STATUSES = {"proved", "partly", "open"}


def rows(text):
    """Each catalogue row as (id, cells); a row is a table line whose first cell is an id."""
    found = []
    for line in text.splitlines():
        match = ROW.match(line)
        if match:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            found.append((match.group(1), cells))
    return found


def defines(path, name):
    source = path.read_text(encoding="utf-8")
    return re.search(rf"^\s*(?:async\s+)?def {re.escape(name)}\(", source, re.M) is not None


def problems(text, root):
    """Every way the catalogue breaks its own rules, one line each."""
    out = []
    found = rows(text)
    ids = [rule for rule, _ in found]
    if ids != [f"V{n}" for n in range(1, len(ids) + 1)]:
        out.append(f"ids are not V1..V{len(ids)} in order: {ids}")
    for rule, cells in found:
        if len(cells) != 6:
            out.append(f"{rule}: {len(cells)} cells, expected 6")
            continue
        status, tests = cells[5], TEST.findall(cells[4])
        if status not in STATUSES:
            out.append(f"{rule}: status {status!r} is not one of {sorted(STATUSES)}")
        if status == "proved" and not any(path.startswith("tests/") for path, _ in tests):
            out.append(f"{rule}: proved, but no named test is under tests/, which CI runs")
        for path, name in tests:
            file = root / path
            if not file.is_file():
                out.append(f"{rule}: {path} does not exist")
            elif not defines(file, name):
                out.append(f"{rule}: {path} defines no test {name}")
    return out


def test_catalogue_holds():
    text = DOC.read_text(encoding="utf-8")
    assert rows(text), "no catalogue rows found"
    assert problems(text, ROOT) == []


def test_problems_catch_each_break(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_real():\n    pass\n", encoding="utf-8")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "test_y.py").write_text("def test_outside():\n    pass\n", encoding="utf-8")
    good = ("| V1 | a | s | c | `tests/test_x.py::test_real` | proved |\n"
            "| V2 | b | s | c | none | open |\n"
            "| V3 | c | s | c | `results/test_y.py::test_outside` | partly |\n"
            "| V4 | d | s | c | none | partly |\n")
    assert problems(good, tmp_path) == []
    cases = {
        "| V1 | a | s | c | `tests/test_x.py::test_gone` | proved |\n": "defines no test test_gone",
        "| V1 | a | s | c | `tests/missing.py::test_real` | proved |\n": "does not exist",
        "| V1 | a | s | c | none | proved |\n": "no named test is under tests/",
        "| V1 | a | s | c | `results/test_y.py::test_outside` | proved |\n": "no named test is under tests/",
        "| V1 | a | s | c | none | maybe |\n": "is not one of",
        "| V2 | a | s | c | none | open |\n": "ids are not",
        "| V1 | a | s | none | open |\n": "5 cells",
    }
    for text, expected in cases.items():
        found = problems(text, tmp_path)
        assert any(expected in line for line in found), (text, found)
