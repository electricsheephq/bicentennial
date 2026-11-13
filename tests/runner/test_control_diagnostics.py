"""A live control arm's diagnostic trace (#505, #506): kept outside the run, with the run's own bytes unchanged."""

import json
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest
from test_control_arms import _digests, control_scenario  # noqa: F401
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner import diagnostics, t2, units

ARMS = ("no_memory", "oracle_evidence")
SECRET = "synthetic-access-token"  # the fixture login home's own access token
LATE = "synthetic-late-needle"
MID = "synthetic-mid-attempt-needle"


@pytest.fixture
def traced(control_scenario, monkeypatch):  # noqa: F811
    """The control fixture's lives, each with a request trail, workspace clones, act state and final replies."""
    s = control_scenario
    s.plant = {}  # where -> (life, branch) whose bytes carry a planted string
    s.unparsed = None  # (life, branch) whose act items have no parsed state, as after a read_state failure
    drive = units.run_life

    def life(**kw):
        run = drive(**kw)
        key, root = (kw["life_dir"].name, kw["branch"]), run._root
        store = BlobStore(root / "run/ledger/blobs", Guard([]))
        text = "synthetic request" + (" " + s.plant["request"][1] if s.plant.get("request", (None,))[0] == key else "")
        req = store.put({"messages": [{"role": "user", "content": text}]})
        upstream = [dict(role="probe_main", served_by="live", req=store.put({"input": "synthetic upstream"}),
                         resp=store.put({"output": "synthetic upstream reply"}))]
        records = tuple(dict(r, req=req, upstream=upstream) for r in run.records)
        surface, workspace = (root / "probe/21" / n for n in ("0", "1"))
        (surface / "store").mkdir(parents=True)
        (surface / "store/notes").write_bytes(b"surface clone, not the workspace")
        (workspace / "docs").mkdir(parents=True)
        (workspace / "docs/decisions.md").write_bytes(b"synthetic decision\n")
        body = b"synthetic edit\n" + (s.plant["workspace"][1].encode() if s.plant.get(
            "workspace", (None,))[0] == key else b"")
        (workspace / "app.py").write_bytes(body)
        act = {i["item_id"]: {"paths": {"app.py": "synthetic edit"}} for i in kw["items"]
               if i["stage"] == "act" and key != s.unparsed}
        finals = ((1, "synthetic final one"), (3, "synthetic final three"))
        return replace(run, records=records, act=act, sessions=(SimpleNamespace(session=21, finals=finals),))

    monkeypatch.setattr(units, "run_life", life)
    return s


def run_pair(s, tmp_path, control, **kw):
    """The same control run without and with --diagnostics; returns both run directories and DIR."""
    assert s.invoke("plain", control=control) == 0
    root = tmp_path / "diag"
    assert s.invoke("traced", control=control, diagnostics=root, **kw) == 0
    return tmp_path / "plain", tmp_path / "traced", root


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("control", ARMS)
def test_1_diagnostics_change_no_byte_under_out(traced, tmp_path, control):
    """With the option, the run directory differs only in its timing fields: the copy's time falls inside the unit and
    run timings (units.json, the receipts, arm_time), which _digests zeroes. Without it, test_f holds the exact bytes."""
    plain, out, root = run_pair(traced, tmp_path, control)
    assert _digests(out) == _digests(plain)
    assert not any("diag" in p.name or p.name == "manifest.json" for p in out.rglob("*"))
    assert files(root)


def test_1_default_arm_is_unchanged():
    # The option never enters an Arm's identity: an arm with a writer equals the arm without one.
    arm = units.Arm("no_memory", {"name": "x"}, role="no_memory")
    assert replace(arm, diagnostics=object()) == arm and "diagnostics" not in repr(replace(arm, diagnostics=1))
    with pytest.raises(ValueError, match="only a control arm"):
        units.Arm("system", {"name": "x"}, diagnostics=object())


@pytest.mark.parametrize("case", ["no_control", "exists", "in_out", "out_in", "in_home", "in_packs", "in_lease"])
def test_2_refused_before_out_exists(traced, tmp_path, capsys, case):
    s = traced
    out = tmp_path / ("nest/out" if case == "out_in" else "out")
    root = {"exists": tmp_path / "taken", "in_out": out / "diag", "out_in": tmp_path / "nest",
            "in_home": s.home / "diag", "in_packs": tmp_path / "packs/diag",
            "in_lease": tmp_path / "bicentennial-0/diag"}.get(case, tmp_path / "diag")
    if case == "exists":
        root.mkdir()
    code = "diagnostics_control" if case == "no_control" else (
        "diagnostics_exists" if case == "exists" else "diagnostics_overlap")
    assert s.invoke(out=out, diagnostics=root, **({} if case == "no_control" else {"control": "oracle_evidence"})) == 3
    assert capsys.readouterr().err.split() == [code]
    assert not out.exists()
    assert root.is_dir() == (case == "exists") and (case != "exists" or not any(root.iterdir()))


def test_3_content_and_manifest(traced, tmp_path):
    s = traced
    _, out, root = run_pair(s, tmp_path, "oracle_evidence")
    kept = files(root)
    manifest = json.loads(kept.pop("manifest.json"))
    assert manifest["commit"] == s.ctx.pins["benchmark_commit"] and manifest["control"] == "oracle_evidence"
    assert manifest["rescan"] == "clean" and manifest["skips"] == [] and manifest["failures"] == []
    assert {r["path"]: (r["bytes"], r["sha256"]) for r in manifest["files"]} == {
        k: (len(v), sha256(v).hexdigest()) for k, v in kept.items()}
    for pack in s.ctx.packs:
        for branch in ("B0", "B1"):
            for turn, item in enumerate(pack.items[branch], 1):
                base = f"{pack.life}/{branch}/0/{item['item_id']}"
                assert json.loads(kept[f"{base}/probe.json"])["item_id"] == item["item_id"]
                assert json.loads(kept[f"{base}/score.json"])["item_id"] == item["item_id"]
                rows = json.loads(kept[f"{base}/trajectory.json"])
                assert rows and all(r["role"] == "probe_main" and r["cursor"]["session"] == 21 for r in rows)
                assert rows[0]["bodies"]["req"]["messages"][0]["content"] == "synthetic request"
                assert rows[0]["bodies"]["resp"]["choices"][0]["message"]["content"]
                assert rows[0]["bodies"]["upstream"] == [{"req": {"input": "synthetic upstream"},
                                                         "resp": {"output": "synthetic upstream reply"}}]
                if item["stage"] == "act":
                    assert json.loads(kept[f"{base}/act.json"]) == {"paths": {"app.py": "synthetic edit"}}
                    # The workspace clone (the last one), not the surface clone before it.
                    assert {k for k in kept if k.startswith(base + "/workspace/")} == {
                        f"{base}/workspace/app.py", f"{base}/workspace/docs/decisions.md"}
                    assert f"{base}/final.txt" not in kept
                else:
                    assert f"{base}/act.json" not in kept and not any(k.startswith(base + "/workspace") for k in kept)
                    expected = {1: b"synthetic final one", 3: b"synthetic final three"}.get(turn)
                    assert kept.get(f"{base}/final.txt") == expected
    assert any(i["stage"] == "act" for p in s.ctx.packs for i in p.items["B0"])


@pytest.mark.parametrize("where", ["request", "workspace"])
def test_4_planted_needle_skips_its_file(traced, tmp_path, where):
    s = traced
    pack = s.ctx.packs[1]
    s.plant[where] = ((pack.life, "B1"), SECRET)
    plain, out, root = run_pair(s, tmp_path, "oracle_evidence")
    assert _digests(out) == _digests(plain)
    raw = files(root)
    assert not any(SECRET.encode() in v for v in raw.values())
    manifest = json.loads(raw["manifest.json"])
    if where == "request":
        skipped = {f"{pack.life}/B1/0/{i['item_id']}/trajectory.json" for i in pack.items["B1"]}
    else:
        skipped = {f"{pack.life}/B1/0/{i['item_id']}/workspace/app.py" for i in pack.items["B1"] if i["stage"] == "act"}
    assert manifest["skips"] == [dict(path=p, reason="credential") for p in sorted(skipped)]
    assert not skipped & set(raw) and manifest["rescan"] == "clean"
    # The same file of the other branch is kept.
    assert any(k.startswith(f"{pack.life}/B0/") and k.endswith(sorted(skipped)[0].rsplit("/", 1)[1]) for k in raw)


def test_4_a_needle_only_the_end_knows_is_reported(traced, tmp_path, monkeypatch, capsys):
    s = traced
    pack = s.ctx.packs[1]
    s.plant["workspace"] = ((pack.life, "B0"), LATE)
    build = t2.build_live_stack

    def stack(path, **kw):
        live = build(path, **kw)
        # The live login learns this needle only by the run's end, as a refreshed token would be learnt.
        live.inner.login.needles = lambda: {LATE: 1} if live.closed else {}
        return live

    monkeypatch.setattr(t2, "build_live_stack", stack)
    plain, out, root = run_pair(s, tmp_path, "oracle_evidence")
    assert _digests(out) == _digests(plain)
    assert capsys.readouterr().err.split() == ["diagnostics_credential"]
    raw = files(root)
    manifest = json.loads(raw["manifest.json"])
    hits = [f"{pack.life}/B0/0/{i['item_id']}/workspace/app.py" for i in pack.items["B0"] if i["stage"] == "act"]
    assert hits and manifest["rescan"] == dict(hits=hits, errors=[])
    assert LATE.encode() not in raw["manifest.json"] and all(h in raw for h in hits)  # reported, never moved


def test_9_a_failing_writer_changes_nothing(traced, tmp_path, monkeypatch, capsys):
    class Broken(BlobStore):
        def get(self, h):
            raise OSError("synthetic blob failure")

    monkeypatch.setattr(diagnostics, "BlobStore", Broken)
    plain, out, root = run_pair(traced, tmp_path, "oracle_evidence")
    assert _digests(out) == _digests(plain)
    manifest = json.loads((root / "manifest.json").read_bytes())
    failed = {r["path"] for r in manifest["failures"]}
    assert failed == {f"{p.life}/{b}/0/{i['item_id']}/trajectory.json"
                      for p in traced.ctx.packs for b in ("B0", "B1") for i in p.items[b]}
    assert {r["error"] for r in manifest["failures"]} == {"OSError"}
    assert "synthetic blob failure" not in (root / "manifest.json").read_text()
    assert capsys.readouterr().err == ""


def test_9_a_failing_manifest_is_one_warning(traced, tmp_path, monkeypatch, capsys):
    def broken(*args):
        raise OSError("synthetic manifest failure")

    monkeypatch.setattr(diagnostics.Diagnostics, "_label", staticmethod(broken))
    plain, out, root = run_pair(traced, tmp_path, "no_memory")
    assert _digests(out) == _digests(plain)
    assert capsys.readouterr().err.split() == ["diagnostics_manifest"]
    assert not (root / "manifest.json").exists()


def test_4_a_file_is_never_overwritten(tmp_path):
    home = tmp_path / "login"
    home.mkdir()
    (home / "auth.json").write_bytes(b'{"tokens": {"access_token": "synthetic-access-token"}}')
    keeper = diagnostics.Diagnostics(tmp_path / "diag", home)
    keeper.create()
    keeper._put("a/b.txt", b"first")
    keeper._put("a/b.txt", b"second")
    assert (tmp_path / "diag/a/b.txt").read_bytes() == b"first"
    assert [p.name for p in (tmp_path / "diag/a").iterdir()] == ["b.txt"]  # no temp file left
    assert keeper.failures == [dict(path="a/b.txt", error="FileExistsError")]
    assert oct((tmp_path / "diag").stat().st_mode & 0o777) == oct(0o700)


def test_d1_an_unparsed_act_item_keeps_its_workspace(traced, tmp_path):
    s = traced
    pack = s.ctx.packs[1]
    s.unparsed = (pack.life, "B1")
    _, _, root = run_pair(s, tmp_path, "oracle_evidence")
    raw = files(root)
    manifest = json.loads(raw["manifest.json"])
    acts = [i["item_id"] for i in pack.items["B1"] if i["stage"] == "act"]
    assert acts
    for iid in acts:
        base = f"{pack.life}/B1/0/{iid}"
        assert f"{base}/act.json" not in raw and f"{pack.life}/B0/0/{iid}/act.json" in raw
        assert {k for k in raw if k.startswith(base + "/workspace/")} == {
            f"{base}/workspace/app.py", f"{base}/workspace/docs/decisions.md"}
        assert dict(path=f"{base}/act.json", reason="no parsed state") in manifest["skips"]


def test_d2_needles_are_read_for_each_file(traced, tmp_path, monkeypatch):
    s = traced
    pack = s.ctx.packs[1]
    s.plant["workspace"] = ((pack.life, "B0"), MID)
    attempt = tmp_path / "diag" / pack.life / "B0" / "0"
    build = t2.build_live_stack

    def stack(path, **kw):
        live = build(path, **kw)
        # The login learns this needle only once the attempt has written its first file, as another unit's refresh
        # would teach it mid-attempt.
        live.inner.login.needles = lambda: {MID: 1} if attempt.is_dir() and any(
            p.is_file() for p in attempt.rglob("*")) else {}
        return live

    monkeypatch.setattr(t2, "build_live_stack", stack)
    plain, out, root = run_pair(s, tmp_path, "oracle_evidence")
    assert _digests(out) == _digests(plain)
    raw = files(root)
    assert not any(MID.encode() in v for v in raw.values())
    skipped = [f"{pack.life}/B0/0/{i['item_id']}/workspace/app.py" for i in pack.items["B0"] if i["stage"] == "act"]
    manifest = json.loads(raw["manifest.json"])
    assert skipped and all(dict(path=p, reason="credential") in manifest["skips"] for p in skipped)
    assert manifest["rescan"] == "clean"


def workspace_keeper(tmp_path, build):
    """A writer and a fake attempt whose probe session 21 has a surface clone 0 and a workspace clone 1."""
    home = tmp_path / "login"
    home.mkdir()
    (home / "auth.json").write_bytes(b'{"tokens": {"access_token": "synthetic-access-token"}}')
    keeper = diagnostics.Diagnostics(tmp_path / "diag", home)
    assert keeper.create() is None
    run = SimpleNamespace(_root=tmp_path / "attempt")
    (run._root / "probe/21/0").mkdir(parents=True)
    workspace = run._root / "probe/21/1"
    workspace.mkdir()
    build(workspace)
    keeper._workspace("item", run, 21)
    return keeper, sorted(keeper.files)


def test_d3_an_oversized_file_is_skipped_unread(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_FILE_BYTES", 10)
    keeper, kept = workspace_keeper(tmp_path, lambda w: (
        (w / "big.bin").write_bytes(b"x" * 11), (w / "small.txt").write_bytes(b"x" * 10)))
    assert kept == ["item/workspace/small.txt"]
    assert keeper.skips == [dict(path="item/workspace/big.bin", reason="size")] and keeper.failures == []


def test_d3_git_metadata_is_one_skip(tmp_path):
    def build(w):
        for n in range(5):
            (w / ".git/objects" / str(n)).mkdir(parents=True)
            (w / ".git/objects" / str(n) / "blob").write_bytes(b"compressed")
        (w / "app.py").write_bytes(b"synthetic edit\n")
    keeper, kept = workspace_keeper(tmp_path, build)
    assert kept == ["item/workspace/app.py"]
    assert keeper.skips == [dict(path="item/workspace/.git", reason="git metadata")]


def test_d3_the_entry_cap_stops_the_walk(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_ENTRIES", 3)
    keeper, kept = workspace_keeper(tmp_path, lambda w: [(w / f"f{n}").write_bytes(b"x") for n in range(5)])
    assert len(kept) == 3 and keeper.skips == [dict(path="item/workspace", reason="entries")]


def test_d3_a_session_without_a_clone_is_a_skip(tmp_path):
    keeper = diagnostics.Diagnostics(tmp_path / "diag", tmp_path)
    keeper._workspace("item", SimpleNamespace(_root=tmp_path / "attempt"), 21)
    assert keeper.skips == [dict(path="item/workspace", reason="no workspace clone")] and keeper.failures == []


def test_d4_a_folder_that_cannot_be_made_refuses(traced, tmp_path, monkeypatch, capsys):
    def refuse(*args, **kw):
        raise OSError("synthetic mkdir failure")

    monkeypatch.setattr(diagnostics.os, "mkdir", refuse)
    assert traced.invoke(control="oracle_evidence", diagnostics=tmp_path / "diag") == 3
    assert capsys.readouterr().err.split() == ["diagnostics_create"]
    assert not (tmp_path / "out").exists() and not (tmp_path / "diag").exists()
