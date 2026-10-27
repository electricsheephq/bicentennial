"""Strict, C-7-pinned inputs for Ring 0 probe micro-lives."""

import json
import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path

from bicentennial.items.levers import STRESS_TAGS
from bicentennial.items.protocol import CANARY, TRACK_BY_PREFIX, cell_stage, cell_track
from bicentennial.items.tags import stage
from bicentennial.items.templates import g1, g2
from bicentennial.world.targeted import MicroSpec, load_tier, micro_life

from .recipes import RECIPES

TEMPLATES_BY_GENRE = {g: {t.template_id: t for t in ts}
                      for g, ts in (("G1", g1.TEMPLATES), ("G2", g2.TEMPLATES))}
NOT_COVERED = (
    dict(genre="G1", track="Keep", reason="no G1 Keep template in v0.1"),
    *(dict(genre=g, track="Rachael", reason="Rachael action bundles deferred to the live tiers (v0.2)")
      for g in ("G1", "G2")),
    *(dict(genre=g, track="Faults", reason="no FAULT template in v0.1") for g in ("G1", "G2")),
    dict(genre="G2", track="Wake", reason="no G2 Wake template in v0.1"),
)
NO_BASELINE_REASON = "intrinsic fault template; no fault-free twin at v0.1"


@dataclass(frozen=True, kw_only=True)
class Row:
    id: str
    genre: str
    template: str
    cell: str
    stage: str
    test: str
    seed: int
    sessions: int
    distance: int
    wake: str
    base: str | None = None
    vary: str | None = None
    gate: str | None = None
    baseline: str | None = None
    schedule_seed: int | None = None
    lever_delta: dict | None = None
    confounded: bool = False
    track: str = field(init=False)
    twin: bool = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "track", cell_track(self.cell))
        object.__setattr__(self, "twin", TEMPLATES_BY_GENRE[self.genre][self.template].twin_type is not None)

    @property
    def lever_key(self):
        return f"s{self.sessions}-d{self.distance}-{self.wake}"

    def micro_spec(self):
        template = TEMPLATES_BY_GENRE[self.genre][self.template]
        return MicroSpec(genre=self.genre, seed=self.seed, sessions=self.sessions, distance=self.distance,
                         wake=self.wake, recipe=f"catalogue-v0:{template.ref}", schedule_seed=self.schedule_seed)


@dataclass(frozen=True)
class Catalogue:
    version: int
    rows: tuple[Row, ...]
    not_covered: tuple[dict, ...]
    c7_sha256: str
    no_baseline: tuple[dict, ...]

    def by_id(self):
        return {r.id: r for r in self.rows}

    def rows_for(self, genre, track=None):
        return tuple(r for r in self.rows if r.genre == genre and (track is None or r.track == track))

    def seeds(self):
        return tuple(sorted({r.seed for r in self.rows}))

    def to_obj(self):
        return dict(canary=CANARY, version=self.version, tier="T0", levers_label="uncalibrated (v0.2)",
                    c7_file="specs/ring0/c7-partial.json", c7_sha256=self.c7_sha256,
                    rows=[asdict(r) for r in self.rows], not_covered=list(self.not_covered),
                    no_baseline=list(self.no_baseline))


def c7_entries(path):
    return json.loads(Path(path).read_bytes())["entries"]


def _require(condition, ident):
    if not condition:
        raise ValueError(ident)


def load_catalogue(path, *, c7_path, tier_path):
    try:
        return _load(path, c7_path, tier_path)
    except (KeyError, TypeError, AttributeError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        raise ValueError("catalogue-v0") from None


def _load(path, c7_path, tier_path):
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    _require(set(data) == {"canary", "version", "tier", "levers_label", "c7_file", "c7_sha256",
                           "rows", "not_covered", "no_baseline"}, "catalogue-v0")
    tier, entries = load_tier(tier_path), c7_entries(c7_path)
    _require(data["canary"] == CANARY and type(data["version"]) is int and data["version"] == 0
             and data["tier"] == "T0" and tier["tier"] == "T0"
             and data["levers_label"] == tier["levers_label"]
             and data["c7_file"] == "specs/ring0/c7-partial.json"
             and data["c7_sha256"] == sha256(Path(c7_path).read_bytes()).hexdigest(), "catalogue-v0")
    rows, vectors, indexed = [], set(), {}
    for raw in data["rows"]:
        ident, genre, name = raw["id"], raw["genre"], raw["template"]
        _require(type(ident) is str, "catalogue-v0")
        _require(genre in TEMPLATES_BY_GENRE and name in TEMPLATES_BY_GENRE[genre], ident)
        template = TEMPLATES_BY_GENRE[genre][name]
        intrinsic = getattr(template, "fault", False)
        faulted = intrinsic or raw["wake"] != "none"
        keys = {"id", "genre", "template", "cell", "stage", "test", "seed", "sessions", "distance", "wake"}
        if raw["test"] in ("INV", "DIR"):
            keys.update(("base", "vary"))
        if raw["test"] == "INV":
            keys.update(("schedule_seed", "lever_delta", "confounded"))
            raw["lever_delta"] = json.loads(raw["lever_delta"])
            _require(type(raw["confounded"]) is bool, ident)
        if template.cell_id == "TUE-EVENT":
            keys.add("gate")
        if faulted:
            keys.add("baseline")
        _require(set(raw) == keys and raw["test"] in ("MFT", "INV", "DIR"), ident)
        # TOML has no null: only intrinsic faults use the empty-string wire representation.
        if faulted:
            _require(type(raw["baseline"]) is str and (raw["baseline"] == "") == intrinsic, ident)
        row = Row(**(raw | ({"baseline": None} if intrinsic else {})))
        _require(re.fullmatch(re.escape(f"{genre.lower()}-{name}-{row.test.lower()}-") + r"[1-9][0-9]*", ident)
                 and ident not in indexed, ident)
        vector = (genre, name, row.seed, row.sessions, row.distance, row.wake)
        _require(vector not in vectors, ident)
        row.micro_spec()
        _require(row.wake in tier["wakes"] and tier["sessions"][0] <= row.sessions <= tier["sessions"][1], ident)
        crossed = (STRESS_TAGS[row.wake],) if row.wake in STRESS_TAGS else ()
        _require(row.cell == template.cell_id and row.track == template.track
                 and row.stage == stage(template.kind, crossed)
                 and cell_stage(row.cell) == ("A" if row.stage == "act" else "R"), ident)
        entry = entries.get(template.ref)
        _require(entry is not None and entry["cell_id"] == row.cell and entry["direction"] == template.direction, ident)
        _require(row.gate == ("#84" if row.cell == "TUE-EVENT" else None), ident)
        rows.append(row)
        indexed[ident] = row
        vectors.add(vector)
    for row in rows:
        if row.test in ("INV", "DIR"):
            base = indexed.get(row.base)
            _require(base is not None and base.test == "MFT"
                     and (base.genre, base.template) == (row.genre, row.template), row.id)
            fields = ("seed", "sessions", "distance", "wake")
            _require(row.vary in (("seed",) if row.test == "INV" else ("distance", "wake")), row.id)
            _require(all(getattr(row, f) == getattr(base, f) for f in fields if f != row.vary), row.id)
            if row.vary == "seed":
                _require(row.seed != base.seed and row.schedule_seed == base.seed, row.id)
            elif row.vary == "distance":
                _require(row.distance == base.distance + 1, row.id)
            else:
                _require(base.wake == "none" and row.wake != "none", row.id)
        if row.baseline is not None:
            baseline = indexed.get(row.baseline)
            _require(baseline is not None and baseline.id != row.id and baseline.wake == "none"
                     and not getattr(TEMPLATES_BY_GENRE[baseline.genre][baseline.template], "fault", False)
                     and all(getattr(row, f) == getattr(baseline, f)
                             for f in ("genre", "template", "seed", "sessions", "distance")), row.id)
    no_baseline = tuple(dict(id=r.id, reason=NO_BASELINE_REASON) for r in sorted(rows, key=lambda r: r.id)
                        if getattr(TEMPLATES_BY_GENRE[r.genre][r.template], "fault", False))
    confounded_pairs = sorted({(r.genre, r.track) for r in rows if r.test == "INV" and r.confounded}
                             - {(r.genre, r.track) for r in rows if r.test == "INV" and not r.confounded})
    not_covered = NOT_COVERED + tuple(dict(genre=g, track=t, reason="every INV row confounded at v0.1")
                                    for g, t in confounded_pairs)
    _require(data["no_baseline"] == list(no_baseline) and data["not_covered"] == list(not_covered), "catalogue-v0")
    for genre in ("G1", "G2"):
        for track in TRACK_BY_PREFIX.values():
            covered = any(r.genre == genre and r.track == track for r in rows)
            absent = any(n["genre"] == genre and n["track"] == track for n in NOT_COVERED)
            _require(covered != absent, "catalogue-v0")
    return Catalogue(0, tuple(sorted(rows, key=lambda r: r.id)), tuple(data["not_covered"]),
                     data["c7_sha256"], no_baseline)


def generate(row, *, out_dir):
    life = micro_life(row.micro_spec(), TEMPLATES_BY_GENRE[row.genre][row.template],
                      RECIPES[row.genre, row.template], out_dir=out_dir)
    if any((i["cell_id"], i["track"], i["stage"]) != (row.cell, row.track, row.stage)
           for i in life.twin.compiled.items):
        life.twin.b1.close()
        shutil.rmtree(out_dir)
        raise ValueError(row.id)
    return life
