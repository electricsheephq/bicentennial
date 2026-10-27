"""Evidence ceiling: verbatim task-listed events only, in task-list order."""

from bicentennial.api.contract import answer, task_ids

from .reference_store import ReferenceStore


class OracleEvidence(ReferenceStore):
    def query(self, task, now):
        ids = task_ids(task, now)
        if any(i not in self.events or self.events[i]["t_sim"] > now for i in ids):
            raise ValueError("oracle evidence unavailable at now")
        return answer([self.events[i] for i in ids])
