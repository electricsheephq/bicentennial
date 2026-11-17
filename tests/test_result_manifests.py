"""Result manifests work from both checkouts and archives, without Git."""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("result_manifests", ROOT / "scripts/result_manifests.py")
manifests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifests)

PAGE = """# A published result

Claim class: a small   fixture
  with wrapped text.

## What this does not prove (§9)

- A wider   claim
  over two lines.
- Another claim.

## Evidence

This is outside the bullet list.
"""


def result(root, name="v2/2026-11-17-example", page=PAGE):
    folder = root / "results" / name
    folder.mkdir(parents=True)
    (folder / "RESULT.md").write_text(page, encoding="utf-8")
    (folder / "artifact.txt").write_bytes(b"published\n")
    return folder


def command(root, *args):
    return manifests.main(list(args), root=root)


def seal(root):
    assert command(root, "backfill") == 0
    assert command(root, "index") == 0


@pytest.fixture
def tree(tmp_path):
    folder = result(tmp_path)
    seal(tmp_path)
    assert command(tmp_path, "check") == 0
    return tmp_path, folder


def test_repository_check():
    assert command(ROOT, "check") == 0


def test_derived_page_and_canonical_bytes(tree):
    root, folder = tree
    raw = (folder / manifests.MANIFEST).read_bytes()
    value = json.loads(raw)
    assert raw == canon(value)
    assert value["schema"] == manifests.SCHEMA
    assert value["page"] == "RESULT.md"
    assert value["title"] == "A published result"
    assert value["claim_class"] == "a small fixture with wrapped text."
    assert value["does_not_prove"] == ["A wider claim over two lines.", "Another claim."]
    assert value["published"] == "2026-11-17"
    assert value["release"] == "v2"
    assert value["backfilled"] is True
    assert value["artifacts"] == [
        dict(path=name, sha256=sha256((folder / name).read_bytes()).hexdigest(),
             bytes=(folder / name).stat().st_size) for name in ("RESULT.md", "artifact.txt")]
    index = json.loads((root / manifests.INDEX).read_bytes())
    path = (folder / manifests.MANIFEST).relative_to(root).as_posix()
    digest = sha256(raw).hexdigest()
    assert index == dict(schema="bicentennial-result-index/1",
                         manifests=[dict(path=path, sha256=digest)],
                         combined_sha256=sha256(f"{digest}  {path}\n".encode()).hexdigest())
    assert (root / manifests.INDEX).read_bytes() == canon(index)


def test_missing_manifest(tmp_path, capsys):
    result(tmp_path)
    assert command(tmp_path, "index") == 0
    assert command(tmp_path, "check") == 1
    assert "missing RESULT-MANIFEST.json" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["byte", "extra", "missing"])
def test_artifact_changes_fail(tree, change, capsys):
    root, folder = tree
    if change == "byte":
        (folder / "artifact.txt").write_bytes(b"Published\n")
    elif change == "extra":
        (folder / "extra.txt").write_bytes(b"extra")
    else:
        (folder / "artifact.txt").unlink()
    assert command(root, "check") == 1
    assert "derived fields differ: artifacts" in capsys.readouterr().out


def test_manifest_without_page(tree, capsys):
    root, folder = tree
    (folder / "RESULT.md").unlink()
    assert command(root, "check") == 1
    assert "missing RESULT.md" in capsys.readouterr().out


def test_stale_index(tree, capsys):
    root, _ = tree
    (root / manifests.INDEX).write_bytes(b"{}")
    assert command(root, "check") == 1
    assert "stale index" in capsys.readouterr().out


def test_legacy_is_unchecked_and_never_rewritten(tmp_path):
    folder = result(tmp_path, page="# Legacy\n\nProse, without the new page fields.\n")
    path = folder / manifests.MANIFEST
    original = b'{ "schema": "bicentennial-v0.1-result/1", "old": 1.5 }\n'
    path.write_bytes(original)
    seal(tmp_path)
    (folder / "artifact.txt").write_bytes(b"not checked")
    assert command(tmp_path, "check") == 0
    assert command(tmp_path, "refresh", str(folder)) == 1
    assert path.read_bytes() == original


def test_nested_result_excluded_from_parent(tmp_path):
    parent = result(tmp_path)
    child = result(tmp_path, "v2/2026-11-17-example/nested/2026-11-18-child")
    (parent / "ordinary").mkdir()
    (parent / "ordinary/é.txt").write_bytes(b"nested artifact")
    (parent / "ordinary/Z.txt").write_bytes(b"first by bytes")
    (parent / "ordinary" / manifests.MANIFEST).write_bytes(b"{}")
    seal(tmp_path)
    value = json.loads((parent / manifests.MANIFEST).read_bytes())
    assert [a["path"] for a in value["artifacts"]] == [
        "RESULT.md", "artifact.txt", "ordinary/Z.txt", "ordinary/é.txt"]
    assert (child / manifests.MANIFEST).is_file()
    # Every manifest is checked for a sibling page, even an excluded manifest name.
    assert command(tmp_path, "check") == 1
    (parent / "ordinary" / manifests.MANIFEST).unlink()
    assert command(tmp_path, "index") == 0
    assert command(tmp_path, "check") == 0


def test_refresh_keeps_extra_keys_and_provenance(tree):
    root, folder = tree
    path = folder / manifests.MANIFEST
    value = json.loads(path.read_bytes()) | dict(run_id="fixture-run", backfilled=False)
    path.write_bytes(canon(value))
    (folder / "RESULT.md").write_text(PAGE.replace("published result", "updated result"), encoding="utf-8")
    (folder / "artifact.txt").write_bytes(b"updated")
    assert command(root, "refresh", str(folder.relative_to(root))) == 0
    updated = json.loads(path.read_bytes())
    assert updated["run_id"] == "fixture-run"
    assert updated["backfilled"] is False
    assert updated["title"] == "A updated result"
    assert command(root, "index") == 0
    assert command(root, "check") == 0


def test_backfill_never_overwrites(tree):
    root, folder = tree
    path = folder / manifests.MANIFEST
    original = b"deliberately not JSON\n"
    path.write_bytes(original)
    assert command(root, "backfill") == 0
    assert path.read_bytes() == original


def test_no_exclusions_heading(tmp_path):
    folder = result(tmp_path, page="# Title\n\nClaim class: fixture\n\n## Evidence\nText.\n")
    seal(tmp_path)
    assert json.loads((folder / manifests.MANIFEST).read_bytes())["does_not_prove"] == []


@pytest.mark.parametrize("page, message", [
    ("# Title\n\nNo claim.\n", "page lacks a line starting"),
    (PAGE.replace("- A wider   claim", "A wider claim"), "must be a bullet list"),
])
def test_invalid_page_is_rejected_without_writes(tmp_path, page, message, capsys):
    folder = result(tmp_path, page=page)
    assert command(tmp_path, "backfill") == 1
    assert message in capsys.readouterr().out
    assert not (folder / manifests.MANIFEST).exists()


def test_malformed_manifest_fails(tree, capsys):
    root, folder = tree
    (folder / manifests.MANIFEST).write_bytes(b"{")
    assert command(root, "index") == 0
    assert command(root, "check") == 1
    assert "Expecting property name" in capsys.readouterr().out


def test_changed_derived_field_fails(tree, capsys):
    root, folder = tree
    path = folder / manifests.MANIFEST
    value = json.loads(path.read_bytes()) | dict(claim_class="unpublished claim")
    path.write_bytes(canon(value))
    assert command(root, "index") == 0
    assert command(root, "check") == 1
    assert "derived fields differ: claim_class" in capsys.readouterr().out


@pytest.mark.parametrize("raw, message", [
    (b"[1, 2]", "manifest must be a JSON object"),
    (b"null", "manifest must be a JSON object"),
    (b"{}", "unknown schema None"),
    (b'{"schema":1}', "unknown schema 1"),
    (b'{"claim_class":"UNPUBLISHED 99%","schema":"bicentennial-result-manifest/2"}',
     "unknown schema 'bicentennial-result-manifest/2'"),
])
def test_unknown_or_non_object_manifest_fails(tree, raw, message, capsys):
    root, folder = tree
    (folder / manifests.MANIFEST).write_bytes(raw)
    assert command(root, "index") == 0
    assert command(root, "check") == 1
    assert message in capsys.readouterr().out


def test_non_canonical_manifest_fails(tree, capsys):
    root, folder = tree
    path = folder / manifests.MANIFEST
    path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=2).encode("utf-8"))
    assert command(root, "index") == 0
    assert command(root, "check") == 1
    assert "not canonical JSON" in capsys.readouterr().out


@pytest.mark.parametrize("line, claim", [
    ("## Evidence", "fixture"),
    ("#", "fixture"),
    ("###### Sixth level", "fixture"),
    ("#537 defines it.", "fixture #537 defines it."),
    ("####### is not a heading", "fixture ####### is not a heading"),
])
def test_claim_stops_only_at_a_heading(tmp_path, line, claim):
    folder = result(tmp_path, page=f"# Title\n\nClaim class: fixture\n{line}\n\n## Evidence\nText.\n")
    seal(tmp_path)
    assert json.loads((folder / manifests.MANIFEST).read_bytes())["claim_class"] == claim


def test_generated_caches_are_not_artifacts(tree):
    root, folder = tree
    before = (folder / manifests.MANIFEST).read_bytes()
    for name in ("__pycache__", ".pytest_cache", ".ruff_cache"):
        (folder / name).mkdir()
        (folder / name / "cache.bin").write_bytes(b"machine-specific")
    (folder / "table.cpython-314.pyc").write_bytes(b"bytecode")
    (folder / "old.pyo").write_bytes(b"bytecode")
    (folder / ".DS_Store").write_bytes(b"finder")
    assert command(root, "check") == 0
    assert command(root, "refresh", str(folder.relative_to(root))) == 0
    assert (folder / manifests.MANIFEST).read_bytes() == before


def test_float_extra_key_fails(tree, capsys):
    root, folder = tree
    path = folder / manifests.MANIFEST
    value = json.loads(path.read_bytes()) | dict(score=0.5)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    assert command(root, "index") == 0
    assert command(root, "check") == 1
    assert "unsupported canonical JSON type: float" in capsys.readouterr().out
