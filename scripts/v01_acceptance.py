"""Read v0.1 output trees and publish deterministic acceptance evidence."""

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYSTEMS = ("hermes-native", "holographic", "mem0-oss")
PLUGINS = ("holographic", "mem0-oss")
REFERENCE = "reference_store"
RUNS = {"t0": ("run1", "run2"), "t1": ("base", "run1", "run2")}
TARGET_MS = {"t0": 60_000, "t1": 600_000}
UNIT = {"t0": "pack", "t1": "run"}
SIGNAL = "Ring 0 developer signal; not predictive of the full tier; never certifies"
WIPED_LABEL = "positive control: must fail"
CLAIM = "unit outputs of the v0.1 kit; not predictive of the full tier"
SCHEMA = "bicentennial-v0.1-result/1"
T1_DISCLOSURES = tuple("t1." + n for n in (
    "assistant_turns", "baselines", "corpus", "corpus_crash", "estimator", "fresh_install",
    "isolation", "key_matching", "receipt", "terminal", "tuesday", "unsettled", "verdicts",
    "verified_empty", "window"))
PLUGIN_T1_DISCLOSURES = ("t1.a4", "t1.plugin_snapshot", "t1.reclassify", "t1.fresh_install_mask")
WITNESSES = ("isolation.forwarded", "isolation.unknown_requests", "no_memory.gold_in_context")
KIT_DISCLOSURES = (
    ("kit.t0_mode", "T0 ran in memory-layer mode on every system; the T0 Hermes-replay fallback "
     "ships in v0.2 (RING0 §13 E5)"),
    ("kit.targets", "loop-time targets are engineering budgets, not bars (PREREG §8 bar 5); "
     "every miss is listed under Target misses"),
    ("kit.determinism", "determinism is claimed per machine and pin set only (RING0 §4)"))
CHECKS = ("runs_complete", "exit_codes", "schema", "t0_packs", "run_status", "t0_identical",
          "t1_gate", "t1_baseline", "t1_identical", "wiped_fails", "isolation", "controls",
          "honeypot", "spend", "pins", "disclosures", "loop_time_measured")
COMMON = ("card.json", "receipt.json", "junit.xml", "invariants.json", "controls.json")
TOP = {"t0": ("pack", "cache", "adapter_invariants.json", "relations.json", "relations.xml",
              "refusal.json"), "t1": ("system", "wiped", "cache", "refusal.json")}
LIMITS = ("These are unit outputs of the v0.1 kit, run on one machine with one pin set. "
          "They are not predictive of the full tier and never certify a system. Determinism is "
          "claimed per machine and pin set only. Act results at T0 and T1 are evidence-conditioned "
          "scripted actions, not an Act judgement. Loop-time targets are engineering budgets, not bars.")


class InputError(Exception):
    def __init__(self, code, where):
        self.code, self.where = code, where


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise InputError("usage", "arguments")

    def exit(self, status=0, message=None):
        self.error(message)


@dataclass
class Run:
    system: str
    tier: str
    name: str
    exit: int
    path: Path
    files: dict
    units: tuple
    unexpected: tuple

    @property
    def where(self):
        return f"{self.system}/{self.tier}/{self.name}"

    def obj(self, rel):
        return self.files.get(rel, (None, None))[1]

    def data(self, rel):
        return self.files[rel][0]


@dataclass
class Contracts:
    canon: object
    sha256_canon: object
    validate: object
    loop_time: object
    determinism_check: object
    invariants: tuple


def contracts():
    from bicentennial.canon import canon, sha256_canon
    from bicentennial.contracts.run import validate
    from bicentennial.report.determinism import determinism_check
    from bicentennial.report.receipt import loop_time
    from bicentennial.report.t1_gate import INVARIANTS

    return Contracts(canon, sha256_canon, validate, loop_time, determinism_check, INVARIANTS)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def obj(value):
    return value if isinstance(value, dict) else {}


def rows(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def read_file(path, where):
    try:
        if path.is_symlink():
            raise OSError("symlink")
        data = path.read_bytes()
        if path.suffix == ".json":
            value = json.loads(data.decode("utf-8"))
        elif path.suffix == ".xml":
            value = ET.fromstring(data)
        else:
            value = None
        return data, value
    except (OSError, UnicodeError, ValueError, ET.ParseError):
        raise InputError("unreadable", where) from None


def entries(path, where):
    try:
        if path.is_symlink() or not path.is_dir():
            raise InputError("layout", where)
        return {p.name: p for p in sorted(path.iterdir())}
    except OSError:
        raise InputError("unreadable", where) from None


def read_runs(root, systems=SYSTEMS):
    """Read only output artifacts; caches and optional invocation logs stay unopened."""
    if not root.exists():
        raise InputError("runs_missing", "--runs")
    expected = tuple(sorted((*systems, REFERENCE)))
    found = entries(root, ".")
    for name in sorted(set(found) ^ set(expected)):
        raise InputError("layout", name)
    result = []
    for system in expected:
        tiers = ("t0",) if system == REFERENCE else ("t0", "t1")
        found = entries(root / system, system)
        for name in sorted(set(found) ^ set(tiers)):
            raise InputError("layout", f"{system}/{name}")
        for tier in tiers:
            prefix = f"{system}/{tier}"
            found = entries(root / prefix, prefix)
            allowed = {n + suffix for n in RUNS[tier] for suffix in ("", ".exit", ".log")}
            required = {n + ".exit" for n in RUNS[tier]}
            for name in sorted((set(found) - allowed) | (required - set(found))):
                raise InputError("layout", f"{prefix}/{name}")
            for name in RUNS[tier]:
                where = f"{prefix}/{name}"
                data, _ = read_file(root / (where + ".exit"), where + ".exit")
                if re.fullmatch(rb"(0|[1-9][0-9]{0,2})\n", data) is None:
                    raise InputError("exit_file", where + ".exit")
                path, files, unexpected, units = root / where, {}, (), ()
                if path.exists() or path.is_symlink():
                    top = entries(path, where)
                    unexpected = tuple(sorted(set(top) - set(TOP[tier])))
                    pending = [p for n, p in top.items() if n in TOP[tier] and n != "cache"]
                    while pending:
                        current = pending.pop(0)
                        rel = current.relative_to(path).as_posix()
                        if current.is_symlink():
                            raise InputError("unreadable", f"{where}/{rel}")
                        if current.is_dir():
                            pending.extend(entries(current, f"{where}/{rel}").values())
                        elif current.suffix in (".json", ".xml"):
                            files[rel] = read_file(current, f"{where}/{rel}")
                    units = (tuple(sorted(str(Path(r).parent.as_posix()) for r in files
                                          if r.startswith("pack/") and r.endswith("/card.json")))
                             if tier == "t0" else ("system", "wiped"))
                result.append(Run(system, tier, name, int(data), path, files, units, unexpected))
    return result


def read_index(directory):
    try:
        _, index = read_file(directory / "index.json", "--t0-packs")
    except InputError:
        raise InputError("index", "--t0-packs") from None
    packs = obj(index).get("packs")
    if obj(index).get("tier") != "T0" or not isinstance(packs, dict) or not packs:
        raise InputError("index", "--t0-packs")
    if any(not isinstance(p, str) or not p.startswith("pack/") or "\\" in p
           or any(c in ("", ".", "..") for c in p.split("/")) for p in packs):
        raise InputError("index", "--t0-packs")
    return tuple(sorted(packs))


def properties(run, unit):
    root = run.obj(f"{unit}/junit.xml")
    if root is None or root.tag != "testsuites":
        return None
    arm = "system" if run.tier == "t0" else unit
    name = f"ring0.{run.tier.upper()}.{run.system}.{arm}"
    suites = [s for s in root.findall("testsuite") if s.get("name") == name]
    if len(suites) != 1:
        return None
    pairs = [(p.get("name"), p.get("value")) for p in suites[0].findall("properties/property")]
    if any(not isinstance(n, str) or not isinstance(v, str) for n, v in pairs):
        return None
    if len({n for n, _ in pairs}) != len(pairs):
        return None
    return dict(pairs)


def gate_property(props):
    try:
        value = json.loads(props.get("gate", "null"))
        return value if isinstance(value, dict) and "baseline_sha256" in value else None
    except ValueError:
        return None


class Predicates:
    """Each named predicate returns its failures; evaluation follows the published order."""

    def __init__(self, args, runs, packs, api, system_hashes):
        self.args, self.runs, self.packs, self.api = args, runs, packs, api
        self.system_hashes, self.invalid = system_hashes, set()

    def units(self, tier=None):
        return ((r, u, obj(r.obj(f"{u}/card.json"))) for r in self.runs
                if tier is None or r.tier == tier for u in r.units)

    def runs_complete(self):
        failures = []
        for r in self.runs:
            if r.exit == 3 or "refusal.json" in r.files:
                code = obj(r.obj("refusal.json")).get("code")
                failures.append(("run_refused", r.where + (f":{code}" if code is not None else "")))
                continue
            required = (["adapter_invariants.json", "relations.json", "relations.xml"]
                        if r.tier == "t0" else [])
            required += [f"{u}/{n}" for u in r.units for n in
                         (*COMMON, *(("corpus.json",) if r.tier == "t1" else ()))]
            if r.exit > 3 or not r.path.is_dir() or not r.units or any(n not in r.files for n in required):
                failures.append(("run_incomplete", r.where))
            elif r.unexpected:
                failures.append(("run_layout", r.where))
        return tuple(failures)

    def exit_codes(self):
        failures = []
        for r in self.runs:
            verdicts = [obj(r.obj(f"{u}/card.json")).get("gate_verdict") for u in r.units]
            if r.tier == "t1":
                verdicts = verdicts[:1]
            derived = 1 if any(v in ("FAIL", "INVALID") for v in verdicts) else (2 if "BLOCKED" in verdicts else 0)
            if r.exit != derived:
                failures.append(("exit_mismatch", r.where))
            if r.tier == "t0" and (r.exit != 0 if r.system == REFERENCE else r.exit not in (0, 1)):
                failures.append(("t0_exit", r.where))
            if r.tier == "t1" and r.exit != 0:
                failures.append(("t1_exit", r.where))
        return tuple(failures)

    def schema(self):
        failures = []

        def check(r, rel, holds):
            if not holds:
                failures.append(("schema_invalid", f"{r.where}/{rel}"))
                self.invalid.add((r.where, rel))

        for r in self.runs:
            invariant_files = [f"{u}/invariants.json" for u in r.units]
            if r.tier == "t0":
                invariant_files.append("adapter_invariants.json")
            for rel in invariant_files:
                value = r.obj(rel)
                check(r, rel, isinstance(value, list) and len(value) == 4 and
                      tuple(v.get("invariant") for v in rows(value)) == self.api.invariants)
        for r, unit, card in self.units():
            for filename, contract in (("card.json", "card_ring0"), ("receipt.json", "receipt")):
                rel, value = f"{unit}/{filename}", r.obj(f"{unit}/{filename}")
                try:
                    self.api.validate(contract, value)
                    holds = filename != "card.json" or (r.data(rel) == self.api.canon(value) and
                        card["tier"] == r.tier.upper() and card["system"] == r.system)
                except (ValueError, TypeError):
                    holds = False
                check(r, rel, holds)
            props = properties(r, unit)
            check(r, f"{unit}/junit.xml", props is not None and
                  (r.tier == "t0" or gate_property(props) is not None))
            if r.tier == "t1":
                value = r.obj(f"{unit}/corpus.json")
                check(r, f"{unit}/corpus.json", isinstance(value, list) and bool(value) and
                      len(rows(value)) == len(value) and all(set(v) ==
                      {"case_id", "first_diff", "reason", "status"} for v in rows(value)))
        return tuple(failures)

    def t0_packs(self):
        return tuple(("t0_pack_set", r.where) for r in self.runs if r.tier == "t0" and r.units != self.packs)

    def run_status(self):
        return tuple(("run_status", f"{r.where}/{u}") for r, u, c in self.units() if c.get("run_status") != "COMPLETE")

    def compare(self, a, b, rel, code, normalize=False):
        if any((r.where, rel) in self.invalid or rel not in r.files for r in (a, b)):
            return ()
        left, right = a.data(rel), b.data(rel)
        if normalize:
            left = self.api.canon(dict(a.obj(rel), gate_verdict="PASS"))
        if left == right:
            return ()
        where = f"{b.where}/{rel}"
        if rel.endswith("card.json"):
            where += ":" + self.api.determinism_check(left, right).first_field
        return ((code, where),)

    def groups(self, tier):
        return [{r.name: r for r in self.runs if (r.system, r.tier) == (s, tier)}
                for s in sorted({r.system for r in self.runs if r.tier == tier})]

    def t0_identical(self):
        failures = []
        for group in self.groups("t0"):
            if "run1" in group and "run2" in group:
                a, b = group["run1"], group["run2"]
                stable = ["adapter_invariants.json", "relations.json"] + [f"{u}/{n}"
                    for u in sorted(set(a.units) & set(b.units))
                    for n in ("card.json", "junit.xml", "invariants.json")]
                for rel in stable:
                    failures.extend(self.compare(a, b, rel, "t0_not_identical"))
        return tuple(failures)

    def t1_gate(self):
        failures = []
        for r, u, c in self.units("t1"):
            if u == "system":
                expected = "CONFORMANCE_PASS" if r.name == "base" else "PASS"
                props = properties(r, u) or {}
                if c.get("gate_verdict") != expected or props.get("gate.final") != c.get("gate_verdict"):
                    failures.append(("t1_system_gate", f"{r.where}/{u}"))
        return tuple(failures)

    def t1_baseline(self):
        failures = []
        for group in self.groups("t1"):
            base = group.get("base")
            if base is None:
                continue
            for r in group.values():
                gate = gate_property(properties(r, "system") or {})
                expected = None if r.name == "base" else digest(base.data("system/card.json"))
                if gate is not None and gate["baseline_sha256"] != expected:
                    failures.append(("t1_baseline", f"{r.where}/system"))
        return tuple(failures)

    def t1_identical(self):
        failures = []
        for group in self.groups("t1"):
            if "run1" in group and "run2" in group:
                for arm in ("system", "wiped"):
                    for name in ("card.json", "junit.xml", "invariants.json", "corpus.json", "controls.json"):
                        failures.extend(self.compare(group["run1"], group["run2"], f"{arm}/{name}", "t1_not_identical"))
            if "base" in group and "run1" in group:
                for arm in ("system", "wiped"):
                    failures.extend(self.compare(group["base"], group["run1"], f"{arm}/card.json",
                                                 "t1_base_differs", normalize=arm == "system"))
        return tuple(failures)

    def wiped_fails(self):
        failures = []
        for r in (r for r in self.runs if r.tier == "t1"):
            system, wiped = (obj(r.obj(f"{u}/card.json")) for u in ("system", "wiped"))
            if wiped.get("gate_verdict") != "FAIL":
                failures.append(("wiped_not_fail", r.where))
            props = properties(r, "system") or {}
            if (obj(system.get("controls")).get("wiped_store") != "FAIL" or
                    props.get("controls.wiped_store") != "FAIL"):
                failures.append(("wiped_store", r.where))
            mapping = {}
            for bundle in rows(wiped.get("bundles")):
                for item in bundle.get("items", []) if isinstance(bundle.get("items"), list) else []:
                    if isinstance(item, str) and isinstance(bundle.get("life"), str):
                        mapping.setdefault(bundle["life"], set()).add(item)
            for single in rows(wiped.get("singletons")):
                if isinstance(single.get("life"), str) and isinstance(single.get("item_id"), str):
                    mapping.setdefault(single["life"], set()).add(single["item_id"])
            if len(mapping) != 2:
                failures.append(("t1_lives", r.where))
            for life in sorted(mapping):
                if not any(i.get("item_id") in mapping[life] and i.get("stage_attribution") in
                           ("stored", "retained") and type(i.get("score_milli")) is int and
                           i["score_milli"] < 1000 for i in rows(wiped.get("items"))):
                    failures.append(("wiped_stage", f"{r.where}:{life}"))
        return tuple(failures)

    def isolation(self):
        failures = []
        for r, u, _ in self.units("t1"):
            props = properties(r, u) or {}
            for witness, code in zip(WITNESSES, ("isolation_forwarded", "isolation_unknown",
                                                "no_memory_gold"), strict=True):
                if witness not in props:
                    failures.append(("property_missing", f"{r.where}/{u}:{witness}"))
                elif props[witness] != "0":
                    failures.append((code, f"{r.where}/{u}"))
        return tuple(failures)

    def controls(self):
        failures = []
        for r in (r for r in self.runs if r.tier == "t1"):
            controls = obj(r.obj("system/controls.json"))
            if (r.data("system/controls.json") != r.data("wiped/controls.json") or
                set(controls) != {"canary", "floor_mismatches", "label", "wipes"} or
                controls.get("label") != WIPED_LABEL or not isinstance(controls.get("wipes"), list)):
                failures.append(("controls", r.where))
            for arm in ("system", "wiped"):
                props = properties(r, arm) or {}
                if (obj(r.obj(f"{arm}/controls.json")).get("floor_mismatches") != [] or
                        props.get("controls.floor_mismatches") != "[]"):
                    failures.append(("floor_mismatches", f"{r.where}/{arm}"))
        return tuple(failures)

    def honeypot(self):
        return tuple(("honeypot", f"{r.where}/{u}") for r, u, c in self.units()
                     if c.get("gate_verdict") == "INVALID" or (properties(r, u) or {}).get("honeypot.hits") != "0")

    def spend(self):
        return tuple(("spend", f"{r.where}/{u}") for r, u, _ in self.units()
                     if obj(r.obj(f"{u}/receipt.json")).get("spend_micro_usd") != 0)

    def pins(self):
        failures = []
        for r, u, c in self.units():
            expected = [("benchmark_commit", self.args.commit, "pins_commit"),
                        ("pack_hash", getattr(self.args, f"{r.tier}_pack_hash"), "pins_pack_hash")]
            if r.system in self.system_hashes:
                expected.append(("system_hash", self.system_hashes[r.system], "pins_system"))
            for field, value, code in expected:
                if obj(c.get("pins")).get(field) != value:
                    failures.append((code, f"{r.where}/{u}"))
        return tuple(failures)

    def disclosures(self):
        failures = []
        for r, u, _ in self.units("t1"):
            props = properties(r, u) or {}
            for name in (*T1_DISCLOSURES, *(PLUGIN_T1_DISCLOSURES if r.system in PLUGINS else ())):
                if name not in props:
                    failures.append((f"disclosure_missing:{name}", f"{r.where}/{u}"))
        return tuple(failures)


def evaluate(args, systems=SYSTEMS):
    """Evaluate all predicates. An empty systems tuple exercises real reference T0 output."""
    api = contracts()
    packs = read_index(Path(args.t0_packs))
    runs = read_runs(Path(args.runs), systems)
    system_hashes = {}
    for s in sorted(systems):
        path = REPO / "systems/registry" / f"{s}.toml"
        try:
            system_hashes[s] = api.sha256_canon([tomllib.loads(path.read_text("utf-8"))["artifact"]])
        except (OSError, ValueError, KeyError, TypeError):
            raise InputError("unreadable", f"systems/registry/{s}.toml") from None
    predicates = Predicates(args, runs, packs, api, system_hashes)
    failures = {"runs_complete": list(predicates.runs_complete())}
    excluded = {where.split(":", 1)[0]: code for code, where in failures["runs_complete"]}
    predicates.runs = [r for r in runs if r.where not in excluded]
    for name in CHECKS[1:-1]:
        failures[name] = list(getattr(predicates, name)())
    failures["loop_time_measured"] = []
    return manifest(args, runs, packs, failures, excluded, predicates.invalid, api, systems)


def loop_time_measured(timing, required):
    return tuple((f"loop_time_unmeasured:{side}", "T1") for side in ("idle", "busy")
                 if required and not timing["T1"][side + "_n"])


def manifest(args, runs, packs, failures, excluded, invalid, api, systems):
    run_rows, misses = [], []
    timing = {t.upper(): dict(unit=UNIT[t], target_ms=TARGET_MS[t], idle_max_ms=None,
              busy_max_ms=None, idle_n=0, busy_n=0) for t in RUNS}
    disclosures = {s: set() for s in sorted((*systems, REFERENCE))}
    for r in runs:
        row = dict(system=r.system, tier=r.tier.upper(), run=r.name, exit=r.exit,
                   spend_micro_usd=0, cards=[], loop=[])
        run_rows.append(row)
        if r.where in excluded:
            row["failed"] = excluded[r.where]
            continue
        for unit in r.units:
            card = obj(r.obj(f"{unit}/card.json"))
            row["cards"].append(dict(unit=unit, sha256=digest(r.data(f"{unit}/card.json")),
                gate_verdict=card.get("gate_verdict") if isinstance(card.get("gate_verdict"), str) else None,
                run_status=card.get("run_status") if isinstance(card.get("run_status"), str) else None))
            receipt = obj(r.obj(f"{unit}/receipt.json"))
            spend = receipt.get("spend_micro_usd")
            row["spend_micro_usd"] += spend if type(spend) is int else 0
            if (r.tier == "t0" or unit == "system") and (r.where, f"{unit}/receipt.json") not in invalid:
                ms, busy = api.loop_time(receipt)
                row["loop"].append(dict(unit=unit, ms=ms, busy=busy))
                stats = timing[r.tier.upper()]
                side = "busy" if busy else "idle"
                stats[side + "_n"] += 1
                previous = stats[side + "_max_ms"]
                stats[side + "_max_ms"] = ms if previous is None else max(previous, ms)
                if ms > TARGET_MS[r.tier]:
                    misses.append(dict(system=r.system, tier=r.tier.upper(), run=r.name,
                        unit=unit, ms=ms, target_ms=TARGET_MS[r.tier], busy=busy))
            if r.name == "run1":
                disclosures[r.system].update((n, v) for n, v in (properties(r, unit) or {}).items()
                                              if n.startswith(("t0.", "t1.")))
    kit = list(KIT_DISCLOSURES)
    for tier, stats in timing.items():
        if not stats["busy_n"]:
            kit.append((f"kit.busy.{tier}", f"{tier} loop time not measured busy"))
    failures["loop_time_measured"] = list(loop_time_measured(timing, bool(systems)))
    disclosures["kit"] = kit
    checks = [dict(name=n, holds=not failures[n], failures=sorted(set(failures[n]))) for n in CHECKS]
    try:
        version = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    except (OSError, ValueError, KeyError):
        raise InputError("unreadable", "pyproject.toml") from None
    return dict(schema=SCHEMA, claim_class=CLAIM, label=SIGNAL, tool_version=version,
        code_commit=args.commit, packs=dict(T0=dict(pack_hash=args.t0_pack_hash, count=len(packs)),
        T1=dict(pack_hash=args.t1_pack_hash)), runs=sorted(run_rows, key=lambda r:
        (r["system"], r["tier"], r["run"])), loop_time=timing,
        target_misses=sorted(misses, key=lambda r: (r["system"], r["tier"], r["run"], r["unit"])),
        disclosures={s: sorted(disclosures[s]) for s in sorted(disclosures)},
        spend_micro_usd=sum(r["spend_micro_usd"] for r in run_rows), checks=checks,
        accepted=all(c["holds"] for c in checks))


def render(m, api):
    """Render solely from the manifest; escape evidence used in Markdown cells."""
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def table(values):
        return "| " + " | ".join(cell(v) for v in values) + " |"

    lines = ["# Bicentennial v0.1 Kit: acceptance result", "", f"Claim class: {m['claim_class']}.",
        f"{m['label']}.", "", f"- Tool version: {m['tool_version']}", f"- Code commit: {m['code_commit']}",
        f"- T0 pack hash ({m['packs']['T0']['count']} packs): {m['packs']['T0']['pack_hash']}",
        f"- T1 pack hash: {m['packs']['T1']['pack_hash']}", f"- Accepted: {'yes' if m['accepted'] else 'no'}",
        f"- Spend: {m['spend_micro_usd']} micro-USD", "", "## Results", "",
        "| System | Tier | Run | Exit | Unit | Gate | Run status | Card sha256 |",
        "|---|---|---|---|---|---|---|---|"]
    for r in m["runs"]:
        prefix = [r["system"], r["tier"], r["run"], r["exit"]]
        if "failed" in r:
            lines.append(table([*prefix, "failed: " + r["failed"], "", "", ""]))
        elif r["tier"] == "T0":
            cards = r["cards"]
            gates = sorted({str(c["gate_verdict"]) for c in cards})
            counts = ", ".join(f"{g} {sum(str(c['gate_verdict']) == g for c in cards)}" for g in gates)
            lines.append(table([*prefix, f"{len(cards)} packs", counts,
                ", ".join(sorted({str(c['run_status']) for c in cards})),
                api.sha256_canon([[c["unit"], c["sha256"]] for c in cards])]))
        else:
            lines.extend(table([*prefix, c["unit"], c["gate_verdict"], c["run_status"], c["sha256"]])
                         for c in r["cards"])
    lines += ["", "## Loop time", "",
        "| Tier | Unit | Target ms | Idle max ms | Busy max ms | Idle n | Busy n |",
        "|---|---|---|---|---|---|---|"]
    for tier, stats in m["loop_time"].items():
        lines.append(table([tier, *[stats[k] if stats[k] is not None else "not measured" for k in
            ("unit", "target_ms", "idle_max_ms", "busy_max_ms", "idle_n", "busy_n")]]))
    lines += ["", "T0's first pack includes the adapter-invariant time.", "", "## Target misses", ""]
    lines += [f"- {r['system']} {r['tier']} {r['run']} {r['unit']}: {r['ms']} ms against "
              f"{r['target_ms']} ms ({'busy' if r['busy'] else 'idle'})" for r in m["target_misses"]] or ["- None."]
    lines += ["", "## Disclosures"]
    for system, pairs in m["disclosures"].items():
        lines += ["", f"### {system}", "", *[f"- {cell(n)}: {cell(v)}" for n, v in pairs]]
    lines += ["", "## Acceptance checks", "", "| Check | Holds | Failures |", "|---|---|---|"]
    for check in m["checks"]:
        failures = "; ".join(f"{c} {w}" for c, w in check["failures"][:5])
        if len(check["failures"]) > 5:
            failures += f" (+{len(check['failures']) - 5} more)"
        lines.append(table([check["name"], "yes" if check["holds"] else "no", failures]))
    return "\n".join([*lines, "", "## What this does not prove", "", LIMITS, ""])


def main(argv=None) -> int:
    parser = Parser(description=__doc__, add_help=False)
    for name in ("runs", "t0-packs", "t0-pack-hash", "t1-pack-hash", "commit", "out"):
        parser.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv)
        for name, size in (("commit", 40), ("t0_pack_hash", 64), ("t1_pack_hash", 64)):
            if re.fullmatch("[0-9a-f]{" + str(size) + "}", getattr(args, name)) is None:
                parser.error("invalid pin")
        if os.environ.get("PYTHONHASHSEED") != "0":
            raise InputError("hashseed", "PYTHONHASHSEED")
        out = Path(args.out)
        if out.exists() or out.is_symlink():
            raise InputError("out_exists", "--out")
        sys.path.insert(0, str(REPO / "src"))
        result = evaluate(args)
        api = contracts()
        data, markdown = api.canon(result), render(result, api)
        try:
            out.mkdir(parents=True)
            (out / "RESULT-MANIFEST.json").write_bytes(data)
            (out / "RESULT.md").write_text(markdown, encoding="utf-8", newline="\n")
        except OSError:
            raise InputError("unreadable", "--out") from None
    except InputError as error:
        print(f"{error.code} {error.where}", file=sys.stderr)
        return 3
    count = 0
    for check in result["checks"]:
        for code, where in check["failures"]:
            print(f"FAIL {check['name']} {code} {where}")
            count += 1
    print("accepted" if result["accepted"] else f"rejected {count}")
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
