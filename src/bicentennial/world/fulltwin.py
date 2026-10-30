"""Full-length twins over the default builders' finite, static fixtures."""

from dataclasses import asdict, dataclass
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.genres.g1_software.world import build_g1, world_meta
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.items.bindings import Binding, compile_bound
from bicentennial.items.protocol import CELL_IDS, DEFERRED_CELLS
from bicentennial.items.templates.g1 import TEMPLATES as G1
from bicentennial.items.templates.g2 import TEMPLATES as G2
from bicentennial.render.session_cut import cut

from . import create_world
from .scale import named
from .schedule import build_schedule
from .targeted import MIN_DISTANCE_SESSIONS, expected_state, seed_text
from .twin import TwinLife, twin_life


@dataclass(frozen=True)
class Candidate:
    template: object
    fields: tuple[tuple[str, object], ...]
    fixture: tuple[str, str]

    def binding(self, checkpoint):
        return Binding(self.template.template_id, self.fields, checkpoint)


# These are logical writer keys, never discovered by probing minted ids. Omit
# surfaced statements and non-context/non-stated preferences by design. Constant
# chains remain listed for diagnostics even when their surface checks refuse.
FIXTURES = {
    "drift-chain": (("chain", "deadline-0", dict(chain_id="deadline-0", depth=1)),
                    ("chain", "deadline-1", dict(chain_id="deadline-1", depth=2)),
                    ("chain", "constraint-0", dict(chain_id="constraint-0", depth=1))),
    "drift-config": tuple(("chain", key, dict(chain_id=key))
                          for key in ("constant-0", "constant-1")),
    "drift-quote": tuple(("chain", key, dict(chain_id=key))
                         for key in ("constant-0", "constant-1")),
    "recall-value": tuple(("statement", key, dict(statement_id=key)) for key in (
        "constraint-1", "constraint-2", "constraint-3", "decision-0", "decision-1")),
    "wake-loop": tuple(("statement", key, dict(statement_id=key))
                       for key in ("decision-0", "decision-1")),
    "tue-ticket": tuple(("commitment", key, dict(commitment_id=key))
                        for key in ("commitment-0", "commitment-1")),
    "drift-asof": (("preference", "seat-long", dict(pref_id="seat-long")),),
    "drift-booking": (("preference", "seat-long", dict(pref_id="seat-long")),),
    "drift-no-update": (("preference", "seat-short", dict(pref_id="seat-short")),),
    "keep-forget": (("forget", "ex", dict(forget_key="ex")),),
    "keep-neighbour": (("forget", "ex", dict(forget_key="ex", predicate="birthday")),),
    "keep-incidental": tuple(("detail", key, dict(detail_id=key))
                             for key in ("gate", "parking")),
    "recall-count": (("attribute", "trip/trip/date", dict(
        entity_kind="trip", entity_key="trip", attr_key="date")),),
    "tue-passport": (("commitment", "passport", dict(commitment_id="passport")),),
}
FIXTURES["drift-chain-fault"] = FIXTURES["drift-chain"]


def candidates(genre):
    if genre not in ("G1", "G2"):
        raise ValueError("genre")
    return tuple(Candidate(t, tuple(sorted(fields.items())), (kind, key))
                 for t in (G1 if genre == "G1" else G2)
                 for kind, key, fields in FIXTURES[t.template_id])


def validate_budget(budget):
    if type(budget) is not list:
        raise ValueError("budget:shape")
    seen = set()
    for row in budget:
        if (type(row) is not list or len(row) != 3 or type(row[0]) is not str
                or row[0] not in CELL_IDS or row[0] in DEFERRED_CELLS
                or type(row[1]) is not int or row[1] not in named("full").checkpoints
                or type(row[2]) is not int or row[2] < 1):
            raise ValueError("budget:shape")
        key = row[0], row[1]
        if key in seen:
            raise ValueError("budget:shape")
        seen.add(key)


def accepts(binding, compile_one):
    try:
        branch = compile_one(binding)
    except ValueError:
        return False
    return (len(branch.entries) == 1
            and branch.entries[0][1]["evidence_session"] is not None
            and binding.checkpoint - branch.entries[0][1]["evidence_session"]
            >= MIN_DISTANCE_SESSIONS)


def select(budget, table, compile_one):
    """Greedily reserve each logical fixture once, independently of input order."""
    validate_budget(budget)
    selected, used = [], set()
    table = sorted(table, key=lambda c: (c.template.template_id, c.fixture))
    for cell, checkpoint, n in sorted(budget):
        found = 0
        for c in table:
            if c.template.cell_id != cell or c.fixture in used:
                continue
            binding = c.binding(checkpoint)
            if not accepts(binding, compile_one):
                continue
            selected.append(binding)
            used.add(c.fixture)
            found += 1
            if found == n:
                break
        if found < n:
            raise ValueError(f"budget:{cell}@{checkpoint}:{found}/{n}")
    return tuple(selected)


def _world(genre, life, seed, directory):
    scale = named("full")
    schedule = build_schedule(seed_text(seed), life, scale)
    path = Path(directory) / "world.B0.db"
    if genre == "G1":
        db = create_world(path, world_meta(seed_text(seed), 200))
        try:
            principal = build_g1(db, schedule).principal
            db.commit()
        except BaseException:
            db.close()
            raise
    elif genre == "G2":
        base = build_base(path, seed=seed_text(seed), life=life, scale=scale)
        db, principal = base.db, base.people.principal
        if base.schedule.to_json() != schedule.to_json():
            db.close()
            raise ValueError("composition")
    else:
        raise ValueError("genre")
    return db, schedule, principal


def _compiler(db, schedule, principal, genre):
    pre = cut(db, schedule, branch="B0", principal_id=principal,
              expected_state=expected_state(genre, schedule)(db))
    templates = G1 if genre == "G1" else G2

    def compile_one(binding):
        return compile_bound(db, schedule, pre, templates, (binding,))

    return compile_one


@dataclass(frozen=True)
class FullTwin:
    twin: TwinLife
    bindings: tuple[Binding, ...]
    prompts: dict[tuple[str, int], tuple[str, ...]]


def build(genre, life, seed, budget, out_dir) -> FullTwin:
    validate_budget(budget)
    table = candidates(genre)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db, schedule, principal = _world(genre, life, seed, out_dir)
    try:
        bindings = select(budget, table, _compiler(db, schedule, principal, genre))
        twin = twin_life(db, schedule, G1 if genre == "G1" else G2, bindings=bindings,
                         world_path=out_dir / "world.B1.db", out_dir=out_dir / "branches",
                         principal_id=principal, expected_state=expected_state(genre, schedule))
    finally:
        db.close()
    (out_dir / "bindings.json").write_bytes(canon([asdict(b) for b in sorted(
        bindings, key=lambda b: (b.template_id, b.fields, b.checkpoint))]) + b"\n")
    records = {r["item_id"]: r for r in twin.compiled.records}
    prompts = {}
    for branch in ("B0", "B1"):
        for checkpoint in sorted({b.checkpoint for b in bindings}):
            prompts[branch, checkpoint] = tuple(i["prompt"] for i in twin.compiled.items
                if records[i["item_id"]]["branch"] == branch and i["probe_point"] == checkpoint)
    return FullTwin(twin, bindings, prompts)


def capacity(genre, life, seed, work_dir):
    table = candidates(genre)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    db, schedule, principal = _world(genre, life, seed, work_dir)
    try:
        compile_one = _compiler(db, schedule, principal, genre)
        return {(cell, checkpoint): len({c.fixture for c in table
                if c.template.cell_id == cell and accepts(c.binding(checkpoint), compile_one)})
                for cell in sorted({c.template.cell_id for c in table})
                for checkpoint in schedule.scale.checkpoints}
    finally:
        db.close()
