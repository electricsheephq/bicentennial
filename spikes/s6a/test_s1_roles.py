"""Offline S1/director seam regressions; minimized fixtures contain no harness text."""

import copy
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "s1"), str(HERE.parent / "s6b")]
import director
import roles
import sol_director as sd

SOURCES = json.loads((HERE.parent / "s1/fixtures/shapes.json").read_text())["sources"]
CHAT = "/main/v1/chat/completions"


class S1Roles(unittest.TestCase):
    def make(self, sol=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        args = SimpleNamespace(life=str(HERE / "micro_life.json"), ledger_dir=str(root / "ledger"),
                               budget_file=str(root / "budget.json"), budget_cap=100, run="seam", model="stub",
                               mode="stub", write_turns=False, measure_overhead=False, chars_per_token=4,
                               context_length=64000, timeout=1, lane_rewrite="", rate_per_min=0)
        return sd.Director(args) if sol else director.Director(args)

    def body(self, d, index=0, sol=False, tools=True):
        msgs = [{"role": "user", "content": d.expected[index]["user"]}]
        body = {"model": "main", "tools": [{"type": "function", "name": "memory",
                                            "function": {"name": "memory"}}] if tools else []}
        return body | ({"input": msgs} if sol else {"messages": msgs})

    def handle(self, d, body, sol=False, path=CHAT):
        return d.handle(body, {}) if sol else d.handle(path, body)

    def test_contexts_equal_recorded_r6_and_r7c(self):
        for sol, name in ((False, "s6a-r6-write"), (True, "s6b-r7c-write")):
            with self.subTest(source=name):
                src = next(s for s in SOURCES if s["source"] == name)
                self.assertEqual(self.make(sol).ctx, roles.Context.of(src["ctx"]))

    def test_r6_128_is_title_and_routes_to_aux(self):
        d = self.make()
        src = next(s for s in SOURCES if s["source"] == "s6a-r6-write")
        for row in src["rows"]:
            with mock.patch.object(roles, "shape", return_value=row["shape"]):
                if row["seq"] == 128:
                    code, _, rec = d.handle(CHAT, {"messages": []})
                    self.assertEqual((code, rec["s1"], rec["role"], rec["subrole"]),
                                     (200, {"role": "title", "method": "shape"}, "aux", "title_generation"))
                    self.assertEqual([u["kind"] for u in rec["upstream"]], ["aux"])
                    return
                result = roles.classify({"method": "POST", "path": CHAT, "body": {}}, d.ctx)
                self.assertEqual(result[0], row["expected"])
                roles.advance(d.ctx, result, row["issued"], row.get("issued_as"))
        self.fail("fixture row 128 missing")

    def test_synthetic_title_overrides_probe_retry_without_harness_text(self):
        for sol in (False, True):
            with self.subTest(sol=sol):
                d = self.make(sol)
                d.cursor = 63
                d.current = d.expected[62]
                body = self.body(d, 62, sol, tools=False)
                if sol:
                    body["instructions"] = "Title: x"
                else:
                    body["messages"].insert(0, {"role": "system", "content": "Title: x"})
                # On the old director the missing Context must not hide the misrouting assertion.
                if hasattr(d, "ctx"):
                    d.ctx.signatures += (roles.Signature("t", "title", "system", 6, roles.h16("Title:")),)
                code, _, rec = self.handle(d, body, sol)
                self.assertEqual((code, rec["role"], rec["subrole"]), (200, "aux", "title_generation"))
                self.assertEqual(rec["s1"], {"role": "title", "method": "shape"})
                self.assertEqual([u["kind"] for u in rec["upstream"]], ["aux"])
                self.assertEqual(d.cursor, 63)

    def test_every_fixture_role_survives_both_director_seams(self):
        for sol in (False, True):
            for src in SOURCES:
                with self.subTest(sol=sol, source=src["source"]):
                    d = self.make(sol)
                    # Other harnesses have their own declared scripts/aliases; use their fixture context.
                    d.ctx = roles.Context.of(src["ctx"])
                    for row in src["rows"]:
                        with mock.patch.object(roles, "shape", return_value=row["shape"]):
                            mapped = director.s1_classify(d, row["shape"]["path"], {})
                        result = mapped[3]
                        self.assertEqual(result[0], row["expected"], (src["source"], row["seq"]))
                        self.assertNotEqual(result[0], "unknown")
                        if result[0] == "compaction":
                            self.assertEqual(mapped[:3], ("summariser", "compression", None))
                        roles.advance(d.ctx, result, row["issued"], row.get("issued_as"))

    def test_reply_id_registration_after_two_concurrent_turns_does_not_rewind(self):
        for sol in (False, True):
            for write in (False, True):
                with self.subTest(sol=sol, write=write):
                    d = self.make(sol)
                    first = 0 if write else 62
                    d.cursor, d.write_turns = first, write
                    entered, release = threading.Event(), threading.Event()
                    real = d.upstream

                    def delayed(body, kind, *rest, entered=entered, release=release, real=real, sol=sol):
                        if threading.current_thread().name.startswith("first"):
                            entered.set()
                            if not release.wait(3):
                                raise AssertionError("second request never released first")
                        up = real(body, kind, *rest)
                        cid = f"call-{threading.current_thread().name}"
                        call = {"id": cid, "type": "function", "function": {"name": "memory", "arguments": "{}"}}
                        if sol:
                            up["events"] = [{"type": "response.output_item.done", "item": {
                                "type": "function_call", "call_id": cid, "name": "memory", "arguments": "{}"}}]
                        else:
                            up["body"]["choices"][0]["message"]["tool_calls"] = [call]
                        return up

                    d.upstream = delayed
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as pool:
                        future = pool.submit(self.handle, d, self.body(d, first, sol), sol)
                        try:
                            self.assertTrue(entered.wait(3))
                            self.assertEqual(self.handle(d, self.body(d, first + 1, sol), sol)[0], 200)
                        finally:
                            release.set()
                        self.assertEqual(future.result(timeout=3)[0], 200)
                    self.assertEqual(d.cursor, first + 2)
                    self.assertEqual(d.current, d.expected[first + 1])
                    ids = d.id_roles
                    self.assertEqual(len(ids), 2)
                    self.assertEqual(d.ctx.issued, {cid: "write_turn" if write else "probe_main" for cid in ids})
                    snapshot = d.cursor
                    # These ids are never registered by re-advancing the earlier cursor result.
                    self.assertEqual(snapshot, first + 2)

    def test_never_raises_and_logs_only_exception_class(self):
        for sol in (False, True):
            for stage in ("classify", "mapping", "advance", "write_shape", "main_without_turn", "malformed", "scalar_items", "scalar_tools", "non_object"):
                with self.subTest(sol=sol, stage=stage):
                    d = self.make(sol)
                    body = self.body(d, sol=sol)
                    result = {"write_shape": ("write_turn", "shape", {}),
                              "main_without_turn": ("replay_main", "cursor", {}),
                              "mapping": ("replay_main", "cursor", {"turn": len(d.expected) + 1})}.get(stage)
                    with mock.patch.object(roles, "classify", wraps=roles.classify) as classify, \
                            mock.patch.object(roles, "advance", wraps=roles.advance) as advance:
                        if stage == "classify":
                            classify.side_effect = RuntimeError("DO-NOT-LOG-THIS")
                        elif stage == "advance":
                            advance.side_effect = RuntimeError("DO-NOT-LOG-THIS")
                        elif result:
                            classify.return_value = result
                        elif stage == "malformed":
                            body["input" if sol else "messages"] = [1]
                        elif stage == "scalar_items":
                            body["input" if sol else "messages"] = 1
                        elif stage == "scalar_tools":
                            body["tools"] = 1
                        elif stage == "non_object":
                            body = []
                        code, _, rec = self.handle(d, body, sol)
                    self.assertEqual((code, rec["role"], rec["subrole"]), (400, "unknown", ""))
                    self.assertFalse(rec["upstream"])
                    self.assertNotIn("DO-NOT-LOG-THIS", json.dumps(rec))
                    self.assertEqual(set(rec["s1"]), {"role", "method"})
                    if stage in ("classify", "advance", "mapping", "malformed"):
                        self.assertIn(rec["s1_error"], ("RuntimeError", "IndexError", "TypeError"))

    def test_retry_continuation_and_missing_pending_use_director_turn(self):
        for sol in (False, True):
            d = self.make(sol)
            self.handle(d, self.body(d, sol=sol), sol)
            self.assertEqual(d.ctx.current, d.ctx.expected[0])
            self.assertEqual(d.current, d.expected[0])
            for which in ("retry", "continuation"):
                with mock.patch.object(roles, "classify", return_value=("replay_main", "cursor", {"turn": which})):
                    code, _, rec = self.handle(d, self.body(d, sol=sol), sol)
                self.assertEqual((code, rec["served"], rec["cursor"]),
                                 (200, "script_retry", {"session": 1, "turn": 1}))
            for role in ("write_turn", "replay_main"):
                with mock.patch.object(roles, "classify", return_value=(role, "cursor", {"call_id": "missing"})):
                    self.assertEqual(self.handle(d, self.body(d, sol=sol), sol)[0], 400)

    def test_auxiliary_labels_and_request_envelope(self):
        for sol in (False, True):
            d = self.make(sol)
            body = self.body(d, sol=sol)
            with mock.patch.object(roles, "classify", wraps=roles.classify) as classify:
                self.handle(d, body, sol)
                classify.assert_called_once_with({"method": "POST", "path": sd.MOUNT + "/responses" if sol else CHAT,
                                                  "body": body}, d.ctx)
            d.id_roles["aux-call"] = ("aux", "vision")
            cases = [("aux", "cursor", {"call_id": "aux-call"}, "aux", "vision"),
                     ("aux", "shape", {"markers": ["hermes_background_review"]}, "aux", "background_review"),
                     ("aux", "shape", {}, "aux", "metadata"),
                     ("summariser", "model_alias", {}, "aux", "summariser"),
                     ("extraction", "model_alias", {}, "aux", "extraction"),
                     ("compaction", "shape", {}, "summariser", "compression")]
            for raw, method, ev, role, sub in cases:
                with mock.patch.object(roles, "classify", return_value=(raw, method, ev)):
                    code, _, rec = self.handle(d, body, sol)
                self.assertEqual((code, rec["role"], rec["subrole"]), (200, role, sub))
                self.assertEqual(rec["upstream"][0]["kind"], "summariser" if raw == "compaction" else "aux")

    def test_known_tightenings(self):
        for sol in (False, True):
            for case in ("substring", "retry_no_tools", "summary_instructions", "undeclared_alias",
                         "malformed", "unanswered_issued", "cursor_before_alias"):
                if not sol and case == "summary_instructions":
                    continue
                with self.subTest(sol=sol, case=case):
                    d = self.make(sol)
                    body = self.body(d, sol=sol)
                    key = "input" if sol else "messages"
                    path = CHAT
                    if case == "substring":
                        body[key][0]["content"] = "prefix " + d.expected[0]["user"]
                    elif case == "retry_no_tools":
                        self.handle(d, copy.deepcopy(body), sol)
                        body["tools"] = []
                    elif case == "summary_instructions":
                        body = {"instructions": sd.SUMMARY_SIG, "input": [{"role": "user", "content": "x"}]}
                    elif case == "undeclared_alias":
                        path, body[key][0]["content"] = "/aux/undeclared/v1/chat/completions", "x"
                    elif case == "malformed":
                        body["tools"] = [1]
                    elif case == "unanswered_issued":
                        d.id_roles["issued"] = ("probe_main", "tool_results")
                        if hasattr(d, "ctx"):
                            d.ctx.issued["issued"] = "probe_main"
                        body[key] += ([{"type": "function_call", "call_id": "issued"},
                                       {"type": "function_call", "call_id": "other"},
                                       {"type": "function_call_output", "call_id": "other", "output": "ok"}]
                                      if sol else [{"role": "assistant", "tool_calls": [{"id": "issued"}, {"id": "other"}]},
                                                   {"role": "tool", "tool_call_id": "other", "content": "ok"}])
                    elif case == "cursor_before_alias":
                        path = "/aux/title_generation/v1/chat/completions"
                    code, _, rec = self.handle(d, body, sol, path)
                    self.assertEqual((code, rec["role"]),
                                     (200, "replay_main") if case == "cursor_before_alias" else (400, "unknown"))


if __name__ == "__main__":
    unittest.main()
