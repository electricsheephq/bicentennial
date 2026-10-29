"""Hand-built issue #241 fixtures; no generated lives or model calls."""

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass
from fractions import Fraction
from hashlib import sha256

import pytest

from bicentennial.controls import cache
from bicentennial.controls.naive_rag import idf_fixed
from bicentennial.filters import droplog
from bicentennial.filters.literal_copy import (
    idf_table,
    literal_copy,
    rare,
    tertiles,
    yields,
)


def event(eid, text):
    return dict(event_id=eid, text=text)


def stream_fixture():
    # Three distinct types: two df=1 ties above the common type's df=2.
    events = [event("plant", "Amber ORCHID beacon!"),
              event("other", "saffron silver lantern"),
              event("common-1", "common words repeat"),
              event("common-2", "common words repeat")]
    return {("life", branch): list(events) for branch in ("B0", "B1")}


def add_bundle(items, records, bid, *, prompts=("amber orchid beacon", "quiet question"),
               spans=(("plant",), ("common-1",)), life="life", track="Drift",
               template_id="copy", version=1, sample=False):
    for index, branch in enumerate(("B0", "B1")):
        iid = f"{bid}-{branch}"
        items[iid] = dict(item_id=iid, prompt=prompts[index], gold_spans=list(spans[index]),
                          track=track, options=[dict(text="amber orchid beacon")])
        records[iid] = dict(item_id=iid, bundle_id=bid, life=life, branch=branch,
                            template_id=template_id, template_version=version,
                            unfiltered_sample=sample)


@pytest.mark.parametrize("sample", [False, True])
@pytest.mark.parametrize("matching_branch", [0, 1])
def test_rare_copy_drops_either_item_and_sample_with_text_free_rows(sample, matching_branch):
    streams, items, records = stream_fixture(), {}, {}
    prompts = ["quiet question", "quiet question"]
    spans = [("common-1",), ("common-1",)]
    prompts[matching_branch] = "AMBER, orchid—beacon!"
    spans[matching_branch] = ("plant",)
    add_bundle(items, records, "copy", prompts=prompts, spans=spans, sample=sample)
    result = literal_copy(streams, items, records)
    bundle, = result.bundles
    assert bundle.dropped and bundle.reason == "literal_copy"
    assert bundle.overlap == Fraction(1)
    assert [item.overlap for item in bundle.items] == [
        Fraction(index == matching_branch) for index in range(2)]
    match, = bundle.items[matching_branch].matches
    digest = sha256(b"amber orchid beacon").hexdigest()[:16]
    assert (match.df, match.idf, match.sha256_prefix) == (1, idf_fixed(4, 1), digest)
    assert len(digest) == 16
    log = droplog.rows(result, {"copy": "Drift"})
    assert log == (
        dict(bundle_id="copy", item_id=f"copy-B{matching_branch}", track="Drift",
             template_id="copy", template_version=1, life="life", branch=f"B{matching_branch}",
             filter="literal_copy", reason="literal_copy", df=1, idf=idf_fixed(4, 1),
             sha256_prefix=digest),
        dict(bundle_id="copy", item_id_0="copy-B0", branch_0="B0", item_id_1="copy-B1",
             branch_1="B1", track="Drift", template_id="copy", template_version=1,
             life="life", filter="literal_copy", reason="overlap", overlap="1/1", tertile=1),
    )
    encoded = json.dumps(log, sort_keys=True)
    assert all(text not in encoded.lower() for text in
               ("amber", "orchid", "beacon", "quiet question", "common words repeat"))
    assert all(type(value) in (str, int) for row in log for value in row.values())


def test_common_copy_is_kept_even_at_full_overlap():
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "common", prompts=("common words repeat", "quiet question"),
               spans=(("common-1",), ("common-1",)))
    result = literal_copy(streams, items, records)
    bundle, = result.bundles
    assert not bundle.dropped and bundle.reason == ""
    assert bundle.items[0].overlap == bundle.overlap == Fraction(1)
    assert not any(item.matches for item in bundle.items)
    log = droplog.rows(result, {"common": "Drift"})
    assert len(log) == 1 and log[0]["reason"] == "overlap"
    assert log[0]["overlap"] == "1/1"


def test_idf_uses_event_documents_distinct_counts_and_rag_tokens():
    events = [event("a", "Alpha beta gamma alpha beta gamma"),
              event("b", "ALPHA, beta gamma!"), event("null", None),
              dict(event_id="missing"), event("left", "left right"),
              event("right", "end start"), event("unicode", "ÉLAN, _X １２!")]
    table = idf_table(events)
    entries = {entry.gram: entry for entry in table.entries}
    assert table.n_events == 7
    assert set(entries) == {("alpha", "beta", "gamma"), ("beta", "gamma", "alpha"),
                            ("gamma", "alpha", "beta"), ("élan", "_x", "１２")}
    assert entries[("alpha", "beta", "gamma")].df == 2
    assert entries[("alpha", "beta", "gamma")].idf == idf_fixed(7, 2)
    assert all(entry.df == 1 and entry.idf == idf_fixed(7, 1)
               for gram, entry in entries.items() if gram != ("alpha", "beta", "gamma"))
    assert rare(table) == frozenset(set(entries) - {("alpha", "beta", "gamma")})


@pytest.mark.parametrize("n_types,rare_indices", [(100, (0,)), (101, (0, 1, 2))])
def test_ceiling_cutoff_and_all_boundary_ties(n_types, rare_indices):
    # At 100 types, ceil(n/100)=1 selects df=1. At 101 it is 2, so both
    # df=2 types join it. The remaining types have df=3 (296/299 events total).
    events = [event(f"{index}-{copy}", f"g{index} x{index} z{index}")
              for index in range(n_types)
              for copy in range(1 if index == 0 else 2 if index <= 2 else 3)]
    table = idf_table(events)
    assert len(table.entries) == n_types
    assert table.n_events == 3 * n_types - 4
    assert rare(table) == frozenset((f"g{i}", f"x{i}", f"z{i}") for i in rare_indices)


def test_empty_and_short_texts_have_no_rare_triples():
    for events in ([], [event("a", None), dict(event_id="b"), event("c", "two words")]):
        table = idf_table(events)
        assert table.n_events == len(events) and table.entries == ()
        assert rare(table) == frozenset()
    assert rare(idf_table([event("one", "a b c")])) == frozenset({("a", "b", "c")})


def test_missing_and_none_evidence_text_are_empty():
    streams, items, records = stream_fixture(), {}, {}
    streams[("life", "B0")].append(event("null", None))
    streams[("life", "B1")].append(dict(event_id="missing"))
    add_bundle(items, records, "textless", spans=(("null",), ("missing",)))
    result = literal_copy(streams, items, records)
    assert not result.bundles[0].dropped
    assert all(item.overlap == Fraction(0) and item.matches == () for item in result.items)


def test_only_prompt_and_own_evidence_count_and_events_do_not_join():
    streams, items, records = stream_fixture(), {}, {}
    for branch in ("B0", "B1"):
        streams[("life", branch)].extend([event("left", "amber orchid"), event("right", "beacon")])
    add_bundle(items, records, "options", prompts=("quiet question", "quiet question"),
               spans=(("plant",), ("plant",)))
    add_bundle(items, records, "nongold", spans=(("common-1",), ("common-1",)))
    add_bundle(items, records, "split", spans=(("left", "right"), ("common-1",)))
    result = literal_copy(streams, items, records)
    assert all(not bundle.dropped for bundle in result.bundles)
    assert next(bundle for bundle in result.bundles if bundle.bundle_id == "split").overlap == 1
    # Split evidence shares all three words, but not one within-event triple.
    assert not any(item.matches for item in result.items)


@pytest.mark.parametrize("prompt_branch", [0, 1])
def test_twins_do_not_share_copy_matches_or_overlap_evidence(prompt_branch):
    streams, items, records = stream_fixture(), {}, {}
    prompts = ["quiet question", "quiet question"]
    spans = [("plant",), ("plant",)]
    prompts[prompt_branch] = "amber orchid beacon common"
    spans[prompt_branch] = ("common-1",)
    add_bundle(items, records, "isolated", prompts=prompts, spans=spans)
    assert ("amber", "orchid", "beacon") in rare(
        idf_table(streams[("life", f"B{prompt_branch}")]))
    result = literal_copy(streams, items, records)
    bundle, = result.bundles
    # The rare prompt triple is in the other twin's evidence only. Own
    # evidence shares just "common"; pooling the twins would give full overlap.
    assert not bundle.dropped and bundle.reason == ""
    assert all(item.matches == () for item in bundle.items)
    assert bundle.items[prompt_branch].overlap == Fraction(1, 4)
    assert bundle.items[1 - prompt_branch].overlap == Fraction(0)
    assert bundle.overlap == Fraction(1, 4)


def test_tables_are_scoped_to_life_and_branch_and_include_nongold_events():
    streams, items, records = stream_fixture(), {}, {}
    common_plant = [event("plant", "amber orchid beacon"),
                    event("nongold", "amber orchid beacon"),
                    event("other", "saffron silver lantern"),
                    event("common-1", "common words repeat")]
    streams[("life", "B1")] = common_plant
    for branch in ("B0", "B1"):
        streams[("other-life", branch)] = common_plant
    add_bundle(items, records, "rare-b0")
    add_bundle(items, records, "common-b1", prompts=("quiet question", "amber orchid beacon"),
               spans=(("common-1",), ("plant",)))
    add_bundle(items, records, "common-life", life="other-life")
    result = literal_copy(streams, items, records)
    assert {bundle.bundle_id: bundle.dropped for bundle in result.bundles} == {
        "rare-b0": True, "common-b1": False, "common-life": False}


def overlap_fixture():
    streams = {("life", branch): [] for branch in ("B0", "B1")}
    items, records, tracks = {}, {}, {}
    # Distinct prompt words: four on B0, two on B1. Every evidence event is
    # one word, so there are no triples and overlap alone cannot drop a pair.
    cases = [("a0", "Drift", 0, False), ("a1", "Drift", 1, False),
             ("a2", "Drift", 1, True), ("a3", "Drift", 2, False),
             ("a4", "Drift", 3, True), ("a5", "Drift", 4, False),
             ("a6", "Drift", 4, True), ("b0", "Keep", 1, False),
             ("b1", "Keep", 4, True)]
    for bid, track, count, half in reversed(cases):
        spans = [[], []]
        for index, tokens in enumerate((list("abcd")[:count], ["x"] if half else [])):
            for token in tokens:
                eid = f"{bid}-{token}"
                streams[("life", f"B{index}")].append(event(eid, token))
                spans[index].append(eid)
        add_bundle(items, records, bid, prompts=("a b c d a", "x y"), spans=spans, track=track)
        tracks[bid] = track
    return streams, items, records, tracks


def test_exact_overlaps_and_rank_tertiles_for_seven_and_two_bundles():
    streams, items, records, tracks = overlap_fixture()
    result = literal_copy(streams, items, records)
    expected = {"a0": Fraction(0), "a1": Fraction(1, 4), "a2": Fraction(1, 2),
                "a3": Fraction(1, 2), "a4": Fraction(3, 4), "a5": Fraction(1),
                "a6": Fraction(1), "b0": Fraction(1, 4), "b1": Fraction(1)}
    assert {bundle.bundle_id: bundle.overlap for bundle in result.bundles} == expected
    item_overlaps = {item.item_id: item.overlap for item in result.items}
    assert item_overlaps["a2-B0"] == Fraction(1, 4)
    assert item_overlaps["a2-B1"] == Fraction(1, 2)
    assert item_overlaps["a4-B0"] == Fraction(3, 4)
    assert all(not bundle.dropped for bundle in result.bundles)
    bins = {"a0": 1, "a1": 1, "a2": 1, "a3": 2, "a4": 2, "a5": 3, "a6": 3,
            "b0": 1, "b1": 2}
    assert tertiles(result, tracks) == bins
    log = droplog.rows(result, tracks)
    assert len(log) == 9
    for row in log:
        value = expected[row["bundle_id"]]
        assert row["reason"] == "overlap"
        assert row["overlap"] == f"{value.numerator}/{value.denominator}"
        assert row["tertile"] == bins[row["bundle_id"]]


def test_tertiles_rank_bundles_from_two_lives_together_within_a_track():
    streams = {(life, branch): [event(token, token) for token in "abcd"]
               for life in ("life", "other-life") for branch in ("B0", "B1")}
    items, records = {}, {}
    cases = [("a-low", "life", 0), ("b-low", "other-life", 1),
             ("c-high", "life", 2), ("d-high", "other-life", 4)]
    for bid, life, count in cases:
        add_bundle(items, records, bid, life=life, prompts=("a b c d", "quiet question"),
                   spans=(tuple("abcd"[:count]), ()))
    result = literal_copy(streams, items, records)
    assert {bundle.bundle_id: bundle.items[0].life for bundle in result.bundles} == {
        bid: life for bid, life, _ in cases}
    assert {bundle.bundle_id: bundle.overlap for bundle in result.bundles} == {
        bid: Fraction(count, 4) for bid, _, count in cases}
    # Four bundles share one ranking: two in tertile 1, then one in each.
    assert tertiles(result, {bid: "Drift" for bid, _, _ in cases}) == {
        "a-low": 1, "b-low": 1, "c-high": 2, "d-high": 3}


def yield_fixture():
    streams, items, records = stream_fixture(), {}, {}
    for version, total, dropped in ((1, 5, 3), (2, 4, 2)):
        for index in range(total):
            # A dropped pair has two matched items. Count pairs, not matches.
            prompts = (("amber orchid beacon", "saffron silver lantern") if index < dropped
                       else ("common words repeat", "quiet question"))
            spans = (("plant", "other"), ("other",)) if index < dropped else (
                ("common-1",), ("common-1",))
            add_bundle(items, records, f"v{version}-{index}", prompts=prompts, spans=spans,
                       version=version, sample=index == 0)
    return streams, items, records


def test_yields_count_bundles_per_version_flag_strictly_above_half_and_derive_filters():
    streams, items, records = yield_fixture()
    result = literal_copy(streams, items, records)
    report = yields(result, records)
    assert set(report) == {("copy", 1), ("copy", 2)}
    assert (report[("copy", 1)].dropped, report[("copy", 1)].total,
            report[("copy", 1)].rate, report[("copy", 1)].flagged) == (3, 5, Fraction(3, 5), True)
    assert (report[("copy", 2)].dropped, report[("copy", 2)].total,
            report[("copy", 2)].rate, report[("copy", 2)].flagged) == (2, 4, Fraction(1, 2), False)
    assert all(value.filters_run == ("literal_copy",) for value in report.values())
    log = droplog.rows(result, {bundle.bundle_id: "Drift" for bundle in result.bundles})
    assert len([row for row in log if row["reason"] == "literal_copy"]) == 10
    assert len([row for row in log if row["reason"] == "overlap"]) == 9


def test_multiple_distinct_matches_are_logged_once_each_within_an_item():
    streams, items, records = stream_fixture(), {}, {}
    text = "amber orchid beacon amber orchid beacon"
    for branch in ("B0", "B1"):
        streams[("life", branch)] = [event("repeated", text)]
    add_bundle(items, records, "many", prompts=(text, "quiet question"),
               spans=(("repeated", "repeated"), ("repeated",)))
    result = literal_copy(streams, items, records)
    match_item = result.bundles[0].items[0]
    assert len(match_item.matches) == 3  # Three distinct types, not four windows.
    assert all(match.df == 1 for match in match_item.matches)
    log = droplog.rows(result, {"many": "Drift"})
    assert len(log) == 4
    assert len({row["sha256_prefix"] for row in log if row["reason"] == "literal_copy"}) == 3


def test_singletons_are_validated_but_do_not_enter_bundle_yields():
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "pair")
    items["single"] = dict(item_id="single", prompt="!!!", track="Keep", gold_spans=[])
    records["single"] = dict(bundle_id=None, life="life", branch="B0", template_id="singleton",
                             template_version=1, unfiltered_sample=False)
    result = literal_copy(streams, items, records)
    assert len(result.items) == 3 and len(result.bundles) == 1
    single = next(item for item in result.items if item.item_id == "single")
    assert single.overlap == Fraction(0) and single.matches == ()
    report = yields(result, records)
    assert set(report) == {("copy", 1)}
    assert report[("copy", 1)].filters_run == ("literal_copy",)
    items["single"]["gold_spans"] = ["absent"]
    with pytest.raises(ValueError, match="gold span absent"):
        literal_copy(streams, items, records)


def test_missing_item_record_is_a_value_error():
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "pair")
    del records["pair-B0"]
    with pytest.raises(ValueError, match="missing record for item pair-B0"):
        literal_copy(streams, items, records)


@pytest.mark.parametrize("elsewhere", [False, True])
def test_gold_span_must_be_in_its_own_branch_stream(elsewhere):
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "pair", spans=(("absent",), ("common-1",)))
    if elsewhere:
        streams[("life", "B1")].append(event("absent", "amber orchid beacon"))
    with pytest.raises(ValueError, match="gold span absent.*branch stream"):
        literal_copy(streams, items, records)


@pytest.mark.parametrize("size", [1, 3])
def test_bundle_must_have_exactly_two_items(size):
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "pair")
    if size == 1:
        del items["pair-B1"]
    else:
        items["third"] = dict(items["pair-B0"], item_id="third")
        records["third"] = dict(records["pair-B0"], item_id="third")
    with pytest.raises(ValueError, match="bundle pair must have exactly two items"):
        literal_copy(streams, items, records)


def test_missing_stream_is_a_value_error():
    items, records = {}, {}
    add_bundle(items, records, "pair")
    with pytest.raises(ValueError, match="missing branch stream"):
        literal_copy({}, items, records)


@pytest.mark.parametrize("source,field,value", [
    ("item", "track", "Keep"),
    ("record", "life", "other-life"),
    ("record", "template_id", "other-template"),
    ("record", "template_version", 2),
])
def test_every_inconsistent_bundle_metadata_field_is_a_value_error(source, field, value):
    streams, items, records = stream_fixture(), {}, {}
    add_bundle(items, records, "pair")
    metadata = items if source == "item" else records
    metadata["pair-B1"][field] = value
    with pytest.raises(ValueError, match="bundle pair has inconsistent metadata"):
        literal_copy(streams, items, records)


def assert_no_float(value):
    assert not isinstance(value, float)
    if is_dataclass(value):
        for field in fields(value):
            assert_no_float(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, child in value.items():
            assert_no_float(key)
            assert_no_float(child)
    elif isinstance(value, (tuple, list, set, frozenset)):
        for child in value:
            assert_no_float(child)


def test_determinism_immutable_results_no_input_mutation_and_no_floats():
    streams, items, records = yield_fixture()
    before = repr((streams, items, records))
    first = literal_copy(streams, items, records)
    assert literal_copy(streams, items, records) == first
    reordered_streams = {key: list(reversed(value)) for key, value in reversed(list(streams.items()))}
    second = literal_copy(reordered_streams, dict(reversed(list(items.items()))),
                          dict(reversed(list(records.items()))))
    assert first == second
    assert repr(first).encode("utf-8") == repr(second).encode("utf-8")
    tracks = {bundle.bundle_id: bundle.items[0].track for bundle in first.bundles}
    first_rows, second_rows = droplog.rows(first, tracks), droplog.rows(second, tracks)
    assert first_rows == second_rows
    assert json.dumps(first_rows).encode() == json.dumps(second_rows).encode()
    first_yields = yields(first, records)
    assert first_yields == yields(second, records)
    table = idf_table(streams[("life", "B0")])
    assert_no_float((first, table, rare(table), first_rows, first_yields, tertiles(first, tracks)))
    with pytest.raises(FrozenInstanceError):
        first.bundles[0].overlap = Fraction(0)
    with pytest.raises(FrozenInstanceError):
        first.items[0].matches[0].df = 99
    with pytest.raises(FrozenInstanceError):
        table.entries[0].df = 99
    with pytest.raises(FrozenInstanceError):
        first_yields[("copy", 1)].total = 99
    assert repr((streams, items, records)) == before


def test_empty_build_has_empty_reports():
    result = literal_copy({}, {}, {})
    assert result.items == result.bundles == ()
    assert tertiles(result, {}) == yields(result, {}) == {}
    assert droplog.rows(result, {}) == ()


def test_filter_package_stays_outside_control_files():
    # CONTROL_FILES already expands the control/reader import closure at import
    # time. Importing filters -> naive_rag must not create the reverse edge.
    assert not any(path.startswith("filters/") for path in cache.CONTROL_FILES)
