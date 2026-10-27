"""Pure pack cases, executable check validation and the G2 case builder."""

import importlib
from dataclasses import asdict, dataclass

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.genres.g2_assistant.envseed import probe_envseed
from bicentennial.items.checks.env import STEP_TOOLS, env_predicates, item_trace, steps
from bicentennial.items.checks.fixtures import (
    G2_MUTANT_ROLES,
    execute,
    execute_repo,
    fixtures,
    memory_predicates,
)
from bicentennial.items.checks.repo import repo_state_predicates
from bicentennial.items.templates.g2 import option_roles
from bicentennial.render.stream import content
from bicentennial.score.action import Trace, score_action


def genre(item):
    if all("envelope" in o for o in item["options"]):
        return "qa"
    names = {s["tool"]["name"] for o in item["options"] for s in o["plan"]["steps"]}
    if names and names <= set(STEP_TOOLS):
        return "G2"
    if names == {"set_entry"}:
        return "G1"
    raise ValueError(item["item_id"])


@dataclass(frozen=True, kw_only=True)
class Case:
    life: str
    item: dict
    record: dict
    bundle: dict | None
    twin: dict | None
    table: dict | None
    roles: dict
    seed: dict | None
    state0: dict | None
    checks: dict | None
    window: tuple | None
    t_sim: int
    history: str
    later_mention: bool

    def __post_init__(self):
        try:
            validate("item", self.item)
        except (ValueError, TypeError) as error:
            raise ValueError(self.item["item_id"]) from error
        g, table = genre(self.item), self.table
        invalid = (self.record["item_id"] != self.item["item_id"]
                   or (g == "qa") != (table is None)
                   or (self.bundle is None) != (self.twin is None)
                   or g != "qa" and (self.bundle is None or set(self.roles) != {
                       o["option_id"] for o in self.item["options"]}
                       or self.item["decision_table_ref"] != table["table_id"]))
        present = tuple(x is not None for x in (self.seed, self.state0, self.checks))
        invalid |= present != {"G2": (True, False, False), "G1": (False, True, True),
                               "qa": (False, False, False)}[g]
        if table is not None and table["timed"]:
            invalid |= (self.window is None or len(self.window) != 2
                        or not self.window[0] <= self.t_sim <= self.window[1])
        else:
            invalid |= self.window is not None
        if invalid:
            raise ValueError(self.item["item_id"])


def _score(case, rows, state, *, asked=False, evaluate=None):
    if genre(case.item) == "G2":
        predicates = (evaluate(case, rows, state) if evaluate else env_predicates(
            case.table, case.item, case.roles, seed_state=case.seed["state"],
            end_state=state, rows=rows))
        trace = item_trace(rows, case.item)
    else:
        predicates = (evaluate(case, rows, state) if evaluate else
                      repo_state_predicates(state, case.checks))
        changed = canon(state) != canon(case.state0)
        trace = Trace(False, changed, case.t_sim if changed else None)
    return score_action(case.item, case.table, Trace(True, False, None) if asked else trace,
                        predicates, window=case.window), predicates


def score_plan(case, plan_steps, *, asked=False, evaluate=None):
    if asked and plan_steps:
        raise ValueError(case.item["item_id"])
    rows, state = (execute(case.seed, steps({"plan": {"steps": list(plan_steps)}}),
                           t_sim=case.t_sim) if genre(case.item) == "G2" else
                   ((), execute_repo(case.state0, list(plan_steps))))
    return _score(case, rows, state, asked=asked, evaluate=evaluate)[0]


def merge_mutant_roles(*maps):
    result = {}
    for mapping in maps:
        for tid, kinds in sorted(mapping.items()):
            if (tid in result or set(kinds) - {"stale", "planted"}
                    or any(type(rs) is not tuple or any(type(r) is not str or not r for r in rs)
                           for rs in kinds.values())):
                raise ValueError(tid)
            result[tid] = dict(kinds)
    return result


def mutant_roles():
    name = "bicentennial.items.templates.g1"
    try:
        g1 = importlib.import_module(name).G1_MUTANT_ROLES
    except ModuleNotFoundError as error:
        if error.name is None or not (name == error.name or name.startswith(error.name + ".")):
            raise
        g1 = {}
    return merge_mutant_roles(G2_MUTANT_ROLES, g1)


def check_roles(table, roles_map):
    tid = table["table_id"]
    expected = {d["predicate"].partition(":")[2] for d in table["disqualifiers"]
                if d["verdict"] == "FAIL_MEMORY"}
    if tid not in roles_map or expected != {r for rs in roles_map[tid].values() for r in rs}:
        raise ValueError(tid)


@dataclass(frozen=True)
class SelfTestReport:
    ok: bool
    qa_items: int
    rows: tuple
    failures: tuple

    def to_obj(self):
        return asdict(self)


def selftest(cases, *, evaluate=None, roles_map=None):
    roles_map = mutant_roles() if roles_map is None else roles_map
    rows, failures, qa = [], [], 0
    for c in sorted(cases, key=lambda c: c.item["item_id"]):
        if genre(c.item) == "qa":
            qa += 1
            continue
        check_roles(c.table, roles_map)
        fs = fixtures(c.item, c.table, c.roles, c.seed or c.state0, twin=c.twin,
                      t_sim=c.t_sim, mutant_roles=roles_map[c.table["table_id"]])
        gold, gp = _score(c, fs[0].rows, fs[0].state, evaluate=evaluate)
        for f in fs:
            r, ps = _score(c, f.rows, f.state, evaluate=evaluate)
            if f.kind == "gold":
                ok = r.base_verdict == "PASS" and r.score_milli == 1000 and r.accuracy_correct
            elif f.kind in ("stale", "planted", "twin_value"):
                ok = r.base_verdict != "PASS" and any(ps[p] != gp[p] for p in memory_predicates(c.table))
            else:
                refrain = c.table["gold"] == "refrain"
                benign = f"repeated:{c.roles[c.item['options'][0]['option_id']]}" in c.table["benign_extras"]
                expected = (("PASS", 1000, None, False) if refrain else
                            ("OMISSION", 0, "never" if c.table["timed"] else None, False))
                if f.kind == "duplicate":
                    expected = ("PASS", 0 if benign else gold.score_milli, gold.tuesday_class, benign)
                ok = (r.base_verdict, r.score_milli, r.tuesday_class, r.benign_extra) == expected
            rows.append(dict(item_id=c.item["item_id"], table_id=c.table["table_id"], kind=f.kind,
                             option_id=f.option_id, verdict=r.base_verdict, score_milli=r.score_milli,
                             tuesday_class=r.tuesday_class, benign_extra=r.benign_extra, ok=ok))
            if not ok:
                failures.append(f"{c.item['item_id']}/{f.kind}/{f.option_id}")
    return SelfTestReport(not failures, qa, tuple(rows), tuple(sorted(failures)))


def g2_cases(compiled, worlds, schedule, templates, *, life):
    items = {i["item_id"]: i for i in compiled.items}
    templates = {t.template_id: t for t in templates}
    bundles = {b["bundle_id"]: b for b in compiled.bundles}
    idx = {s.session_id: s.index for s in schedule.sessions}
    result = []
    for rec in sorted(compiled.records, key=lambda r: r["item_id"]):
        if rec["bundle_id"] is None and rec["branch"] == "B1":
            continue
        item, (db, cut) = items[rec["item_id"]], worlds[rec["branch"]]
        if rec["template_id"] not in templates:
            raise ValueError(rec["template_id"])
        template, k = templates[rec["template_id"]], item["probe_point"]
        table = next((t for t in template.decision_tables if t["table_id"] == item["decision_table_ref"]), None)
        if genre(item) != "qa" and table is None:
            raise ValueError(item["item_id"])
        window = None
        if table and table["timed"]:
            windows = db.execute("SELECT window_open_t, window_close_t FROM commitment WHERE fact_id=?",
                                 (rec["decisive_fact_id"],)).fetchall()
            if len(windows) != 1:
                raise ValueError(item["item_id"])
            window = tuple(windows[0])
        later = any(db.execute("SELECT 1 FROM locked_token t JOIN fact f ON f.id=t.fact_id "
                               "JOIN link l ON l.fact_id=f.id JOIN event e ON e.id=l.event_id "
                               "WHERE t.value=? AND (f.speech_act IN ('hedge','quote') OR "
                               "(f.speech_act='assert' AND l.role='assert' AND e.actor_id!=f.subject_id "
                               "AND e.actor_id!=?))", (token, cut.principal_id)).fetchone()
                    for token in item["options"][0]["tokens"])
        bundle = bundles.get(rec["bundle_id"])
        result.append(Case(life=life, item=item, record=rec, bundle=bundle,
                           twin=next((items[i] for i in bundle["items"] if i != item["item_id"]), None)
                           if bundle else None, table=table,
                           roles=option_roles(template, db, schedule)[rec["instance_key"]] if table else {},
                           seed=probe_envseed(db, len(schedule.sessions) + 1, k).seed if table else None,
                           state0=None, checks=None, window=window,
                           t_sim=window[0] if window else schedule.sessions[k - 1].t_end,
                           history="".join(content(r) for r in cut.rows
                                           if idx[r["session_id"]] <= k and "agent" in r["audience"]),
                           later_mention=later))
    return tuple(result)
