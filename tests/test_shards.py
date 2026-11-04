"""Offline placement, measurement, log rebuilding, and whole-file collection checks."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import conftest as shards
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/shard_weights.py"


@pytest.mark.parametrize("total", range(1, 13))
@pytest.mark.parametrize("source", ["synthetic", "committed"])
def test_partition_and_input_order(total, source):
    if source == "synthetic":
        files = [f"tests/test_{index:02}.py" for index in range(31)]
        weights = {path: float(index % 7 + 1) for index, path in enumerate(files[:20])}
    else:
        weights = json.loads((ROOT / "tests/shard_weights.json").read_text())
        files = sorted(set(weights) | {"tests/test_unlisted_a.py", "tests/test_unlisted_b.py"})
    placement = shards.place(files, weights, total)
    selections = [{path for path, index in placement.items() if index == shard} for shard in range(total)]
    assert set(placement) == set(files)
    assert set().union(*selections) == set(files)
    assert sum(map(len, selections)) == len(files)
    assert all(0 <= index < total for index in placement.values())
    assert shards.place(list(reversed(files)), weights, total) == placement
    assert shards.place(files[1:] + files[:1], weights, total) == placement


def test_path_and_shard_ties():
    assert shards.place(["c", "b", "a", "d"], {}, 3) == {"a": 0, "b": 1, "c": 2, "d": 0}


@pytest.mark.parametrize("absent_weight, expected", [
    (None, {"a": 0, "m": 1, "n": 1, "z": 0}),
    (100, {"a": 0, "m": 1, "n": 0, "z": 1}),
])
def test_unlisted_uses_table_median(absent_weight, expected):
    weights = {"a": 8.0, "z": 2.0}
    if absent_weight is not None:
        weights["not_collected"] = absent_weight
    assert shards.place(["z", "n", "m", "a"], weights, 2) == expected


def test_empty_table_uses_one_second():
    assert shards.place(["c", "b", "a"], {}, 2) == {"a": 0, "b": 1, "c": 0}


def test_greedy_balance():
    weights = dict(zip("abcdef", [9, 8, 7, 6, 5, 4], strict=True))
    placement = shards.place(list(reversed(weights)), weights, 3)
    assert placement == {"a": 0, "b": 1, "c": 2, "d": 2, "e": 1, "f": 0}
    assert [sum(weights[path] for path, index in placement.items() if index == shard)
            for shard in range(3)] == [13, 13, 13]


def hook_config():
    plugins, deselected = [], []
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(register=plugins.append),
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    return config, plugins, deselected


def test_hook_places_sorted_unique_files_once(monkeypatch):
    monkeypatch.setenv("BICENTENNIAL_TEST_SHARDS", "2")
    monkeypatch.setenv("BICENTENNIAL_TEST_SHARD", "0")
    monkeypatch.setattr(shards, "_load_weights", lambda: {})
    calls = []
    original = shards.place

    def capture(files, weights, total):
        calls.append(list(files))
        return original(files, weights, total)

    monkeypatch.setattr(shards, "place", capture)
    items = [SimpleNamespace(nodeid=node) for node in
             ["tests/z.py::test_b", "tests/a.py::test_a", "tests/z.py::test_a", "tests/m.py::test_a"]]
    config, plugins, deselected = hook_config()
    shards.pytest_collection_modifyitems(config, items)
    assert calls == [["tests/a.py", "tests/m.py", "tests/z.py"]]
    assert [item.nodeid for item in items] == ["tests/z.py::test_b", "tests/a.py::test_a", "tests/z.py::test_a"]
    assert [item.nodeid for item in deselected] == ["tests/m.py::test_a"]
    assert len(plugins) == 1


@pytest.mark.parametrize("total", [None, "", "0", "1", "-2"])
def test_unsharded_hook_returns_early(monkeypatch, total):
    if total is None:
        monkeypatch.delenv("BICENTENNIAL_TEST_SHARDS", raising=False)
    else:
        monkeypatch.setenv("BICENTENNIAL_TEST_SHARDS", total)
    monkeypatch.setenv("BICENTENNIAL_TEST_SHARD", "invalid but unused")
    monkeypatch.setattr(shards, "_load_weights", lambda: pytest.fail("table must not be read"))
    config, plugins, deselected = hook_config()
    items = [SimpleNamespace(nodeid="tests/a.py::test_a")]
    shards.pytest_collection_modifyitems(config, items)
    assert len(items) == 1 and not plugins and not deselected


@pytest.mark.parametrize("total, index, reason", [
    ("bad", "0", "must be an integer"), ("2", "bad", "must be an integer"),
    ("2", "-1", "out of range"), ("2", "2", "out of range"),
])
def test_invalid_shard_settings(monkeypatch, total, index, reason):
    monkeypatch.setenv("BICENTENNIAL_TEST_SHARDS", total)
    monkeypatch.setenv("BICENTENNIAL_TEST_SHARD", index)
    with pytest.raises(pytest.UsageError, match=reason):
        shards.pytest_collection_modifyitems(hook_config()[0], [])


def test_table_relative_to_conftest_and_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shards, "__file__", str(tmp_path / "conftest.py"))
    monkeypatch.chdir(ROOT)
    assert shards._load_weights() == {}
    (tmp_path / "shard_weights.json").write_text('{"tests/a.py": 2.3}')
    assert shards._load_weights() == {"tests/a.py": 2.3}


@pytest.mark.parametrize("contents", ["{", "[]", '{"a": -1}', '{"a": true}',
                                     '{"a": "2"}', '{"a": NaN}', '{"a": Infinity}', "\xff"])
def test_invalid_table(monkeypatch, tmp_path, contents):
    monkeypatch.setattr(shards, "__file__", str(tmp_path / "conftest.py"))
    (tmp_path / "shard_weights.json").write_bytes(contents.encode("latin1"))
    with pytest.raises(pytest.UsageError, match="cannot load"):
        shards._load_weights()


def test_unreadable_table(monkeypatch, tmp_path):
    monkeypatch.setattr(shards, "__file__", str(tmp_path / "conftest.py"))
    (tmp_path / "shard_weights.json").mkdir()
    with pytest.raises(pytest.UsageError, match="cannot load"):
        shards._load_weights()


def test_measurement_sums_all_phases_and_formats_line():
    plugin = shards._ShardDurations(1, 7)
    # tests/m.py rounds to 0.1 only when the phases are summed before rounding.
    for path, durations in [("tests/z.py", [0.11, 1.21, 0.32]), ("tests/a.py", [0.2, 0.3, 0.4]),
                            ("tests/m.py", [0.04, 0.04, 0.04])]:
        for when, duration in zip(["setup", "call", "teardown"], durations, strict=True):
            plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=f"{path}::test_x", when=when, duration=duration))
    plugin.pytest_runtest_logreport(SimpleNamespace(nodeid="tests/a.py::test_y", when="setup", duration=0.2))
    lines = []
    reporter = SimpleNamespace(write_line=lines.append)
    plugin.pytest_terminal_summary(reporter)
    assert lines == ['shard-durations v1 1 7 {"tests/a.py":1.1,"tests/m.py":0.1,"tests/z.py":1.6}']


def run_tiny_pytest(root, total=None, index=None, collect=True):
    env = os.environ.copy()
    for name in ("BICENTENNIAL_TEST_SHARDS", "BICENTENNIAL_TEST_SHARD"):
        env.pop(name, None)
    if total is not None:
        env.update(BICENTENNIAL_TEST_SHARDS=str(total), BICENTENNIAL_TEST_SHARD=str(index))
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", "pytest.ini"]
    if collect:
        args.append("--collect-only")
    result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode in (0, 5), result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def tiny_tree(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    shutil.copy(ROOT / "tests/conftest.py", tests / "conftest.py")
    (tests / "shard_weights.json").write_text('{"tests/test_c.py": 9.0, "tests/test_a.py": 3.0}')
    for name in "abcde":
        (tests / f"test_{name}.py").write_text("def test_one(): pass\ndef test_two(): pass\n")
    return tmp_path


@pytest.mark.parametrize("total", [2, 3])
def test_collection_partition_end_to_end(tiny_tree, total):
    def nodes(output):
        return {line for line in output.splitlines() if line.startswith("tests/") and "::" in line}

    baseline = nodes(run_tiny_pytest(tiny_tree))
    selections = [nodes(run_tiny_pytest(tiny_tree, total, index)) for index in range(total)]
    assert len(baseline) == 10
    assert set().union(*selections) == baseline
    assert sum(map(len, selections)) == len(baseline)
    for path in {node.split("::")[0] for node in baseline}:
        assert sum(any(node.startswith(path + "::") for node in selected) for selected in selections) == 1


def test_quiet_measurement_and_unsharded_silence(tiny_tree):
    for total, indices in [(None, [None]), (1, [0]), (2, range(2)), (7, range(7))]:
        for index in indices:
            output = run_tiny_pytest(tiny_tree, total, index, collect=False)
            lines = [line for line in output.splitlines() if line.startswith("shard-durations v1 ")]
            if total is None or total < 2:
                assert not lines
                continue
            assert len(lines) == 1, output
            assert lines[0].startswith(f"shard-durations v1 {index} {total} ")
            payload = lines[0].split(maxsplit=4)[4]
            weights = json.loads(payload)
            expected = shards.place([f"tests/test_{name}.py" for name in "abcde"],
                                    {"tests/test_c.py": 9.0, "tests/test_a.py": 3.0}, total)
            assert set(weights) == {path for path, shard in expected.items() if shard == index}
            assert all(type(value) is float and value >= 0 and value == round(value, 1)
                       for value in weights.values())
            assert payload == json.dumps(weights, sort_keys=True, separators=(",", ":"))


def log_line(index, total, weights):
    return f"shard-durations v1 {index} {total} {json.dumps(weights)}\n"


def run_script(tmp_path, logs, existing=False):
    paths = []
    for index, content in enumerate(logs):
        path = tmp_path / f"job-{index}.log"
        path.write_text(content)
        paths.append(str(path))
    out = tmp_path / "weights.json"
    if existing:
        out.write_text("preserve me\n")
    result = subprocess.run([sys.executable, str(SCRIPT), *paths, "--out", str(out)],
                            capture_output=True, text=True)
    return result, out


def test_script_merges_timestamped_logs(tmp_path):
    result, out = run_script(tmp_path, [
        "2026-11-04T08:00:00.1234567Z unrelated output\n"
        + "2026-11-04T08:00:00.1234567Z " + log_line(1, 3, {"tests/z.py": 12.34}),
        log_line(0, 3, {"tests/a.py": 0.06}) + "2026-11-04T08:00:01Z " + log_line(2, 3, {}),
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
    assert out.read_text() == '{\n "tests/a.py": 0.1,\n "tests/z.py": 12.3\n}\n'


@pytest.mark.parametrize("invalid, logs, reason", [
    ("mixed", [log_line(0, 2, {}) + log_line(1, 3, {})], "mixed shard totals"),
    ("missing", [log_line(0, 2, {})], "missing shard index"),
    ("repeated", [log_line(0, 2, {}) + log_line(0, 2, {}) + log_line(1, 2, {})], "repeated shard index"),
    ("duplicate_file", [log_line(0, 2, {"a": 1}) + log_line(1, 2, {"a": 2})], "file in two shards"),
    ("duplicate_key", ['shard-durations v1 0 2 {"a":1,"a":2}\n' + log_line(1, 2, {})], "duplicate file"),
    ("no_lines", ["ordinary pytest output\n"], "no shard-durations"),
    ("bad_index", [log_line(2, 2, {})], "out of range"),
    ("bad_total", [log_line(0, 1, {})], "out of range"),
    ("bad_json", ["shard-durations v1 0 2 {\n"], "Expecting"),
    ("bad_line", ["shard-durations v1 0\n"], "malformed"),
    ("negative", [log_line(0, 2, {"a": -1})], "finite nonnegative"),
    ("boolean", [log_line(0, 2, {"a": True})], "finite nonnegative"),
    ("nan", [log_line(0, 2, {"a": float("nan")})], "finite nonnegative"),
    ("array", ["shard-durations v1 0 2 []\n"], "expected an object"),
])
@pytest.mark.parametrize("existing", [False, True])
def test_script_refusals_write_nothing(tmp_path, invalid, logs, reason, existing):
    result, out = run_script(tmp_path, logs, existing)
    assert result.returncode != 0, invalid
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert reason in result.stderr
    if existing:
        assert out.read_text() == "preserve me\n"
    else:
        assert not out.exists()


def test_script_missing_log_and_default_destination(tmp_path):
    spec = importlib.util.spec_from_file_location("shard_weights", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.DEFAULT_OUT == ROOT / "tests/shard_weights.json"
    out = tmp_path / "out.json"
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "absent"), "--out", str(out)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and len(result.stderr.splitlines()) == 1
    assert not out.exists()
