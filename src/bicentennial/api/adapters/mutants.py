"""Single-fault reference-store controls, isolated by fresh conformance fixtures."""

from .reference_store import ReferenceStore, tokens


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


class forget_cached_output(ReferenceStore):
    """Erases the stored event but answers from an in-memory copy, uncited."""

    def forget(self, selector):
        self.cached = [e["text"] for i, e in self.events.items() if i in selector["event_ids"]]
        super().forget(selector)

    def query(self, task, now):
        result = super().query(task, now)
        words = set(tokens(task["prompt"]))
        leaked = [text for text in getattr(self, "cached", ()) if words & set(tokens(text))]
        return dict(result, output=leaked[0]) if leaked and not result["citations"] else result
