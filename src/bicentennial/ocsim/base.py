"""Build binding OC base documents from locked, synthetic-testable sources.

No schema loader or contract validator runs here; the history checks are frozen
below and covered by C-8, together with the token estimator.
"""

import io
import json
import math
import os
import re
import statistics
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.ocsim import inputs, reserve, run
from bicentennial.runner.dispatch import anchor_order
from bicentennial.stats import pilot
from bicentennial.world import scale
from bicentennial.world.tokens import estimate_tokens

ROSTER = "prereg/roster/full-tier.json"
C12 = "prereg/completion/C-12.json"
C11 = "prereg/completion/C-11.json"
C1 = "prereg/completion/C-1.json"
C2 = "prereg/completion/C-2.json"
C4 = "prereg/completion/C-4.json"
DRY = "prereg/ocsim/dry-set.json"
RENDER_CODE = ("src/bicentennial", "tiers", "specs/ring0", "schemas")
STAGE_B = ("#245 issuecomment-6522316290", "#245 issuecomment-6522904866",
           "#245 issuecomment-6524597333")
FIELD_ARTIFACTS = {"rows": (ROSTER,), "required": (C12,), "lanes": (C11, C1, C2),
                   "lives": (DRY,), "alloc_by_b": (DRY, C12), "n_lives_floor": (ROSTER, C12),
                   "probe_only": (DRY, C4)}
BASE_FIELDS = ("required", "alloc_by_b", "checkpoints", "lives", "rows", "lanes",
               "passover", "control_failure", "probe_only", "n_lives_floor", "planning")
RESERVED = frozenset(("S", "F", "C", "RAG", "CEIL", "anchor", "no_memory", "oracle_evidence"))
SESSION_REQUIRED = frozenset(("canary", "index", "kind", "wake_before", "fault_points",
                              "long_sprint", "est_tokens", "probe_point", "expected_state"))
SESSION_ALLOWED = SESSION_REQUIRED
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
FAULTS = ("restart", "kill", "compaction", "swap")
RULING = "#245 issuecomment-6520675813"
CLARIFICATION = "#245 issuecomment-6521154213"


class BaseRefused(ValueError):
    """All field refusals, in stable order; no partial document is emitted."""

    def __init__(self, refusals):
        self.refusals = tuple(sorted(set(refusals)))
        super().__init__("; ".join(f"{field}: {reason}" for field, reason in self.refusals))


def _need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _shape(value, keys, reason):
    _need(isinstance(value, dict) and value.keys() == set(keys), reason)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _strings(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _json(raw, name):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, f"{name}:duplicate_key:{key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"{name}:nonfinite:{value}")

    try:
        return json.loads(raw, object_pairs_hook=unique_keys, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name}:invalid_json") from error


def marker_id(root, commit):
    """C-14 has no binding machine-readable declaration yet."""
    raise ValueError("pending:C-14")


def _git_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _git(context, *args, reason):
    try:
        return subprocess.run(("git", "-C", str(context.root), *args),
                              capture_output=True, check=False, env=_git_env())
    except OSError as error:
        raise ValueError(reason) from error


def c8_check(context):
    """Compare committed C-8 closures using today's path policy for both."""
    hashes = {}
    for name, commit in (("analysis", context.get("bar2")["run_lock"]["analysis_commit"]),
                         ("head", "HEAD")):
        listing = _git(context, "ls-tree", "-r", "--name-only", commit, "--",
                       *run._C8_FIXED, *run._C8_DIRS, reason="c8:git")
        _need(listing.returncode == 0, "c8:git")
        paths = [p for p in listing.stdout.decode().splitlines()
                 if "__pycache__" not in Path(p).parts and not p.endswith(".pyc")]
        _need(set(run._C8_FIXED) <= set(paths), "c8:bar2_mismatch")
        archive = _git(context, "archive", "--format=tar", commit, "--", *paths, reason="c8:git")
        _need(archive.returncode == 0, "c8:git")
        with tempfile.TemporaryDirectory() as directory:
            with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
                tar.extractall(directory, filter="data")
            hashes[name] = run.c8_hash(Path(directory))
    context.provenance["c8"] = hashes
    _need(hashes["analysis"] == hashes["head"], "c8:bar2_mismatch")


def _session(record, index, where):
    reason = f"history:bad_session:{where}"
    _shape(record, SESSION_ALLOWED, reason)
    _need(record["canary"] == CANARY and type(record["index"]) is int
          and record["index"] == index and record["kind"] == "work"
          and _integer(record["est_tokens"])
          and type(record["long_sprint"]) is bool and type(record["probe_point"]) is bool, reason)
    _need(_strings(record["wake_before"])
          and all(v in (*FAULTS, "gap") for v in record["wake_before"]), reason)
    state = record["expected_state"]
    _shape(state, ("repo_tree_hash", "env_state_hash"), reason)
    _need(all(_hex(v, 64) for v in state.values()), reason)
    _need(isinstance(record["fault_points"], list), reason)
    for fault in record["fault_points"]:
        _shape(fault, ("kind", "session", "turn"), reason)
        _need(fault["kind"] in FAULTS and _integer(fault["session"], 1)
              and (fault["turn"] is None or _integer(fault["turn"], 1)), reason)


def _history(data):
    _shape(data, ("generator_version", "lives"), "history:shape:root")
    _need(isinstance(data["generator_version"], str) and isinstance(data["lives"], dict)
          and bool(data["lives"]), "history:shape:lives")
    for life, branches in data["lives"].items():
        _shape(branches, ("B0", "B1"), f"history:shape:{life}")
        for branch, sessions in branches.items():
            _need(isinstance(sessions, list) and bool(sessions), f"history:shape:{life}/{branch}")
            for index, record in enumerate(sessions, 1):
                _session(record, index, f"{life}/{branch}/{index}")
    return data


def _position(kind, index, checkpoint, n):
    return (_integer(index, 1) and
            ((kind == "replay" and index <= n and checkpoint is None)
             or (kind == "probe" and index > n and _integer(checkpoint, 1) and checkpoint <= n)))


def _chain(chain, n, where, life, items):
    _shape(chain, ("attempt", "stopped", "sessions"), f"bar2:chain_shape:{where}")
    _need(_integer(chain["attempt"]) and isinstance(chain["sessions"], list),
          f"bar2:chain_shape:{where}")
    stop = chain["stopped"]
    if stop is not None:
        reason = f"bar2:stop_mismatch:{where}"
        _shape(stop, ("class", "label", "session", "kind", "checkpoint"), reason)
        _need(stop["class"] in ("SYSTEM_FAILURE", "BLOCKED") and isinstance(stop["label"], str)
              and _position(stop["kind"], stop["session"], stop["checkpoint"], n), reason)
    seen, listed = set(), set()
    for session in chain["sessions"]:
        reason = f"bar2:session_shape:{where}"
        _shape(session, ("index", "kind", "checkpoint", "wall_ms", "gate_ms", "egress_wait_ms", "items"), reason)
        index = session["index"]
        _need(_position(session["kind"], index, session["checkpoint"], n),
              f"bar2:session_index:{where}")
        _need(index not in seen, f"bar2:duplicate_session:{where}")
        seen.add(index)
        _need((session["wall_ms"] is None or _integer(session["wall_ms"]))
              and _integer(session["gate_ms"]) and _integer(session["egress_wait_ms"])
              and _strings(session["items"]), reason)
        _need(bool(session["items"]) == (session["kind"] == "probe"), reason)
        if stop is not None and index == stop["session"]:
            _need(all(session[k] == stop[k] for k in ("kind", "checkpoint")),
                  f"bar2:stop_mismatch:{where}")
        for iid in session["items"]:
            _need(iid not in listed, f"bar2:item_twice:{where}")
            listed.add(iid)
            _need(iid not in items or items[iid]["life"] == life, f"bar2:item_life:{where}")
    if stop is not None:
        for session in chain["sessions"]:
            if stop["kind"] == "replay":
                after = (session["index"] > stop["session"] if session["kind"] == "replay"
                         else session["checkpoint"] >= stop["session"])
            else:
                after = (session["index"] > stop["checkpoint"] if session["kind"] == "replay"
                         else session["index"] > stop["session"])
            _need(not after, f"bar2:after_stop:{where}")


def _bar2(data, history, roster):
    _shape(data, ("run_lock", "arms", "items", "probe_only", "bundles"), "bar2:shape:root")
    lock = data["run_lock"]
    _shape(lock, ("benchmark_commit", "analysis_commit", "generator_version", "generator_versions",
                  "history_sha256", "status", "account_pool"),
           "bar2:shape:run_lock")
    _need(_hex(lock["benchmark_commit"], 40) and _hex(lock["history_sha256"], 64)
          and isinstance(lock["generator_version"], str), "bar2:shape:run_lock")
    versions = lock["generator_versions"]
    _need(_hex(lock["analysis_commit"], 40) and isinstance(versions, dict) and bool(versions)
          and all(isinstance(k, str) and bool(k) and isinstance(v, str) and bool(v) and "+" not in v
                  for k, v in versions.items())
          and "+".join(sorted(set(versions.values()))) == lock["generator_version"],
          "bar2:shape:run_lock")
    pool = lock["account_pool"]
    _need(_strings(pool) and bool(pool) and pool == sorted(set(pool))
          and all(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", v) for v in pool),
          "bar2:account_pool:run_lock")
    arms, items = data["arms"], data["items"]
    _need(isinstance(arms, dict) and isinstance(items, dict), "bar2:shape:arms/items")
    for iid, item in items.items():
        _shape(item, ("life", "prompt", "classes"), f"bar2:item_shape:{iid}")
        _need(isinstance(item["life"], str) and isinstance(item["prompt"], str), f"bar2:item_shape:{iid}")
        _need(isinstance(item["classes"], dict) and item["classes"].keys() == arms.keys(),
              f"bar2:classes_incomplete:{iid}")
        _need(all(v in inputs.FAILURE_CLASSES for v in item["classes"].values()), f"bar2:item_class:{iid}")
    markers = 0
    for arm, value in arms.items():
        _shape(value, ("kind", "lives"), f"bar2:arm_shape:{arm}")
        _need(value["kind"] in ("system", "marker"), f"bar2:arm_kind:{arm}")
        markers += value["kind"] == "marker"
        _need(markers <= 1, "bar2:two_markers:arms")
        if value["kind"] == "system" and roster is not None:
            _need(arm in {s["id"] for s in roster["systems"]}, f"bar2:not_on_roster:{arm}")
        _need(isinstance(value["lives"], dict) and value["lives"].keys() == history["lives"].keys(),
              f"bar2:lives_mismatch:{arm}")
        for life, branches in value["lives"].items():
            _need(isinstance(branches, dict) and not branches.keys() - {"B0", "B1"},
                  f"bar2:chain_shape:{arm}/{life}")
            for branch in ("B0", "B1"):
                keeps = branches.get(branch, {})
                _need(isinstance(keeps, dict) and not keeps.keys() - {"K100", "K10"},
                      f"bar2:chain_shape:{arm}/{life}/{branch}")
                for keep in ("K100", "K10"):
                    where = f"{arm}/{life}/{branch}/{keep}"
                    _need(keep in keeps, f"bar2:chain_missing:{where}")
                    _chain(keeps[keep], len(history["lives"][life][branch]), where, life, items)
    _bundles_shape(data["bundles"], arms, history["lives"])
    _probe_shape(data["probe_only"], history["lives"], items)
    return data


def _probe_shape(probes, lives, items):
    _shape(probes, reserve.PROBE_ONLY_LOAD, "bar2:probe_only_shape:probe_only")
    for arm, records in probes.items():
        _shape(records, lives, f"bar2:probe_only_shape:{arm}")
        for life, branches in records.items():
            _shape(branches, ("B0", "B1"), f"bar2:probe_only_shape:{arm}/{life}")
            seen = set()
            for branch, sessions in branches.items():
                where = f"{arm}/{life}/{branch}"
                reason = f"bar2:probe_only_shape:{where}"
                _need(isinstance(sessions, list), reason)
                checkpoints = set()
                for session in sessions:
                    reason = f"bar2:probe_only_shape:{where}"
                    _shape(session, ("checkpoint", "attempt", "stopped", "wall_ms", "items",
                                     "context_tokens"), reason)
                    checkpoint = session["checkpoint"]
                    _need(_integer(checkpoint, 1) and checkpoint <= len(lives[life][branch])
                          and checkpoint not in checkpoints and _integer(session["attempt"], 1)
                          and type(session["stopped"]) is bool
                          and (session["wall_ms"] is None or _integer(session["wall_ms"]))
                          and _strings(session["items"]) and bool(session["items"])
                          and isinstance(session["context_tokens"], list), reason)
                    checkpoints.add(checkpoint)
                    reason = f"bar2:probe_only_item:{where}"
                    _need(len(session["items"]) == len(session["context_tokens"]), reason)
                    for iid, tokens in zip(session["items"], session["context_tokens"], strict=True):
                        _need(_integer(tokens) and (arm != "F" or tokens == 2)
                              and iid in items and iid not in seen and items[iid]["life"] == life, reason)
                        seen.add(iid)


def _bundles_shape(bundles, arms, lives):
    _need(isinstance(bundles, dict), "bar2:bundles_shape:root")
    for arm, rows in bundles.items():
        reason = f"bar2:bundles_shape:{arm}"
        _need(arm in arms and arms[arm]["kind"] == "system" and isinstance(rows, list), reason)
        seen = set()
        for row in rows:
            _need(isinstance(row, list) and len(row) == 5, reason)
            bid, life, track, keep, score = row
            _need(isinstance(bid, str) and bool(bid) and isinstance(life, str)
                  and life in lives and track in inputs.TRACKS and keep in ("K100", "K10")
                  and (score is None or type(score) is int and -1000 <= score <= 1000), reason)
            _need((bid, keep) not in seen, reason)
            seen.add((bid, keep))


def _controls(raw):
    try:
        inputs.load(raw, ())
    except ValueError as error:
        raise ValueError(f"controls:{error}") from error
    data = _json(raw, "controls")
    for name in ("A", "A_prime"):
        for output in data[name].values():
            _need(not output.keys() - {"items", "bundles", "singleton_lives", "reports"},
                  "controls:unknown_key:arm")
            for item in output["items"]:
                _shape(item, ("item_id", "cell_id", "stage", "track", "failure_class", "score_milli"),
                       "controls:unknown_key:item")
            for bundle in output["bundles"]:
                _shape(bundle, ("bundle_id", "cell_id", "life", "items"), "controls:unknown_key:bundle")
    return data


class _Context:
    def __init__(self, bar2, controls, history, root):
        self.root, self.values, self.errors = root, {}, {}
        self.provenance = {"artifacts": [], "containers": {
            name: sha256(raw).hexdigest() for name, raw in
            (("bar2", bar2), ("controls", controls), ("history", history))}}
        self.global_reason = None
        self._save("history", _history, history, json_name="history")
        self._save("controls", _controls, controls)
        self._save("bar2", _json, bar2, "bar2")
        data = self.values.get("bar2", {})
        lock = data.get("run_lock", {}) if isinstance(data, dict) else {}
        self.commit = lock.get("benchmark_commit", "") if isinstance(lock, dict) else ""
        if isinstance(lock, dict) and "status" in lock and lock["status"] != "complete":
            self.global_reason = "bar2_not_run_of_record"
        hist = self.values.get("history")
        if (hist is not None and isinstance(lock, dict) and _hex(lock.get("history_sha256"), 64)
                and isinstance(lock.get("generator_version"), str)) and (
                lock.get("history_sha256") != sha256(history).hexdigest()
                or lock.get("generator_version") != hist["generator_version"]):
            self.global_reason = "history_mismatch"
        self._save("roster", self.artifact, ROSTER)
        if "bar2" not in self.errors:
            if hist is None:
                self.errors["bar2"] = self.errors["history"]
            else:
                self._save("bar2", _bar2, data, hist, self.values.get("roster"))

    def _save(self, name, function, *args, json_name=None):
        try:
            if json_name is not None:
                args = (_json(args[0], json_name),)
            self.values[name] = function(*args)
        except (ValueError, TypeError, KeyError) as error:
            self.errors[name] = str(error)

    def get(self, name):
        if name in self.errors:
            raise ValueError(self.errors[name])
        return self.values[name]

    def artifact(self, path):
        if path not in (ROSTER, C12, C11, C1, C2, C4, DRY):
            raise AssertionError(f"unknown artifact: {path}")
        if path in self.values:
            return self.values[path]
        _need(_hex(self.commit, 40), f"source_missing:{path}")
        try:
            result = subprocess.run(("git", "-C", str(self.root), "show", f"{self.commit}:{path}"),
                                    capture_output=True, check=False, env=_git_env())
        except OSError as error:
            raise ValueError(f"source_missing:{path}") from error
        _need(result.returncode == 0, f"source_missing:{path}")
        raw = result.stdout
        data = _json(raw, path)
        _need(isinstance(data, dict), f"source_shape:{path}")
        if path in (C1, C2):
            keys = ("pinned_model",) if path == C1 else ("swap_model", "effort")
            _need(isinstance(data.get("status"), str)
                  and all(isinstance(data.get(k), str) for k in keys), f"source_shape:{path}")
        if path == C4:
            _need(isinstance(data.get("status"), str)
                  and isinstance(data.get("window_name"), str) and bool(data["window_name"])
                  and _integer(data.get("window_tokens"), 1), f"source_shape:{path}")
        _need(data.get("status") == "binding", f"source_provisional:{path}")
        if path == ROSTER:
            _shape(data, ("status", "systems", "reference", "pre_generator_lcmx"), f"source_shape:{path}")
            _need(isinstance(data["systems"], list) and bool(data["systems"]), f"source_shape:{path}")
            ids = []
            for system in data["systems"]:
                _shape(system, ("id", "lcmx"), f"source_shape:{path}")
                _need(isinstance(system["id"], str) and bool(system["id"])
                      and type(system["lcmx"]) is bool, f"source_shape:{path}")
                ids.append(system["id"])
            _need(len(ids) == len(set(ids)), f"source_shape:{path}")
            flags = {s["id"]: s["lcmx"] for s in data["systems"]}
            _need(isinstance(data["reference"], str) and isinstance(data["pre_generator_lcmx"], str)
                  and flags.get(data["reference"]) is False
                  and flags.get(data["pre_generator_lcmx"]) is True
                  and sum(flags.values()) == 2, f"source_shape:{path}")
        elif path == C12:
            _shape(data, ("status", "profile", "required"), f"source_shape:{path}")
            _need(data["profile"] == "Text" and _strings(data["required"]), f"source_shape:{path}")
        elif path == C11:
            reason = f"source_shape:{path}"
            _shape(data, ("status", "lanes"), reason)
            lanes = data["lanes"]
            _need(isinstance(lanes, dict) and {"pinned", "swap"} <= lanes.keys()
                  and not lanes.keys() - {"pinned", "swap", "replication"}, reason)
            for entry in lanes.values():
                _shape(entry, ("model", "concurrency", "rate_per_min", "accounts"), reason)
                _need(isinstance(entry["model"], str) and _integer(entry["accounts"], 1)
                      and all(entry[k] is None or _integer(entry[k], 1)
                              for k in ("concurrency", "rate_per_min"))
                      and any(entry[k] is not None for k in ("concurrency", "rate_per_min")), reason)
        elif path == DRY:
            _dry_shape(data)
        self.provenance["artifacts"].append({"path": path, "commit": self.commit,
                                             "sha256": sha256(raw).hexdigest()})
        self.values[path] = data
        return data


def _rates(context):
    data, history = context.get("bar2"), context.get("history")
    rates, waits = {}, {}
    for arm, value in sorted(data["arms"].items()):
        wall = tokens = gate = egress = counted = untimed = 0
        for life, branches in value["lives"].items():
            for branch, keeps in branches.items():
                for chain in keeps.values():
                    for session in chain["sessions"]:
                        if session["kind"] == "probe":
                            _need(all(i in data["items"] for i in session["items"]),
                                  f"rows:unmatched_session:{arm}/{life}/{branch}/{session['index']}")
                        if session["wall_ms"] is None:
                            untimed += 1
                            continue
                        if chain["stopped"] is not None and session["index"] == chain["stopped"]["session"]:
                            continue
                        if session["kind"] == "replay":
                            count = history["lives"][life][branch][session["index"] - 1]["est_tokens"]
                        else:
                            count = sum(estimate_tokens(data["items"][i]["prompt"]) for i in session["items"])
                        counted += 1
                        tokens += count
                        wall += session["wall_ms"]
                        gate += session["gate_ms"]
                        egress += session["egress_wait_ms"]
        if counted:
            _need(tokens > 0, f"rows:zero_tokens:{arm}")
            _need(wall > 0, f"rows:zero_wall:{arm}")
            rates[arm] = Fraction(wall, tokens)
            waits[arm] = {"gate": Fraction(gate, wall), "egress_wait": Fraction(egress, wall),
                          "untimed_sessions": untimed}
    context.provenance["waits"] = waits
    context.values["rates"] = rates
    return rates


def _rows(context):
    context.get("bar2")
    context.get("history")
    roster = context.get("roster")
    marker = marker_id(context.root, context.commit)
    ids = [s["id"] for s in roster["systems"]] + [marker]
    for arm in ids:
        _need(arm not in RESERVED, f"row_id_reserved:{arm}")
    _need(isinstance(marker, str) and bool(marker) and len(ids) == len(set(ids)), "rows:marker_id")
    for arm, value in context.get("bar2")["arms"].items():
        _need(value["kind"] != "marker" or arm == marker, f"rows:marker_mismatch:{arm}")
    rates = _rates(context)
    _need(bool(rates), "rows:no_timed_arm")
    fallback = max(rates.values())
    return [{"row": arm, "rate": rates.get(arm, fallback)} for arm in sorted(ids)]


def _passover(context, excluded=frozenset()):
    data, history = context.get("bar2"), context.get("history")
    counts = {}
    for arm, value in sorted(data["arms"].items()):
        if value["kind"] != "system" or arm in excluded:
            continue
        count = counts[arm] = {"units": len(value["lives"]), "failed": 0, "blocked": 0}
        for life, branches in value["lives"].items():
            classes = set()
            for branch, keeps in branches.items():
                stop = keeps["K100"]["stopped"]
                n = len(history["lives"][life][branch])
                if stop and (stop["kind"] == "replay" or stop["checkpoint"] < n):
                    classes.add(stop["class"])
            if classes:
                count["failed" if "SYSTEM_FAILURE" in classes else "blocked"] += 1
    total = sum(c["units"] for c in counts.values())
    value = ({key: Fraction(sum(c[key] for c in counts.values()), total) for key in ("failed", "blocked")}
             if total else None)
    return value, counts


def _passover_rule(context):
    value, _ = _passover(context)
    _need(value is not None, "passover:no_real_arm")
    return value


def _control_failure(context, excluded=frozenset()):
    controls, data, history = context.get("controls"), context.get("bar2"), context.get("history")
    classes, lives, counts = {}, {}, {}
    for arm in inputs.ARMS:
        output = controls["A"][arm]
        lives[arm] = dict(output["singleton_lives"])
        for bundle in output["bundles"]:
            lives[arm].update((iid, bundle["life"]) for iid in bundle["items"])
        _need(set(lives[arm].values()) == set(history["lives"]), "control_failure:lives_mismatch")
        classes[arm] = {item["item_id"]: item["failure_class"] for item in output["items"]}
    for arm in inputs.ARMS:
        failed = set()
        for iid, failure in classes[arm].items():
            every = (all(c.get(iid) == "BLOCKED" for c in classes.values())
                     and all(v == "BLOCKED" for a, v in data["items"].get(iid, {}).get("classes", {}).items()
                             if a not in excluded))
            if failure == "BLOCKED" and not every:
                failed.add(lives[arm][iid])
        counts[arm] = {"units": len(set(lives[arm].values())), "failed": len(failed), "blocked": 0}
    total = sum(c["units"] for c in counts.values())
    return (Fraction(sum(c["failed"] for c in counts.values()), total) if total else None), counts


def _control_rule(context):
    value, _ = _control_failure(context)
    context.provenance["a_prime"] = {
        arm: {"items": len(output["items"]), "bundles": len(output["bundles"])}
        for arm, output in context.get("controls")["A_prime"].items()}
    return value


def _checkpoints(context):
    return [20, 60, 120, 200]


def _required(context):
    cells = context.artifact(C12)["required"]
    _need(bool(cells), "required:empty")
    _need(cells == sorted(set(cells)), "required:not_sorted_unique")
    return cells


def runner_cap(context, lane):
    raise ValueError("pending:bar-2 runner")


def _lanes(context):
    lanes = context.artifact(C11)["lanes"]
    pinned, swap = context.artifact(C1), context.artifact(C2)
    _need(lanes["pinned"]["model"] == pinned["pinned_model"]
          and lanes["swap"]["model"] == swap["swap_model"]
          and lanes["pinned"]["model"] != lanes["swap"]["model"], "lanes:c11_route")
    if "replication" in lanes:
        context.provenance["lanes_not_drawn"] = lanes["replication"]
    result = []
    for name in ("pinned", "swap"):
        lane = lanes[name]
        _need(lane["concurrency"] is not None, "pending:B-15 rate-only concurrency")
        entry = {"name": name, "concurrency": lane["concurrency"], "accounts": lane["accounts"],
                 "runner_cap": runner_cap(context, lane)}
        if lane["rate_per_min"] is not None:
            entry["rate_per_min"] = lane["rate_per_min"]
        result.append(entry)
    return result


def alloc_total(b):
    return (3 * b + 4) // 5


def _alloc(context):
    cells = _required(context)
    _need(bool(cells), "required:empty")
    checkpoints = _checkpoints(context)
    result, disclosure = {}, {}
    for b in sorted({b for _, b in run.LADDER}):
        q, r = divmod(alloc_total(b), len(cells))
        order = sorted(cells, key=lambda cell, b=b: sha256(canon(["ocsim-alloc", b, cell])).hexdigest())
        totals = {cell: q + (i < r) for i, cell in enumerate(order)}
        counts, cursor = {}, 0
        for cell in order:
            whole, extra = divmod(totals[cell], len(checkpoints))
            for checkpoint in checkpoints:
                counts[cell, checkpoint] = whole
            for _ in range(extra):
                counts[cell, checkpoints[cursor % len(checkpoints)]] += 1
                cursor += 1
        result[str(b)] = [[cell, checkpoint, counts[cell, checkpoint]]
                          for cell in cells for checkpoint in checkpoints]
        disclosure[str(b)] = {"cells": totals, "checkpoints": {
            str(checkpoint): sum(counts[cell, checkpoint] for cell in cells)
            for checkpoint in checkpoints}}
    # Each budget keys its own cell order and extras, so b=300 need not cover a smaller budget's pair.
    need = {}
    for rows in result.values():
        for cell, checkpoint, n in rows:
            need[cell, checkpoint] = max(need.get((cell, checkpoint), 0), n)
    for life in context.artifact(DRY)["lives"]:
        bundles = {(cell, checkpoint): n for cell, checkpoint, n in life["bundles"]}
        _need(all(bundles.get(pair, 0) >= n for pair, n in need.items()), "alloc_by_b:dry_below")
    context.provenance["alloc"] = disclosure
    return result


def _dry_shape(data):
    reason = "lives:dry_shape"
    _shape(data, ("status", "lives"), reason)
    _need(isinstance(data["lives"], list), reason)
    for life in data["lives"]:
        _shape(life, ("i", "life", "genre", "seed", "generator_version", "render_commit",
                      "fork", "branches", "bundles", "anchor"), reason)
        _need(_integer(life["i"]) and isinstance(life["life"], str)
              and isinstance(life["genre"], str) and _integer(life["seed"])
              and isinstance(life["generator_version"], str)
              and _hex(life["render_commit"], 40) and _integer(life["fork"], 1), reason)
        _shape(life["branches"], ("B0", "B1"), reason)
        for branch in life["branches"].values():
            _shape(branch, ("est_tokens", "probe_points", "probe_tokens", "swap", "content_sha256",
                            "probe_items", "probe_only_context", "ceil_peak"), reason)
            for key, minimum in (("est_tokens", 1), ("probe_points", 1), ("probe_tokens", 0),
                                 ("swap", 1), ("probe_items", 0), ("ceil_peak", 0)):
                _need(isinstance(branch[key], list)
                      and all(_integer(v, minimum) for v in branch[key]), reason)
            _shape(branch["probe_only_context"], reserve.PROBE_ONLY_LOAD, reason)
            lists = [branch[k] for k in ("probe_items", "probe_tokens", "ceil_peak")]
            lists += list(branch["probe_only_context"].values())
            _need(all(isinstance(v, list) and len(v) == len(branch["probe_points"])
                      and all(_integer(n) for n in v) for v in lists), reason)
            _need(isinstance(branch["content_sha256"], list)
                  and all(_hex(v, 64) for v in branch["content_sha256"]), reason)
        _need(isinstance(life["bundles"], list), reason)
        seen = set()
        for bundle in life["bundles"]:
            _need(isinstance(bundle, list) and len(bundle) == 3
                  and isinstance(bundle[0], str) and _integer(bundle[1], 1)
                  and _integer(bundle[2]), reason)
            pair = tuple(bundle[:2])
            _need(pair not in seen, reason)
            seen.add(pair)
        _need(isinstance(life["anchor"], list), reason)
        refs = []
        for pair in life["anchor"]:
            _need(isinstance(pair, list) and len(pair) == 2
                  and _hex(pair[0], 64) and _integer(pair[1]), reason)
            refs.append(pair[0])
        _need(refs == sorted(set(refs)), reason)


def _render_check(context, commit):
    ancestor = _git(context, "merge-base", "--is-ancestor", commit, context.commit, reason="lives:git")
    _need(ancestor.returncode in (0, 1), "lives:git")
    _need(ancestor.returncode == 0, "lives:render_commit")
    diff = _git(context, "diff", "--quiet", commit, context.commit, "--", *RENDER_CODE, reason="lives:git")
    _need(diff.returncode in (0, 1), "lives:git")
    _need(diff.returncode == 0, "lives:render_code")


def _lives(context):
    full = scale.named("full")
    if list(full.checkpoints) != _checkpoints(context):
        raise AssertionError("full checkpoints differ from base checkpoints")
    records = context.artifact(DRY)["lives"]
    _need(len(records) == 48, "lives:dry_identity")
    versions = context.get("bar2")["run_lock"]["generator_versions"]
    result, checked = [], set()
    for i, life in enumerate(records):
        genre = "G1" if i % 2 == 0 else "G2"
        seed = int.from_bytes(sha256(canon(["ocsim-dry", i])).digest()[:8], "big") >> 1
        _need(life["i"] == i and life["life"] == f"ocsim-dry-{i:03d}"
              and life["genre"] == genre and life["seed"] == seed, "lives:dry_identity")
        _need(life["generator_version"] == versions.get(genre), "lives:generator_version")
        if life["render_commit"] not in checked:
            _render_check(context, life["render_commit"])
            checked.add(life["render_commit"])
        b0, b1 = (life["branches"][b] for b in ("B0", "B1"))
        _need(b0["swap"] == b1["swap"], "lives:swap_differs")
        _need(b0["swap"] == [full.swap], "lives:swap")
        for branch in (b0, b1):
            _need(len(branch["est_tokens"]) == full.sessions
                  and len(branch["probe_tokens"]) == len(full.checkpoints)
                  and len(branch["content_sha256"]) == full.checkpoints[0], "lives:dry_shape")
            _need(branch["probe_points"] == list(full.checkpoints), "lives:probe_points")
        fork = life["fork"]
        _need(fork <= full.checkpoints[0], "lives:fork_late")
        differences = [j for j, (a, b) in enumerate(zip(b0["content_sha256"], b1["content_sha256"], strict=True), 1)
                       if a != b]
        _need(bool(differences), "lives:no_fork")
        _need(fork == differences[0], "lives:fork_mismatch")
        result.append({"life": life["life"], "b0_tokens": b0["est_tokens"],
                       "b1_tokens": b1["est_tokens"][fork - 1:], "fork": fork, "swap": full.swap,
                       "b0_probe_tokens": b0["probe_tokens"], "b1_probe_tokens": b1["probe_tokens"]})
    context.provenance["swaps"] = {life["life"]: life["swap"] for life in result}
    return result


def _planning(context):
    return False


def _roster_m(roster):
    m = len(roster["systems"]) - 2
    _need(m >= 1, "n_lives_floor:roster_m")
    return m


def _keep_subset(bundles, tracks):
    subset = sorted({life for _, life, track, keep, _ in next(iter(bundles.values()), ())
                     if track == "Keep" and keep == "K10"}) if "Keep" in tracks else []
    _need("Keep" not in tracks or len(subset) == 4, "n_lives_floor:keep_subset")
    return subset


def _life_count(sigma_d, m):
    z_a = statistics.NormalDist().inv_cdf(1 - 0.05 / (2 * m))
    z_b = statistics.NormalDist().inv_cdf(0.8)
    n = ((z_a + z_b) * sigma_d / 8) ** 2
    return min(48, max(24, math.ceil(n))), n


def _n_lives_floor(context):
    roster = context.get("roster")
    m = _roster_m(roster)
    controls = context.get("controls")
    tracks = set()
    for cell in _required(context):
        found = {item["track"] for arm in inputs.ARMS for item in controls["A"][arm]["items"]
                 if item["cell_id"] == cell}
        _need(bool(found), f"n_lives_floor:required_track:{cell}")
        tracks.update(found)
    data = context.get("bar2")
    arms = sorted(a for a, value in data["arms"].items() if value["kind"] == "system")
    bundles = data["bundles"]
    _need(all(a in bundles for a in arms), "n_lives_floor:bundles_mismatch")
    _need(len({frozenset(tuple(r[:4]) for r in bundles[a]) for a in arms}) <= 1,
          "n_lives_floor:bundles_mismatch")
    for arm in arms:
        for track in sorted({r[2] for r in bundles[arm]}):
            _need(track in tracks, f"n_lives_floor:bundles_track:{arm}/{track}")
    lives = sorted(context.get("history")["lives"])
    _need(len(lives) == 16, "n_lives_floor:bar2_lives")
    subset = _keep_subset(bundles, tracks)
    flags = {s["id"]: s["lcmx"] for s in roster["systems"]}
    # Bar 2 runs the full pilot roster (PREREG l.463); without the reference, its contrasts are missing from the family.
    _need(roster["reference"] in arms, "n_lives_floor:no_reference")
    pairs = list(combinations([a for a in arms if not flags[a]], 2))
    _need(bool(pairs), "n_lives_floor:no_pairs")
    scored = {a: {tuple(r[:4]) for r in bundles[a] if r[4] is not None} for a in arms}
    for a, b in pairs:
        common = scored[a] & scored[b]
        for track in sorted(tracks):
            valid = {life for _, life, t, k in common if t == track and k == "K100"}
            if track == "Keep":
                valid &= {life for _, life, t, k in common if t == track and k == "K10"}
            _need(bool(valid), f"n_lives_floor:empty_track:{a}/{b}/{track}")
    sigma_d, deviations = pilot.sigma_d(bundles, pairs, tracks, lives)
    value, n = _life_count(sigma_d, m)
    context.provenance["n_lives"] = {
        "M": m, "pairs": [[a, b, sd.hex()] for (a, b), sd in sorted(deviations.items())],
        "sigma_d": sigma_d.hex(), "z": [statistics.NormalDist().inv_cdf(p).hex()
                                        for p in (1 - 0.05 / (2 * m), 0.8)],
        "n": n.hex(), "keep_subset": subset}
    return value


def _probe_rates(context):
    data = context.get("bar2")
    rates, provenance = {}, {}
    for arm, lives in sorted(data["probe_only"].items()):
        counted = wall = tokens = 0
        for branches in lives.values():
            for sessions in branches.values():
                for session in sessions:
                    if session["wall_ms"] is None or session["stopped"]:
                        continue
                    counted += 1
                    wall += session["wall_ms"]
                    tokens += (sum(estimate_tokens(data["items"][i]["prompt"]) for i in session["items"])
                               + sum(session["context_tokens"]))
        if counted:
            _need(tokens > 0, f"probe_only:zero_tokens:{arm}")
            _need(wall > 0, f"probe_only:zero_wall:{arm}")
            rates[arm] = Fraction(wall, tokens)
        provenance[arm] = dict(timed_sessions=counted, wall_ms=wall, tokens=tokens,
                               source="own" if counted else "slowest")
    _need(bool(rates), "probe_only:no_timed_arm")
    slowest = max(rates.values())
    for arm in reserve.PROBE_ONLY_LOAD:
        rates.setdefault(arm, slowest)
    rates["anchor"] = rates["C"]
    provenance["anchor"] = {**provenance["C"], "source": "C"}
    context.provenance["probe_only_rates"] = provenance
    return rates


def _probe_controls(context):
    data, controls = context.get("bar2"), context.get("controls")
    for name, arm in inputs.ARMS.items():
        output = controls["A"][name]
        owners = dict(output["singleton_lives"])
        for bundle in output["bundles"]:
            owners.update((iid, bundle["life"]) for iid in bundle["items"])
        expected = {life: {i["item_id"] for i in output["items"] if owners[i["item_id"]] == life}
                    for life in context.get("history")["lives"]}
        actual = {life: {iid for sessions in branches.values() for s in sessions for iid in s["items"]}
                  for life, branches in data["probe_only"][arm].items()}
        _need(actual == expected and set(owners.values()) == set(expected), "probe_only:controls_mismatch")


def _probe_only(context):
    context.get("bar2")
    _probe_controls(context)
    window = context.artifact(C4)["window_tokens"]
    full = scale.named("full")
    _need(window == full.window, "probe_only:c4_window")
    rows, anchors = [], {}
    for life in context.artifact(DRY)["lives"]:
        who = life["life"]
        for branch, record in life["branches"].items():
            reason = f"probe_only:dry_inconsistent:{who}/{branch}"
            for c, checkpoint in enumerate(record["probe_points"]):
                count, prompt, peak = (record[k][c] for k in ("probe_items", "probe_tokens", "ceil_peak"))
                contexts = {a: v[c] for a, v in record["probe_only_context"].items()}
                _need(count >= sum(n for _, k, n in life["bundles"] if k == checkpoint), reason)
                _need(contexts["F"] == 2 * count, reason)  # B-21: F carries 2 context tokens per item
                total = prompt + contexts["CEIL"]
                _need((count == 0 and prompt == peak == 0 and not any(contexts.values()))
                      or (count > 0 and total <= peak * count and peak <= total), reason)
                for arm in reserve.PROBE_ONLY_LOAD:
                    if arm != "CEIL" or peak <= window:
                        rows.append([arm, who, branch, checkpoint, prompt + contexts[arm]])
        anchor = dict(life["anchor"])
        _need(len(anchor) == sum(n for _, k, n in life["bundles"] if k > full.swap),
              f"probe_only:anchor_count:{who}")
        _need(len(anchor) >= 20, f"probe_only:anchor_short:{who}")
        order = anchor_order(str(life["seed"]), who, anchor)
        anchors[who] = sum(anchor[ref] for ref in order[:20])
    return dict(tokens=sorted(rows), anchor_tokens=anchors, rates=_probe_rates(context))


@dataclass(frozen=True)
class Rule:
    rule: str
    sources: tuple[str, ...]
    function: object


RULES = {
    field: Rule(rule, (RULING, *sources), function)
    for field, rule, sources, function in (
        ("rows", "B-1", ("PREREG l.40,435,452,566,718", "B-2"), _rows),
        ("passover", "B-3", ("PREREG l.40,441", CLARIFICATION), _passover_rule),
        ("control_failure", "B-4", ("PREREG l.549,777",), _control_rule),
        ("lanes", "B-5, B-15, B-16", ("PREREG l.26,716", *STAGE_B), _lanes),
        ("alloc_by_b", "B-6", ("PREREG l.418", *STAGE_B), _alloc),
        ("checkpoints", "B-7", ("PREREG l.418",), _checkpoints),
        ("lives", "B-7, B-17, B-17a, B-17b, B-18, B-19", ("PREREG l.431,734,795", *STAGE_B), _lives),
        ("probe_only", "B-8, B-21 to B-25",
         ("PREREG l.453,759", CLARIFICATION, "#245 issuecomment-6535643668"), _probe_only),
        ("n_lives_floor", "B-9, B-26, B-27",
         ("PREREG l.491,498,503", "PREREG l.574", "#245 issuecomment-6535643668"), _n_lives_floor),
        ("required", "B-10", ("PREREG l.27",), _required),
        ("planning", "B-10", (), _planning),
    )}


def build_base(*, bar2: bytes, controls: bytes, history: bytes, root: Path) -> bytes:
    """Return canonical base bytes only when every registered field succeeds."""
    context = _Context(bar2, controls, history, root)
    document, refusals = {}, []
    for field in BASE_FIELDS:
        try:
            _need(context.global_reason is None, context.global_reason)
            _need(field in RULES, "rule_missing")
            rule = RULES[field]
            document[field] = rule.function(context)
            paths = FIELD_ARTIFACTS.get(field, ())
            context.provenance[field] = {"rule": rule.rule, "sources": list(rule.sources),
                                         "artifacts": [a for a in context.provenance["artifacts"]
                                                       if a["path"] in paths]}
        except AssertionError:
            raise
        except Exception as error:
            refusals.append((field, str(error)))
    if context.global_reason is None and "bar2" not in context.errors:
        try:
            c8_check(context)
        except AssertionError:
            raise
        except Exception as error:
            refusals.append(("C-8", str(error)))
    if refusals:
        raise BaseRefused(refusals)
    excluded = {s["id"] for s in context.get("roster")["systems"] if s["lcmx"]}
    neutrality = {}
    for label, omitted in (("all", frozenset()), ("without_lcmx", excluded)):
        passes, stops = _passover(context, omitted)
        failure, units = _control_failure(context, omitted)
        rates = [v for arm, v in context.values["rates"].items() if arm not in omitted]
        neutrality[label] = {"passover": passes, "control_failure": failure,
                             "fallback_row_rate": max(rates) if rates else None,
                             "passover_counts": stops, "control_counts": units}
    context.provenance.update(
        account_pool=context.get("bar2")["run_lock"]["account_pool"], neutrality=neutrality,
        pending_disclosures=["B-4 recovered INFRA attempts: pending; sources C5a's container (B-4) and the bar-2 runner",
                             "B-9 sigma_d's scale difference from the full tier (PREREG l.548): the card",
                             "B-8 the anchor's rate: C's measured pinned-lane rate, a proxy for the swap lane, since bar 2 never runs the swap model: the card"])
    document["base_provenance"] = context.provenance
    return canon(run._encode(document))
