"""#608: a refused request's evidence reaches unit_diagnostics.json before its sandbox is deleted."""

import json

from test_unreadable_state import harness, lives, unit, unit_sessions  # noqa: F401

from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter

PLANTED = ("planted-user-608a", "planted-args-608b", "planted-output-608c", "planted-system-608d",
           "/srv/planted-path-608e/notes.txt")


def todo_after_tool_results(alias, user):
    """A probe turn's tool call, its result, then a trailing user row that no rule matches."""
    return {"model": alias, "tools": [{"type": "function", "function": {"name": "terminal"}}], "messages": [
        {"role": "system", "content": f"{PLANTED[3]} working in {PLANTED[4]}"}, {"role": "user", "content": user},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-608", "type": "function", "function": {
            "name": "terminal", "arguments": json.dumps({"command": PLANTED[1]})}}]},
        {"role": "tool", "tool_call_id": "call-608", "content": PLANTED[2]},
        {"role": "user", "content": PLANTED[0]}]}


def test_probe_refusal_evidence_outlives_the_sandbox(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    session, sent = adapter.HermesAdapter.run_session, []

    def refused(self, index, **kw):
        result = session(self, index, **kw)
        probe = next(s for s in self.script["sessions"] if s["index"] == index)
        if probe["kind"] == "probe" and not sent:  # the first probe session of the first attempt only
            alias = self.director.route["alias"]
            body = todo_after_tool_results(alias, probe["turns"][-1]["user"])
            sent.append(self.director.handle("POST", "/main/v1/chat/completions", {}, canon(body))[0])
            sent.append((index, probe["turns"][-1]["n"], alias))
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", refused)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    status, (index, turn, alias) = sent
    assert status == 400 and result.attempts == 2
    assert not (tmp_path / "attempts" / "0" / "B0").exists() and not (tmp_path / "attempts" / "1" / "B0").exists()
    first, second = result.runs
    (row,) = getattr(first, "refusals", [None])
    assert getattr(second, "refusals", None) == []
    assert {k: v for k, v in row.items() if k not in ("seq", "attempt_id")} == {
        "served": "refused_unknown", "status": 400, "method": "POST", "path": "/main/v1/chat/completions",
        "wire": "chat", "session": index, "cursor": {"session": index, "turn": turn}, "s1_role": "unknown",
        "s1_method": "unknown", "reason": "no rule matched", "model": alias, "n_messages": 5,
        "shape": "suctu", "last_role": "user", "tool_calls": 1, "tool_results": 1, "call_ids": ["call-608"],
        "result_ids": ["call-608"]}
    (ledgered,) = [r for r in first.records if r.get("served") == "refused_unknown"]
    assert (row["seq"], row["attempt_id"]) == (ledgered["seq"], ledgered["attempt_id"])
    raw = (tmp_path / "out" / "unit_diagnostics.json").read_bytes()
    diagnostics = json.loads(raw)
    assert [a.get("refusals") for a in diagnostics["attempts"]] == [[row], None]
    assert not [p for p in PLANTED if p.encode() in raw or p.encode() in canon(row)]


def test_a_refusal_alone_writes_unit_diagnostics(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    """A refused_float retry of a probe turn: the attempt completes, unstopped, with no incidental row."""
    session, sent = adapter.HermesAdapter.run_session, []

    def refused(self, index, **kw):
        result = session(self, index, **kw)
        probe = next(s for s in self.script["sessions"] if s["index"] == index)
        if probe["kind"] == "probe" and not sent:
            body = {"model": self.director.route["alias"], "temperature": 0.5,
                    "messages": [{"role": "user", "content": probe["turns"][-1]["user"]}],
                    "tools": [{"type": "function", "function": {"name": "terminal"}}]}
            raw = json.dumps(body).encode()  # canon refuses the float, as the director's own canon check does
            sent.append(self.director.handle("POST", "/main/v1/chat/completions", {}, raw)[0])
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", refused)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    (run,) = result.runs
    assert sent == [400] and result.attempts == 1
    assert (run.stopped, run.incidental_unknown_400) == (None, 0)
    (row,) = getattr(run, "refusals", [None])
    assert (row["served"], row["s1_role"]) == ("refused_float", "probe_main")
    path = tmp_path / "out" / "unit_diagnostics.json"
    assert path.exists() and json.loads(path.read_bytes()) == dict(
        attempts=[dict(attempt=0, stopped=None, incidental_unknown_400=0, refusals=[row])])


def test_only_rows_of_the_evidence_shape_reach_the_diagnostics(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    session, sent = adapter.HermesAdapter.run_session, []

    def refused(self, index, **kw):
        result = session(self, index, **kw)
        probe = next(s for s in self.script["sessions"] if s["index"] == index)
        if probe["kind"] == "probe" and not sent:
            body = {"model": self.director.route["alias"], "temperature": 0.5,
                    "messages": [{"role": "user", "content": probe["turns"][-1]["user"]}],
                    "tools": [{"type": "function", "function": {"name": "terminal"}}]}
            sent.append(self.director.handle("POST", "/main/v1/chat/completions", {}, json.dumps(body).encode())[0])
            with (self.director.ledger.root / "refusals.jsonl").open("ab") as f:  # no row the director could write
                f.write(b'{"status": 0.5}\n{"served": "refused_float", "planted": "planted-user-608a"}\n[1]\n'
                        + b"[" * 100_000 + b"\n")
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", refused)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    (run,) = result.runs
    assert sent == [400] and [r["served"] for r in run.refusals] == ["refused_float"]
    assert json.loads((tmp_path / "out" / "unit_diagnostics.json").read_bytes())["attempts"][0]["refusals"] == run.refusals
