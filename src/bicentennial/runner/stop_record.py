"""A stopped T2 run's per-attempt sends and infrastructure causes (attempts.json)."""

from collections import Counter

from bicentennial.canon import canon


def _tries(rows):
    """Each live try diagnostic, walked as T2-lite's holds walk them (runner/t2lite.py _holds)."""
    for row in rows:
        for upstream in row.get("upstream", ()):
            if upstream.get("served_by") != "live":
                continue
            yield from (d for d in upstream.get("diagnostics", ()) if d.get("kind") == "try")


def _sends(tries):
    tries = tuple(tries)
    sent = [d for d in tries if d.get("sent")]
    refused = [d["t_refused_ms"] for d in tries if type(d.get("t_refused_ms")) is int]
    return dict(sent=len(sent), resent=sum(type(d.get("try")) is int and d["try"] > 1 for d in sent),
        refused=len(refused), first_refused_ms=min(refused, default=None),
        last_sent_ms=max((d["t_sent_ms"] for d in sent if type(d.get("t_sent_ms")) is int), default=None))


def build(*, runs, labels, stack, max_sends, cap, phase, identity_tries):
    """Canonical attempts.json bytes, or None when anything fails: the refusal then stays as before.

    Counts and times only: no item id, answer, envelope, score, request hash or served model. The times are the
    live stack's own monotonic clock (one pacer per run), so they order sends across units and attempts.
    """
    try:
        state = stack.state() if stack is not None else {}
        scored = {(*identity, attempt): found for identity, pairs in labels for attempt, found in pairs}
        attempts = []
        for run in runs:
            key = (run.arm, run.life, run.branch, run.attempt)
            attempts.append(dict(arm=run.arm, life=run.life, branch=run.branch, attempt=run.attempt,
                **_sends(_tries(run.records)),
                infra=dict(sorted(Counter(label for cls, label in run.classes.values()
                                          if cls == "INFRA_FAILURE").items())),
                score_infra=dict(sorted(Counter(scored.get(key, ())).items())),
                stopped=list(run.stopped[:2]) if run.stopped else None,
                audit=run.audit.get("status")))
        identity = _sends(identity_tries)
        sends = state.get("sends")
        attributed = identity["sent"] + sum(a["sent"] for a in attempts)
        latest = max(((a["last_sent_ms"], n) for n, a in enumerate(attempts) if a["last_sent_ms"] is not None),
                     default=None)
        if identity["last_sent_ms"] is not None and (latest is None or identity["last_sent_ms"] > latest[0]):
            reached = "identity_check"
        else:
            reached = None if latest is None else {k: attempts[latest[1]][k]
                                                   for k in ("arm", "life", "branch", "attempt")}
        return canon(dict(attempts=attempts, identity_check=identity, cap_reached_in=reached,
            totals=dict(max_sends=max_sends, cap=cap, phase=phase, sends=sends, identity_check=identity["sent"],
                attempts=attributed - identity["sent"],
                unattributed=sends - attributed if type(sends) is int else None)))
    except Exception:
        return None
