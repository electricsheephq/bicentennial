"""Probe-live developer runs over T1 lives, with all-or-refusal publication."""

import fcntl
import json
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bicentennial.canon import canon, sha256_canon
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.check import Voids
from bicentennial.director.responder import Reply
from bicentennial.director.upstream import login as custody
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items.protocol import CANARY
from bicentennial.probe.scripted_reader import ReaderResult
from bicentennial.report.receipt import (
    build_receipt,
    ledger_latencies,
    load_milli,
    raw_body_digest,
)
from bicentennial.report.t2lite_card import _LIVE_ANSWER, build_t2lite_card
from bicentennial.report.t2lite_flips import (
    BaselineRefused,
    check_baseline_t2lite,
    flip_report,
)
from bicentennial.runner import t0, t1
from bicentennial.runner.hermes_score import MISSING, Infra, identity0, score_item
from bicentennial.runner.life import LifeRun, _rows, _tokens, run_life
from bicentennial.runner.live import build_live_stack
from bicentennial.runner.probe_live import LiveCredentialStop
from bicentennial.sandbox import fixedroot
from bicentennial.score.classes import outcome
from bicentennial.systems.hermes_plugin import is_plugin, resolve_worker_env

MODEL, EFFORT = "gpt-6.1-sol", "medium"
# The live lane's settings, required as in the spikes; nothing defaults to a fake address.
LIVE_ENV = ("BICENTENNIAL_SOL_TOKEN_URL", "BICENTENNIAL_SOL_CLIENT_ID", "BICENTENNIAL_SOL_BASE_URL")
# Never sent upstream (build_live_stack sets send_cap=False); it only bounds the zero-price reservation.
MAX_OUTPUT_TOKENS = 1000
PIN_FIELDS = ("benchmark_commit", "generator_commit", "director_commit", "scorer_commit", "harness_hash")


def _write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(value))


def _read(root, name):
    return json.loads((Path(root) / name).read_bytes())


class _Guard:
    def __init__(self, stack):
        self.stack, self.canary = stack, False

    def __getattr__(self, name):
        return getattr(self.stack, name)

    def respond(self, call):
        self.canary |= CANARY.encode() in canon(call.body)
        if self.canary:
            return Reply(503, "live_stopped", "live", call.model)
        return self.stack.respond(call)


def _isolation(run):
    # Worker sockets use T1's check. Provider rows use A5's live predicate (audit/readback.py) and only
    # that: A5's other failures are scripted-reply checks, which the audit status makes INFRA, as in T1.
    try:
        t0._check_egress([([], run.egress)], t1.T1Refused)
    except t1.T1Refused:
        raise t1.T1Refused("isolation") from None
    for r in run.records:
        live = [u for u in r.get("upstream", ()) if u.get("served_by") == "live"]
        if (r.get("served_by") == "live" or live) and not (
                r.get("role") == "probe_main" and all(u.get("role") == "probe_main" for u in live)):
            raise t1.T1Refused("isolation")


def _secrets(home, login=None):
    raw = (home / "auth.json").read_bytes()
    values = {raw}
    def visit(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("access_token", "refresh_token", "id_token") and isinstance(value, str) and value:
                    values.update((value.encode(), canon(value)[1:-1]))
                visit(value)
    visit(json.loads(raw))
    if login is not None:
        values.update(v.encode() for v in login.needles() if v)
    return values


def _scan(out, needles):
    if any(n in p.read_bytes() for p in out.rglob("*") if p.is_file() for n in needles):
        raise t1.T1Refused("credential_scan")


def _card(ctx, rows, *, identity="unobserved", cached=False, prime=False):
    g2_actions = {i["item_id"] for p in ctx.packs if p.genre == "G2"
                  for items in p.items.values() for i in items if i["stage"] == "act"}
    return build_t2lite_card(system=ctx.entry["name"], pack_hash=ctx.pack_hash,
        seed_hash=ctx.pins["seed_hash"], pins={k: ctx.pins[k] for k in PIN_FIELDS},
        model=MODEL, effort=EFFORT, served_identity=identity, aa_prime=prime, items=rows,
        not_scored_live=sorted({r["item_id"] for r in rows
                               if r["item_id"] in g2_actions and r["failure_class"] is None}),
        # The null-citation escape on an answer; an unknown reply always has a null citation.
        counts=dict(floor_cached=int(cached), null_citation=sum(r["envelope"] is not None and
            r["envelope"]["type"] != "unknown" and r["envelope"]["citation"] is None for r in rows)),
        answer_contract_sha256=answer_contract.contract_hash())


def _unit(ctx, pack, branch, arm, scratch, live, runs, out, floor_stops=None):
    for attempt in range(3):
        try:
            run = run_life(arm=arm, entry=ctx.entry, life_dir=pack.life_dir, branch=branch,
                items=pack.items[branch], records=pack.records_b[branch], keys=pack.keys,
                scratch=scratch / str(attempt), run=ctx.run_id, attempt=attempt, gate=ctx.gate,
                current_lock=ctx.current_lock, voids=Voids(), harness_pin=ctx.harness_pin,
                hermes=ctx.hermes, plugin_source=None if arm == "no_memory" else ctx.plugin_source,
                worker_argv=t1._worker(ctx, pack.life, branch, arm), visible=pack.visible,
                honeypot_token=pack.meta["honeypot_token"], live=live,
                extra_env=resolve_worker_env(ctx.entry["name"], ctx.model_cache) if arm != "no_memory" else None)
        except LiveCredentialStop:
            ledger = scratch / str(attempt) / branch / "run/ledger"
            rows = _rows(ledger)
            runs.append(LifeRun(arm, pack.life, branch, attempt, records=tuple(rows),
                tokens_by_role=_tokens(ledger, rows)))
            raise
        runs.append(run)
        try:
            _isolation(run)
            if live.canary:
                raise t1.T1Refused("canary")
            if live.state().get("spend_stopped"):
                raise t1.T1Refused("spend_stop")
            scores = {}
            probes = _read(run._root, "t2lite_probes.json")
            # T1's relabel (runner/t1.py): a stop the floor shared is the harness's, not the system's.
            floor_stop = (floor_stops or {}).get(pack.life + branch)
            relabel = (arm == "system" and is_plugin(ctx.entry["name"]) and run.stopped
                and run.stopped[1] in t1.RELABEL and floor_stop and list(floor_stop)[1:] == list(run.stopped)[1:])
            for item in pack.items[branch]:
                iid = item["item_id"]
                cls, label = run.classes.get(iid, (None, None))
                if relabel and (cls, label) == ("SYSTEM_FAILURE", run.stopped[1]):
                    cls = "INFRA_FAILURE"
                if run.audit.get("status") != "OK" and cls not in ("SYSTEM_FAILURE", "INFRA_FAILURE"):
                    cls, label = "INFRA_FAILURE", "audit"
                shadow, answer = run.results.get(iid, MISSING), run.envelopes.get(iid, MISSING)
                not_scored_live = (pack.genre == "G2" and item["stage"] == "act"
                                  and cls not in ("SYSTEM_FAILURE", "INFRA_FAILURE"))
                result = shadow
                if isinstance(shadow, ReaderResult):
                    # The answer is the live model's; the selection and competitors are the shadow's. Ring 0
                    # ties the two, which does not hold here, so score the answer as L4's card check reads it.
                    asserted = isinstance(answer, dict) and answer.get("type") != "unknown"
                    result = replace(shadow, selected_option=_LIVE_ANSWER if asserted else None, competing_present=())
                if not_scored_live:
                    scores[iid] = dict(identity0(item), infra_reruns=attempt, base_verdict=None,
                        score_milli=None, worst_case_milli=None, accuracy_correct=None,
                        tuesday_class=None, envelope=None, failure_class=None, benign_extra=False)
                else:
                    scores[iid] = score_item(item, cls=cls, label=label,
                        result=result, envelope=answer,
                        act=run.act.get(iid, MISSING), case=pack.cases[iid], keys=pack.keys[iid],
                        scoring_evidence=pack.scoring["evidence"].get(iid), attempt=attempt,
                        stored_roots=run.stored_roots.get(iid), retained_roots=run.retained_roots.get(iid))
                if isinstance(shadow, ReaderResult) and cls != "SYSTEM_FAILURE" and not isinstance(scores[iid], Infra):
                    scores[iid].update(selected_option=shadow.selected_option,
                                       competing_present=list(shadow.competing_present))
                if cls or isinstance(scores[iid], Infra) or not_scored_live:
                    next(p for p in probes if p["item_id"] == iid)["shadow"]["stage_attribution"] = None
            _write(out, "t2lite_probes.json", probes)
        finally:
            run.cleanup()
        if attempt == 2 or not any(isinstance(s, Infra) for s in scores.values()):
            break
    for iid, scored in scores.items():
        if isinstance(scored, Infra):
            scores[iid] = outcome(identity0(pack.cases[iid].item), None, cause="INFRA_FAILURE", infra_reruns=2)
    # The shadow selection belongs to the shadow, not the live scorer's synthetic option.
    for probe in probes:
        row = scores[probe["item_id"]]
        if row["failure_class"] is None:
            row["selected_option"] = probe["shadow"]["selected_option"]
    return scores, probes


def _joined(pack, branch, scores, probes):
    rows, swap = {}, pack.schedule.scale.swap
    for probe in probes:
        iid = probe["item_id"]
        item = next(i for i in pack.items[branch] if i["item_id"] == iid)
        record = pack.records[iid]
        bundle = next((b for b in pack.pack["bundles"] if iid in b["items"]), None)
        rows[iid] = dict(scores[iid], life=pack.life, branch=branch, probe_point=probe["checkpoint"],
            probe_session=probe["probe_session"], template_ref=f"{record['template_id']}-v{record['template_version']}",
            genre=pack.genre, twin_bundle=None if bundle is None else bundle["bundle_id"], twin_flip=None,
            in_context=probe["shadow"]["in_context"], value_match=probe["envelope"]["value_match"],
            citation_match=probe["envelope"]["citation_match"], crosses_cold_restart=t1._crosses(pack, item),
            swap_position="none" if swap is None else "before" if item["probe_point"] < swap else "after")
    return rows


def _holds(rows):
    waits, held_ms, reasons = 0, 0, set()
    for row in rows:
        for upstream in row.get("upstream", ()):
            if upstream.get("served_by") != "live":
                continue
            holding = False
            for diagnostic in upstream.get("diagnostics", ()):
                if diagnostic.get("kind") == "hold":
                    # One wait emits consecutive reasons, followed by a try (or the reply ends).
                    if not holding:
                        waits += 1
                        held_ms += diagnostic["held_ms"]
                    reasons.add(diagnostic["reason"])
                    holding = True
                else:
                    holding = False
    return dict(waits=waits, held_ms=held_ms, reasons=sorted(reasons))


def _receipt(runs, start, status):
    rows = [r for run in runs for r in run.records]
    tokens, runtime, failed = {}, {}, {}
    for run in runs:
        for name, count in run.egress.get("failed_samples", {}).items():
            failed[name] = failed.get(name, 0) + count
        for role, pair in run.tokens_by_role.items():
            old = tokens.get(role, (0, 0))
            tokens[role] = tuple(a + b for a, b in zip(old, pair, strict=True))
    for row in rows:
        if row.get("type") == "request":
            runtime[row["role"]] = runtime.get(row["role"], 0) + row["t_ms"]
    return build_receipt(run_status=status, wall_start_ms=start, wall_end_ms=int(time.time() * 1000),
        latency_ms=ledger_latencies(rows), load_milli=load_milli(os.getloadavg()),
        busy_marker_readings=[], tokens_by_role=tokens,
        runtime_by_role=runtime, spend_micro_usd=0, store_growth_bytes=sum(r.store_growth_bytes for r in runs),
        process_ids=[p for r in runs for p in r.process_ids], ports=[int(r.run_values["director_port"])
            for r in runs if r.run_values], temporary_paths=[r.run_values["sandbox_root"] for r in runs if r.run_values],
        raw_body_digest=raw_body_digest(rows), egress_failed_samples=failed,
        timings=[dict(arm=r.arm, life=r.life, branch=r.branch,
            attempt=r.attempt, egress_pid_samples=r.egress.get("samples"),
            egress_sample_ms=r.egress.get("sample_ms"), **r.timings) for r in runs if r.timings])


def _select(ctx, only):
    """The units to run, and the item ids a checkpoint rerun keeps. The rerun replays its whole branch: compiling only
    the checkpoint's items changes the script, and the write audit then fails (A4 gaps)."""
    if only is None:
        return [(p, b) for p in ctx.packs for b in ("B0", "B1")], None
    life, branch, checkpoint = only
    for pack in ctx.packs:
        if pack.life == life:
            keep = {i["item_id"] for i in pack.items[branch] if i["probe_point"] == checkpoint}
            if keep:
                return [(pack, branch)], keep
    raise t1.T1Refused("only")


def _tool_failure(out, created):
    if created:
        fixedroot.remove_tree(out)
        out.mkdir()
        _write(out, "refusal.json", dict(code="tool_failure"))
    print("tool_failure", file=sys.stderr)
    traceback.print_exc()
    return 70


def _cached_floor(path, ids, units):
    """An entry is a hit only if it covers every floor item and unit; any other entry is a miss, so the floor runs
    live and the run writes a whole entry again."""
    try:
        floor = _read(path.parent, path.name) if path is not None and path.is_file() else None
    except (OSError, ValueError):
        return None
    if (isinstance(floor, dict) and isinstance(floor.get("outcomes"), dict) and isinstance(floor.get("stops"), dict)
            and set(floor["outcomes"]) == ids and set(floor["stops"]) == units):
        return floor
    return None


ROLES = {"baseline": "baseline", "of": "aa_of", "prime": "aa_prime"}


def _references(prospective, selection, baseline, aa_of, aa_prime):
    """Read and check every earlier run before anything is sent, so a bad one never costs a live run."""
    cards, outcomes = {}, {}
    try:
        for name, path in (("baseline", baseline), ("of", aa_of), ("prime", aa_prime)):
            if path is not None:
                cards[name] = _read(path, "card.json")
                if name != "of":
                    outcomes[name] = _read(path, "outcomes.json")
    except (OSError, ValueError):
        raise t1.T1Refused("baseline_unreadable") from None
    places = {i["item_id"]: (pack.life, branch, i["probe_point"]) for pack, branch in selection for i in pack.items[branch]}
    for name, card in cards.items():
        role = ROLES[name]
        try:
            check_baseline_t2lite(prospective, card)
        except BaselineRefused as error:
            # L5 calls the compared card the baseline; name the earlier run this flag gave.
            reason = error.reason if role == "baseline" else (
                "invalid_card:" + role if error.reason == "invalid_card:baseline" else role + ":" + error.reason)
            raise BaselineRefused(reason) from None
        try:
            # The same items, each in the same place: a rerun command is built from these fields.
            if {i["item_id"] for i in card["items"]} != places.keys() or any(
                    (row["life"], row["branch"], row["probe_point"]) != places.get(iid)
                    for iid, row in outcomes.get(name, {}).items()):
                raise t1.T1Refused(role + "_items")
        except (KeyError, TypeError, AttributeError):
            raise t1.T1Refused("baseline_invalid") from None
    if baseline is not None:
        try:
            # L5's own checks with the baseline on both sides: its outcomes vouch for its card, and A′'s for its own.
            flip_report(cards["baseline"], cards["baseline"], outcomes["baseline"], outcomes["baseline"],
                        aa_prime=outcomes.get("prime"), aa_prime_card=cards.get("prime"))
        except BaselineRefused as error:
            # The baseline stands in both places here, so a refusal of the "current" side is the baseline's.
            raise BaselineRefused(error.reason.replace(":current", ":baseline")) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise t1.T1Refused("baseline_invalid") from None
    return cards, outcomes


def run_t2lite(*, system, packs_dir, pack_hash, out, login_home, max_sends, hermes=None,
               plugin_source=None, model_cache=None, cache=None, sandbox_slot=0,
               baseline=None, aa_of=None, aa_prime=None, only=None, repeat=1, entry=None, worker_argv=None):
    out, home = Path(out), Path(login_home)
    start, runs, created, stack, login, account = int(time.time() * 1000), [], False, None, None, None
    needles, pending_cache, live, custody_rows = set(), None, None, []
    try:
        # Arguments and settings first: these refusals create no output, so the same command can run again.
        if (repeat < 1 or max_sends < 0 or repeat != 1 and only is None
                or only is not None and (baseline or aa_of or aa_prime)
                or aa_prime is not None and baseline is None or aa_of and aa_prime):
            raise t1.T1Refused("rerun_arguments")
        missing = [name for name in LIVE_ENV if not os.environ.get(name)]
        if missing:
            print(" ".join(missing), file=sys.stderr)
            raise t1.T1Refused("live_config")
        if not (home / "auth.json").is_file():
            raise t1.T1Refused("login_home")
        if out.exists() or out.is_symlink():
            raise t1.T1Refused("out_exists")
        if any(p is not None and fixedroot.overlaps(p) for p in (
                out, home, packs_dir, cache, baseline, aa_of, aa_prime, hermes, plugin_source, model_cache)):
            raise t1.T1Refused("sandbox_overlap")
        if any(fixedroot.within(p, out) or fixedroot.within(out, p) for p in (
                home, Path(packs_dir), *([Path(cache)] if cache else []))):
            raise t1.T1Refused("output_overlap")
        out.mkdir(parents=True)
        created = True
        if system == "lcm-x" and (home / ".bicentennial-operator").exists():
            raise t1.T1Refused("operator_identity")
        account = os.open(home / ".t2lite.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(account, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise t1.T1Refused("account_busy") from None
        ctx = t1.prepare(system=system, packs=packs_dir, pack_hash=pack_hash, hermes=hermes,
            plugin_source=plugin_source, model_cache=model_cache, entry=entry, worker_argv=worker_argv)
        ctx = SimpleNamespace(**(vars(ctx) | {"run_id": "t2lite-" + uuid4().hex}))
        selection, keep = _select(ctx, only)
        references, outcomes = _references(_card(ctx, [], prime=aa_of is not None), selection, baseline,
                                           aa_of, aa_prime)
        # The benchmark commit stands for the director, reader and scorer code the floor ran.
        key = sha256_canon([ctx.pack_hash, MODEL, EFFORT, answer_contract.contract_hash(), ctx.pins["harness_hash"],
                            ctx.pins["benchmark_commit"]])
        floor_path = Path(cache) / (key + ".t2lite-floor.json") if cache else None
        floor = _cached_floor(floor_path, {i["item_id"] for p in ctx.packs for b in ("B0", "B1") for i in p.items[b]},
                              {p.life + b for p in ctx.packs for b in ("B0", "B1")})
        cached = floor is not None
        floor_stops = floor["stops"] if cached else {}
        needles = _secrets(home)
        with fixedroot.lease(sandbox_slot, t1.T1Refused) as scratch:
            stack = build_live_stack(out / "spend.json", login_home=home, run=ctx.run_id,
                token_url=os.environ[LIVE_ENV[0]], client_id=os.environ[LIVE_ENV[1]],
                base_url=os.environ[LIVE_ENV[2]],
                max_output_tokens=MAX_OUTPUT_TOKENS, max_sends=max_sends, model=MODEL, effort=EFFORT)
            login = stack.inner.login
            live = _Guard(stack)
            try:
                if not cached:
                    floor = {"outcomes": {}, "stops": floor_stops}
                    for pack in ctx.packs:
                        for branch in ("B0", "B1"):
                            scores, _ = _unit(ctx, pack, branch, "no_memory", scratch / "floor" / pack.life / branch,
                                live, runs, out / "no_memory" / pack.life / branch)
                            floor["outcomes"].update(scores)
                            stopped = runs[-1].stopped
                            floor_stops[pack.life + branch] = list(stopped) if stopped else None
                    if floor_path and not any(r["failure_class"] == "BLOCKED" for r in floor["outcomes"].values()):
                        pending_cache = (floor_path, floor)
                print("floor: reused from the cache" if cached else "floor: ran live", file=sys.stderr)
                repetitions = []
                for rep in range(repeat):
                    scores, joined = {}, {}
                    for pack, branch in selection:
                        values, probes = _unit(ctx, pack, branch, "system", scratch / str(rep) / pack.life / branch,
                            live, runs, out / "repetitions" / str(rep) / pack.life / branch, floor_stops)
                        rows = _joined(pack, branch, values, probes)
                        if keep is not None:
                            values = {i: v for i, v in values.items() if i in keep}
                            rows = {i: v for i, v in rows.items() if i in keep}
                        scores.update(values)
                        joined.update(rows)
                    repetitions.append(joined)
                identities = stack.served_identities()
                card = _card(ctx, list(scores.values()), identity=canon(identities).decode() if identities else "unobserved",
                    cached=cached, prime=aa_of is not None)
            finally:
                try:
                    stack.close()
                    needles.update(_secrets(home, login))
                finally:
                    custody_rows.extend(login.drain())
            _write(out, "outcomes.json", repetitions[-1])
            _write(out, "repetitions.json", repetitions)
            _write(out, "no_memory.json", floor)
            _write(out, "custody.json", custody_rows)
            _write(out, "disclosures.json", {"live": dict(stack.state(),
                holds=_holds(row for run in runs for row in run.records)), **{
                key: sorted({i for r in runs if r.arm == arm for i in r.transforms})
                for key, arm in (("t1.transforms", "system"), ("no_memory.transforms", "no_memory"))}})
            if baseline:
                self_band = aa_of is not None and Path(aa_of).resolve() == Path(baseline).resolve()
                report = flip_report(card, references["baseline"], outcomes["baseline"], repetitions[-1],
                    aa_prime=repetitions[-1] if self_band else outcomes.get("prime"),
                    aa_prime_card=card if self_band else references.get("prime"))
                report["served_identity"] = dict(baseline=references["baseline"]["served_identity"],
                    current=card["served_identity"], changed=references["baseline"]["served_identity"] != card["served_identity"])
                _write(out, "flips.json", report)
            _write(out, ".receipt.json", _receipt(runs, start, "COMPLETE"))
            _write(out, ".card.json", card)
            _scan(out, needles)
            if pending_cache:
                # Written whole, then renamed into place, so no reader sees a partial entry.
                temp = pending_cache[0].with_name(pending_cache[0].name + "." + ctx.run_id)
                _write(temp.parent, temp.name, pending_cache[1])
                temp.replace(pending_cache[0])
            (out / ".receipt.json").replace(out / "receipt.json")
            (out / ".card.json").replace(out / "card.json")
        return 0
    except (LiveCredentialStop, custody.Stop, BaselineRefused, *t1.REFUSALS) as error:
        reasons = getattr(error, "reasons", ())
        code = ("credential_stop" if isinstance(error, (LiveCredentialStop, custody.Stop)) else
            error.reason if isinstance(error, BaselineRefused) else getattr(error, "code", None) or (
                ",".join(sorted(reasons)) if reasons else
                "gate_refused" if isinstance(error, GateRefused) else "pin_mismatch"))
        if code in ("credential_stop", "spend_stop") and live is not None and live.canary:
            code = "canary"  # INVALID outranks a stop: the guard latched a canary body
        try:
            if created:
                try:
                    _scan(out, needles)
                except t1.T1Refused:
                    code = "credential_scan"
                fixedroot.remove_tree(out)
                out.mkdir()
                if code in ("credential_stop", "spend_stop"):
                    # L1's custody rows say why: the drained log, and a Stop's own records.
                    files = {"receipt.json": canon(_receipt(runs, start, "INFRA_FAILURE")),
                             "custody.json": canon(custody_rows + list(getattr(error, "records", ())))}
                    if any(n in data for data in files.values() for n in needles):
                        code = "credential_scan"
                    else:
                        for name, data in files.items():
                            (out / name).write_bytes(data)
                _write(out, "refusal.json", dict(code=code))
        except Exception:
            # A failure while refusing goes the tool_failure way, which removes everything written.
            return _tool_failure(out, created)
        print(code, file=sys.stderr)
        return 3
    except Exception:
        return _tool_failure(out, created)
    finally:
        if account is not None:
            os.close(account)
