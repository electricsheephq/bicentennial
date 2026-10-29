"""Small, synthetic B0 builds; no generation, models, or real-stream measurements."""

import math
import random
from dataclasses import FrozenInstanceError
from fractions import Fraction
from types import SimpleNamespace

import pytest

from bicentennial.filters import salience as gate


def event(text, gold, *, seq=0, session="session", **fields):
    values = dict(event_id=f"{session}-{seq}", session_id=session, seq=seq,
                  text=text, gold_critical=gold, kind="note", actor="principal", channel="chat")
    return SimpleNamespace(**(values | fields))


def balanced():
    streams = {}
    for life in range(6):
        streams[f"life-{life}"] = [
            event(text, gold, seq=index, session=f"session-{int(gold)}",
                  kind=("note", "tool")[index % 2], actor=("agent", "principal")[index % 2],
                  channel=("chat", "mail")[index % 2])
            for gold in (False, True)
            for index, text in enumerate(("a", "AA 2!", "red blue", ""))
        ]
    return streams


def principals(streams):
    return {life: "principal" for life in streams}


@pytest.mark.parametrize("reverse", [False, True])
def test_length_leak(reverse):
    streams = {f"life-{life}": [
        event("go go go go " if gold != reverse else "go go ", gold,
              session=f"session-{int(gold)}", seq=seq)
        for gold in (False, True) for seq in range(2)
    ] for life in range(5)}
    report = gate.salience(streams, principals(streams))
    statistics = dict(report.feature_statistics)
    assert report.verdict == "FAIL"
    assert not report.passed
    assert statistics["chars"] == statistics["words"] == Fraction(1)
    assert report.classifier_statistic == Fraction(1)
    assert report.worst_feature == "chars"  # lexical tie break, including classifier
    assert report.worst_statistic == Fraction(1)
    assert report.reasons == ()
    assert (report.gold_critical_count, report.other_count) == (10, 10)


def test_balanced():
    streams = balanced()
    report = gate.salience(streams, principals(streams))
    assert report.verdict == "PASS"
    assert report.passed
    assert all(value == Fraction(1, 2) for _, value in report.feature_statistics)
    assert report.classifier_statistic == Fraction(1, 2)
    assert report.worst_statistic == Fraction(1, 2)
    assert report.reasons == ()
    assert (report.gold_critical_count, report.other_count) == (24, 24)


def test_exact_auc_with_tie():
    # Positives 1,3,4 beat respectively 1, 2.5, 3 of negatives 0,2,3,5.
    scores = [1, 3, 4, 0, 2, 3, 5]
    labels = [True, True, True, False, False, False, False]
    assert gate.rank_auc(scores, labels) == Fraction(13, 24)
    assert gate.rank_auc([-score for score in scores], labels) == Fraction(11, 24)
    assert gate.rank_auc([Fraction(score, 7) for score in scores], labels) == Fraction(13, 24)
    assert gate.rank_auc([0] * 7, labels) == Fraction(1, 2)
    # Exercise the report's direction-independent statistic on the same 3-v-4 population.
    for direction in (1, -1):
        events = [event("x" * (6 + direction * score), label, session=f"s-{index}")
                  for index, (score, label) in enumerate(zip(scores, labels, strict=True))]
        report = gate.salience({"life": events}, {"life": "principal"})
        assert dict(report.feature_statistics)["chars"] == Fraction(13, 24)


def test_auc_invalid_or_empty_inputs():
    assert gate.rank_auc([], []) is None
    assert gate.rank_auc([1, 2], [True, True]) is None
    assert gate.rank_auc([1, 2], [False, False]) is None
    with pytest.raises(ValueError, match="same length"):
        gate.rank_auc([1], [])


@pytest.mark.parametrize("gold", [False, True])
def test_empty_class(gold):
    report = gate.salience({"life-a": [event("a", gold)], "life-b": [event("b", gold)]},
                           {"life-a": "principal", "life-b": "principal"})
    assert report.verdict == "UNDEFINED"
    assert not report.passed
    assert report.reasons == ("empty_class",)
    assert all(value is None for _, value in report.feature_statistics)
    assert report.classifier_statistic is None
    assert report.worst_feature is report.worst_statistic is None
    assert (report.gold_critical_count, report.other_count) == ((2, 0) if gold else (0, 2))


@pytest.mark.parametrize("streams", [{}, {"life": []}])
def test_empty_build(streams):
    report = gate.salience(streams, principals(streams))
    assert report.verdict == "UNDEFINED"
    assert not report.passed
    assert report.reasons == ("empty_class", "too_few_lives")
    assert report.classifier_statistic is None
    assert (report.gold_critical_count, report.other_count) == (0, 0)


def test_single_life_still_reports_features():
    report = gate.salience({"only": balanced()["life-0"]}, {"only": "principal"})
    assert report.verdict == "UNDEFINED"
    assert not report.passed
    assert report.reasons == ("too_few_lives",)
    assert report.classifier_statistic is None
    assert all(value == Fraction(1, 2) for _, value in report.feature_statistics)


def test_training_fold_one_class():
    report = gate.salience({"a": [event("a", False)], "b": [event("bb", True)]},
                           {"a": "principal", "b": "principal"})
    assert report.verdict == "UNDEFINED"
    assert not report.passed
    assert report.reasons == ("fold_one_class",)
    assert report.classifier_statistic is None
    assert dict(report.feature_statistics)["chars"] == Fraction(1)
    assert (report.gold_critical_count, report.other_count) == (1, 1)


def test_exact_feature_list():
    assert gate.FEATURES == (
        "chars", "words", "digit_share", "uppercase_share", "punctuation", "position",
        "actor_is_principal", "kind", "channel",
    )
    streams = balanced()
    assert gate.salience(streams, principals(streams)).feature_names == (
        "chars", "words", "digit_share", "uppercase_share", "punctuation", "position",
        "actor_is_principal", "kind=note", "kind=tool", "channel=chat", "channel=mail",
    )


def test_speaker_role_leak_across_life_specific_ids():
    principal_ids = {f"life-{index}": f"entity-{2 * index}" for index in range(10)}
    streams = {life: [
        event("x", gold, seq=seq, session=f"s-{int(gold)}",
              actor=f"entity-{2 * index + 1}" if gold else principal_id)
        for gold in (False, True) for seq in range(2)
    ] for index, (life, principal_id) in enumerate(principal_ids.items())}
    report = gate.salience(streams, principal_ids)
    assert report.verdict == "FAIL"
    assert report.reasons == ()
    assert dict(report.feature_statistics)["actor_is_principal"] == Fraction(1)
    assert report.classifier_statistic == Fraction(1)
    assert (report.gold_critical_count, report.other_count) == (20, 20)
    actor_ids = {item.actor for events in streams.values() for item in events}
    assert all(actor_id not in name for actor_id in actor_ids for name in report.feature_names)
    names, rows = gate._population(streams, principal_ids)
    role_column = names.index("actor_is_principal")
    assert all(values[role_column] == int(not gold) for _, values, gold in rows)
    shuffled = {life: list(reversed(streams[life])) for life in reversed(streams)}
    assert gate.salience(shuffled, dict(reversed(list(principal_ids.items())))) == report
    # Arbitrary per-life id renaming preserves the role and every statistic.
    for events in streams.values():
        for item in events:
            item.actor = f"renamed-{item.actor}"
    renamed = {life: f"renamed-{actor_id}" for life, actor_id in principal_ids.items()}
    assert gate.salience(streams, renamed) == report


@pytest.mark.parametrize("events", [[], [event("x", False)]])
def test_missing_principal_raises(events):
    with pytest.raises(ValueError, match="missing principals for lives: missing"):
        gate.salience({"known": [], "missing": events}, {"known": "principal"})


def test_metadata_never_becomes_a_feature():
    streams = balanced()
    original = gate.salience(streams, principals(streams))
    for events in streams.values():
        for item in events:
            marker = "GOLD" * 20 if item.gold_critical else "other"
            item.event_id = f"{marker}-{item.seq}"
            item.session_id = f"{marker}-session"
            item.seq = 100 + 7 * item.seq  # rank, rather than numeric seq, is the feature
            item.render = dict(lane=marker, template_id=marker, phrase_id=marker, voice=marker)
            item.fact_ids = [marker]
            item.tool = dict(secret=marker)
            item.call_id = marker
            item.turn_key = marker
            item.sha256 = marker
            item.expected_result_sha256 = marker
            item.canary = marker
            item.visibility = marker
            item.audience = [marker]
            item.t_sim = 123456 if item.gold_critical else 0
            item.tz = marker
            item.payload = dict(secret=marker)
    # Mapping events and attribute events must have exactly the same interpretation.
    modified = gate.salience({life: [vars(item).copy() for item in events]
                              for life, events in streams.items()}, principals(streams))
    assert modified == original
    assert modified.verdict == "PASS"


def test_exact_surface_features_and_session_rank():
    streams = {"b": [event("ÉA ٢，_", True, seq=90), event("", False, seq=40),
                     event(None, False, session="other", seq=100)],
               "a": [event("x", True, seq=900)]}
    names, rows = gate._population(streams, principals(streams))
    assert names[:7] == gate.FEATURES[:7]
    assert rows == [
        ("a", (1, 1, Fraction(0), Fraction(0), 0, 0, 1, 1, 1), True),
        ("b", (0, 0, Fraction(0), Fraction(0), 0, 0, 1, 1, 1), False),
        ("b", (0, 0, Fraction(0), Fraction(0), 0, 0, 1, 1, 1), False),
        ("b", (6, 3, Fraction(1, 6), Fraction(1, 3), 2, 1, 1, 1, 1), True),
    ]


def test_threshold_is_inclusive_and_classifier_gates(monkeypatch):
    streams = {life: [event(text, gold, session=f"s-{index}")
                      for index, (text, gold) in enumerate([
                          ("a", True), ("a", True), ("aaa", True),
                          ("aaa", True), ("aaa", True), ("aa", False)])]
               for life in ("a", "b")}
    monkeypatch.setattr(gate, "_classifier", lambda *args: (Fraction(3, 5), ()))
    report = gate.salience(streams, principals(streams))
    assert dict(report.feature_statistics)["chars"] == Fraction(3, 5)
    assert report.verdict == "PASS"
    monkeypatch.setattr(gate, "_classifier", lambda *args: (Fraction(61, 100), ()))
    report = gate.salience(streams, principals(streams))
    assert report.verdict == "FAIL"
    assert report.worst_feature == "classifier"
    assert report.worst_statistic == Fraction(61, 100)


def test_classifier_constants_and_training_only_scaling():
    assert (gate.MAX_FOLDS, gate.GRADIENT_STEPS, gate.LEARNING_RATE, gate.L2) == (5, 500, 0.1, 1e-3)
    assert gate.THRESHOLD == Fraction(3, 5)
    # Constant in training means dropped, even when held-out values are extreme.
    assert gate._fit_predict([(10.0,), (10.0,)], [False, True],
                             [(-1000.0,), (1000.0,)]) == (0.0, 0.0)
    # Changing other held-out values must not affect training or scaling.
    middle = gate._fit_predict([(0.0,), (2.0,)], [False, True], [(1.0,)])
    expanded = gate._fit_predict([(0.0,), (2.0,)], [False, True],
                                [(1.0,), (1000.0,), (-1.0,)])
    assert middle == pytest.approx((0.0,), abs=1e-12)
    assert expanded[0] == middle[0]
    assert expanded[1] > 0 > expanded[2]


@pytest.mark.parametrize("steps,tolerance", [(1, 1e-12), (2, 1e-9)])
def test_fit_predict_golden(monkeypatch, steps, tolerance):
    monkeypatch.setattr(gate, "GRADIENT_STEPS", steps)
    # Training mean/SD are both 1: train becomes (-1, +1), held-out (0, 2).
    # First gradient is -1/2; the next is -sigmoid(-0.05) + L2 * 0.05.
    weight = 0.05
    if steps == 2:
        weight += 0.1 / (1 + math.exp(0.05)) - 0.1 * gate.L2 * 0.05
    logits = gate._fit_predict([(0.0,), (2.0,)], [False, True], [(1.0,), (3.0,)])
    assert logits == pytest.approx((0.0, 2 * weight), rel=0, abs=tolerance)


@pytest.mark.parametrize("steps,tolerance", [(1, 1e-12), (2, 1e-9)])
def test_fit_predict_bias_is_unpenalised(monkeypatch, steps, tolerance):
    monkeypatch.setattr(gate, "GRADIENT_STEPS", steps)
    # An asymmetric fixture moves the bias. Step 1's errors (1/2, -1/2, -1/2) give
    # a bias gradient of -1/6, so the bias is 1/60. The logits are then -0.05 and
    # +0.05, so step 2's bias gradient is -sigmoid(-0.05)/3, with no L2 term. A
    # held-out row at the training mean standardises to 0 and reads the bias alone.
    bias = 1 / 60
    if steps == 2:
        bias += 0.1 / (1 + math.exp(0.05)) / 3
    logits = gate._fit_predict([(0.0,), (2.0,), (2.0,)], [False, True, True], [(4 / 3,)])
    assert logits == pytest.approx((bias,), rel=0, abs=tolerance)


def test_folds_by_sorted_life_and_sorted_features(monkeypatch):
    streams = {f"life-{index}": [event("x" * (index + 1), gold, session=f"s-{int(gold)}")
                                for gold in (False, True)] for index in reversed(range(7))}
    calls = []
    char_column = sorted(("chars", "words", "digit_share", "uppercase_share", "punctuation",
                          "position", "actor_is_principal", "kind=note", "channel=chat")).index("chars")

    def predict(train, labels, held_out):
        calls.append((tuple(row[char_column] for row in train), tuple(labels),
                      tuple(row[char_column] for row in held_out)))
        return tuple(row[char_column] for row in held_out)

    monkeypatch.setattr(gate, "_fit_predict", predict)
    report = gate.salience(streams, principals(streams))
    assert report.classifier_statistic == Fraction(1, 2)
    assert len(calls) == 5
    for fold, (train, labels, held_out) in enumerate(calls):
        assert held_out == tuple(float(i + 1) for i in range(7) if i % 5 == fold for _ in range(2))
        assert train == tuple(float(i + 1) for i in range(7) if i % 5 != fold for _ in range(2))
        assert labels == (False, True) * (len(train) // 2)
    original_calls = calls.copy()
    shuffled = {life: list(reversed(streams[life])) for life in reversed(streams)}
    assert gate.salience(shuffled, principals(shuffled)) == report
    assert calls[5:] == original_calls


@pytest.mark.parametrize("direction", [1, -1])
def test_out_of_fold_auc_reads_both_directions(monkeypatch, direction):
    streams = {life: [event("a", False, session="s-0"), event("aaa", True, session="s-1")]
               for life in ("a", "b")}
    names, _ = gate._population(streams, principals(streams))
    char_column = sorted(names).index("chars")

    def predict(train, labels, held_out):
        return tuple(direction * row[char_column] for row in held_out)

    monkeypatch.setattr(gate, "_fit_predict", predict)
    assert gate.salience(streams, principals(streams)).classifier_statistic == Fraction(1)


def test_determinism_and_frozen_result():
    streams = balanced()
    first = gate.salience(streams, principals(streams))
    assert gate.salience(streams, principals(streams)) == first
    generator = random.Random(241)
    lives = list(streams)
    generator.shuffle(lives)
    shuffled = {life: list(streams[life]) for life in lives}
    for events in shuffled.values():
        generator.shuffle(events)
    assert gate.salience(shuffled, principals(shuffled)) == first
    with pytest.raises(FrozenInstanceError):
        first.verdict = "FAIL"
    assert isinstance(first.feature_statistics, tuple)
    assert isinstance(first.reasons, tuple)
