"""Window-bounded full history: a diagnostic, never a gate."""

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.contract import answer, task_ids
from bicentennial.world.scale import DEV_WINDOW
from bicentennial.world.tokens import estimate_tokens

from .common import run_arm


class FullHistory(ReferenceStore):
    def history(self, now):
        return [e for e in list(self.events.values()) if e["t_sim"] <= now]

    def query(self, task, now):
        task_ids(task, now)
        return answer(self.history(now))


def fits(adapter, now, window):
    return estimate_tokens(answer(adapter.history(now))["output"]) <= window


def run(inp, *, score, window=DEV_WINDOW):
    arm = run_arm(inp, FullHistory, score=score, keep=lambda a, n: fits(a, n, window))
    return dict(arm, fits={"run": len(arm["items"]), "of": len(inp.pack["items"])})
