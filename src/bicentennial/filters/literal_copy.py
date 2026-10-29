"""Exact, model-free literal-copy and overlap reports (issue #241, choices 1–7).

Inputs are build-local mappings of JSON-shaped data. Results contain only frozen
dataclasses and immutable values; copy matches retain hashes, never source text.
Singleton items (record bundle_id=None) receive item diagnostics and validation,
but do not enter bundle decisions, tertiles or yields. No input is modified.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from typing import Any

from bicentennial.controls.naive_rag import idf_fixed, words

type Trigram = tuple[str, str, str]
type JsonObject = Mapping[str, Any]


@dataclass(frozen=True)
class IdfEntry:
    gram: Trigram
    df: int
    idf: int


@dataclass(frozen=True)
class IdfTable:
    n_events: int
    entries: tuple[IdfEntry, ...]


@dataclass(frozen=True)
class CopyMatch:
    df: int
    idf: int
    sha256_prefix: str


@dataclass(frozen=True)
class ItemCopy:
    item_id: str
    bundle_id: str | None
    track: str
    life: str
    branch: str
    template_id: str
    template_version: int
    overlap: Fraction
    matches: tuple[CopyMatch, ...]


@dataclass(frozen=True)
class BundleCopy:
    bundle_id: str
    items: tuple[ItemCopy, ItemCopy]
    dropped: bool
    reason: str
    overlap: Fraction


@dataclass(frozen=True)
class CopyResult:
    items: tuple[ItemCopy, ...]
    bundles: tuple[BundleCopy, ...]


@dataclass(frozen=True)
class Yield:
    dropped: int
    total: int
    rate: Fraction
    flagged: bool
    filters_run: tuple[str, ...]


def _text(event: JsonObject) -> str:
    return event.get("text") or ""


def _grams(text: str) -> frozenset[Trigram]:
    tokens = words(text)
    return frozenset((tokens[i], tokens[i + 1], tokens[i + 2])
                     for i in range(len(tokens) - 2))


def idf_table(events: Sequence[JsonObject]) -> IdfTable:
    """Count each triple once per event, including textless events in N.

    Triples never cross event boundaries. Entries are in lexical token order;
    IDF is the existing naive RAG fixed-point integer, cached here by df.
    """
    counts: Counter[Trigram] = Counter()
    for event in events:
        counts.update(_grams(_text(event)))
    weights = {df: idf_fixed(len(events), df) for df in sorted(set(counts.values()))}
    entries = tuple(IdfEntry(gram, counts[gram], weights[counts[gram]]) for gram in sorted(counts))
    return IdfTable(len(events), entries)


def rare(table: IdfTable) -> frozenset[Trigram]:
    """Top ceil(distinct triple types / 100) by IDF, with all cutoff ties."""
    if not table.entries:
        return frozenset()
    rank = (len(table.entries) + 99) // 100
    cutoff = sorted((entry.idf for entry in table.entries), reverse=True)[rank - 1]
    return frozenset(entry.gram for entry in table.entries if entry.idf >= cutoff)


def literal_copy(
    streams: Mapping[tuple[str, str], Sequence[JsonObject]],
    items: Mapping[str, JsonObject],
    records: Mapping[str, JsonObject],
) -> CopyResult:
    """Apply filter 1 to every bundle, including the unfiltered sample.

    Only prompt and gold-span event texts participate. Evidence words and
    triples are unions over separate events. Empty prompt vocabulary has zero
    overlap. Either item's match drops the pair; high overlap alone never does.
    """
    members: dict[str, list[str]] = {}
    for iid in sorted(items):
        if iid not in records:
            raise ValueError(f"missing record for item {iid}")
        bid = records[iid]["bundle_id"]
        if bid is not None:
            members.setdefault(bid, []).append(iid)
    for bid, ids in sorted(members.items()):
        if len(ids) != 2:
            raise ValueError(f"bundle {bid} must have exactly two items")
        metadata = {(items[iid]["track"], records[iid]["life"],
                     records[iid]["template_id"], records[iid]["template_version"])
                    for iid in ids}
        if len(metadata) != 1:
            raise ValueError(f"bundle {bid} has inconsistent metadata")

    # Whole streams, not just gold evidence, define each branch's IDF table.
    indexes = {}
    for key in sorted(streams):
        events = streams[key]
        table = idf_table(events)
        indexes[key] = ({event["event_id"]: _text(event) for event in events},
                        {entry.gram: entry for entry in table.entries}, rare(table))

    outcomes = {}
    for iid in sorted(items):
        item, record = items[iid], records[iid]
        key = (record["life"], record["branch"])
        if key not in indexes:
            raise ValueError(f"missing branch stream for item {iid}")
        texts, entries, rare_grams = indexes[key]
        evidence_words, evidence_grams = set(), set()
        for eid in sorted(set(item["gold_spans"])):
            if eid not in texts:
                raise ValueError(f"gold span {eid} is not in item {iid}'s branch stream")
            evidence_words.update(words(texts[eid]))
            evidence_grams.update(_grams(texts[eid]))
        prompt_words = set(words(item["prompt"]))
        overlap = (Fraction(len(prompt_words & evidence_words), len(prompt_words))
                   if prompt_words else Fraction(0))
        shared = _grams(item["prompt"]) & evidence_grams & rare_grams
        matches = tuple(CopyMatch(entries[gram].df, entries[gram].idf,
                                  sha256(" ".join(gram).encode("utf-8")).hexdigest()[:16])
                        for gram in sorted(shared))
        outcomes[iid] = ItemCopy(iid, record["bundle_id"], item["track"], *key,
                                 record["template_id"], record["template_version"],
                                 overlap, matches)

    bundles = []
    for bid, ids in sorted(members.items()):
        pair = (outcomes[ids[0]], outcomes[ids[1]])
        dropped = any(item.matches for item in pair)
        bundles.append(BundleCopy(bid, pair, dropped, "literal_copy" if dropped else "",
                                  max(item.overlap for item in pair)))
    return CopyResult(tuple(outcomes[iid] for iid in sorted(outcomes)), tuple(bundles))


def tertiles(result: CopyResult, tracks: Mapping[str, str]) -> Mapping[str, int]:
    """Rank all bundles within tracks[bundle_id], including dropped bundles.

    Cut sizes are ceil(n/3), ceil((n-ceil(n/3))/2), then the remainder.
    Equal overlaps are ordered by bundle id. Small tracks may have empty bins.
    """
    groups: dict[str, list[BundleCopy]] = {}
    for bundle in result.bundles:
        groups.setdefault(tracks[bundle.bundle_id], []).append(bundle)
    bins = {}
    for track in sorted(groups):
        ranked = sorted(groups[track], key=lambda bundle: (bundle.overlap, bundle.bundle_id))
        first = (len(ranked) + 2) // 3
        second = first + (len(ranked) - first + 1) // 2
        for rank, bundle in enumerate(ranked):
            bins[bundle.bundle_id] = 1 if rank < first else 2 if rank < second else 3
    return {bid: bins[bid] for bid in sorted(bins)}


def yields(
    result: CopyResult,
    records: Mapping[str, JsonObject],
    *,
    filters_run: Sequence[str],
) -> Mapping[tuple[str, int], Yield]:
    """Dropped/total bundles per template version; flag strictly above half.

    filters_run is copied to a tuple in the supplied order, without inferring
    that any other filters ran. Multiple item matches still count as one drop.
    """
    counts = {}
    for bundle in result.bundles:
        keys = set()
        for item in bundle.items:
            if item.item_id not in records:
                raise ValueError(f"missing record for item {item.item_id}")
            record = records[item.item_id]
            keys.add((record["template_id"], record["template_version"]))
        if len(keys) != 1:
            raise ValueError(f"bundle {bundle.bundle_id} has inconsistent template versions")
        key = next(iter(keys))
        dropped, total = counts.get(key, (0, 0))
        counts[key] = (dropped + int(bundle.dropped), total + 1)
    names = tuple(filters_run)
    return {key: Yield(dropped, total, Fraction(dropped, total), 2 * dropped > total, names)
            for key, (dropped, total) in sorted(counts.items())}
