"""Schedule-derived positions and single uncalibrated lever values."""

import json

from bicentennial.render.stream import content
from bicentennial.world.tokens import estimate_tokens

STRESS_TAGS = {"kill": "crash", "compaction": "compaction", "swap": "swap"}
LEVERS = tuple(sorted(("distance_sessions", "distance_s", "distance_tokens_est", "dispersion",
                       "interference", "chain_depth", "salience", "wake_events", "fault_proximity")))


def wake_points(schedule):
    return tuple(sorted([(kind, s, t or 0) for kind, s, t in schedule.wakes() if kind != "restart"]
                        + [("compaction", p.index, len(p.turn_t)) for p in schedule.sessions if p.long_sprint]))


def compute(db, schedule, cut, *, gold_spans, decisive_fact_id, probe_point):
    levers = dict.fromkeys(LEVERS)
    levers["dispersion"] = 0
    if not gold_spans:
        return levers, (), None
    plans = schedule.sessions
    indices = {p.session_id: p.index for p in plans}
    spans = [r for r in cut.rows if r["event_id"] in gold_spans]
    anchor = spans[-1]
    positions = [(indices[r["session_id"]], int(r["turn_key"].rsplit("/t", 1)[1])) for r in spans]
    s_a, n_a = positions[-1]
    k, t_p = probe_point, plans[probe_point - 1].t_end
    stresses = [(kind, s, t) for kind, s, t in wake_points(schedule) if s <= k]
    points = [(kind, s, t) for kind, s, t in stresses if (s_a, n_a) <= (s, t)]
    # Stress tags cover every required span; distance levers retain the latest anchor.
    crossed = tuple(sorted({STRESS_TAGS[kind] for kind, s, t in stresses
                            if kind in STRESS_TAGS and any(pos <= (s, t) for pos in positions)}))

    def ordinal(s, n):
        return sum(len(p.turn_t) for p in plans[:s - 1]) + n

    faults = [ordinal(s, t) - ordinal(s_a, n_a) for kind, s, t in points
              if kind in ("kill", "compaction")]
    after = cut.rows[cut.rows.index(anchor) + 1:]
    salience = [db.execute("SELECT salience FROM event WHERE id=?", (r["event_id"],)).fetchone()[0]
                for r in spans]
    levers.update(distance_sessions=k - s_a, distance_s=t_p - anchor["t_sim"],
                  distance_tokens_est=estimate_tokens("".join(content(r) for r in after
                                                              if indices[r["session_id"]] <= k)),
                  dispersion=len({r["session_id"] for r in spans}), salience=min(salience),
                  wake_events=k - s_a + 1 + sum(kind == "kill" for kind, _, _ in points),
                  fault_proximity=min(faults) if faults else None)
    if decisive_fact_id is not None:
        d = db.execute("SELECT subject_id, predicate FROM fact WHERE id=?", (decisive_fact_id,)).fetchone()
        visible = db.execute("SELECT DISTINCT f.id, f.subject_id, f.predicate, l.role, e.audience_json FROM fact f "
                             "JOIN link l ON l.fact_id=f.id JOIN event e ON e.id=l.event_id "
                             "WHERE e.t_sim < ? ORDER BY f.id, l.role", (t_p,)).fetchall()
        visible = [r for r in visible if "agent" in json.loads(r["audience_json"])]
        levers["interference"] = len({r["id"] for r in visible if r["predicate"] == d["predicate"]
                                     and r["subject_id"] != d["subject_id"] and r["role"] == "assert"
                                     })
        levers["chain_depth"] = len({r["id"] for r in visible if r["predicate"] == d["predicate"]
                                    and r["subject_id"] == d["subject_id"] and r["role"] == "retract"
                                    })
    return levers, crossed, s_a
