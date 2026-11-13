"""BM25 chunk anchor v1."""

from bicentennial.api.adapters.bm25 import BM25 as Scorer
from bicentennial.controls.naive_rag import chunks

from . import Anchor


class BM25(Anchor):
    recall_basis = "chunk_quote"
    k = 5

    def select(self, prompt, now):
        docs = [(e["event_id"], n, text) for e in self.visible(now)
                for n, text in enumerate(chunks(e["text"]))]
        scores = Scorer().scores(prompt, [dict(text=text) for _, _, text in docs])
        ranked = sorted(((-score, eid, n, text) for score, (eid, n, text) in
                         zip(scores, docs, strict=True) if score > 0))
        return [(eid, text) for _, eid, _, text in ranked[:self.k]]
