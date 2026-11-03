"""Probe-live developer runs over T1 lives, with all-or-refusal publication."""

import fcntl
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bicentennial.canon import canon, sha256_canon
from bicentennial.director.compiler import answer_contract
from bicentennial.director.responder import Call
from bicentennial.director.roles import MAIN_ROLES
from bicentennial.director.upstream import login as custody
from bicentennial.packs.install import verify
from bicentennial.report.receipt import (
    background_summary,
    build_receipt,
    ledger_latencies,
    load_milli,
    raw_body_digest,
)
from bicentennial.report.t2lite_card import build_t2lite_card
from bicentennial.report.t2lite_flips import (
    BaselineRefused,
    check_baseline_t2lite,
    flip_report,
)
from bicentennial.runner import t1
from bicentennial.runner.hermes_score import identity0 as identity0
from bicentennial.runner.live import build_live_stack
from bicentennial.runner.probe_live import LiveCredentialStop
from bicentennial.runner.units import (
    UnitRefusal,
    _check_stop,
    _read,
    _write,
    reduce_refusals,
    refusal_code,
)
from bicentennial.runner.units import _Guard as _Guard
from bicentennial.runner.units import _unit as _unit
from bicentennial.sandbox import fixedroot
from bicentennial.score.classes import outcome as outcome
from bicentennial.systems.hermes_plugin import cache_digest

MODEL, EFFORT = "gpt-6.1-sol", "medium"
IDENTITY_TEXT = "Reply with the single word: ok."
# The live lane's settings, required as in the spikes; nothing defaults to a fake address.
LIVE_ENV = ("BICENTENNIAL_SOL_TOKEN_URL", "BICENTENNIAL_SOL_CLIENT_ID", "BICENTENNIAL_SOL_BASE_URL")
# Never sent upstream (build_live_stack sets send_cap=False); it only bounds the zero-price reservation.
MAX_OUTPUT_TOKENS = 1000
PIN_FIELDS = ("benchmark_commit", "generator_commit", "director_commit", "scorer_commit", "harness_hash")


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


def _joined(pack, branch, scores, probes):
    rows, swap = {}, pack.schedule.scale.swap
    for probe in probes:
        iid = probe["item_id"]
        item = next(i for i in pack.items[branch] if i["item_id"] == iid)
        record = pack.records[iid]
        bundle = next((b for b in pack.pack["bundles"] if iid in b["items"]), None)
        # The match fields describe the scored envelope; the live answer's own parse and matches stay in t2lite_probes.json.
        scored = scores[iid]["envelope"] is not None
        rows[iid] = dict(scores[iid], life=pack.life, branch=branch, probe_point=probe["checkpoint"],
            probe_session=probe["probe_session"], template_ref=f"{record['template_id']}-v{record['template_version']}",
            genre=pack.genre, twin_bundle=None if bundle is None else bundle["bundle_id"],
            in_context=probe["shadow"]["in_context"], value_match=probe["envelope"]["value_match"] if scored else None,
            citation_match=probe["envelope"]["citation_match"] if scored else None,
            crosses_cold_restart=t1._crosses(pack, item),
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


def _receipt(runs, start, status, turn_wait_s=3.0, units=()):
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
        turn_wait_s=turn_wait_s, units=units,
        background=[background_summary(arm,
            [r.background_records or r.records for r in runs if r.arm == arm],
            [n for r in runs if r.arm == arm for n in r.background_threads], main_roles=MAIN_ROLES)
            for arm in sorted({r.arm for r in runs} | {"system"})],
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
            and isinstance(floor.get("served_identity"), str) and floor["served_identity"]
            and floor["served_identity"] != "unobserved" and "unidentified" not in floor["served_identity"]
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


def _collect_unit(runs, units, *args, **kwargs):
    """Merge one unit's attempts in serial order, including a refusing attempt."""
    try:
        result = _unit(*args, **kwargs)
    except UnitRefusal as failure:
        runs.extend(failure.runs)
        units.append(failure.timing)
        raise reduce_refusals([failure.error]) from None
    runs.extend(result.runs)
    units.append(result.timing)
    return result


def run_t2lite(*, system, packs_dir, pack_hash, out, login_home, max_sends, hermes=None,
               plugin_source=None, model_cache=None, cache=None, sandbox_slot=0,
               baseline=None, aa_of=None, aa_prime=None, only=None, repeat=1, entry=None, worker_argv=None, turn_wait_s=3.0):
    out, home = Path(out), Path(login_home)
    start, runs, created, stack, login, account = int(time.time() * 1000), [], False, None, None, None
    units = []
    needles, pending_cache, live, custody_rows = set(), None, None, []
    try:
        turn_wait_s = t1.validate_turn_wait(turn_wait_s)
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
            plugin_source=plugin_source, model_cache=model_cache, entry=entry, worker_argv=worker_argv,
            turn_wait_s=turn_wait_s)
        ctx = SimpleNamespace(**(vars(ctx) | {"run_id": "t2lite-" + uuid4().hex, "turn_wait_s": turn_wait_s}))
        with fixedroot.lease(sandbox_slot, t1.T1Refused) as scratch:
            t1.check_install(ctx, scratch)
            selection, keep = _select(ctx, only)
            references, outcomes = _references(_card(ctx, [], prime=aa_of is not None), selection, baseline,
                                               aa_of, aa_prime)
            # A run whose --aa-of and --baseline name one directory is that run's A′, and its own outcomes are the band.
            # Decided before any send, by file identity: a symlink or another spelling on a case-insensitive disk is the
            # same directory, a copy at another path is not.
            self_band = aa_of is not None and baseline is not None and os.path.samefile(aa_of, baseline)
            # The benchmark commit stands for the director, reader and scorer code the floor ran.
            key_parts = [ctx.pack_hash, MODEL, EFFORT, answer_contract.contract_hash(), ctx.pins["harness_hash"],
                         ctx.pins["benchmark_commit"]]
            if turn_wait_s != 3.0:
                key_parts.append(f"turn_wait_s={turn_wait_s}")
            key = sha256_canon(key_parts)
            floor_path = Path(cache) / (key + ".t2lite-floor.json") if cache else None
            floor = _cached_floor(floor_path, {i["item_id"] for p in ctx.packs for b in ("B0", "B1") for i in p.items[b]},
                                  {p.life + b for p in ctx.packs for b in ("B0", "B1")})
            cached = floor is not None
            identity_check = None
            floor_message = "floor: ran live"
            needles = _secrets(home)
            stack = build_live_stack(out / "spend.json", login_home=home, run=ctx.run_id,
                token_url=os.environ[LIVE_ENV[0]], client_id=os.environ[LIVE_ENV[1]],
                base_url=os.environ[LIVE_ENV[2]],
                max_output_tokens=MAX_OUTPUT_TOKENS, max_sends=max_sends, model=MODEL, effort=EFFORT)
            login = stack.inner.login
            live = _Guard(stack)
            try:
                if cached:
                    reply = live.respond(Call(role="identity_check", subrole="", wire="chat",
                        body={"messages": [{"role": "user", "content": IDENTITY_TEXT}]},
                        model=MODEL, cursor=None, run_key=ctx.run_id + ":identity"))
                    _check_stop(live)
                    ids = stack.served_identities()
                    observed = canon(ids).decode() if ids else "unobserved"
                    cached = reply.served == "live" and observed == floor["served_identity"]
                    identity_check = dict(served=reply.served, observed=observed, matched=cached,
                        tries=sum(d.get("kind") == "try" for d in reply.upstream),
                        held_ms=sum(d["held_ms"] for d in reply.upstream if d.get("kind") == "hold"))
                    floor_message = ("floor: reused from the cache (served identity matched)" if cached else
                        "floor: ran live (served identity differs from the cache entry)"
                        if reply.served == "live" and ids and "unidentified" not in ids.values() else
                        "floor: ran live (served identity not confirmed)")
                floor_stops = floor["stops"] if cached else {}
                if not cached:
                    floor = {"outcomes": {}, "stops": floor_stops}
                    measured = True
                    for pack in ctx.packs:
                        for branch in ("B0", "B1"):
                            _check_stop(live)
                            unit = _collect_unit(runs, units, ctx, pack, branch, "no_memory", scratch / "floor" / pack.life / branch,
                                live, out / "no_memory" / pack.life / branch)
                            measured &= unit.measured
                            floor["outcomes"].update(unit.scores)
                            stopped = unit.stop
                            floor_stops[pack.life + branch] = list(stopped) if stopped else None
                    ids = stack.served_identities()
                    floor["served_identity"] = canon(ids).decode() if ids else "unobserved"
                    if (floor_path and measured and ids and "unidentified" not in ids.values()
                            and stack.state().get("identity_drift") is None
                            and not any(r["failure_class"] == "BLOCKED" for r in floor["outcomes"].values())):
                        pending_cache = (floor_path, floor)
                    elif floor_path and not measured:
                        print("floor: not cached (an item was not measured from a live answer)", file=sys.stderr)
                print(floor_message, file=sys.stderr)
                repetitions = []
                for rep in range(repeat):
                    scores, joined = {}, {}
                    for pack, branch in selection:
                        _check_stop(live)
                        unit = _collect_unit(runs, units, ctx, pack, branch, "system", scratch / str(rep) / pack.life / branch,
                            live, out / "repetitions" / str(rep) / pack.life / branch, floor_stops)
                        values, probes = unit.scores, unit.probes
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
            verify(packs_dir, pack_hash=pack_hash, lock=ctx.current_lock(), expected_lock=ctx.lock)
            if ctx.model_cache is not None and cache_digest(ctx.model_cache, t1.T1Refused) != ctx.model_cache_sha256:
                raise t1.T1Refused("model_cache_changed")
            honeypot_hits = sum(run.honeypot_hits for run in runs)
            if honeypot_hits:
                raise t1.T1Refused("honeypot")
            _write(out, "outcomes.json", repetitions[-1])
            _write(out, "repetitions.json", repetitions)
            _write(out, "no_memory.json", floor)
            _write(out, "custody.json", custody_rows)
            _write(out, "disclosures.json", {"honeypot_hits": honeypot_hits, "turn_wait_s": str(turn_wait_s),
                "identity_check": identity_check, "live": dict(stack.state(),
                holds=_holds(row for run in runs for row in run.records)), **{
                key: sorted({i for r in runs if r.arm == arm for i in r.transforms})
                for key, arm in (("t1.transforms", "system"), ("no_memory.transforms", "no_memory"))}})
            if baseline:
                report = flip_report(card, references["baseline"], outcomes["baseline"], repetitions[-1],
                    aa_prime=repetitions[-1] if self_band else outcomes.get("prime"),
                    aa_prime_card=card if self_band else references.get("prime"), turn_wait_s=turn_wait_s)
                report["served_identity"] = dict(baseline=references["baseline"]["served_identity"],
                    current=card["served_identity"], changed=references["baseline"]["served_identity"] != card["served_identity"])
                _write(out, "flips.json", report)
            _write(out, ".receipt.json", _receipt(runs, start, "COMPLETE", ctx.turn_wait_s, units))
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
        code = refusal_code(error, live=live, runs=runs, needles=needles)
        try:
            if created:
                try:
                    _scan(out, needles)
                except t1.T1Refused:
                    code = "credential_scan"
                fixedroot.remove_tree(out)
                out.mkdir()
                if code in ("credential_stop", "spend_stop", "live_stop"):
                    # L1's custody rows say why: the drained log, and a Stop's own records.
                    files = {"receipt.json": canon(_receipt(runs, start, "INFRA_FAILURE", turn_wait_s, units)),
                             "custody.json": canon(custody_rows + list(getattr(error, "records", ())))}
                    if any(n in data for data in files.values() for n in needles):
                        code = "credential_scan"
                    else:
                        for name, data in files.items():
                            (out / name).write_bytes(data)
                detail = [error.reason] if code == "live_stop" else list(getattr(error, "detail", ()))
                _write(out, "refusal.json", dict(code=code, **({"detail": detail} if detail else {})))
        except Exception:
            # A failure while refusing goes the tool_failure way, which removes everything written.
            return _tool_failure(out, created)
        if code == "live_stop":
            print(code + " " + error.reason, file=sys.stderr)
        else:
            print(code, *(getattr(error, "detail", ()) if code == "pin_mismatch" else ()), file=sys.stderr)
        return 3
    except Exception:
        return _tool_failure(out, created)
    finally:
        if account is not None:
            os.close(account)
