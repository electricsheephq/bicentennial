"""Probe-only live service, with an independent scripted reader and report evidence."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from bicentennial.audit.readback import output
from bicentennial.canon import canon
from bicentennial.director.upstream.login import CREDENTIAL_STOPS
from bicentennial.director.upstream.router import ProbeLiveRouter as ProbeLiveRouter
from bicentennial.genres.g2_assistant.envseed import probe_envseed
from bicentennial.items.templates import g2
from bicentennial.items.templates.g1.common import repo_checks, repo_state
from bicentennial.ledger import BlobStore, Guard
from bicentennial.packs.catalogue import TEMPLATES_BY_GENRE
from bicentennial.probe.probe_responder import _earlier_body
from bicentennial.probe.scripted_reader import failing_stage, read
from bicentennial.render.stream import content
from bicentennial.report.t2lite_diag import (
    citation_match,
    value_match,
    value_match_normalised,
)
from bicentennial.runner.hermes_score import MISSING, score_item
from bicentennial.score.exposure import context_text
from bicentennial.score.qa import parse_envelope, score_qa

LIVE_FAILURES = frozenset("responder_live_" + code for code in (
    "stopped", "unsupported", "spend_stop", "hold_expired", "no_upstream", "unavailable")) | {"director_error"}


class LiveCredentialStop(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def live_probe_code(row):
    return row.get("served") if row.get("role") == "probe_main" and row.get("served") in LIVE_FAILURES else None


def strip_contract(body, prompt, suffix):
    """Copy the body, removing only this item's instruction from user text."""
    body = deepcopy(body)
    for message in body.get("messages", []):
        if message.get("role") != "user" or not suffix:
            continue
        text = message.get("content")
        if isinstance(text, str):
            message["content"] = text.replace(prompt + suffix, prompt, 1)
        elif isinstance(text, list):
            for block in text:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block["text"] = block["text"].replace(prompt + suffix, prompt, 1)
    return body


class ProbeLiveLeg:
    def __init__(self, live, live_model, scripted, answer_contract):
        if live_model is None:
            if len(live.upstreams) != 1:
                raise ValueError("probe_live_model_ambiguous")
            live_model = next(iter(live.upstreams))
        self.live, self.model, self.scripted, self.contract = live, live_model, scripted, answer_contract
        self.wire = live.wire
        self.latest, self.initial, self.errors, self.identity_flags = {}, {}, {}, set()
        self.final_items, self.transforms = set(), set()
        self.drift = deepcopy(self.state().get("identity_drift"))

    def state(self):
        return self.live.state()

    def served_identities(self):
        return self.live.served_identities()

    def check_session(self, previous=None):
        state = self.state()
        drift = deepcopy(state.get("identity_drift"))
        if drift != self.drift and previous is not None:
            self.identity_flags.add(previous)
        self.drift = drift
        reason = state.get("stop_reason")
        if reason in CREDENTIAL_STOPS or state.get("login_stop"):
            raise LiveCredentialStop(reason if reason in CREDENTIAL_STOPS else state["login_stop"])

    def results(self):
        return dict(self.latest)

    def respond(self, call):
        # The bridge pins effort on chat translation; native Responses would bypass that pin.
        if call.wire != "chat":
            raise ValueError("probe_live_requires_chat")
        position = (call.cursor["session"], call.cursor["turn"])
        iid = self.scripted.cursors[position]
        view, keys = self.scripted.readers[iid]
        key = (call.run_key, *position)
        # The body is the one the live model sent: like T1's reader, the shadow sees the model's own earlier
        # messages in this session, but never this item's answer, which is the reply.
        try:
            body = self._without_contracts(call.body, position[0])
            result = read(view, keys, context_text(body), mode="hermes", earlier=context_text([
                self._without_contracts(_earlier_body(v), position[0])
                for v in self.scripted.earlier(call.run_key, *position)]))
            self.initial.setdefault(key, result.in_context)
            if iid not in self.errors:
                self.latest[iid] = result
        except Exception as error:
            self.initial.setdefault(key, None)
            self.errors[iid] = type(error).__name__
            self.latest.pop(iid, None)
        reply = self.live.respond(replace(call, model=self.model))
        return replace(reply, model=call.model)

    def _without_contracts(self, body, session):
        """Every QA turn of this session carries the contract, in this request and in the earlier ones the shadow reads:
        it reads none of them, as T1 has none."""
        if not isinstance(body, dict):
            return body
        for (index, _), other in sorted(self.scripted.cursors.items()):
            shown = self.scripted.readers[other][0]
            if index == session and "envelope" in shown["options"][0]:
                body = strip_contract(body, shown["prompt"], self.contract.render(
                    [o["envelope"] for o in shown["options"]]))
        return body

    def _act_stage(self, item, result, evidence, probe, record, db, schedule):
        if result is None or item["item_id"] not in evidence.act or item["item_id"] in evidence.classes:
            return None
        genre = db.execute("SELECT genre FROM meta").fetchone()[0]
        template = replace(TEMPLATES_BY_GENRE[genre][record["template_id"]], checkpoint=probe.checkpoint)
        table = next(t for t in template.decision_tables if t["table_id"] == item["decision_table_ref"])
        window = tuple(db.execute("SELECT window_open_t, window_close_t FROM commitment WHERE fact_id=?",
                                 (record["decisive_fact_id"],)).fetchone()) if table["timed"] else None
        g1 = genre == "G1"
        case = SimpleNamespace(item=item, table=table, window=window,
            t_sim=window[0] if window else schedule.sessions[probe.checkpoint - 1].t_end,
            seed=None if g1 else probe_envseed(db, probe.index, probe.checkpoint).seed,
            state0=repo_state(db, schedule, probe.checkpoint) if g1 else None,
            checks=repo_checks(template, db, schedule)[record["instance_key"]] if g1 else None,
            roles={} if g1 else g2.option_roles(template, db, schedule)[record["instance_key"]])
        iid = item["item_id"]
        scored = score_item(item, cls=None, label=None, result=result, envelope=MISSING, act=evidence.act[iid],
            case=case, scoring_evidence=None, keys=self.scripted.readers[iid][1],
            stored_roots=evidence.stored_roots.get(iid), retained_roots=evidence.retained_roots.get(iid),
            attempt=evidence.attempt)
        return scored.get("stage_attribution") if isinstance(scored, dict) else None

    def write_records(self, root, compiled, items, evidence, rows, life_dir, branch, db, schedule, item_records):
        stream = [json.loads(line) for line in (life_dir / f"stream.{branch}.jsonl").read_bytes().splitlines()]
        blobs = BlobStore(root / "run/ledger/blobs", Guard([]))
        by_id, records = {i["item_id"]: i for i in items}, []
        metadata = {r["item_id"]: r for r in item_records}
        # The stack's identity_drift holds only the first drift; each off-baseline reply is marked in its row.
        changed = {(r.get("cursor") or {}).get("session") for r in rows if r.get("role") == "probe_main" and any(
            isinstance(d, dict) and d.get("identity_changed") is True
            for u in r.get("upstream", []) for d in u.get("diagnostics", []))}
        for probe in compiled.probes:
            for n, iid in enumerate(probe.item_ids, 1):
                item, result = by_id[iid], self.latest.get(iid)
                qa = item["stage"] != "act"
                texts = [content(r) for r in stream if r["event_id"] in item["gold_spans"]]
                gold = next(o.get("envelope") for o in item["options"] if o["option_id"] == item["gold"]["option_id"])
                final = next((r for r in reversed(rows) if r.get("role") == "probe_main" and
                              r.get("cursor") == dict(session=probe.index, turn=n)), {})
                if qa and final.get("status") == 200:
                    calls, reply_texts = output(json.loads(blobs.get(final["resp"])), "chat")
                    if not calls:
                        served = parse_envelope("".join(reply_texts))
                        if iid not in self.final_items:
                            evidence.envelopes[iid] = served
                        elif served != evidence.envelopes[iid]:
                            self.transforms.add(iid)  # the delivered final is not the live model's answer (DESIGN §14)
                env = evidence.envelopes.get(iid)
                # A classed item has no stage attribution, as in the scorer.
                attribution = (failing_stage(result, self.scripted.readers[iid][1],
                    failed=score_qa(item, env, evidence_texts=texts).score_milli != 1000,
                    stored_roots=evidence.stored_roots.get(iid), retained_roots=evidence.retained_roots.get(iid))
                    if qa and result and iid not in evidence.classes else
                    self._act_stage(item, result, evidence, probe, metadata[iid], db, schedule) if not qa else None)
                initial = next((value for key, value in self.initial.items() if key[1:] == (probe.index, n)), None)
                records.append(dict(item_id=iid, probe_session=probe.index, checkpoint=probe.checkpoint, stage=item["stage"],
                    shadow=dict(selected_option=result.selected_option if result else None,
                        in_context=result.in_context if result else None, in_context_initial=initial,
                        carry_over=result.carry_over if result else None, shadow_error=self.errors.get(iid),
                        stage_attribution=attribution),
                    envelope=dict(parsed=env, value_match=value_match(gold, env) if qa else None,
                        value_match_normalised=value_match_normalised(gold, env) if qa else None,
                        citation_match=citation_match(env["citation"], texts) if env else None),
                    live=dict(served_by=final.get("served_by"), served=final.get("served"),
                              identity_flag=probe.index in self.identity_flags or probe.index in changed)))
        (root / "t2lite_probes.json").write_bytes(canon(sorted(records, key=lambda r: r["item_id"])))
