"""Branchwise invariance and bundle-minimum directional diagnostics."""

import bicentennial.canon as canonical
from bicentennial.contracts.bundle import NONRESULTS
from bicentennial.score.bundle import twin_min


class Relation(tuple):
    """Immutable relation record without dependencies beyond the scoring modules."""

    __slots__ = ()
    fields = ("row", "base", "test", "vary", "row_score", "base_score", "status", "lever_delta")

    def __new__(cls, row, base, test, vary, row_score, base_score, status, lever_delta=None):
        return tuple.__new__(cls, (row, base, test, vary, row_score, base_score, status, lever_delta))

    def __getattr__(self, name):
        if name not in self.fields:
            raise AttributeError(name)
        return self[self.fields.index(name)]

    def to_obj(self):
        return dict(zip(self.fields, self, strict=True))


class Report(tuple):
    """Frozen diagnostic relations; no MFT score expectation is invented here."""

    __slots__ = ()

    def __new__(cls, relations):
        return tuple.__new__(cls, (tuple(relations),))

    @property
    def relations(self):
        return self[0]

    @property
    def flagged(self):
        return tuple(sorted(r.row for r in self.relations if r.status == "flagged"))

    def to_obj(self):
        schema = canonical.__file__.rsplit("/", 3)[0] + "/schemas/item.schema.json"
        with open(schema, encoding="utf-8") as source:
            canary = canonical.json.load(source)["properties"]["canary"]["enum"][0]
        return dict(canary=canary, catalogue_version=0,
                    labels=["not predictive of the full tier; never certifies", "rungs: uncalibrated (v0.2)"],
                    relations=[r.to_obj() for r in self.relations], flagged=list(self.flagged),
                    counts={s: sum(r.status == s for r in self.relations)
                            for s in ("holds", "flagged", "unscored", "confounded")})


def check(rows, outcomes):
    rows = tuple(rows)
    indexed = {r.id: r for r in rows}
    if len(indexed) != len(rows) or set(outcomes) != set(indexed):
        raise ValueError("catalogue-v0")
    scores = {}
    for row in rows:
        branches = outcomes[row.id]
        if set(branches) != ({"B0", "B1"} if row.twin else {"B0"}):
            raise ValueError(row.id)
        for branch in sorted(branches):
            outcome = branches[branch]
            score, failure = outcome.get("score_milli"), outcome.get("failure_class")
            if (not {"score_milli", "failure_class"} <= outcome.keys()
                    or (score is None) != (failure in NONRESULTS)
                    or score is not None and (type(score) is not int or not -1000 <= score <= 1000)):
                raise ValueError(row.id)
        scores[row.id] = twin_min(branches["B0"], branches["B1"]) if row.twin else branches["B0"]["score_milli"]
    relations = []
    for row in sorted(rows, key=lambda r: r.id):
        if row.test == "MFT":
            continue
        if row.base not in indexed:
            raise ValueError(row.id)
        score, base_score = scores[row.id], scores[row.base]
        if row.test == "INV" and row.confounded:
            status = "confounded"
        elif score is None or base_score is None:
            status = "unscored"
        elif row.test == "INV":
            a, b = outcomes[row.id], outcomes[row.base]
            holds = set(a) == set(b) and all(
                (a[k]["failure_class"], a[k]["score_milli"]) == (b[k]["failure_class"], b[k]["score_milli"])
                for k in sorted(a))
            status = "holds" if holds else "flagged"
        else:
            status = "flagged" if score > base_score else "holds"
        relations.append(Relation(row.id, row.base, row.test, row.vary, score, base_score, status, row.lever_delta))
    return Report(relations)
