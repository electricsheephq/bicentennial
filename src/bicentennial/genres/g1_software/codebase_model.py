"""Commits and structured diffs: commit events carry them, and repository state is derived from rows at read time."""

from dataclasses import dataclass

from bicentennial.world.db import insert_event, insert_fact_surface, insert_link
from bicentennial.world.lineage import atomic
from bicentennial.world.processes import SALIENCE, mint

PROCESS = "g1_software"
# Amendment 1 A2: a commit lands at its statement's instant, ordered after it, so the
# repository state and as_valid(t) agree at every boundary.
COMMIT_LAG_S = 0
PATHS = {"flag": "config/flags.toml", "constant": "config/settings.toml", "endpoint": "service/routes.toml",
         "decision": "docs/decisions.md"}
OPS = ("add_flag", "add_constant", "change_constant", "add_endpoint", "record_decision")
_ADD = {"flag": "add_flag", "endpoint": "add_endpoint", "decision": "record_decision"}


@dataclass(frozen=True)
class Diff:
    event_id: str
    t: int
    author_id: str
    op: str
    path: str
    entity_id: str
    name: str
    key: str
    before: str | None
    after: str
    fact_id: str


def write_commit(db, schedule, *, unit_id, n, fact_id, author) -> str:
    """One commit event that mentions the fact and surfaces it in the repository."""
    with atomic(db):
        asserts = db.execute("SELECT e.t_sim, e.id FROM link l JOIN event e ON e.id = l.event_id "
                             "WHERE l.fact_id = ? AND l.role = 'assert'", (fact_id,)).fetchall()
        if len(asserts) != 1:
            raise ValueError("a committed fact needs exactly one asserting event")
        t = asserts[0][0] + COMMIT_LAG_S
        kind = db.execute("SELECT s.kind FROM fact f JOIN entity s ON s.id = f.subject_id WHERE f.id = ?",
                          (fact_id,)).fetchone()
        if kind is None or kind[0] not in PATHS:
            raise ValueError("the fact's subject kind has no repository path")
        if [tuple(r) for r in db.execute("SELECT kind FROM entity WHERE id = ?", (author,))] != [("person",)]:
            raise ValueError("a commit author must be a person")
        end = db.execute("SELECT t_end FROM session WHERE t_start <= ?1 AND ?1 < t_end", (asserts[0][0],)).fetchone()
        if end is None or t >= end[0]:
            raise ValueError("a commit must land inside its statement's session")
        # A nonempty suffix sorts after its prefix in G09's (t_sim, id) order.
        eid = asserts[0][1] + ":commit:" + mint(schedule, PROCESS, unit_id, "event", "commit", n)
        insert_event(db, id=eid, t_sim=t, kind="commit", channel="commit", actor_id=author, audience_json=["agent"],
                     visibility="shared", salience=SALIENCE, payload_json={})
        insert_link(db, event_id=eid, fact_id=fact_id, role="mention")
        insert_fact_surface(db, fact_id=fact_id, surface="repo", from_t=t)
    return eid


def diffs(db) -> tuple[Diff, ...]:
    """Every commit in (t_sim, id) order; `before` is the pair's previous `after`."""
    out, last = [], {}
    for e in db.execute("SELECT id, t_sim, kind, channel, actor_id FROM event "
                        "WHERE kind = 'commit' OR channel = 'commit' ORDER BY t_sim, id").fetchall():
        if (e["kind"], e["channel"]) != ("commit", "commit"):
            raise ValueError("kind commit and channel commit go together")
        links = db.execute("SELECT fact_id, role FROM link WHERE event_id = ?", (e["id"],)).fetchall()
        if len(links) != 1 or links[0]["role"] != "mention":
            raise ValueError("a commit has exactly one link, a mention")
        found = db.execute("SELECT f.subject_id, f.predicate, s.kind, s.canonical_name, t.value FROM fact f "
                           "JOIN entity s ON s.id = f.subject_id JOIN locked_token t ON t.fact_id = f.id "
                           "WHERE f.id = ?", (links[0]["fact_id"],)).fetchall()
        if len(found) != 1:
            raise ValueError("a committed fact needs exactly one locked token")
        subject, key, kind, name, after = found[0]
        if kind not in PATHS:
            raise ValueError("the fact's subject kind has no repository path")
        pair = (subject, key)
        if pair in last and kind != "constant":
            raise ValueError("a flag, endpoint or decision is committed once")
        op = _ADD.get(kind) or ("change_constant" if pair in last else "add_constant")
        out.append(Diff(e["id"], e["t_sim"], e["actor_id"], op, PATHS[kind], subject, name, key, last.get(pair),
                        after, links[0]["fact_id"]))
        last[pair] = after
    return tuple(out)


def state_at(db, t) -> dict[str, dict[str, str]]:
    """Per path, {name: after} from the last diff of each pair at or before t."""
    state = {path: {} for path in sorted(PATHS.values())}
    for d in diffs(db):
        if d.t <= t:
            state[d.path][d.name] = d.after
    return {path: dict(sorted(names.items())) for path, names in state.items()}
