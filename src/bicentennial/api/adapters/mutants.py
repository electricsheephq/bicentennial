"""Single-fault reference-store controls, isolated by fresh conformance fixtures."""

from .reference_store import ReferenceStore


class wipe_on_restart(ReferenceStore):
    def restore(self, data):
        self.reset()


class truncate_after_compaction(ReferenceStore):
    def maintain(self):
        self.events = dict(sorted(self.events.items(), key=lambda pair: self.tie(pair[1]))[-2:])


class orphan_tool_result(ReferenceStore):
    def ingest(self, event):
        super().ingest(event)
        if event["kind"] == "tool_result":
            self.events.pop(event["call_id"], None)


class forget_ignored(ReferenceStore):
    def forget(self, selector):
        pass


class stale_wins(ReferenceStore):
    def tie(self, event):
        return -event["t_sim"], event["event_id"]
