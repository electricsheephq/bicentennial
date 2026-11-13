"""Rarest prompt word first, whole-event grep anchor v1."""

from bicentennial.controls.naive_rag import words

from . import Anchor


class Grep(Anchor):
    def select(self, prompt, now):
        events = list(reversed(self.visible(now)))
        terms = {term: [e for e in events if term in words(e["text"])]
                 for term in sorted(set(words(prompt)))}
        seen, ordered = set(), []
        for term in sorted(terms, key=lambda t: (len(terms[t]), t)):
            for event in terms[term]:
                if event["event_id"] not in seen:
                    seen.add(event["event_id"])
                    ordered.append(event)
        return self.bounded(ordered)
