"""Transactional T0/T1 pack construction, with controls and construction gates."""

import json
import shutil
from contextlib import ExitStack, closing
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from bicentennial.api.contract import event_copy
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import validate
from bicentennial.controls.battery import check_distribution, check_pack
from bicentennial.controls.cache import compute, pack_controls, write_entry
from bicentennial.controls.common import ControlInput
from bicentennial.genres.g2_assistant.envseed import probe_envseed
from bicentennial.items.protocol import CANARY
from bicentennial.items.reader_keys import KINDS, life_keys
from bicentennial.items.templates import g1, g2
from bicentennial.items.templates.g1.common import option_roles, repo_checks, repo_state
from bicentennial.keyed import mint_id
from bicentennial.probe.scripted_reader import read
from bicentennial.render.stream import content
from bicentennial.score.check_selftest import Case, g2_cases
from bicentennial.world.db import open_world
from bicentennial.world.targeted import load_tier, seeds_manifest, t1_lives

from .catalogue import TEMPLATES_BY_GENRE, c7_entries, generate, load_catalogue
from .manifest import (
    boundary_hashes,
    file_manifest,
    file_sha256,
    labels,
    leaks,
    tree_sha256,
)
from .scoring import SCORING_FILES, code_sha256, make_score, scoring_obj

REPO_ROOT = Path(__file__).resolve().parents[3]


class PackRefused(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def api_events(cut):
    """Project stream rows to the public API in their original stream order."""
    return [event_copy(dict(event_id=r["event_id"], t_sim=r["t_sim"], kind="message",
                            actor=r["actor"], text=content(r)))
            for r in cut.rows if "agent" in r["audience"]]


def g1_cases(compiled, worlds, schedule, templates, *, life):
    items = {i["item_id"]: i for i in compiled.items}
    templates = {t.template_id: t for t in templates}
    bundles = {b["bundle_id"]: b for b in compiled.bundles}
    idx = {s.session_id: s.index for s in schedule.sessions}
    result = []
    for rec in sorted(compiled.records, key=lambda r: r["item_id"]):
        if rec["bundle_id"] is None and rec["branch"] == "B1":
            continue
        item, (db, cut) = items[rec["item_id"]], worlds[rec["branch"]]
        template, k = templates[rec["template_id"]], item["probe_point"]
        table = next((t for t in template.decision_tables
                      if t["table_id"] == item["decision_table_ref"]), None)
        if table and table["timed"]:
            raise ValueError(table["table_id"])
        t_sim = schedule.sessions[k - 1].t_end
        later = bool(db.execute("SELECT 1 FROM fact d JOIN fact f ON f.subject_id=d.subject_id "
                               "AND f.predicate=d.predicate AND f.id!=d.id AND f.object!=d.object "
                               "JOIN link l ON l.fact_id=f.id JOIN event e ON e.id=l.event_id "
                               "WHERE d.id=? AND l.role='assert' AND e.t_sim < ? AND EXISTS "
                               "(SELECT 1 FROM json_each(e.audience_json) WHERE value='agent') "
                               "AND e.t_sim > (SELECT min(a.t_sim) FROM event a JOIN link dl "
                               "ON dl.event_id=a.id WHERE dl.fact_id=d.id AND dl.role='assert') "
                               "AND (f.speech_act IN ('hedge','quote') OR "
                               "(f.speech_act='assert' AND l.role='assert' AND e.actor_id!=f.subject_id "
                               "AND e.actor_id!=?))",
                               (rec["decisive_fact_id"], t_sim, cut.principal_id)).fetchone())
        bundle = bundles.get(rec["bundle_id"])
        result.append(Case(life=life, item=item, record=rec, bundle=bundle,
                           twin=next((items[i] for i in bundle["items"] if i != item["item_id"]), None)
                           if bundle else None, table=table,
                           roles=option_roles(template, db, schedule)[rec["instance_key"]] if table else {},
                           seed=None, state0=repo_state(db, schedule, k) if table else None,
                           checks=repo_checks(template, db, schedule)[rec["instance_key"]] if table else None,
                           window=None, t_sim=t_sim,
                           history="".join(content(r) for r in cut.rows
                                           if idx[r["session_id"]] <= k and "agent" in r["audience"]),
                           later_mention=later))
    return tuple(result)


def _write(path, obj):
    path.write_bytes(canon(obj))


def _templates(t, records):
    items = {i["item_id"]: i for i in t.twin.compiled.items}
    assigned = []
    for tid in sorted({r["template_id"] for r in records}):
        points = {items[r["item_id"]]["probe_point"] for r in records if r["template_id"] == tid}
        if len(points) != 1:
            raise ValueError(tid)
        assigned.append(replace(TEMPLATES_BY_GENRE[t.genre][tid], checkpoint=next(iter(points))))
    return tuple(assigned)


def _needles(items, records, bundles, keys, worlds):
    values = dict(item_id=[i["item_id"] for i in items],
                  option_id=[o["option_id"] for i in items for o in i["options"]],
                  bundle_id=[b["bundle_id"] for b in bundles],
                  decisive_fact_id=[r["decisive_fact_id"] for r in records if r["decisive_fact_id"]],
                  fact_id=[r[0] for b in sorted(worlds)
                           for r in worlds[b][0].execute("SELECT id FROM fact ORDER BY id")])
    needles = {k: frozenset(v.encode() for v in values[k]) for k in sorted(values)}
    needles["reader_key"] = frozenset(canon(k) for k in keys)
    needles["gold_option"] = frozenset(canon(o) for i in items for o in i["options"]
                                       if o["option_id"] == i["gold"]["option_id"])
    return needles


def _prepare(t, worlds, path, tier, rel, row, spec, entries, common_pins):
    compiled, schedule = t.twin.compiled, t.schedule
    records = sorted((r for r in compiled.records if r["bundle_id"] is not None or r["branch"] == "B0"),
                     key=lambda r: r["item_id"])
    ids = {r["item_id"] for r in records}
    items = sorted((i for i in compiled.items if i["item_id"] in ids), key=lambda i: i["item_id"])
    bundles = sorted(compiled.bundles, key=lambda b: b["bundle_id"])
    templates = _templates(t, records)
    for template in templates:
        entry = entries.get(template.ref)
        if (entry is None or canon(entry["decision_tables"]) != canon(list(template.decision_tables))
                or entry["cell_id"] != template.cell_id or entry["direction"] != template.direction):
            raise PackRefused("c7")
    for stage, track in sorted({(i["stage"], i["track"]) for i in items}):
        if all(i["gold"]["never_observed"] for i in items if (i["stage"], i["track"]) == (stage, track)):
            raise PackRefused("abstention_only")
    keys = tuple(k for k in life_keys(compiled, schedule, worlds) if k["item_id"] in ids)
    cases = (g1_cases if t.genre == "G1" else g2_cases)(compiled, worlds, schedule, templates, life=t.life)
    if {c.item["item_id"] for c in cases} != ids:
        raise ValueError(t.life)
    report = check_pack(cases)
    if not report.ok:
        raise PackRefused("check_pack")
    evidence = {c.item["item_id"]: [content(r) for r in worlds[c.record["branch"]][1].rows
                if r["event_id"] in c.item["gold_spans"]] for c in cases if c.table is None}
    obj = scoring_obj(cases, evidence)
    score, competing = make_score(obj), []
    by_key = {k["item_id"]: k for k in keys}
    for c in cases:
        if c.item["stage"] != "act":
            continue
        for kind in KINDS:
            key = by_key[c.item["item_id"]]
            ctx = "\n".join(sorted(v["token"] for v in key["competing"] if v["kind"] == kind))
            if ctx:
                result = read(reader_view(c.item), key, ctx, mode="api")
                s = score(c.item, result).score_milli
                competing.append(dict(item_id=c.item["item_id"], kind=kind,
                                      selected_option=result.selected_option, score_milli=s))
                if c.bundle["twin_type"] == "fork" and kind == "stale" and s != -1000:
                    raise PackRefused("competing_context")
    pack_id = mint_id(canon(["pack", tier, rel]).decode(), 0)
    h = mint_id(canon(["honeypot", pack_id]).decode(), 0)
    now = {i["item_id"]: schedule.sessions[i["probe_point"] - 1].t_end for i in items}
    events = {t.life: {b: api_events(worlds[b][1]) for b in sorted(worlds)}}
    key_bytes = b"".join(canon(k) + b"\n" for k in keys)
    pack = dict(canary=CANARY, pack_id=pack_id, tier=tier, genre=t.genre, seeds=[t.seed], lives=[t.life],
                items=items, bundles=bundles, qa_order=sorted(i["item_id"] for i in items if i["stage"] != "act"),
                controls={n: "not run in v0.1" for n in
                          ("full_history", "naive_rag", "no_memory", "oracle_evidence")},
                hashes=dict(world_b0=t.manifest["world_hash_b0"], world_b1=t.manifest["world_hash_b1"],
                            history_set=t.manifest["history_set_hash"], reader_keys=sha256(key_bytes).hexdigest(),
                            scoring=sha256_canon(obj)))
    try:
        entry = compute(ControlInput(pack, keys, events, now, sha256_canon(obj)),
                        score=score, harness_pin=common_pins["harness_pin"])
    except ValueError:
        raise PackRefused("controls") from None
    if tier == "T0" and entry["broken"]:
        raise PackRefused("controls_broken")
    visible, sealed = path / "visible", path / "sealed"
    visible.mkdir(parents=True)
    sealed.mkdir()
    for b in sorted(worlds):
        db, _ = worlds[b]
        _write(visible / f"events.{b}.json", dict(canary=CANARY, branch=b, events=events[t.life][b]))
        points = sorted({c.item["probe_point"] for c in cases if c.record["branch"] == b
                         and (t.genre == "G1" or c.item["stage"] == "act")})
        data = ({str(k): repo_state(db, schedule, k) for k in points} if t.genre == "G1" else
                {str(k): probe_envseed(db, len(schedule.sessions) + 1, k).seed for k in points})
        name, field = ("repo", "states") if t.genre == "G1" else ("env", "seeds")
        _write(visible / f"{name}.{b}.json", dict(canary=CANARY, branch=b, **{field: data}))
    _write(visible / "answer_key.json", dict(canary=CANARY, title="Benchmark answer key", reference_answer_token=h))
    findings = leaks({p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(visible.iterdir())},
                     _needles(items, records, bundles, keys, worlds))
    if findings:
        raise PackRefused("leak")
    pack["hashes"]["controls"] = write_entry(sealed / "controls.json", entry)
    pack["controls"] = pack_controls(entry)
    validate("pack", pack)
    _write(sealed / "pack.json", pack)
    (sealed / "reader_keys.jsonl").write_bytes(key_bytes)
    _write(sealed / "records.json", records)
    _write(sealed / "scoring.json", obj)
    meta = dict(canary=CANARY, tier=tier, genre=t.genre, life=t.life, seed=t.seed, row=row,
                generator=t.manifest, singleton_lives={i: t.singleton_lives[i]
                    for i in sorted(t.singleton_lives) if i in ids},
                duty_items=sorted(compiled.duty_items() & ids), restart_crossing=sorted(t.restart_crossing),
                now=now, honeypot_token=h)
    if tier == "T1":
        meta["not_exercised"] = sorted(spec["not_exercised"])
    _write(sealed / "meta.json", meta)
    _write(sealed / "build_log.json", dict(canary=CANARY, check_pack=report.to_obj(),
                                          competing=competing, controls_broken=entry["broken"]))
    pins = dict(common_pins, **{k: entry["key"][k] for k in
                ("scorer_sha256", "controls_sha256", "reader_sha256")},
                scoring_sha256=sha256_canon(obj), controls_key_sha256=entry["key_sha256"],
                c7_entries={t.ref: entries[t.ref]["entry_sha256"] for t in templates},
                generator_version=t.manifest["generator_version"],
                **{k: t.manifest[k] for k in ("world_hash_b0", "world_hash_b1", "history_set_hash")},
                **boundary_hashes(t.life, t.twin.cuts))
    return pack_id, cases, pins


def _build_pack(t, path, **kwargs):
    t.twin.b1.close()
    with ExitStack() as stack:
        worlds = {b: (stack.enter_context(closing(open_world(t.out_dir / f"world.{b}.db", readonly=True))), cut)
                  for b, cut in zip(("B0", "B1"), t.twin.cuts, strict=True)}
        pack_id, cases, pins = _prepare(t, worlds, path, **kwargs)
    life = path / "sealed/life"
    life.mkdir()
    for source in sorted(t.out_dir.iterdir()):
        if source.is_file() and not source.name.startswith("items."):
            shutil.copyfile(source, life / source.name)
    for b in ("B0", "B1"):
        (life / f"items.{b}.json").write_bytes(canon([
            c.item for c in cases if c.record["branch"] == b]) + b"\n")
    files = file_manifest(path)
    manifest = dict(canary=CANARY, pack_id=pack_id, tier=kwargs["tier"], genre=t.genre,
                    path=kwargs["rel"], labels=labels(kwargs["tier"]), honeypot="visible/answer_key.json",
                    visible=[p for p in sorted(files) if p.startswith("visible/")],
                    sealed=[p for p in sorted(files) if p.startswith("sealed/")], files=files, pins=pins)
    _write(path / "manifest.json", manifest)
    return manifest, cases


def build_tier(tier, out, *, harness_artifacts, root=REPO_ROOT, rows=None):
    if tier not in ("T0", "T1") or tier == "T1" and rows is not None:
        raise ValueError("tier")
    root, out = Path(root), Path(out)
    dest, staging, work = (out / name for name in (tier, tier + ".staging", tier + ".work"))
    if any(p.exists() or p.is_symlink() for p in (dest, staging, work)):
        raise FileExistsError(tier)
    staging.mkdir(parents=True)
    lives = []
    try:
        spec = load_tier(root / f"tiers/life_specs/{tier.lower()}.toml")
        c7_path = root / "specs/ring0/c7-partial.json"
        entries, catalogue = c7_entries(c7_path), None
        jobs = []
        if tier == "T0":
            cp = root / "packs/catalogue-v0.toml"
            catalogue = load_catalogue(cp, c7_path=c7_path, tier_path=root / "tiers/life_specs/t0.toml")
            seed_manifest = seeds_manifest(dict(spec, seeds=list(catalogue.seeds())))
            for r in sorted(catalogue.rows if rows is None else rows, key=lambda r: r.id):
                if r.gate is None:
                    template = TEMPLATES_BY_GENRE[r.genre][r.template]
                    rel = f"pack/{r.genre}/{r.track}/{template.template_id}@{template.version}/{r.lever_key}/{r.seed}"
                    jobs.append((rel, asdict(r), r))
        else:
            seed_manifest = seeds_manifest(spec)
            lives = list(t1_lives(spec, {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}, root=work))
            jobs = [(f"pack/{t.genre}/{t.life}/{t.seed}", dict(row), t)
                    for row, t in zip(spec["lives"], lives, strict=True)]
        common = dict(harness_pin=sha256_canon(harness_artifacts), c7_sha256=file_sha256(c7_path),
                      seed_hash=sha256_canon(seed_manifest))
        if catalogue:
            common["catalogue_sha256"] = file_sha256(cp)
        packs, all_cases, histories, versions, pins = {}, [], {}, {}, None
        for rel, row, source in jobs:
            t = generate(source, out_dir=work / source.id) if tier == "T0" else source
            if tier == "T0":
                lives.append(t)
            manifest, cases = _build_pack(t, staging / rel, tier=tier, rel=rel, row=row,
                                           spec=spec, entries=entries, common_pins=common)
            version = manifest["pins"]["generator_version"]
            if not version or "+" in version or versions.get(t.genre, version) != version:
                raise PackRefused("generator_version")
            versions[t.genre] = version
            packs[rel] = dict(pack_id=manifest["pack_id"], tree_sha256=tree_sha256(staging / rel))
            all_cases.append(cases)
            histories[rel] = manifest["pins"]["history_set_hash"]
            pins = {k: manifest["pins"][k] for k in
                    ("scorer_sha256", "controls_sha256", "reader_sha256", "harness_pin")}
        distribution = check_distribution(all_cases, not_exercised=spec.get("not_exercised", ()))
        if not distribution.ok:
            raise PackRefused("check_distribution")
        if pins is None:
            raise ValueError("empty_tier")
        pins["scoring_code_sha256"] = code_sha256(SCORING_FILES)
        index = dict(canary=CANARY, tier=tier, labels=labels(tier), seeds_manifest=seed_manifest,
                     seed_hash=common["seed_hash"], generator_version="+".join(sorted(set(versions.values()))),
                     generator_versions={g: versions[g] for g in sorted(versions)},
                     rendered_history_set_hash=sha256_canon(histories), packs=packs, pins=pins,
                     harness_artifacts=json.loads(canon(harness_artifacts)), distribution=distribution.to_obj())
        if catalogue:
            index["catalogue"] = dict(version=catalogue.version, sha256=common["catalogue_sha256"],
                c7_sha256=common["c7_sha256"], not_covered=list(catalogue.not_covered),
                skipped=[dict(id=r.id, gate=r.gate) for r in catalogue.rows if r.gate is not None])
        else:
            index["not_exercised"] = sorted(spec["not_exercised"])
        _write(staging / "index.json", index)
        shutil.rmtree(work)
        staging.rename(dest)
        return dict(index=index, pack_hash=tree_sha256(dest))
    except BaseException:
        for t in lives:
            t.twin.b1.close()
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
        raise
