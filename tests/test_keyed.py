import ast
import inspect
import os
import subprocess
import sys
from collections import Counter
from hashlib import sha256

import pytest

from bicentennial import keyed
from bicentennial.canon import canon

KEY = ("seed", ("arm", "life"), 2, "draw")


def test_draw_matches_formula_and_subprocesses():
    code = (
        "from bicentennial.keyed import assert_hashseed, draw; "
        "assert_hashseed(); print(draw('seed', ('arm', 'life'), 2, 'draw'))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    outputs = [subprocess.run([sys.executable, "-c", code], env=env,
                              check=True, capture_output=True, text=True).stdout
               for _ in range(2)]
    expected = int.from_bytes(
        sha256(canon(["seed", ["arm", "life"], 2, "draw"])).digest()[:8], "big"
    )
    assert outputs == [f"{expected}\n"] * 2
    assert keyed.draw(*KEY) == expected


@pytest.mark.parametrize("hashseed", [None, "1"])
def test_hashseed_guard(hashseed):
    env = dict(os.environ)
    env.pop("PYTHONHASHSEED", None)
    if hashseed is not None:
        env["PYTHONHASHSEED"] = hashseed
    result = subprocess.run(
        [sys.executable, "-c", "from bicentennial.keyed import assert_hashseed; "
         "assert_hashseed()"], env=env, capture_output=True,
    )
    assert result.returncode == 70


def test_integer_bounds_and_small_range_distribution():
    draws = [keyed.uniform_int("seed", (str(i),), 0, "bounds", -1, 1)
             for i in range(1000)]
    assert all(-1 <= value <= 1 for value in draws)
    assert set(draws) == {-1, 0, 1}
    assert all(250 <= count <= 420 for count in Counter(draws).values())


def test_rejection_sampling_preserves_attempt_key(monkeypatch):
    calls = []
    values = iter([(1 << 64) - 1, 4])

    def draw(seed, unit, attempt, name):
        calls.append((seed, unit, attempt, name))
        return next(values)

    monkeypatch.setattr(keyed, "draw", draw)
    assert keyed.uniform_int(*KEY, 0, 2) == 1
    assert calls == [KEY, (*KEY[:3], "draw#retry1")]


def test_integer_edge_ranges():
    assert keyed.uniform_int(*KEY, 7, 7) == 7
    assert keyed.uniform_int(*KEY, 0, (1 << 64) - 1) == keyed.draw(*KEY)
    assert -(1 << 100) <= keyed.uniform_int(*KEY, -(1 << 100), 1 << 100) <= 1 << 100
    with pytest.raises(ValueError):
        keyed.uniform_int(*KEY, 2, 1)
    with pytest.raises(TypeError):
        keyed.uniform_int(*KEY, 0.0, 1)


def test_choice():
    seq = ("a", "b", "c")
    assert keyed.choice(*KEY, seq) == seq[keyed.uniform_int(*KEY, 0, 2)]
    with pytest.raises(IndexError):
        keyed.choice(*KEY, [])


def test_shuffle_is_deterministic_permutation():
    source = list(range(20))
    first = keyed.shuffle(*KEY, source)
    assert first == keyed.shuffle(*KEY, source)
    assert sorted(first) == source == list(range(20))
    assert first is not source
    assert keyed.shuffle(*KEY, []) == []
    assert keyed.shuffle(*KEY, (1,)) == [1]


def test_shuffle_names_each_swap(monkeypatch):
    names = []

    def draw(seed, unit, attempt, name):
        names.append(name)
        return 0

    monkeypatch.setattr(keyed, "draw", draw)
    assert keyed.shuffle(*KEY, [0, 1, 2, 3]) == [1, 2, 3, 0]
    assert names == ["draw#3", "draw#2", "draw#1"]


def test_minted_id_is_stable():
    expected = "bcw-" + sha256(canon(["run", 7])).hexdigest()[:16]
    assert keyed.mint_id("run", 7) == expected == keyed.mint_id("run", 7)
    assert keyed.mint_id("run", 8) != expected


def test_no_ambient_randomness_imports():
    tree = ast.parse(inspect.getsource(keyed))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"time", "random", "uuid", "datetime"}
