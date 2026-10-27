"""BM25, k1=6/5, b=3/4; fixed-point IDF, exact rational term weights.

IDF is floor(1e6 * ln(1 + (N-df+1/2)/(df+1/2))). ln uses 24
atanh-series terms after binary range reduction to [1, 2), with no floats.
"""

from collections import Counter
from fractions import Fraction as F

from .reference_store import ReferenceStore, tokens


def log_fixed(x):
    shifts = 0
    while x >= 2:
        x /= 2
        shifts += 1

    def series(z):
        return 2 * sum((z ** (2 * k + 1) / (2 * k + 1) for k in range(24)), F(0))

    return int(1_000_000 * (shifts * series(F(1, 3)) + series((x - 1) / (x + 1))))


class BM25(ReferenceStore):
    def scores(self, prompt, events):
        docs = [Counter(tokens(e["text"])) for e in events]
        total = sum(sum(doc.values()) for doc in docs)
        if not total:
            return [0] * len(docs)
        scores = [F(0) for _ in docs]
        for term in sorted(set(tokens(prompt))):
            df = sum(term in doc for doc in docs)
            idf = log_fixed(1 + F(2 * (len(docs) - df) + 1, 2 * df + 1))
            for i, doc in enumerate(docs):
                tf = doc[term]
                norm = F(6, 5) * (F(1, 4) + F(3 * sum(doc.values()) * len(docs), 4 * total))
                scores[i] += idf * F(tf * 11, 5) / (tf + norm)
        return scores
