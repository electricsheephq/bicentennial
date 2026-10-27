"""Schedule stages, decisive-fact surfaces and canonical state predicates."""

import json
import re

from bicentennial.canon import canon


def stage(kind, crossed):
    return "act" if kind == "act" else "survive" if crossed else "remember"


def labels(stage, crossed):
    return sorted(["voice: template", *(f"survive:{t}" for t in crossed)]) if stage == "survive" else ["voice: template"]


def memory_tag(db, fact_ids, t_probe):
    """The caller supplies only the decisive fact (Amendment 1 A3)."""
    return "env_recoverable" if any(db.execute(
        "SELECT 1 FROM fact_surface WHERE fact_id=? AND from_t < ?", (fid, t_probe)).fetchone()
        for fid in sorted(set(fact_ids) - {None})) else "memory_exclusive"


def precondition(cut, k):
    state = next(s["expected_state"] for s in cut.sessions if s["index"] == k)
    return canon(dict(after_session=k, env_state_hash=state["env_state_hash"],
                      repo_tree_hash=state["repo_tree_hash"])).decode()


def check_precondition(text, *, repo_tree_hash, env_state_hash):
    try:
        obj = json.loads(text)
        if (type(obj) is not dict or set(obj) != {"after_session", "env_state_hash", "repo_tree_hash"}
                or canon(obj).decode() != text or type(obj["after_session"]) is not int
                or obj["after_session"] < 1 or any(type(obj[key]) is not str or not re.fullmatch(
                    r"[a-f0-9]{64}", obj[key]) for key in ("env_state_hash", "repo_tree_hash"))):
            raise ValueError("invalid precondition")
    except (TypeError, KeyError) as error:
        raise ValueError("invalid precondition") from error
    return obj["repo_tree_hash"] == repo_tree_hash and obj["env_state_hash"] == env_state_hash
