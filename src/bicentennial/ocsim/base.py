"""Build binding OC base documents from locked, synthetic-testable sources.

Stage a deliberately refuses the five rules assigned to later stages. No
schema loader or contract validator runs here; the history checks are frozen
below and covered by C-8, together with the token estimator.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.ocsim import inputs, run
from bicentennial.world.tokens import estimate_tokens

ROSTER = "prereg/roster/full-tier.json"
C12 = "prereg/completion/C-12.json"
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


def _bar2(data, history, roster):
    _shape(data, ("run_lock", "arms", "items"), "bar2:shape:root")
    lock = data["run_lock"]
    _shape(lock, ("benchmark_commit", "generator_version", "history_sha256", "status", "account_pool"),
           "bar2:shape:run_lock")
    _need(_hex(lock["benchmark_commit"], 40) and _hex(lock["history_sha256"], 64)
          and isinstance(lock["generator_version"], str), "bar2:shape:run_lock")
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
    return data


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
        _need(_hex(self.commit, 40), f"source_missing:{path}")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
        try:
            result = subprocess.run(("git", "-C", str(self.root), "show", f"{self.commit}:{path}"),
                                    capture_output=True, check=False, env=env)
        except OSError as error:
            raise ValueError(f"source_missing:{path}") from error
        _need(result.returncode == 0, f"source_missing:{path}")
        raw = result.stdout
        data = _json(raw, path)
        _need(isinstance(data, dict), f"source_shape:{path}")
        _need(data.get("status") == "binding", f"source_provisional:{path}")
        if path == ROSTER:
            _shape(data, ("status", "systems"), f"source_shape:{path}")
            _need(isinstance(data["systems"], list) and bool(data["systems"]), f"source_shape:{path}")
            ids = []
            for system in data["systems"]:
                _shape(system, ("id", "lcmx"), f"source_shape:{path}")
                _need(isinstance(system["id"], str) and bool(system["id"])
                      and type(system["lcmx"]) is bool, f"source_shape:{path}")
                ids.append(system["id"])
            _need(len(ids) == len(set(ids)), f"source_shape:{path}")
        else:
            _shape(data, ("status", "profile", "required"), f"source_shape:{path}")
            _need(data["profile"] == "Text" and _strings(data["required"]), f"source_shape:{path}")
        self.provenance["artifacts"].append({"path": path, "commit": self.commit,
                                             "sha256": sha256(raw).hexdigest()})
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
    _need(cells == sorted(set(cells)), "required:not_sorted_unique")
    return cells


def _planning(context):
    return False


def _pending(rule):
    def refuse(context):
        raise ValueError(f"pending:{rule}")
    return refuse


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
        ("lanes", "B-5", ("PREREG l.26,716",), _pending("B-5")),
        ("alloc_by_b", "B-6", ("PREREG l.418",), _pending("B-6")),
        ("checkpoints", "B-7", ("PREREG l.418",), _checkpoints),
        ("lives", "B-7", ("PREREG l.431,734,795",), _pending("B-7")),
        ("probe_only", "B-8", ("PREREG l.453,759", CLARIFICATION), _pending("B-8")),
        ("n_lives_floor", "B-9", ("PREREG l.491,498,503",), _pending("B-9")),
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
            context.provenance[field] = {"rule": rule.rule, "sources": list(rule.sources)}
        except Exception as error:
            refusals.append((field, str(error)))
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
        pending_disclosures=["B-4 recovered INFRA attempts: stage c, with the probe-only arms' bar-2 records"])
    document["base_provenance"] = context.provenance
    return canon(run._encode(document))
