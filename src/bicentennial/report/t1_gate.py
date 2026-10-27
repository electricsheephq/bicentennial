"""Pure T1 gating over caller-supplied outcomes, invariants and corpus results."""

import copy
import hashlib
import json
from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.contracts.run import validate

INVARIANTS = ("INV-VERB", "INV-NEW", "INV-PAIR", "INV-FORGET")
GATED_T1 = INVARIANTS[:3]
INV_STATUSES = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_EXERCISED", "INFRA_FAILURE")
VERDICT_KEYS = ("failed", "inconclusive", "infra", "invariant", "members", "reasons", "status",
                "uninformative")
CORPUS_STATUSES = ("PASS", "FAIL", "INFRA_FAILURE")
CORPUS_REASONS = ("", "mismatch", "system_failure", "stale_case", "infra")
CORPUS_KEYS = ("case_id", "first_diff", "reason", "status")
GATE_VERDICTS = ("PASS", "CONFORMANCE_PASS", "FAIL", "INVALID", "BLOCKED")
EXIT = {"PASS": 0, "CONFORMANCE_PASS": 0, "FAIL": 1, "INVALID": 1, "BLOCKED": 2}
ARMS = ("system", "wiped")
ACCEPTED = ("PASS", "CONFORMANCE_PASS")
REASONS = ("baseline_absent", "corpus_fail", "corpus_infra", "invariant_fail", "invariant_infra",
           "regression", "run_status", "wiped_pass", "wiped_uninformative")


class BaselineMismatch(ValueError):
    def __init__(self, field):
        self.field = field
        super().__init__(f"baseline mismatch: {field}")


@dataclass(frozen=True)
class GateResult:
    arm: str
    verdict: str
    exit_code: int
    run_status: str
    baseline_sha256: str | None
    invariants: tuple[tuple[str, str], ...]
    regressions: tuple[str, ...]
    excluded: tuple[str, ...]
    corpus_failed: tuple[str, ...]
    blocked: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_obj(self):
        return json.loads(canon({k: getattr(self, k) for k in self.__dataclass_fields__}))


def check_baseline(baseline: bytes, *, system: str, pins: dict) -> dict:
    """Refuse noncanonical, invalid or incompatible accepted baseline cards."""
    try:
        card = json.loads(baseline)
        if type(baseline) is not bytes or canon(card) != baseline:
            raise ValueError("baseline must be canonical bytes")
    except (TypeError, UnicodeError) as error:
        raise ValueError("invalid baseline bytes") from error
    validate("card_ring0", card)
    for field, matches in (("tier", card["tier"] == "T1"),
                           ("gate_verdict", card["gate_verdict"] in ACCEPTED),
                           ("system", card["system"] == system),
                           ("pins.pack_hash", card["pins"]["pack_hash"] == pins["pack_hash"]),
                           ("pins.seed_hash", card["pins"]["seed_hash"] == pins["seed_hash"])):
        if not matches:
            raise BaselineMismatch(field)
    return card


def _rows(values, keys):
    rows = []
    try:
        for value in values:
            row = value if isinstance(value, dict) else value.to_obj()
            if not isinstance(row, dict) or sorted(row) != list(keys):
                raise ValueError("unexpected result keys")
            canon(row)
            rows.append(row)
    except (TypeError, AttributeError) as error:
        raise ValueError("invalid result objects") from error
    return rows


def t1_gate(card, baseline, corpus, *, invariants, crossing, arm="system") -> GateResult:
    """Evaluate both arms identically, applying the control condition to the system."""
    if not isinstance(card, dict) or "gate_verdict" in card or card.get("tier") != "T1":
        raise ValueError("a provisional T1 card is required")
    validate("card_ring0", dict(copy.deepcopy(card), gate_verdict="INVALID"))
    if arm not in ARMS:
        raise ValueError("unknown arm")
    current = {b["bundle_id"]: b for b in card["bundles"]}
    try:
        crossing = tuple(crossing)
        if not crossing or any(type(i) is not str or i not in current for i in crossing):
            raise ValueError("crossing requires known bundle ids")
    except TypeError as error:
        raise ValueError("crossing must be iterable") from error
    crossing = sorted(set(crossing))
    inv = _rows(invariants, VERDICT_KEYS)
    if (len(inv) != len(INVARIANTS)
            or sorted(r["invariant"] for r in inv if type(r["invariant"]) is str) != sorted(INVARIANTS)
            or any(r["status"] not in INV_STATUSES for r in inv)):
        raise ValueError("exactly one valid verdict per invariant is required")
    inv = {r["invariant"]: r["status"] for r in inv}
    if inv["INV-FORGET"] != "NOT_EXERCISED":
        raise ValueError("T1 does not exercise forgetting")
    cases = _rows(corpus, CORPUS_KEYS)
    ids = [r["case_id"] for r in cases]
    if (not cases or any(type(i) is not str or not i for i in ids)
            or len(set(ids)) != len(ids)
            or any(r["status"] not in CORPUS_STATUSES or r["reason"] not in CORPUS_REASONS
                   or r["status"] == "PASS" and (r["reason"] != "" or r["first_diff"] is not None)
                   for r in cases)):
        raise ValueError("invalid corpus results")
    reasons, blocked, regressions, excluded, failed = set(), set(), [], [], []
    for name in GATED_T1:
        if inv[name] == "INFRA_FAILURE":
            reasons.add("invariant_infra")
            blocked.add(f"invariant:{name}")
        elif inv[name] != "PASS":
            reasons.add("invariant_fail")
    if baseline is None:
        reasons.add("baseline_absent")
    else:
        previous = check_baseline(baseline, system=card["system"], pins=card["pins"])
        previous = {b["bundle_id"]: b for b in previous["bundles"]}
        if current.keys() != previous.keys():
            raise BaselineMismatch("bundles")
        for bid in crossing:
            c, b = current[bid]["score_milli"], previous[bid]["score_milli"]
            if type(c) is not int or type(b) is not int:
                excluded.append(bid)
            elif c < b:
                regressions.append(bid)
        if regressions:
            reasons.add("regression")
    for row in cases:
        if row["status"] == "FAIL":
            reasons.add("corpus_fail")
            failed.append(row["case_id"])
        elif row["status"] == "INFRA_FAILURE":
            reasons.add("corpus_infra")
            blocked.add(f"corpus:{row['case_id']}")
    if card["run_status"] != "COMPLETE":
        reasons.add("run_status")
        blocked.add(f"run_status:{card['run_status']}")
    if arm == "system":
        control = card["controls"]["wiped_store"]
        if control == "PASS":
            reasons.add("wiped_pass")
        elif control == "uninformative":
            reasons.add("wiped_uninformative")
    if "wiped_pass" in reasons:
        verdict = "INVALID"
    elif reasons & {"invariant_fail", "regression", "corpus_fail", "wiped_uninformative"}:
        verdict = "FAIL"
    elif blocked:
        verdict = "BLOCKED"
    else:
        verdict = "CONFORMANCE_PASS" if baseline is None else "PASS"
    return GateResult(arm, verdict, EXIT[verdict], "BLOCKED" if blocked else card["run_status"],
                      hashlib.sha256(baseline).hexdigest() if baseline is not None else None,
                      tuple((name, inv[name]) for name in GATED_T1),
                      *(tuple(sorted(set(v))) for v in (regressions, excluded, failed, blocked, reasons)))
