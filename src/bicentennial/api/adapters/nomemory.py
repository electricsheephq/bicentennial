"""No-memory floor: never retains an event."""

from bicentennial.api.contract import answer, event_copy, task_ids

from .reference_store import ReferenceStore


class NoMemory(ReferenceStore):
    def ingest(self, event):
        event_copy(event)

    def query(self, task, now):
        task_ids(task, now)
        return answer()

    def restore(self, data):
        restored = ReferenceStore()
        restored.restore(data)
        self.reset()
