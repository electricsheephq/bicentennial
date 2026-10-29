"""Hand-computed event deletion examples; no generated-world dependencies."""

from collections import Counter

import pytest

from bicentennial.repro.ddmin import Constraints, ddmin, is_closed

IDS = tuple(f"e{n}" for n in range(1, 41))


def pair(kept, attempt):
    return "A" if {"e7", "e19"} <= set(kept) else None


def test_pair_of_forty():
    result = ddmin(IDS, pair, target="A")
    assert result.kept == ("e7", "e19")
    assert result.exhausted is False
    assert result.failures == result.runs == 3


@pytest.mark.parametrize("edge", ["e1", "e40"])
def test_single_edges(edge):
    result = ddmin(IDS, lambda kept, attempt: "A" if edge in kept else None, target="A")
    assert result.kept == (edge,)
    assert result.failures == result.runs == 3
    assert result.exhausted is False


def test_group_atomic():
    constraints = Constraints(groups=(frozenset(("e7", "e8")),))

    def oracle(kept, attempt):
        assert ("e7" in kept) == ("e8" in kept)
        return pair(kept, attempt)

    result = ddmin(IDS, oracle, target="A", constraints=constraints)
    assert result.kept == ("e7", "e8", "e19")
    assert result.exhausted is False


def test_lineage_requires():
    constraints = Constraints(requires=(("e19", frozenset(("e3",))),))
    seen = []

    def oracle(kept, attempt):
        seen.append(kept)
        return pair(kept, attempt)

    result = ddmin(IDS, oracle, target="A", constraints=constraints)
    assert result.kept == ("e3", "e7", "e19")
    assert seen[0] == IDS
    assert all("e19" not in kept or "e3" in kept for kept in seen)


def test_two_requirement_sets_both_hold():
    constraints = Constraints(requires=(("e19", frozenset(("e3",))),
                                        ("e19", frozenset(("e5",)))))
    result = ddmin(IDS, pair, target="A", constraints=constraints)
    assert result.kept == ("e3", "e5", "e7", "e19")
    assert is_closed({"e3", "e7", "e19"}, constraints) is False
    assert is_closed(result.kept, constraints) is True


def test_other_signature_is_a_pass():
    def oracle(kept, attempt):
        if {"e7", "e19"} <= set(kept):
            return "A"
        return "B" if "e7" in kept else None

    result = ddmin(IDS, oracle, target="A")
    assert result.kept == ("e7", "e19")
    assert result.failures == 3


def test_flaky_two_of_three():
    def flaky(kept, attempt):
        return pair(kept, attempt) if attempt % 3 != 2 else None

    result = ddmin(IDS, flaky, target="A")
    assert result.kept == ("e7", "e19")
    assert (result.failures, result.runs) == (2, 3)
    assert result.exhausted is False
    with pytest.raises(ValueError, match="full schedule"):
        ddmin(IDS, flaky, target="A", threshold=3)


def test_never_fails_raises():
    with pytest.raises(ValueError, match="full schedule"):
        ddmin(IDS, lambda kept, attempt: None, target="A")


def test_budget():
    calls = []

    def oracle(kept, attempt):
        calls.append((kept, attempt))
        return pair(kept, attempt)

    result = ddmin(IDS, oracle, target="A", max_tests=3)
    # Full -> first half (fails) -> first quarter (passes); fourth set is refused.
    assert calls == [(kept, attempt) for kept in (IDS, IDS[:20], IDS[:10])
                     for attempt in range(3)]
    assert result.kept == IDS[:20]
    assert result.tests == 3
    assert result.exhausted is True
    assert result.failures == result.runs == 3
    assert pair(result.kept, 0) == "A"


def test_memoised():
    calls = Counter()

    def oracle(kept, attempt):
        calls[kept, attempt] += 1
        return pair(kept, attempt)

    result = ddmin(IDS, oracle, target="A")
    assert result.kept == ("e7", "e19")
    assert all(count == 1 for count in calls.values())
    assert len({kept for kept, attempt in calls}) == result.tests
    assert len(calls) == result.tests * 3
    assert {attempt for kept, attempt in calls} == {0, 1, 2}


@pytest.mark.parametrize("case", [
    "duplicates", "empty-id", "empty-schedule", "not-sequence", "overlap", "empty-group",
    "unknown-group", "unknown-derivative", "unknown-source", "empty-sources", "self-source",
    "threshold-zero", "threshold-high", "repeats-zero", "budget-zero", "target-empty",
    "bool-repeats", "bool-threshold", "bool-budget",
])
def test_invalid_inputs(case):
    ids, options = IDS, {"target": "A"}
    with pytest.raises(ValueError):
        if case == "duplicates":
            ids = ("e1", "e1")
        elif case == "empty-id":
            ids = ("",)
        elif case == "empty-schedule":
            ids = ()
        elif case == "not-sequence":
            ids = "e1"
        elif case == "overlap":
            options["constraints"] = Constraints(groups=(frozenset(("e1", "e2")),
                                                          frozenset(("e2", "e3"))))
        elif case == "empty-group":
            options["constraints"] = Constraints(groups=(frozenset(),))
        elif case == "unknown-group":
            options["constraints"] = Constraints(groups=(frozenset(("e41",)),))
        elif case in ("unknown-derivative", "unknown-source", "empty-sources", "self-source"):
            derivative = "e41" if case == "unknown-derivative" else "e19"
            sources = {"unknown-source": ("e41",), "empty-sources": (),
                       "self-source": ("e19",)}.get(case, ("e3",))
            options["constraints"] = Constraints(requires=((derivative, frozenset(sources)),))
        else:
            key, value = {
                "threshold-zero": ("threshold", 0), "threshold-high": ("threshold", 4),
                "repeats-zero": ("repeats", 0), "budget-zero": ("max_tests", 0),
                "target-empty": ("target", ""), "bool-repeats": ("repeats", True),
                "bool-threshold": ("threshold", True), "bool-budget": ("max_tests", True),
            }[case]
            options[key] = value
        ddmin(ids, pair, **options)


def test_closure_cascades_through_groups():
    constraints = Constraints(groups=(frozenset(("e7", "e8")),), requires=(
        ("e7", frozenset(("e3",))), ("e19", frozenset(("e8",))),
        ("e3", frozenset(("e1",))),
    ))

    def oracle(kept, attempt):
        assert is_closed(kept, constraints)
        return pair(kept, attempt)

    result = ddmin(IDS, oracle, target="A", constraints=constraints)
    assert result.kept == ("e1", "e3", "e7", "e8", "e19")
    assert is_closed((), constraints) is True
    assert is_closed({"e1", "e3", "e7"}, constraints) is False


def test_source_alternatives():
    constraints = Constraints(requires=(("e19", frozenset(("e3", "e5"))),))
    assert is_closed({"e3", "e19"}, constraints) is True
    assert is_closed({"e5", "e19"}, constraints) is True
    assert is_closed({"e19"}, constraints) is False


def test_subset_complement_order():
    calls = []

    def oracle(kept, attempt):
        calls.append(kept)
        return "A" if {"e2", "e4"} <= set(kept) else None

    result = ddmin(IDS[:5], oracle, target="A", repeats=1)
    # n=2 splits 3+2. After no reduction, n=4 splits 2+1+1+1.
    # Repeated complements are memo hits; remove e3 is the first success.
    assert calls[:9] == [IDS[:5], IDS[:3], IDS[3:5], IDS[:2], ("e3",),
                         ("e4",), ("e5",), ("e3", "e4", "e5"),
                         ("e1", "e2", "e4", "e5")]
    assert result.kept == ("e2", "e4")
    assert result.failures == result.runs == 1


def test_exact_budget_completion_is_not_exhaustion():
    calls = []

    def oracle(kept, attempt):
        calls.append((kept, attempt))
        return "A"

    result = ddmin(("e1",), oracle, target="A", max_tests=1)
    assert result.kept == ("e1",)
    assert result.tests == 1
    assert result.exhausted is False
    assert calls == [(("e1",), 0), (("e1",), 1), (("e1",), 2)]


def test_empty_candidates_are_not_tested():
    constraints = Constraints(requires=(("e1", frozenset(("e2",))),
                                        ("e2", frozenset(("e1",)))))
    calls = []

    def oracle(kept, attempt):
        calls.append(kept)
        return "A"

    result = ddmin(("e1", "e2"), oracle, target="A", constraints=constraints, max_tests=1)
    assert result.kept == ("e1", "e2")
    assert result.tests == 1
    assert result.exhausted is False
    assert calls == [("e1", "e2")] * 3
