"""Build-level B0 salience gate (PREREG-v0.4 §4; issue #241, choice 9).

Call ``salience`` with exactly one B0 stream and its principal's actor id per
life. Branch selection belongs to the caller. No stream, pack, or item record
is changed by this module.
"""

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, Protocol

FEATURES = ("chars", "words", "digit_share", "uppercase_share", "punctuation",
            "position", "actor_is_principal", "kind", "channel")
THRESHOLD = Fraction(3, 5)
MAX_FOLDS = 5
GRADIENT_STEPS = 500
LEARNING_RATE = 0.1
L2 = 1e-3


class _Event(Protocol):
    event_id: str
    session_id: str
    seq: int
    kind: str
    actor: str
    channel: str
    gold_critical: bool
    text: str | None


type Event = _Event | Mapping[str, object]
type Number = int | Fraction | float


@dataclass(frozen=True)
class SalienceReport:
    """Immutable statistics; None denotes an undefined AUC, never a pass.

    Statistics are direction-independent. Worst ties use the smallest name;
    ``classifier`` participates in the worst statistic. Counts cover all events.
    """

    verdict: Literal["PASS", "FAIL", "UNDEFINED"]
    feature_statistics: tuple[tuple[str, Fraction | None], ...]
    classifier_statistic: Fraction | None
    worst_feature: str | None
    worst_statistic: Fraction | None
    reasons: tuple[str, ...]
    gold_critical_count: int
    other_count: int

    @property
    def feature_names(self) -> tuple[str, ...]:
        """Expanded names, including data-sorted one-hot categories."""
        return tuple(name for name, _ in self.feature_statistics)

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"


def _field(event: Event, name: str):
    return event.get(name) if isinstance(event, Mapping) else getattr(event, name)


def _population(streams: Mapping[str, Sequence[Event]], principals: Mapping[str, str]):
    categories = {name: sorted({_field(event, name) for events in streams.values()
                                for event in events}) for name in FEATURES[7:]}
    names = FEATURES[:7] + tuple(f"{name}={value}" for name in FEATURES[7:]
                                 for value in categories[name])
    rows = []
    for life in sorted(streams):
        # IDs establish grouping/order and principal identity, never features.
        # Valid streams have unique seq within a session; event_id breaks ties.
        events = sorted(streams[life], key=lambda e: (
            _field(e, "session_id"), _field(e, "seq"), _field(e, "event_id")))
        positions = {}
        for event in events:
            session = _field(event, "session_id")
            position = positions.get(session, 0)
            positions[session] = position + 1
            # Payload-only events have no text; do not inspect their payload.
            text = _field(event, "text") or ""
            size = len(text)
            values = (size, len(re.findall(r"\w+", text)),
                      Fraction(sum(c.isdigit() for c in text), size) if size else Fraction(0),
                      Fraction(sum(c.isupper() for c in text), size) if size else Fraction(0),
                      sum(unicodedata.category(c).startswith("P") for c in text), position,
                      int(_field(event, "actor") == principals[life]))
            values += tuple(int(_field(event, name) == value) for name in FEATURES[7:]
                            for value in categories[name])
            rows.append((life, values, bool(_field(event, "gold_critical"))))
    return names, rows


def rank_auc(scores: Sequence[Number], labels: Sequence[bool]) -> Fraction | None:
    """Mann–Whitney AUC, with exact half credit for ties; None if a class is empty."""
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have the same length")
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(scores, labels, strict=True), key=lambda row: row[0])
    wins_twice = below = start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        positive_ties = sum(label for _, label in ordered[start:end])
        negative_ties = end - start - positive_ties
        wins_twice += positive_ties * (2 * below + negative_ties)
        below += negative_ties
        start = end
    return Fraction(wins_twice, 2 * positives * negatives)


def _either_direction(auc: Fraction | None) -> Fraction | None:
    return None if auc is None else max(auc, 1 - auc)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


def _fit_predict(train, labels, held_out) -> tuple[float, ...]:
    """Training-only population SD; constant columns dropped; unpenalised bias.

    Minimise mean logistic loss + L2/2 * sum(weight**2). All parameters start
    at zero and update simultaneously. Return logits as monotone rank scores,
    avoiding sigmoid saturation turning distinct scores into artificial ties.
    Columns and rows arrive in canonical order from ``_classifier``.
    """
    count = len(train)
    scaling = []
    for column in range(len(train[0])):
        values = [row[column] for row in train]
        if all(value == values[0] for value in values):
            continue
        mean = sum(values) / count
        sd = math.sqrt(sum((value - mean) ** 2 for value in values) / count)
        scaling.append((column, mean, sd))

    def standardise(rows):
        return [tuple((row[column] - mean) / sd for column, mean, sd in scaling)
                for row in rows]

    training, testing = standardise(train), standardise(held_out)
    # Cache columns in the same canonical row order for gradient products.
    training_columns = tuple(zip(*training, strict=True))
    weights, bias = [0.0] * len(scaling), 0.0
    for _ in range(GRADIENT_STEPS):
        errors = [_sigmoid(bias + math.sumprod(weights, row)) - label
                  for row, label in zip(training, labels, strict=True)]
        gradients = [math.sumprod(errors, column) / count + L2 * weight
                     for weight, column in zip(weights, training_columns, strict=True)]
        bias -= LEARNING_RATE * sum(errors) / count
        weights = [weight - LEARNING_RATE * gradient
                   for weight, gradient in zip(weights, gradients, strict=True)]
    return tuple(bias + math.sumprod(weights, row) for row in testing)


def _classifier(names, rows, lives) -> tuple[Fraction | None, tuple[str, ...]]:
    if len(lives) < 2:
        return None, ("too_few_lives",)
    k = min(MAX_FOLDS, len(lives))
    folds = {life: index % k for index, life in enumerate(lives)}
    columns = sorted(range(len(names)), key=lambda index: names[index])
    vectors = [tuple(float(values[index]) for index in columns) for _, values, _ in rows]
    wins = pairs = 0
    for fold in range(k):
        training = [index for index, row in enumerate(rows) if folds[row[0]] != fold]
        held_out = [index for index, row in enumerate(rows) if folds[row[0]] == fold]
        labels = [rows[index][2] for index in training]
        if not labels or all(labels) or not any(labels):
            return None, ("fold_one_class",)
        predictions = _fit_predict([vectors[index] for index in training], labels,
                                   [vectors[index] for index in held_out])
        # Pair events only within a fold: fold models trained on different
        # prevalence have different biases, so pooled logits would rank folds.
        held_out_labels = [rows[index][2] for index in held_out]
        auc = rank_auc(predictions, held_out_labels)
        if auc is not None:
            positives = sum(held_out_labels)
            fold_pairs = positives * (len(held_out_labels) - positives)
            wins += auc * fold_pairs
            pairs += fold_pairs
    if not pairs:
        return None, ("held_out_one_class",)
    return _either_direction(Fraction(wins, pairs)), ()


def salience(streams: Mapping[str, Sequence[Event]],
             principals: Mapping[str, str]) -> SalienceReport:
    r"""Measure one build's B0 streams, failing closed on undefined statistics.

    Text uses Unicode ``\w+`` words, ``isdigit``/``isupper`` character shares,
    and Unicode P-category punctuation. Empty/absent text has zero shares.
    Actors become a principal-role indicator using each life's principal id;
    a missing principal mapping raises ValueError, including for empty lives.
    Folds assign sorted lives by index modulo min(5, number of lives). The
    classifier AUC pools Mann–Whitney pairs within each held-out fold only.
    """
    missing = sorted(set(streams) - principals.keys())
    if missing:
        raise ValueError(f"missing principals for lives: {', '.join(missing)}")
    names, rows = _population(streams, principals)
    labels = [row[2] for row in rows]
    positives = sum(labels)
    statistics = tuple((name, _either_direction(rank_auc(
        [row[1][column] for row in rows], labels))) for column, name in enumerate(names))
    reasons = []
    classifier = None
    if not positives or positives == len(rows):
        reasons.append("empty_class")
        if len(streams) < 2:
            reasons.append("too_few_lives")
    else:
        classifier, classifier_reasons = _classifier(names, rows, sorted(streams))
        reasons.extend(classifier_reasons)
    defined = [(name, value) for name, value in (*statistics, ("classifier", classifier))
               if value is not None]
    worst = max((value for _, value in defined), default=None)
    worst_feature = min((name for name, value in defined if value == worst), default=None)
    verdict = "UNDEFINED" if reasons else "FAIL" if worst > THRESHOLD else "PASS"
    return SalienceReport(verdict, statistics, classifier, worst_feature, worst,
                          tuple(reasons), positives, len(rows) - positives)
