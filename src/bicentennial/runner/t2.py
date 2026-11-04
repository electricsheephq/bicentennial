"""Public T2 runs with per-unit floors and retained failed probes."""

import fcntl
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bicentennial.canon import canon, sha256_canon
from bicentennial.director.compiler import answer_contract
from bicentennial.director.responder import Call
from bicentennial.director.upstream import login as custody
from bicentennial.items.protocol import CANARY
from bicentennial.packs.install import verify
from bicentennial.report.t2_card import _row_counts, build_t2_card
from bicentennial.runner import t1
from bicentennial.runner.arm_time import calculate_arm_times
from bicentennial.runner.kept import KeptRefused, keep_failed
from bicentennial.runner.live import build_live_stack
from bicentennial.runner.probe_live import LiveCredentialStop
from bicentennial.runner.t2lite import (
    EFFORT,
    IDENTITY_TEXT,
    LIVE_ENV,
    MAX_OUTPUT_TOKENS,
    MODEL,
    PIN_FIELDS,
    _cached_floor,
    _holds,
    _joined,
    _receipt,
    _scan,
    _secrets,
    _tool_failure,
)
from bicentennial.runner.units import (
    T2_SPEC,
    Arm,
    _check_stop,
    _Guard,
    _read,
    _write,
    make_units,
    refusal_code,
    schedule,
)
from bicentennial.sandbox import fixedroot
from bicentennial.systems.hermes_plugin import cache_digest

CODE_PINS = ("controls_sha256", "reader_sha256", "scoring_sha256", "scorer_sha256")
CARD_PINS = (*PIN_FIELDS, "system_hash", "route_table_hash", "write_turn_package_hash")


def floor_key(ctx, pack, branch, *, probe_mode, turn_wait_s):
    """A floor belongs to a life tree and probe policy, independent of system and slots."""
    return sha256_canon([ctx.index["packs"][pack.rel]["tree_sha256"], branch, MODEL, EFFORT,
        answer_contract.contract_hash(), ctx.pins["harness_hash"], ctx.pins["benchmark_commit"],
        f"probe_mode={probe_mode}", f"turn_wait_s={turn_wait_s}"])


def keep_hook(ctx, roots, needles):
    """Route each system arm's retained probes to its own publication root."""
    def keep(unit, run, scores, excluded):
        actions = {i["item_id"] for items in unit.pack.items.values() for i in items
                   if unit.pack.genre == "G2" and i["stage"] == "act"}
        keep_failed(run, scores, roots[unit.arm.key], pack_hash=ctx.pack_hash,
            pins={k: unit.pack.manifest["pins"][k] for k in CODE_PINS}, canary=CANARY,
            excluded=set(excluded) | actions, credential_needles=needles)
    return keep


def _card(ctx, results, floor, identity, out):
    index = _read(out / "kept", "index.json")
    pointers = {(r["life"], r["branch"], r["item_id"]): r["kept"] for r in index if r["kept"]}
    items, broken = [], set()
    for pack in ctx.packs:
        for row in _read(pack.dir / "sealed", "controls.json")["broken"]:
            broken.add((row["stage"], row["track"]))
        for branch in ("B0", "B1"):
            unit = results[("system", pack.life, branch)]
            for item in pack.items[branch]:
                iid = item["item_id"]
                items.append(dict(unit.scores[iid], life=pack.life, genre=pack.genre, branch=branch,
                    probe_point=item["probe_point"], repro=pointers.get((pack.life, branch, iid))))
    unscored = sorted([r["life"], r["branch"], r["item_id"]] for r in items
                      if r["genre"] == "G2" and r["stage"] == "act")
    counts = _row_counts(dict(items=items, floor=floor, not_scored_live=unscored))
    counts["infra"] = sum(r["failure_class"] == "BLOCKED" for r in items)
    return build_t2_card(system=ctx.entry["name"], pack_hash=ctx.pack_hash, seed_hash=ctx.pins["seed_hash"],
        pins={k: ctx.pins[k] for k in CARD_PINS}, model=MODEL, effort=EFFORT, served_identity=identity,
        aa_prime=False, items=items, counts=counts, answer_contract_sha256=answer_contract.contract_hash(),
        not_scored_live=unscored, seed_source={"kind": "public"},
        groups=[list(g) for g in sorted({(r["cell_id"], r["stage"]) for r in items})], floor=floor,
        controls_broken=[dict(stage=s, track=t) for s, t in sorted(broken)])


def run_t2(*, system, packs_dir, pack_hash, out, login_home, max_sends, hermes=None,
           plugin_source=None, model_cache=None, cache=None, sandbox_slot=0,
           entry=None, worker_argv=None, turn_wait_s=3.0, slots=None):
    if slots is not None and (type(slots) is not int or slots < 1):
        raise ValueError("slots must be a positive integer")
    out, home = Path(out), Path(login_home)
    start, runs, created, stack, login, account = int(time.time() * 1000), [], False, None, None, None
    units = []
    needles, pending_cache, live, custody_rows = set(), [], None, []
    try:
        turn_wait_s = t1.validate_turn_wait(turn_wait_s)
        # Arguments and settings first: these refusals create no output, so the same command can run again.
        if max_sends < 0:
            raise ValueError("max_sends must be non-negative")
        missing = [name for name in LIVE_ENV if not os.environ.get(name)]
        if missing:
            print(" ".join(missing), file=sys.stderr)
            raise t1.T1Refused("live_config")
        if not (home / "auth.json").is_file():
            raise t1.T1Refused("login_home")
        if out.exists() or out.is_symlink():
            raise t1.T1Refused("out_exists")
        if any(p is not None and fixedroot.overlaps(p) for p in (
                out, home, packs_dir, cache, hermes, plugin_source, model_cache)):
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
            turn_wait_s=turn_wait_s, spec=T2_SPEC)
        effective = ctx.roots if slots is None else slots
        if effective > ctx.roots:
            raise ValueError("slots exceed admission")
        ctx = SimpleNamespace(**(vars(ctx) | {"run_id": "t2-" + uuid4().hex, "turn_wait_s": turn_wait_s}))
        with fixedroot.lease(sandbox_slot, t1.T1Refused) as scratch:
            t1.check_install(ctx, scratch)
            queued = make_units(ctx, [Arm.from_context(ctx, "system")], scratch, out)
            floors = [u for u in queued if u.arm.role == "no_memory"]
            paths, keys, floor, provenance = {}, {}, {}, {}
            for unit in floors:
                name = f"{unit.pack.life}/{unit.branch}"
                key = floor_key(ctx, unit.pack, unit.branch, probe_mode=T2_SPEC.probe_mode,
                                turn_wait_s=turn_wait_s)
                keys[name] = key
                paths[name] = Path(cache) / (key + ".t2-floor.json") if cache else None
                entry0 = _cached_floor(paths[name], {i["item_id"] for i in unit.pack.items[unit.branch]},
                                       {unit.pack.life + unit.branch})
                if entry0 is not None:
                    floor[name] = entry0
                provenance[name] = dict(cached=False, reason="cache miss")
            needles = _secrets(home)
            stack = build_live_stack(out / "spend.json", login_home=home, run=ctx.run_id,
                token_url=os.environ[LIVE_ENV[0]], client_id=os.environ[LIVE_ENV[1]],
                base_url=os.environ[LIVE_ENV[2]], max_output_tokens=MAX_OUTPUT_TOKENS,
                max_sends=max_sends, model=MODEL, effort=EFFORT)
            login, live = stack.inner.login, _Guard(stack)
            identity_check = None
            try:
                if floor:
                    reply = live.respond(Call(role="identity_check", subrole="", wire="chat",
                        body={"messages": [{"role": "user", "content": IDENTITY_TEXT}]},
                        model=MODEL, cursor=None, run_key=ctx.run_id + ":identity"))
                    _check_stop(live)
                    ids = stack.served_identities()
                    observed = canon(ids).decode() if ids else "unobserved"
                    identity_check = dict(served=reply.served, observed=observed,
                        tries=sum(d.get("kind") == "try" for d in reply.upstream),
                        held_ms=sum(d["held_ms"] for d in reply.upstream if d.get("kind") == "hold"))
                    for name in list(floor):
                        matched = reply.served == "live" and observed == floor[name]["served_identity"]
                        provenance[name] = dict(cached=matched, reason="served identity matched" if matched else
                            "served identity differs" if reply.served == "live" else "served identity not confirmed")
                        if not matched:
                            del floor[name]
                floor_stops = {k: stop for entry0 in floor.values() for k, stop in entry0["stops"].items()}
                todo = [u for u in queued if u.arm.role != "no_memory" or f"{u.pack.life}/{u.branch}" not in floor]
                collected = schedule(ctx, todo, live, spec=T2_SPEC, roots=effective, floor_stops=floor_stops,
                                     keep=keep_hook(ctx, {"system": out}, needles))
                results = collected.merge(runs, units)
                ids = stack.served_identities()
                identity = canon(ids).decode() if ids else "unobserved"
                for unit in floors:
                    name = f"{unit.pack.life}/{unit.branch}"
                    if name in floor:
                        continue
                    result = results[unit.identity]
                    entry0 = dict(outcomes=result.scores,
                        stops={unit.pack.life + unit.branch: list(result.stop) if result.stop else None},
                        served_identity=identity)
                    floor[name] = entry0
                    if (paths[name] and result.measured and ids and "unidentified" not in ids.values()
                            and stack.state().get("identity_drift") is None
                            and not any(r["failure_class"] == "BLOCKED" for r in result.scores.values())):
                        pending_cache.append((paths[name], entry0))
                floor_block = dict(served_identity=identity, units={name: dict(cache_key=keys[name],
                    cached=provenance[name]["cached"]) for name in keys})
                card = _card(ctx, results, floor_block, identity, out)
                outcomes = {}
                for unit in queued:
                    if unit.arm.role == "system":
                        result = results[unit.identity]
                        for iid, row in _joined(unit.pack, unit.branch, result.scores, result.probes).items():
                            outcomes[f"{unit.pack.life}/{unit.branch}/{iid}"] = row
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
            _write(out, "outcomes.json", outcomes)
            _write(out, "no_memory.json", floor)
            _write(out, "custody.json", custody_rows)
            _write(out, "disclosures.json", dict(honeypot_hits=honeypot_hits, turn_wait_s=str(turn_wait_s),
                identity_check=identity_check, floor=provenance,
                live=dict(stack.state(), holds=_holds(row for run in runs for row in run.records)), **{
                    key: sorted({i for r in runs if r.arm == arm for i in r.transforms})
                    for key, arm in (("t2.transforms", "system"), ("no_memory.transforms", "no_memory"))}))
            receipt = _receipt(runs, start, "COMPLETE", turn_wait_s, units)
            end = receipt["wall_end_ms"]
            _write(out, "units.json", dict(slots=effective, admitted_slots=ctx.roots,
                start_ms=receipt["wall_start_ms"], end_ms=end,
                units=[dict(row, slots=effective) for row in units],
                arm_time=calculate_arm_times(effective, units, receipt["wall_start_ms"], end)))
            for arm in ("system", "no_memory"):
                _write(out / "receipts", arm + ".json", _receipt([r for r in runs if r.arm == arm],
                    start, "COMPLETE", turn_wait_s, [r for r in units if r["arm"] == arm]))
            _write(out, ".receipt.json", receipt)
            _write(out, ".card.json", card)
            _scan(out, needles)
            for path, entry0 in pending_cache:
                temp = path.with_name(path.name + "." + ctx.run_id)
                _write(temp.parent, temp.name, entry0)
                temp.replace(path)
            (out / ".receipt.json").replace(out / "receipt.json")
            (out / ".card.json").replace(out / "card.json")
        return 0
    except (LiveCredentialStop, custody.Stop, KeptRefused, *t1.REFUSALS) as error:
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
