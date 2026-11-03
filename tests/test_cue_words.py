"""Action requests must require memory without announcing that a memory exists."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial import cue_words


def template(tmp_path, prompt, *, action=True):
    path = tmp_path / "sample.py"
    table = ', decision_table_ref="table"' if action else ""
    # Parsing must never execute the source, even if it cannot be imported.
    path.write_text(f'raise RuntimeError("do not import")\nInstance(prompt={prompt}{table})\n')
    return path


def test_current_templates():
    requests = cue_words.template_requests()
    expected = []
    for path in sorted(cue_words.TEMPLATES.rglob("*.py")):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Instance"
                    and any(kw.arg == "decision_table_ref" for kw in node.keywords)):
                expected.append((path, node.lineno))
    assert expected
    assert len(requests) == len(expected)
    assert {(r.source, int(r.item.split(":")[1])) for r in requests} == set(expected)
    assert not cue_words.check_requests(requests)


@pytest.mark.parametrize("prompt", ['"Use the usual setting."', 'f"Use {name}: as agreed."'])
def test_planted_template(tmp_path, prompt):
    path = template(tmp_path, prompt)
    hits = cue_words.check_requests(cue_words.template_requests(tmp_path))
    assert hits
    assert all(hit.source == path and hit.item.startswith("sample:2:") for hit in hits)
    assert ("as agreed" if prompt.startswith("f") else "usual") in [hit.phrase for hit in hits]


def test_recall_template_excluded(tmp_path):
    template(tmp_path, '"What is my usual setting?"', action=False)
    assert not cue_words.check_requests(cue_words.template_requests(tmp_path))


def test_fstring_gap(tmp_path):
    template(tmp_path, 'f"Use as {name}agreed; do it like {other}last time."')
    requests = cue_words.template_requests(tmp_path)
    assert len(requests) == 1
    assert not cue_words.check_requests(requests)


@pytest.mark.parametrize("text,phrase", [
    ("unusual", None), ("usually", None), ("preroutine", None),
    ("As Usual", "as usual"), ("re-established", "established"),
    ("AS\n  AGREED", "as agreed"), ("(routine)", "routine"),
])
def test_boundaries(text, phrase):
    hits = cue_words.check_requests([cue_words.Request(Path("sample.py"), "sample", (text,))])
    assert bool(hits) == (phrase is not None)
    if phrase:
        assert phrase in [hit.phrase for hit in hits]


@pytest.mark.parametrize("phrase", [
    "usual", "as usual", "as always", "established", "our regular", "like last time",
    "the same as before", "the usual", "my usual", "as before", "same as last time",
    "as we discussed", "as agreed", "the regular", "routine",
])
def test_vocabulary(phrase):
    hits = cue_words.check_requests([
        cue_words.Request(Path("sample.py"), "sample", (f"Please use {phrase.upper()}.",)),
    ])
    assert phrase in [hit.phrase for hit in hits]


def test_all_modules_and_calls(tmp_path):
    nested = tmp_path / "unselected"
    nested.mkdir()
    path = template(nested, '"Use routine."')
    with path.open("a") as stream:
        stream.write('protocol.Instance(prompt="As agreed.", decision_table_ref="table")\n')
    requests = cue_words.template_requests(tmp_path)
    assert len(requests) == 2
    assert [hit.phrase for hit in cue_words.check_requests(requests)] == ["routine", "as agreed"]


@pytest.mark.parametrize("prompt", ["request_text", '"Use " + name', "None"])
def test_unsupported_action_prompt(tmp_path, prompt):
    template(tmp_path, prompt)
    with pytest.raises(ValueError, match="constant or f-string"):
        cue_words.template_requests(tmp_path)



@pytest.mark.parametrize("call,match", [
    ('Instance(**common)', "keyword arguments only"),
    ('Instance("key", prompt="Use it.", decision_table_ref="table")', "keyword arguments only"),
    ('replace(base, prompt="Use the usual setting.")', "replace"),
    ('replace(base, decision_table_ref="table")', "replace"),
    ('dataclasses.replace(base, **fields)', "replace"),
])
def test_unsupported_instance_call(tmp_path, call, match):
    # An action request the walker cannot read must fail, never vanish from the check.
    (tmp_path / "sample.py").write_text(f"{call}\n")
    with pytest.raises(ValueError, match=match):
        cue_words.template_requests(tmp_path)


def test_text_replace_is_not_a_prompt(tmp_path):
    template(tmp_path, 'f"Record the {p.replace(\'_\', \' \')} in {path}."')
    assert len(cue_words.template_requests(tmp_path)) == 1

def fake_pack(tmp_path, *, cue=True):
    root = tmp_path / "pack"
    life = root / "sealed" / "life"
    life.mkdir(parents=True)
    for branch in ("B0", "B1"):
        rows = [dict(item_id=f"action-{branch}", stage="act",
                     prompt="Use the regular setting." if cue else "Use this setting."),
                dict(item_id=f"recall-{branch}", stage="remember",
                     prompt="What is the usual routine?")]
        (life / f"items.{branch}.json").write_text(json.dumps(rows))
    (root / "manifest.json").write_text('{"untouched": true}\n')
    return root


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_pack_action_and_recall_readonly(tmp_path):
    root = fake_pack(tmp_path)
    before = snapshot(root)
    hits = cue_words.check_requests(cue_words.pack_requests(root))
    assert [(h.source.name, h.item, h.phrase) for h in hits] == [
        (f"items.{branch}.json", f"action-{branch}", "the regular") for branch in ("B0", "B1")]
    assert snapshot(root) == before


def test_pack_recall_excluded(tmp_path):
    root = fake_pack(tmp_path, cue=False)
    before = snapshot(root)
    assert not cue_words.check_requests(cue_words.pack_requests(root))
    assert snapshot(root) == before


def cli(*args):
    return subprocess.run([sys.executable, "-m", "bicentennial.cue_words", *map(str, args)],
                          capture_output=True, text=True, check=False)


def test_cli_clean():
    result = cli()
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_cli_hit(tmp_path):
    path = template(tmp_path, '"Use as agreed."')
    result = cli("--templates", tmp_path)
    assert result.returncode == 1, result.stderr
    assert result.stdout.splitlines() == [f"{path}: sample:2:0: as agreed"]
    assert result.stderr == ""


def test_cli_pack_hit(tmp_path):
    root = fake_pack(tmp_path)
    before = snapshot(root)
    result = cli(root)
    assert result.returncode == 1, result.stderr
    assert result.stdout.splitlines() == [
        f"{root / 'sealed/life' / f'items.{branch}.json'}: action-{branch}: the regular"
        for branch in ("B0", "B1")]
    assert snapshot(root) == before


@pytest.mark.parametrize("case", ["flag", "missing", "templates-missing", "empty", "no-items", "syntax",
                                  "expression", "json"])
def test_cli_usage_error(tmp_path, case):
    if case == "flag":
        args = ["--unknown"]
    elif case == "missing":
        args = [tmp_path / "missing"]
    elif case == "templates-missing":
        args = ["--templates", tmp_path / "missing"]
    elif case == "empty":
        args = ["--templates", tmp_path]
    elif case == "no-items":
        (tmp_path / "sealed" / "life").mkdir(parents=True)
        (tmp_path / "sealed" / "life" / "manifest.json").write_text("{}")
        args = [tmp_path]
    elif case == "syntax":
        (tmp_path / "sample.py").write_text("Instance(")
        args = ["--templates", tmp_path]
    elif case == "expression":
        template(tmp_path, "request_text")
        args = ["--templates", tmp_path]
    else:
        (tmp_path / "items.B0.json").write_text("{")
        args = [tmp_path]
    result = cli(*args)
    assert result.returncode == 2
    assert "error:" in result.stderr
    guard = {"templates-missing": "not a template directory", "no-items": "no branch item files"}.get(case)
    assert guard is None or guard in result.stderr
    assert result.stdout == ""
