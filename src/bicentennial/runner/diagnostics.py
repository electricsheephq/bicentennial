"""A live control arm's reader trace, kept privately outside the run directory (#505, #506).

The benchmark owner's tool: `bicentennial t2 --control ARM --diagnostics DIR`. Each attempt that reaches scoring
keeps, per item, under DIR/<life>/<branch>/<attempt>/<item_id>/:

- trajectory.json: every probe_main ledger row of the item's probe session, each with a `bodies` field holding its
  decoded req/resp blobs and each upstream entry's;
- act.json and workspace/<path>: for an act item, the state the scorer read and the post-action workspace clone's files;
- final.txt: for a QA item, the raw final reply text, when there is one;
- score.json and probe.json: the attempt's score row and probe row.

Every file is scanned for the run's current credential needles before it is written, and DIR/manifest.json records
each file's size and sha256, every skip and failure, and a rescan of DIR with the run's final needle set. Nothing here
writes under the run directory, and no failure here reaches the attempt (it is recorded by path and exception type).
"""

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4

from bicentennial.canon import canon
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner.kept import _needle_forms, plain_item_id
from bicentennial.runner.t2lite import _secrets
from bicentennial.sandbox import fixedroot


def refusal(diagnostics, control, out, others):
    """The refusal code for a --diagnostics DIR this run cannot use, or None. Nothing is created."""
    if diagnostics is None:
        return None
    if control is None:
        return "diagnostics_control"
    path = Path(diagnostics)
    if path.exists() or path.is_symlink():
        return "diagnostics_exists"
    paths = [Path(out), *(Path(p) for p in others if p is not None)]
    if fixedroot.overlaps(path) or any(_nested(path, p) for p in paths):
        return "diagnostics_overlap"
    return None


def _nested(a, b):
    # within() matches existing entries by identity; neither DIR nor out exists yet, so their spellings are compared too.
    if fixedroot.within(a, b) or fixedroot.within(b, a):
        return True
    x, y = (Path(os.path.realpath(Path(os.getcwd(), p))).as_posix().casefold() for p in (a, b))
    return x == y or x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/")


def _body(store, blob):
    data = store.get(blob)
    try:
        return json.loads(data)
    except ValueError:
        return data.decode("utf-8", "backslashreplace")


class Diagnostics:
    """Shared by every unit thread of one run; files are written once each, the manifest at the run's end."""

    def __init__(self, root, home):
        self.root, self.home = Path(root), Path(home)
        self.login, self.commit, self.control = None, None, None
        self.files, self.skips, self.failures = {}, [], []
        self._lock = Lock()

    def create(self):
        self.root.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(self.root, 0o700)

    def _needles(self):
        # Every needle the run knows now: the login home's, and the live login's once the stack exists.
        return _needle_forms(tuple(n for n in _secrets(self.home, self.login) if n))

    def _fail(self, rel, error):
        with self._lock:
            self.failures.append(dict(path=rel, error=type(error).__name__))

    def _put(self, rel, data, needles):
        """Write one file atomically, never over an existing one; a needle in its path or bytes skips it.

        data is bytes, or a function that makes them, so a failure to make them costs this file only."""
        try:
            data = data() if callable(data) else data
            if any(n in os.fsencode(rel) for n in needles):
                with self._lock:
                    self.skips.append(dict(path_sha256=sha256(rel.encode()).hexdigest(), reason="credential_path"))
                return
            if any(n in data for n in needles):
                with self._lock:
                    self.skips.append(dict(path=rel, reason="credential"))
                return
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.link(temp, target)  # a rename that refuses an existing target
            finally:
                temp.unlink(missing_ok=True)
            with self._lock:
                self.files[rel] = dict(path=rel, bytes=len(data), sha256=sha256(data).hexdigest())
        except Exception as error:  # noqa: BLE001 - a diagnostic never reaches the attempt
            self._fail(rel, error)

    def keep(self, pack, branch, attempt, run, scores, probes):
        """Keep every item of one scored attempt; called before the attempt's cleanup, never raises."""
        base = f"{pack.life}/{branch}/{attempt}"
        try:
            if not (plain_item_id(pack.life) and plain_item_id(branch)):
                raise ValueError("path")
            needles = self._needles()
            store = BlobStore(run._root / "run/ledger/blobs", Guard([]))
            sessions = {p["item_id"]: p for p in probes}
            finals = {s.session: dict(s.finals) for s in run.sessions}
            turns = {}
        except Exception as error:  # noqa: BLE001
            self._fail(base, error)
            return
        for item in pack.items[branch]:
            iid = item["item_id"]
            try:
                if not plain_item_id(iid):
                    raise ValueError("path")
                probe = sessions.get(iid)
                session = probe["probe_session"] if probe else None
                # The compiler keeps item order within a probe session (runner/units.py _floor_measured).
                turns[session] = turns.get(session, 0) + 1
                self._item(f"{base}/{iid}", item, run, store, needles, probe, session, turns[session],
                           finals.get(session, {}), scores.get(iid))
            except Exception as error:  # noqa: BLE001
                self._fail(f"{base}/{iid}", error)

    def _item(self, rel, item, run, store, needles, probe, session, turn, finals, score):
        iid = item["item_id"]
        self._put(f"{rel}/probe.json", lambda: canon(probe), needles)
        self._put(f"{rel}/score.json", lambda: canon(score if isinstance(score, dict) or score is None
                                                     else dict(infra=getattr(score, "label", None))), needles)

        def trajectory():
            # A missing or undecodable blob costs this file only.
            rows = []
            for row in run.records:
                cursor = row.get("cursor")
                if row.get("role") != "probe_main" or not isinstance(cursor, dict) or cursor.get("session") != session:
                    continue
                bodies = {k: _body(store, row[k]) for k in ("req", "resp") if row.get(k)}
                bodies["upstream"] = [{k: _body(store, u[k]) for k in ("req", "resp") if u.get(k)}
                                      for u in row.get("upstream", ())]
                rows.append(dict(row, bodies=bodies))
            return canon(rows)

        self._put(f"{rel}/trajectory.json", trajectory, needles)
        if iid in run.act:
            self._put(f"{rel}/act.json", lambda: canon(run.act[iid]), needles)
            self._workspace(rel, run, session, needles)
        elif item.get("stage") != "act" and turn in finals:
            self._put(f"{rel}/final.txt", lambda: finals[turn].encode(), needles)

    def _workspace(self, rel, run, session, needles):
        # life.py clones the surfaces, then the workspace last, to probe/<session>/<n>; swap_in's restore returns the
        # edited workspace to its clone path, so the highest n holds what the reader left.
        try:
            clones = run._root / "probe" / str(session)
            clone = clones / str(max(int(p.name) for p in clones.iterdir() if p.name.isdigit()))
            paths = sorted(clone.rglob("*"))
        except Exception as error:  # noqa: BLE001
            self._fail(f"{rel}/workspace", error)
            return
        for path in paths:
            name = f"{rel}/workspace/{path.relative_to(clone).as_posix()}"
            try:
                if path.is_symlink():
                    with self._lock:
                        self.skips.append(dict(path=name, reason="symlink"))
                elif path.is_file():
                    self._put(name, path.read_bytes, needles)  # an unreadable file costs that file only
            except Exception as error:  # noqa: BLE001
                self._fail(name, error)

    def finish(self, needles):
        """Rescan DIR with the final needle set and write the manifest; any failure is one stderr warning code."""
        if not self.root.is_dir():
            return
        try:
            try:
                final = set(needles) | set(_secrets(self.home, self.login))
            except Exception:  # noqa: BLE001 - the run's own final set still applies
                final = set(needles)
            forms = _needle_forms(tuple(n for n in final if n))
            hits, errors = [], []
            for path in sorted(self.root.rglob("*")):
                rel = path.relative_to(self.root).as_posix()
                try:
                    if any(n in os.fsencode(rel) for n in forms):
                        hits.append(self._label(rel, forms))
                    elif path.is_file() and not path.is_symlink() and _hit(path, forms):
                        hits.append(rel)
                except Exception as error:  # noqa: BLE001
                    errors.append(dict(path=self._label(rel, forms), error=type(error).__name__))
            with self._lock:
                manifest = dict(commit=self.commit, control=self.control,
                    files=[self.files[k] for k in sorted(self.files)],
                    skips=sorted(self.skips, key=canon), failures=sorted(self.failures, key=canon),
                    rescan="clean" if not hits and not errors else dict(hits=hits, errors=errors))
            # A path that only the final set flags is named by its hash, so the manifest never carries a needle.
            for row in (*manifest["files"], *manifest["skips"], *manifest["failures"]):
                if "path" in row:
                    row["path"] = self._label(row["path"], forms)
            data = canon(manifest)
            if any(n in data for n in forms):
                raise ValueError("manifest")
            target = self.root / "manifest.json"
            temp = target.with_name(f".manifest.json.{uuid4().hex}.tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.link(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - the run's exit code and outputs never depend on this
            print("diagnostics_manifest", file=sys.stderr)
            return
        if hits or errors:
            print("diagnostics_credential", file=sys.stderr)

    @staticmethod
    def _label(rel, needles):
        if isinstance(rel, str) and any(n in os.fsencode(rel) for n in needles):
            return "sha256:" + sha256(rel.encode()).hexdigest()
        return rel


def _hit(path, needles):
    longest = max(map(len, needles), default=1)
    with path.open("rb") as stream:
        tail = b""
        while chunk := stream.read(1 << 20):
            data = tail + chunk
            if any(n in data for n in needles):
                return True
            tail = data[-(longest - 1):] if longest > 1 else b""
    return False
