"""S8's keyed world records and offline evidence helpers.

The spike is advisory. No value here is a memory-system score or a freeze.
"""

import argparse
import base64
import csv
import json
import os
import re
import runpy
import subprocess
import sys
import threading
import time
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import render

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.director.core import Director
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream import Holds, LiveResponder, Pacer, Upstream
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
    verify_pin,
)
from bicentennial.keyed import choice, shuffle, uniform_int
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner.guard import read_marker, reexec_niced
from bicentennial.runner.lock import attempt_id
from bicentennial.runner.spend import Price, Spend
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.systems.registry import load

SEED = "p08"
VISION_CAP = 10_000_000
BASE, DAY, STEP = 1_600_000_000, 86400, 60
KINDS = ("settings", "receipt", "desk")
SERVICES = ("ASTER", "BRIX", "COVEN", "DORIN", "ELVEX", "FENRO", "GAVIK", "HUSPA")
STORES = ("ALTO", "BERYL", "CIRRO", "DELVA", "EMBER", "FOLIO", "GROVE", "HAVEN")
ITEMS = ("WAFER", "BREAD", "COCOA", "DATES", "RICE", "TEA", "PEAR", "OATS")
OBJECTS = ("MUG", "LAMP", "BOOK", "PLANT", "PHONE", "CLOCK")
REGISTRY = Path(__file__).resolve().parents[2] / "systems" / "registry"


def load_entry(name="hermes-native"):
    if name != "hermes-native":
        raise ValueError("S8 permits only hermes-native")
    return load(REGISTRY / f"{name}.toml")


def _integer(life, image_id, field, attempt, lo, hi):
    return uniform_int(SEED, ("p08", life, image_id, "value", field), attempt, "draw", lo, hi)


def _choice(life, image_id, field, attempt, choices):
    return choice(SEED, ("p08", life, image_id, "value", field), attempt, "draw", choices)


def _different(draw, original):
    attempt = 1
    while True:
        value = draw(attempt)
        if value != original:
            return value
        attempt += 1


def _money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def _code(life, image_id, field, attempt):
    letter = _choice(life, image_id, field + "-letter", attempt, tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    digits = _integer(life, image_id, field + "-digits", attempt, 0, 999)
    return f"{letter}{digits:03d}"


def _receipt(life, image_id, twin):
    values = {"STORE": _choice(life, image_id, "STORE", 0, STORES)}
    original_items = shuffle(SEED, ("p08", life, image_id, "value", "ITEMS"), 0, "draw", ITEMS)[:3]
    selected = original_items
    if twin:
        def items_at(attempt):
            return shuffle(SEED, ("p08", life, image_id, "value", "ITEMS"), attempt, "draw", ITEMS)[:3]
        selected = _different(lambda a: sorted(items_at(a)), sorted(original_items))
    prices = [_integer(life, image_id, f"PRICE{i}", 0, 100, 9999) for i in range(1, 4)]
    if twin:
        original_total, attempt = sum(prices), 1
        while True:
            prices = [_integer(life, image_id, f"PRICE{i}", attempt, 100, 9999) for i in range(1, 4)]
            if sum(prices) != original_total:
                break
            attempt += 1
    for i, (item, price) in enumerate(zip(selected, prices, strict=True), 1):
        values[f"ITEM{i}"], values[f"PRICE{i}"] = item, _money(price)
    values["TOTAL"] = _money(sum(prices))
    return values


def _desk(life, image_id, twin):
    unit = ("p08", life, image_id, "value", "OBJECTS")
    original = shuffle(SEED, unit, 0, "draw", OBJECTS)[:5]
    selected = original
    if twin:
        # Keep the named query target and the hidden object stable. The visible
        # set changes, while codes unrelated to the code question remain B0's.
        available = [obj for obj in OBJECTS if obj not in (original[0], original[4])]
        attempt = 1
        while True:
            middle = shuffle(SEED, unit, attempt, "draw", available)[:3]
            selected = [original[0], *middle, original[4]]
            if set(selected[:4]) != set(original[:4]):
                break
            attempt += 1
    values = {}
    for i, obj in enumerate(selected, 1):
        field = f"CODE{i}"
        code = _code(life, image_id, field, 0)
        if twin and i == 1:
            code = _different(lambda a, field=field: _code(life, image_id, field, a), code)
        values[f"OBJECT{i}"], values[field] = obj, code
    return values


def world(life, branch="B0"):
    if branch not in ("B0", "B1"):
        raise ValueError("branch must be B0 or B1")
    records = []
    for kind in KINDS:
        image_id = f"{life}-{kind}"
        twin = branch == "B1"
        if kind == "settings":
            values = {"SERVICE": _choice(life, image_id, "SERVICE", 0, SERVICES)}
            def port(a, image_id=image_id):
                return str(_integer(life, image_id, "PORT", a, 1024, 65535))

            def mode(a, image_id=image_id):
                return _choice(life, image_id, "MODE", a, ("ACTIVE", "STANDBY", "DRAIN", "PAUSED"))
            values["PORT"] = _different(port, port(0)) if twin else port(0)
            values["MODE"] = _different(mode, mode(0)) if twin else mode(0)
        elif kind == "receipt":
            values = _receipt(life, image_id, twin)
        else:
            values = _desk(life, image_id, twin)
        records.append({"life": life, "image_id": image_id, "kind": kind, "values": values})
    return records


def images():
    """Yield the life images and question-only F4 controls in stable order."""
    for index in range(10):
        life = f"s8-life-{index:02d}"
        for branch in ("B0", "B1"):
            for record in world(life, branch):
                style = render.presentation(record, SEED)
                for view, family in (("life", f"F{style['family']}"), ("held-out", "F4")):
                    png, manifest = render.render(record, family, SEED)
                    yield {"id": f"{record['image_id']}-{branch}-{view}", "record": record,
                           "branch": branch, "view": view, "family": family, "png": png, "manifest": manifest}


def render_all(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for image in images():
        png, manifest = image["png"], canon(image["manifest"])
        stem = out / image["id"]
        stem.with_suffix(".png").write_bytes(png)
        stem.with_suffix(".json").write_bytes(manifest)
        index.append({"id": image["id"], "view": image["view"], "family": image["family"],
                      "sha256": sha256(png).hexdigest(), "manifest_sha256": sha256(manifest).hexdigest()})
    (out / "index.json").write_bytes(canon(index))
    return sha256(canon(index)).hexdigest()


class Routed:
    """Keep background writes and perception live, with other auxiliaries scripted."""

    def __init__(self, live, scripted):
        self.live, self.scripted = live, scripted

    def respond(self, call):
        live_role = call.role in ("write_turn", "probe_main", "memory_write", "summariser")
        live_aux = (call.role, call.subrole) in (("aux", "summariser"), ("aux", "vision"))
        responder = self.live if live_role or live_aux else self.scripted
        return responder.respond(call)


class ByModel:
    """Dispatch only to explicitly provisioned models; an absent model fails closed."""

    def __init__(self, models):
        self.models = dict(models)

    def respond(self, call):
        return self.models[call.model].respond(call)


class CaptionCache:
    """Cache successful identical vision calls; the runner sets arm before use."""

    def __init__(self, inner):
        self.inner = inner
        self.cache = {}
        self.hits = Counter()
        self.arm = None
        self.events = []

    def respond(self, call):
        if (call.role, call.subrole) != ("aux", "vision"):
            return self.inner.respond(call)
        if self.arm is None:
            raise ValueError("vision cache requires the calling arm")
        key = sha256(canon({"model": call.model, "body": call.body})).hexdigest()
        self.events.append({"arm": self.arm, "hit": key in self.cache, "run_key": call.run_key})
        if key in self.cache:
            self.hits[self.arm] += 1
            return self.cache[key]
        reply = self.inner.respond(call)
        if reply.status == 200:
            self.cache[key] = reply
        return reply


def _has_image(value):
    if isinstance(value, dict):
        return value.get("type") == "image_url" or any(_has_image(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_image(child) for child in value)
    return False


def image_requests(records, blobs):
    return [record for record in records if record.get("type", "request") == "request" and (
        (record.get("role"), record.get("subrole")) == ("aux", "vision") or _has_image(blobs[record["req"]]))]


def _normalise(value):
    value = str(value).strip().upper()
    return value[:-1] if value.endswith(".") else value


def score(kind, gold, final):
    answer = _normalise(final)
    if kind == "number":
        return answer.replace("$", "").replace(",", "") == _normalise(gold).replace("$", "").replace(",", "")
    if kind == "list":
        expected = gold if isinstance(gold, list) else str(gold).split(",")
        return {item.strip().upper() for item in answer.split(",")} == {str(item).strip().upper() for item in expected}
    if kind in ("string", "code"):
        return answer == _normalise(gold)
    raise ValueError("unknown answer type")


CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
MODE_WALL_S = 21600
REPO = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).resolve().with_name("worker.py")
ANALYSIS_PROMPT = "What does this image show?"


def channels(life):
    offset = int(life.rsplit("-", 1)[1]) % 3
    return dict(zip(("attachment", "workspace", "screen"), KINDS[offset:] + KINDS[:offset], strict=True))


def questions(life, branch="B0"):
    result = []
    for channel, kind in channels(life).items():
        if channel == "screen":
            continue
        record = next(r for r in world(life, branch) if r["kind"] == kind)
        v = record["values"]
        if kind == "settings":
            pairs = [("number", "PORT", "port", v["PORT"]), ("string", "MODE", "mode", v["MODE"])]
        elif kind == "receipt":
            pairs = [("number", "TOTAL", "total", v["TOTAL"]),
                     ("list", "ITEMS", "items", [v[f"ITEM{i}"] for i in range(1, 4)])]
        else:
            pairs = [("code", "CODE1", f"code on the {v['OBJECT1'].lower()}", v["CODE1"]),
                     ("list", "OBJECTS", "other objects with legible tags", [v[f"OBJECT{i}"] for i in range(2, 5)])]
        for type_, field, label, gold in pairs:
            suffix = {"number": "number", "code": "code", "string": "string", "list": "comma-separated list"}[type_]
            result.append({"id": f"{kind}:{field}", "image_id": record["image_id"], "channel": channel,
                           "kind": type_, "gold": gold,
                           "user": f"In the {kind} image, what is the {label}? Answer with only the {suffix}."})
    return result


def turn(text, n, kind="probe", calls=()):
    return {"n": n, "kind": kind, "user": text, "assistant": "Noted." if kind == "replay" else None,
            "tool_calls": list(calls)}


def script_of(life, sessions):
    obj = {"canary": CANARY, "life_id": life, "genre": "G1", "harness": "hermes", "sessions": sessions}
    validate("script", obj)
    return obj


def attach(text, path, mode, paths):
    user = paths["native_text"](text, str(path)) if mode == "native" else text
    paths["attachments"][user] = {"text": text, "paths": [str(path)]}
    return user


def build_script(life, mode, *, branch, paths):
    mapping, sessions = channels(life), []
    for index in range(1, 7):
        kind = "probe" if index == 6 else "replay"
        if index == 2:
            inbox = Path(paths["home"]) / ".s8-inbox" / f"{life}-{mapping['attachment']}.png"
            workspace = Path(paths["workspace"]) / f"{life}-{mapping['workspace']}.png"
            users = [attach("Please keep this image for later.", inbox, mode, paths),
                     f"The image file is in the workspace at {workspace}. Please inspect it."]
            turns = [turn(users[0], 1, kind), turn(users[1], 2, kind, [
                {"name": "vision_analyze", "args": {"image_url": str(workspace), "question": ANALYSIS_PROMPT}}])]
        else:
            users = [q["user"] for q in questions(life, branch)] if index == 6 else [
                f"Day {index}: let us review the garden schedule.", f"Day {index}: the next task is organising the shelf."]
            turns = [turn(user, n, kind) for n, user in enumerate(users, 1)]
        sessions.append({"index": index, "kind": kind, "turns": turns})
    obj = script_of(life, sessions)
    disclosed = {("desk", "OBJECT1")}  # Named by the code question; never gold.
    values = [v.casefold() for b in ("B0", "B1") for r in world(life, b) for f, v in r["values"].items()
              if (r["kind"], f) not in disclosed]
    if scan_script(json.loads(canon(obj).decode().casefold()), [], values):
        raise ValueError("script_value_leak")
    return obj


def routes(mode, glm, vision):
    model = glm if mode == "text" else vision
    return RouteTable.load({"routes": [{"system": "hermes-native", "segment": "seg0", "alias": "bicentennial-main",
                                       "probe_model": model, "summariser": model, "vision": vision, "served_by": "live"}]})


def bootstrap(mode, stat, lives):
    """Each life holds paired integer outcomes; pool items after cluster resampling."""
    if not lives or not any(lives):
        return {"n_draws": 10000, "lb": None, "ub": None}
    totals = [(sum(a - b for a, b in life), len(life)) for life in lives]
    sampled = []
    for b in range(10000):
        rows = [totals[uniform_int("p08-bootstrap", (mode, stat), b, f"life#{j}", 0, len(lives) - 1)]
                for j in range(len(lives))]
        n = sum(row[1] for row in rows)
        sampled.append(1000 * sum(row[0] for row in rows) // n if n else 0)
    sampled.sort()
    return {"n_draws": 10000, "lb": sampled[500], "ub": sampled[9499]}


def admission(fidelity, n, lives, na_reader, bounds):
    pending = fidelity.get("state") == "pending_human_key"
    rules = {"fidelity": not pending and fidelity.get("n") == 200 and fidelity.get("legible_milli", 0) >= 950
             and fidelity.get("verifier_recall_milli", 0) >= 990,
             "sample": n >= 30 and lives >= 10, "reader": n > 0 and 1000 * na_reader <= 200 * n,
             "direct": bounds["D-F"]["lb"] is not None and bounds["D-F"]["lb"] >= 300,
             "shuffle": bounds["S-F"]["ub"] is not None and bounds["S-F"]["ub"] <= 100}
    return {"rules": rules, "admitted": all(rules.values()), "state": "pending_human_key" if pending else "evaluated"}


def profile(modes):
    return "admitted" if set(modes) == {"text", "native"} and all(
        mode["admission"]["admitted"] and all(pair.get("routed") is True for pair in mode["channels"].values())
        for mode in modes.values()) else "pending"


def rag(question, descriptions):
    def tokens(text):
        return set(re.findall(r"[a-z0-9]+", text.lower()))
    q = tokens(question)
    ranked = [(Fraction(len(q & tokens(text)), len(q | tokens(text)) or 1), -i, text)
              for i, text in enumerate(descriptions)]
    return max(ranked)[2] if ranked else ""


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write(path, obj, *, exclusive=False):
    with Path(path).open("xb" if exclusive else "wb") as stream:
        stream.write(canon(obj) + b"\n")


def gate():
    readings = []
    for attempt in range(121):
        marker = read_marker()
        readings.append({"exit": marker.exit, "state": marker.state})
        if marker.exit == 0 and marker.state not in (None, "unset"):
            return readings
        if attempt < 120:
            time.sleep(60)
    raise Stopped("marker_refused", 3)


class Stopped(RuntimeError):
    def __init__(self, code, exit_code=4):
        super().__init__(code)
        self.code, self.exit_code = code, exit_code


def auth(vision=False):
    key = os.environ["BICENTENNIAL_VISION_KEY" if vision else "BICENTENNIAL_UPSTREAM_KEY"]
    return {"Authorization": f"Bearer {key}"}


def provision(scratch, glm, vision, maximum, paid=False, cap=VISION_CAP, price=None):
    if not 0 <= cap <= VISION_CAP:
        raise ValueError("vision_cap_exceeded")
    plan = Spend(scratch / "plan-spend.json", 0, Price(0, 0))
    lanes = [("glm-0", list(dict.fromkeys([glm] + ([] if paid else [vision]))), plan, False)]
    if paid:
        lanes.append(("vision-0", [vision], Spend(scratch / "vision-spend.json", cap, price), True))
    responders, models = [], {}
    for account, names, spend, is_vision in lanes:
        upstreams = [Upstream("vision" if is_vision else "glm", name,
                              os.environ["BICENTENNIAL_VISION_URL" if is_vision else "BICENTENNIAL_UPSTREAM_OPENAI_URL"],
                              "chat", spend, Price(**spend.policy["price"]), maximum,
                              glm_plan=not is_vision, send_cap=is_vision) for name in names]
        responder = LiveResponder(account, Pacer(180, 10, threading.Event()), lambda v=is_vision: auth(v), upstreams,
                                  Holds())
        responders.append(responder)
        models.update({name: responder for name in names})
    return CaptionCache(ByModel(models)), responders


def boundary(responders, started, egress=None):
    if time.monotonic() - started >= MODE_WALL_S:
        raise Stopped("MODE_WALL_S")
    if egress and egress.get("non_loopback"):
        raise Stopped("non_loopback")
    for responder in responders:
        state = responder.state()
        if state["identity_drift"] or state["stopped"] or state["spend_stopped"]:
            raise Stopped("identity_drift" if state["identity_drift"] else state["stop_reason"] or "live_spend_stop")
        if any("quota" in active for active in responder.holds.active.values()):
            raise Stopped("quota_hold")
        if any(_read(up.spend.path)["settled"] for up in responder.upstreams.values() if up.glm_plan):
            raise Stopped("plan_spend")


def _hashes(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "image_url":
            url = obj.get("image_url", {})
            url = url.get("url", "") if isinstance(url, dict) else url
            if url.startswith("data:image/png;base64,"):
                yield sha256(base64.b64decode(url.split(",", 1)[1], validate=True)).hexdigest()
        for child in obj.values():
            yield from _hashes(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from _hashes(child)


def ledger(root):
    path = Path(root) / "ledger" / "ledger.jsonl"
    records = [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []
    store = BlobStore(path.parent / "blobs", None)
    refs = {r[k] for rec in records for r in (rec, *rec.get("upstream", [])) for k in ("req", "resp") if k in r}
    return records, {ref: json.loads(store.get(ref)) for ref in refs}


def captions(root, identity):
    records, blobs = ledger(root)
    found = {}
    s2 = {r["attempt_id"] for r in records if (r.get("cursor") or {}).get("session") == 2}
    for rec in records:
        if rec["attempt_id"] in s2 and (rec.get("role"), rec.get("subrole")) == ("aux", "vision") and rec.get("status") == 200:
            for digest in _hashes(blobs[rec["req"]]):
                if digest in identity:
                    for up in rec.get("upstream", []):
                        if "resp" in up:
                            found[identity[digest]] = blobs[up["resp"]].get("text", "")
    return found


def probe_vision(model, *, director):
    record = world("s8-life-00")[0]
    png, _ = render.render(record, "F0", SEED)
    body = {"model": "bicentennial-aux-vision", "messages": [{"role": "user", "content": [
        {"type": "text", "text": ANALYSIS_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
    status, _, _ = director.handle("POST", "/aux/vision/v1/chat/completions", {}, canon(body))
    records, blobs = ledger(director.ledger.root.parent)
    rec = records[-1]
    up = rec.get("upstream", [])
    answered = any(blobs[u["resp"]].get("text", "").strip() for u in up if "resp" in u)
    return {"model": model, "status": status, "served": rec["served"], "answered": status == 200 and answered}


def run_arm(scratch, mode, life, arm, cache, responders, table, checkout, inputs, started, *, image_kind=None,
            descriptions=(), worker_argv=None):
    readings = gate()
    label = arm + ("-" + image_kind if image_kind else "")
    root = scratch / f"p08-{mode}-{life}-{label}"
    root.mkdir()
    branch = "B1" if arm == "T" else "B0"
    paths = {"home": root / "home", "workspace": root / "workspace", "attachments": {}}
    builder = scratch / "builder-home"
    builder.mkdir(exist_ok=True)
    def native_text(text, path):
        return subprocess.run([str(checkout / ".venv/bin/python"), str(WORKER), "--native-text", text, path],
                              env={"PATH": os.defpath, "HOME": str(builder), "HERMES_HOME": str(builder),
                                   "PYTHONPATH": str(checkout), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
                              capture_output=True, text=True, check=True).stdout.rstrip("\n")
    paths["native_text"] = native_text
    files = {}
    for channel, kind in channels(life).items():
        if channel == "screen":
            continue
        record = next(r for r in world(life, branch) if r["kind"] == kind)
        family = "F4" if arm == "H" else f"F{render.presentation(record, SEED)['family']}"
        png, _ = render.render(record, family, SEED)
        path = paths["home"] / ".s8-inbox" / f"{record['image_id']}.png" if channel == "attachment" else paths["workspace"] / f"{record['image_id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        files[path] = png
    qs = [q for q in questions(life, branch) if image_kind is None or q["id"].startswith(image_kind + ":")]
    if arm in ("M", "T"):
        script = build_script(life, mode, branch=branch, paths=paths)
    else:
        users = [q["user"] for q in qs]
        if arm in ("D", "H"):
            path = next(p for p in files if p.stem == qs[0]["image_id"])
            users[0] = attach(users[0], path, mode, paths)
        if arm == "R":
            users = ["Notes:\n" + rag(user, descriptions) + "\n\nQuestion: " + user for user in users]
        script = script_of(life, [{"index": 6, "kind": "probe", "turns": [turn(u, n) for n, u in enumerate(users, 1)]}])
    for path in files:
        path.unlink()
    if arm in ("D", "H"):
        for path, png in files.items():
            if path.stem == qs[0]["image_id"]:
                path.write_bytes(png)
    side = scratch / f"p08-{root.name}.json"
    _write(side, {"mode": mode, "attachments": paths["attachments"]}, exclusive=True)
    cache.arm = root.name
    event_start = len(cache.events)
    inputs["script_hashes"][root.name] = sha256_canon(script)
    clock = SimClock(scratch / f"{root.name}-clock.json", BASE, STEP)
    adapter = HermesAdapter(load_entry(), script=script, route_table=table, schedule=FaultLite.load([], script),
                            responder=Routed(cache, ScriptedResponder(load_entry())), clock=clock, root=root,
                            scratch=scratch, life=life, branch=branch, run=root.name, kill_mode="boundary",
                            worker_argv=worker_argv or [str(checkout / ".venv/bin/python"), str(WORKER), str(side)],
                            checkout=checkout, harness_pin=inputs["hermes_pin"],
                            write_prompt=runpy.run_path(str(REPO / "spikes/s7/readback.py"))["SUFFIX"])
    receipt = {"mode": mode, "life": life, "arm": arm, "sessions": [], "answers": {}, "shuffled": {}, "stop": None,
               "marker": readings, "inputs": inputs, "route_hash": sha256_canon(table.to_obj())}
    lock = sha256_canon(inputs)
    try:
        for session in script["sessions"]:
            boundary(responders, started, adapter.egress.summary())
            i = session["index"]
            if i == 2:
                for path, png in files.items():
                    path.write_bytes(png)
            result = adapter.run_session(i, sim_t_s=BASE + i * DAY, lock_hash=lock,
                                         attempt_id=attempt_id(lock, label, life, branch, i, 0))
            receipt["sessions"].append({"index": i, "gate": list(result.gate), "timings_ms": result.timings_ms})
            if i == 2:
                for path in files:
                    if ".s8-inbox" in path.parts:
                        path.unlink(missing_ok=True)
            if i == 6:
                b0 = {q["id"]: q for q in questions(life)}
                for q, (_, final) in zip(qs, result.finals, strict=True):
                    receipt["answers"][q["id"]] = score(q["kind"], q["gold"], final)
                    receipt["shuffled"][q["id"]] = score(q["kind"], b0[q["id"]]["gold"], final)
            if any(r.get("role") == "unknown" for r in adapter.records()):
                unknown = [r for r in adapter.records() if r.get("role") == "unknown"]
                _, blobs = ledger(root)
                print(canon([{"path": r["path"], "wire": "chat", "keys": sorted(blobs[r["req"]])} for r in unknown]).decode(), file=sys.stderr)
                raise Stopped("unknown")
            boundary(responders, started, adapter.egress.summary())
    except (Stopped, HarnessFailed) as exc:
        receipt["stop"] = exc.code if isinstance(exc, Stopped) else "HarnessFailed:" + str(exc)
        if any("native_text_mismatch" in p.read_text() for p in (root / "logs").glob("*.stderr")):
            receipt["stop"] = "native_text_mismatch"
    finally:
        receipt["egress"] = adapter.close()
        receipt["cache_events"] = cache.events[event_start:]
        receipt["states"] = [r.state() for r in responders]
        receipt["identities"] = [r.served_identities() for r in responders]
        receipt["wall_ms"] = int((time.monotonic() - started) * 1000)
        _write(root / "receipt.json", receipt)
    if receipt["stop"]:
        raise Stopped(receipt["stop"])
    return root


def scan(scratch):
    needles = [os.environ.get(name, "").encode() for name in ("BICENTENNIAL_UPSTREAM_KEY", "BICENTENNIAL_VISION_KEY")]
    result = {}
    for root in sorted(Path(scratch).glob("p08-*/")):
        count = 0
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                raw = path.read_bytes()
                count += sum(raw.count(n) for n in needles if n)
        _, blobs = ledger(root)
        count += sum(canon(obj).count(n) for obj in blobs.values() for n in needles if n)
        result[root.name] = count
    return result


def summarise(scratch, fidelity=None):
    scratch = Path(scratch)
    fidelity = fidelity or {"n": 200, "state": "pending_human_key"}
    result = {"canary": CANARY, "claim_class": "advisory", "mode": "live", "inputs": {}, "fidelity": fidelity,
              "disclosures": ["The desk code question names OBJECT1, which is excluded from the list gold."],
              "lane": _read(scratch / "lane.json") if (scratch / "lane.json").exists() else {"state": "not_run"},
              "modes": {}, "operating": {"unknown_total": 0, "scan": scan(scratch)}}
    image_ids = {sha256(im["png"]).hexdigest(): im["record"]["image_id"] for im in images()}
    for file in sorted(scratch.glob("p08-*/receipt.json")):
        receipt, root = _read(file), file.parent
        mode, life, arm = (receipt[k] for k in ("mode", "life", "arm"))
        result["inputs"].setdefault(mode, receipt["inputs"])["script_hashes"].update(receipt["inputs"]["script_hashes"])
        view = result["modes"].setdefault(mode, {"rows": [], "lives": {}, "channels": {
            c: {"routed": False, "requests": {}, "lives": []} for c in ("attachment", "workspace")},
            "detail_retention": {"n": 0, "retained": 0}})
        view["channels"]["screen"] = {"not_run": "no_screen_tool", "routed": False}
        outcomes = view["lives"].setdefault(life, {})
        outcomes.setdefault(arm, {}).update(receipt["answers"])
        if arm == "T":
            outcomes["S"] = receipt["shuffled"]
        records, blobs = ledger(root)
        requests = [r for r in records if r.get("type") == "request"]
        unknown = [r for r in requests if r["role"] == "unknown"]
        result["operating"]["unknown_total"] += len(unknown)
        if unknown or receipt["egress"]["non_loopback"] or any(result["operating"]["scan"].values()):
            raise Stopped("unsafe_evidence")
        image_recs = image_requests(requests, blobs)
        tries, hits = [], iter(receipt.get("cache_events", []))
        for rec in requests:
            cached = next(hits, {}).get("hit", False) if (rec["role"], rec["subrole"]) == ("aux", "vision") and rec["served"] != "refused_float" else False
            if not cached:
                tries.extend(dict(d, record=rec["seq"], image=rec in image_recs,
                                  model=up.get("model"), role=up.get("role", rec["role"])) for up in rec.get("upstream", [])
                             for d in up.get("diagnostics", []) if d.get("kind") == "try")
        s6 = {r["attempt_id"] for r in requests if (r.get("cursor") or {}).get("session") == 6}
        reinspections = [r for r in image_recs if r["attempt_id"] in s6] if arm in ("M", "T") else []
        view["rows"].append({k: receipt[k] for k in ("life", "arm", "states", "identities", "egress", "marker", "sessions", "wall_ms", "stop") } | {
            "memory": "hermes-native", "harness": receipt["inputs"]["hermes_pin"], "commit": receipt["inputs"]["hermes_commit"],
            "models": receipt["inputs"]["models"], "calls_by_role": dict(Counter(f"{r['role']}/{r['subrole']}" for r in requests)),
            "image_requests": len(image_recs), "classified": len(requests), "vision_calls": tries,
            "spend_microdollars": sum(d["charged"] or 0 for d in tries),
            "holds": [d for r in requests for up in r.get("upstream", []) for d in up.get("diagnostics", []) if d.get("kind") == "hold"],
            "identity_changed": sorted({r["attempt_id"] for r in requests for up in r.get("upstream", []) for d in up.get("diagnostics", []) if d.get("identity_changed")}),
            "cache_hits": sum(e["hit"] for e in receipt.get("cache_events", [])), "reinspections": len(reinspections),
            "reinspection_reserved": sum(d["reserved"] or 0 for d in tries if any(r["seq"] == d["record"] for r in reinspections)),
            "reinspection_charged": sum(d["charged"] or 0 for d in tries if any(r["seq"] == d["record"] for r in reinspections))})
        if arm == "M":
            desc = captions(root, image_ids)
            for q in questions(life):
                gold = q["gold"] if isinstance(q["gold"], list) else [q["gold"]]
                view["detail_retention"]["n"] += mode == "text"
                view["detail_retention"]["retained"] += mode == "text" and all(_normalise(v) in _normalise(desc.get(q["image_id"], "")) for v in gold)
            s2 = {r["attempt_id"] for r in requests if (r.get("cursor") or {}).get("session") == 2}
            for channel, kind in channels(life).items():
                if channel == "screen":
                    continue
                turn_n = 1 if channel == "attachment" else 2
                matched = []
                for i, rec in enumerate(image_recs):
                    hashes = list(_hashes(blobs[rec["req"]]))
                    if rec["served"] == "refused_float" and i + 1 < len(image_recs):
                        hashes = list(_hashes(blobs[image_recs[i + 1]["req"]]))
                    cursor = rec.get("cursor") or {}
                    if rec["attempt_id"] in s2 and (not cursor or cursor.get("turn") == turn_n) and any(image_ids.get(h) == f"{life}-{kind}" for h in hashes):
                        matched.append(rec)
                pair = view["channels"][channel]
                for rec in matched:
                    key = f"{rec['role']}/{rec['subrole']}"
                    pair["requests"][key] = pair["requests"].get(key, 0) + 1
                answered = any(r["status"] == 200 and r["role"] in ("replay_main", "write_turn") and
                               (r.get("cursor") or {}) == {"session": 2, "turn": turn_n} and
                               r["seq"] >= min((m["seq"] for m in matched), default=10**12) for r in requests)
                pair["lives"].append(bool(matched) and answered)
                pair["routed"] = all(pair["lives"])
    for mode, view in result["modes"].items():
        lives = list(view.pop("lives").values())
        base = [(life, key) for life in lives for key in life.get("M", {})]
        view["accuracy"] = {}
        for arm in ("D", "M", "F", "R", "T", "S", "H"):
            values = [life[arm][key] for life, key in base if key in life.get(arm, {}) and
                      (arm != "M" or life.get("D", {}).get(key) is True)]
            view["accuracy"][arm] = {"n": len(values), "milli": 1000 * sum(values) // len(values) if values else None}
        if mode == "native":
            view["accuracy"]["R"] = {"not_applicable": True}
        bounds = {f"{arm}-F": bootstrap(mode, f"{arm}-F", [[(life[arm][key], life["F"][key]) for key in life.get(arm, {}) if key in life.get("F", {})] for life in lives]) for arm in ("D", "S")}
        na = sum(life.get("D", {}).get(key) is False for life, key in base)
        complete = [set.intersection(*(set(life.get(a, {})) for a in ("M", "D", "F", "S"))) for life in lives]
        view.update(bounds=bounds, na_reader=na, n=len(base), n_lives=len(lives),
                    admission=admission(fidelity, sum(map(len, complete)), sum(bool(c) for c in complete), na, bounds))
        calls = [d for row in view["rows"] if row["arm"] == "M" for d in row["vision_calls"] if d["sent"] and d["image"]]
        view["projection"] = {"label": "projection", "basis": "M", "b_img": 40, "L_img": 8, "calls": len(calls),
                              "delivered_images": len(lives) * 2, "microdollars": sum(d["charged"] or 0 for d in calls) * 320 // (len(lives) * 2 or 1)}
    result["operating"]["spend"] = {p.name: _read(p) for p in scratch.glob("*-spend.json")}
    result["admission"] = {"profile": profile(result["modes"])}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("render", "keysheet", "fidelity", "probe-vision", "live", "scan", "summarise"):
        sub = commands.add_parser(command)
        if command in ("render", "keysheet", "fidelity", "summarise"):
            sub.add_argument("--out", required=True, type=Path)
        if command in ("live", "scan", "summarise", "probe-vision"):
            sub.add_argument("--scratch", required=True, type=Path)
        if command == "fidelity":
            sub.add_argument("--key", required=True, type=Path)
        if command == "summarise":
            sub.add_argument("--fidelity", required=True, type=Path)
        if command == "probe-vision":
            sub.add_argument("--model", required=True)
        if command == "live":
            sub.add_argument("--mode", choices=("text", "native"), required=True)
            sub.add_argument("--hermes", required=True, type=Path)
            for name in ("glm-model", "vision-model", "native-model", "max-output-source"):
                sub.add_argument("--" + name, required=True)
            sub.add_argument("--max-output", required=True, type=int)
            for name in ("vision-price-in", "vision-price-out"):
                sub.add_argument("--" + name, type=int)
            sub.add_argument("--vision-price-source")
            sub.add_argument("--vision-cap", type=int, default=VISION_CAP)
    args = parser.parse_args(argv)
    if args.command in ("live", "probe-vision", "keysheet"):
        reexec_niced(sys.argv)
    try:
        if args.command == "render":
            print(render_all(args.out))
        elif args.command == "keysheet":
            args.out.mkdir(parents=True, exist_ok=False)
            rows = render.keysheet(list(images()))
            with (args.out / "key.csv").open("x", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("id", "crop", "typed"))
                writer.writeheader()
                for row in rows:
                    (args.out / row["crop"]).write_bytes(row["png"])
                    writer.writerow({"id": row["id"], "crop": row["crop"], "typed": ""})
        elif args.command == "fidelity":
            _write(args.out, render.fidelity(render.keysheet(list(images())), args.key), exclusive=True)
        elif args.command == "scan":
            counts = scan(args.scratch)
            print(canon(counts).decode())
            if any(counts.values()):
                return 4
        elif args.command == "summarise":
            if args.out.exists():
                raise ValueError("output_exists")
            _write(args.out, summarise(args.scratch, _read(args.fidelity)), exclusive=True)
        else:
            if args.command == "live" and (args.native_model != args.vision_model or not 0 <= args.vision_cap <= VISION_CAP or args.max_output < 1):
                raise ValueError("invalid_model_or_cap")
            gate()
            scratch = args.scratch.resolve()
            scratch.mkdir(parents=True, exist_ok=True)
            if args.command == "probe-vision":
                cache, responders = provision(scratch, args.model, args.model, 1024)
                cache.arm = "probe"
                root = scratch / "p08-probe"
                root.mkdir()
                script = script_of("s8-probe", [{"index": 1, "kind": "probe", "turns": [turn(ANALYSIS_PROMPT, 1)]}])
                director = Director(script, routes("text", args.model, args.model), "hermes-native", "s8-probe", "B0",
                                    "probe", (), cache, SimClock(root / "clock.json", BASE, STEP), Guard([]),
                                    {"sandbox_root": str(root), "director_port": "0"})
                try:
                    director.start_session(1, BASE, sha256_canon(script), "s8-probe", root / "ledger")
                    probe = probe_vision(args.model, director=director)
                    _write(scratch / "lane.json", {"probe": probe, "chosen": "glm_plan" if probe["answered"] else "paid"}, exclusive=True)
                    print(canon(probe).decode())
                    boundary(responders, time.monotonic())
                finally:
                    director.close()
            else:
                lane = _read(scratch / "lane.json")
                paid = lane["chosen"] == "paid"
                prices = (args.vision_price_in, args.vision_price_out, args.vision_price_source)
                if (paid and any(p is None for p in prices)) or (not paid and any(p is not None for p in prices)):
                    raise ValueError("vision_price_arguments")
                if not paid and lane["probe"]["model"] != args.vision_model:
                    raise ValueError("vision_probe_model_mismatch")
                checkout, entry = args.hermes.resolve(), load_entry()
                commit = verify_pin(checkout, entry["artifact"])
                table = routes(args.mode, args.glm_model, args.vision_model)
                price = Price(args.vision_price_in, args.vision_price_out) if paid else Price(0, 0)
                inputs = {"seed": SEED, "base_commit": "5d2241e", "hermes_pin": entry["artifact"], "hermes_commit": commit,
                          "models": {"glm": args.glm_model, "vision": args.vision_model, "native": args.native_model,
                                     "max_output": args.max_output, "max_output_source": args.max_output_source,
                                     "vision_price": {"input": price.input_per_million, "output": price.output_per_million,
                                                      "source": args.vision_price_source or "GLM plan, subscription"}},
                          "script_hashes": {}, "route_hash": sha256_canon(table.to_obj()),
                          "images": [{"id": im["id"], "sha256": sha256(im["png"]).hexdigest(),
                                      "manifest_sha256": sha256_canon(im["manifest"])} for im in images()]}
                cache, responders = provision(scratch, args.glm_model, args.vision_model, args.max_output, paid, args.vision_cap, price)
                started = time.monotonic()
                for index in range(10):
                    life = f"s8-life-{index:02d}"
                    desc = {}
                    for arm in ("M", "T", "F", "D", "H", *(["R"] if args.mode == "text" else [])):
                        for kind in ([k for c, k in channels(life).items() if c != "screen"] if arm in ("D", "H") else [None]):
                            boundary(responders, started)
                            root = run_arm(scratch, args.mode, life, arm, cache, responders, table, checkout, inputs,
                                           started, image_kind=kind, descriptions=list(desc.values()))
                            if arm == "M":
                                identity = {sha256(im["png"]).hexdigest(): im["record"]["image_id"] for im in images()}
                                found = captions(root, identity)
                                desc = {f"{life}-{k}": found.get(f"{life}-{k}", "") for c, k in channels(life).items() if c != "screen"}
                _write(scratch / f"inputs-{args.mode}.json", inputs, exclusive=True)
        return 0
    except Stopped as exc:
        print(exc.code, file=sys.stderr)
        return exc.exit_code
    except PinMismatch:
        print("s8: harness pin refused", file=sys.stderr)
        return 3
    except (ValueError, OSError, subprocess.SubprocessError):
        print("s8: invalid or existing inputs", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
