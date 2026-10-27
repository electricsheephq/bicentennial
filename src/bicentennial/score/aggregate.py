"""Exact bundle/life means and separate diagnostics; no headline or verdict."""

from fractions import Fraction

from bicentennial.canon import milli
from bicentennial.contracts.bundle import DISQUALIFIERS, NONRESULTS
from bicentennial.score.bundle import make_bundle, twin_min

LABEL = "pre-C-12: every Act cell of the pack, not the C-12 required cells"


def _values(items):
    return items.values() if isinstance(items, dict) else items


def _mean(values):
    return sum(values, Fraction()) / len(values) if values else None


def _ratio(n, d):
    return milli(Fraction(n, d)) if d else None


def _rows(bundles, items, *, keep=None, minus_one=None, mode="bundle", blocked=frozenset(),
          blocked_items=frozenset(), singletons=(), keep_items=None):
    if keep is not None and set(keep) - {b["bundle_id"] for b in bundles}:
        raise ValueError("keep names an unknown bundle")
    groups, counts = {}, {}
    for bundle in bundles:
        a, b = (items[i] for i in bundle["items"])
        key = (a["stage"], a["track"])
        lives = groups.setdefault(key, {})
        excluded = bundle["failure_class"] == "BLOCKED" or bundle["bundle_id"] in blocked
        counts[key] = counts.get(key, 0) + excluded
        system_failure = any(i["failure_class"] == "SYSTEM_FAILURE" for i in (a, b))
        score = twin_min(a, b, minus_one=minus_one, worst=mode == "worst")
        if mode == "worst" and system_failure:  # A3 overrides keep and non-result twins.
            values = [-1000]
        elif excluded and mode == "worst" or keep is not None and bundle["bundle_id"] not in keep:
            continue
        elif score is None:
            continue
        else:
            values = [a["score_milli"], b["score_milli"]] if mode == "single" else [score]
        lives.setdefault(bundle["life"], []).extend(values)
    for item, life in singletons:
        key = (item["stage"], item["track"])
        lives = groups.setdefault(key, {})
        excluded = item["failure_class"] == "BLOCKED" or item["item_id"] in blocked_items
        counts[key] = counts.get(key, 0) + excluded  # shown, never charged
        if keep_items is not None and item["item_id"] not in keep_items and not (
                mode == "worst" and item["failure_class"] == "SYSTEM_FAILURE"):  # A1, with A3's override
            continue
        score = item["worst_case_milli" if mode == "worst" else "score_milli"]
        if score is not None:
            if minus_one is not None and score == -1000:
                score = minus_one
            lives.setdefault(life, []).append(score)
    rows = []
    for (stage, track), lives in sorted(groups.items()):
        score = _mean([_mean(values) for values in lives.values()])
        row = dict(stage=stage, track=track,
                   score_milli=milli(score / 1000) if score is not None else None)
        if mode == "worst":
            row["blocked"] = counts[(stage, track)]
        rows.append(row)
    return rows


def stage_track_rows(bundles, items, *, keep=None, minus_one=None, singletons=()):
    return _rows(bundles, items, keep=keep, minus_one=minus_one, singletons=singletons)


def worst_case_rows(bundles, items, *, keep=None, blocked=frozenset(), blocked_items=frozenset(),
                    singletons=()):
    return _rows(bundles, items, keep=keep, blocked=blocked, blocked_items=blocked_items, mode="worst",
                 singletons=singletons)


def single_item_rows(bundles, items, *, keep=None):
    return _rows(bundles, items, keep=keep, mode="single")


def twin_consistency(bundles, items, *, keep=None):
    if keep is not None and set(keep) - {b["bundle_id"] for b in bundles}:
        raise ValueError("keep names an unknown bundle")
    counts = {}
    for bundle in bundles:
        a, b = (items[i] for i in bundle["items"])
        if a["stage"] != "act":
            continue
        row = counts.setdefault(a["track"], dict(consistent=0, scored=0))
        if (keep is None or bundle["bundle_id"] in keep) and twin_min(a, b) is not None:
            row["scored"] += 1
            row["consistent"] += all(i["accuracy_correct"] is True for i in (a, b))
    return [dict(track=track, **row, consistency_milli=_ratio(row["consistent"], row["scored"]))
            for track, row in sorted(counts.items())]


def violations(items, *, duty_items=frozenset()):
    counts = {}
    for item in _values(items):
        if item["stage"] == "act":
            row = counts.setdefault(item["track"], dict(fail_memory=0, harmful_extra=0,
                                                       harmful_omission=0))
            verdict = item["base_verdict"]
            if verdict in DISQUALIFIERS:
                row[verdict.lower()] += 1
            row["harmful_omission"] += (item["item_id"] in duty_items and verdict == "OMISSION")
    return [dict(track=track, **row) for track, row in sorted(counts.items())]


def accuracy(items, *, blocked_items=frozenset()):
    counts = {}
    for item in _values(items):
        if item["stage"] != "act":
            continue
        row = counts.setdefault(item["cell_id"], dict.fromkeys(
            ("correct", "eligible", "blocked", "na_exposure", "na_clock"), 0))
        failure = item["failure_class"]
        if item["item_id"] in blocked_items and failure != "SYSTEM_FAILURE":
            failure = "BLOCKED"
        if failure in NONRESULTS:
            row[failure.lower().replace("n/a_", "na_")] += 1
        else:
            row["eligible"] += 1
            row["correct"] += item["accuracy_correct"] is True and failure != "SYSTEM_FAILURE"
    cells = [dict(cell_id=cell, **row, accuracy_milli=_ratio(row["correct"], row["eligible"]))
             for cell, row in sorted(counts.items())]
    mean = _mean([Fraction(row["correct"], row["eligible"]) for row in cells if row["eligible"]])
    eligible = sum(row["eligible"] for row in cells)
    excluded = sum(row[k] for row in cells for k in ("blocked", "na_exposure", "na_clock"))
    return dict(cells=cells, figure_milli=milli(mean) if mean is not None else None,
                incomplete=not cells or 20 * excluded > eligible + excluded, label=LABEL)


def coverage(bundles, *, blocked=frozenset(), blocked_items=frozenset(), singletons=()):
    counts = dict.fromkeys(("blocked", "na_exposure", "na_clock"), 0)
    failures = ["BLOCKED" if b["bundle_id"] in blocked else b["failure_class"] for b in bundles]
    failures += ["BLOCKED" if item["item_id"] in blocked_items else item["failure_class"]
                 for item, _ in singletons]  # A2: a singleton is one unit
    for failure in failures:
        if failure in NONRESULTS:
            counts[failure.lower().replace("n/a_", "na_")] += 1
    assigned, excluded = len(failures), sum(counts.values())
    return dict(assigned=assigned, scored=assigned - excluded, **counts,
                coverage_milli=_ratio(assigned - excluded, assigned),
                incomplete=not assigned or 20 * excluded > assigned)


def _validated(items, bundles, validate):
    values = list(_values(items))
    for item in values:
        validate("item_outcome", item)
    indexed = {item["item_id"]: item for item in values}
    if len(indexed) != len(values) or isinstance(items, dict) and items != indexed:
        raise ValueError("duplicate item or mismatched map key")
    ids, members = set(), set()
    for bundle in bundles:
        validate("bundle_outcome", bundle)
        if bundle["bundle_id"] in ids or any(i not in indexed or i in members for i in bundle["items"]):
            raise ValueError("duplicate bundle, unknown item or item in multiple bundles")
        identity = {k: bundle[k] for k in ("bundle_id", "cell_id", "twin_type", "life")}
        if bundle != make_bundle(identity, *(indexed[i] for i in bundle["items"])):
            raise ValueError("bundle differs from its item projection")
        ids.add(bundle["bundle_id"])
        members.update(bundle["items"])
    return indexed, set(indexed) - members


def reduce(items, bundles, *, keep=None, blocked=frozenset(), blocked_items=frozenset(),
           singleton_lives=None, duty_items=frozenset(), keep_items=None) -> dict:
    from bicentennial.contracts.run import validate

    items, unbundled = _validated(items, bundles, validate)
    singleton_lives = {} if singleton_lives is None else singleton_lives
    if any(items[i]["stage"] == "act" for i in unbundled) or set(singleton_lives) != unbundled:
        raise ValueError("every unbundled QA item needs exactly one singleton life; act needs a bundle")
    if any(type(life) is not str or not life or "\n" in life for life in singleton_lives.values()):
        raise ValueError("singleton life must be a nonempty string")
    if (set(blocked) - {b["bundle_id"] for b in bundles}
            or (set(blocked_items) | set(duty_items)) - items.keys()):
        raise ValueError("exclusion or duty names an unknown identity")
    options = dict(keep=keep, keep_items=keep_items,
                   singletons=[(items[i], singleton_lives[i]) for i in sorted(unbundled)])
    return dict(aggregates=_rows(bundles, items, **options),
                sensitivity=dict(minus_one_at_zero=_rows(bundles, items, minus_one=0, **options),
                                 minus_one_at_minus_two=_rows(bundles, items, minus_one=-2000, **options)),
                worst_case=_rows(bundles, items, mode="worst", blocked=blocked, blocked_items=blocked_items,
                                 **options),
                single_item=_rows(bundles, items, mode="single", **options),
                twin_consistency=twin_consistency(bundles, items, keep=keep),
                violations=violations(items, duty_items=duty_items),
                accuracy=accuracy(items, blocked_items=blocked_items),
                coverage=coverage(bundles, blocked=blocked, blocked_items=blocked_items,
                                  singletons=options["singletons"]))


def common_valid(arms) -> frozenset[str]:
    sets = [{b["bundle_id"] for b in bundles if b["score_milli"] is not None}
            for _, bundles in arms.values()]
    return frozenset.intersection(*(frozenset(s) for s in sets)) if sets else frozenset()


def compare(arms, *, singleton_lives=None, duty_items=frozenset()) -> dict:
    """singleton_lives and duty_items are shared by every arm; a singleton with no result in some arm
    is dropped from all, and one BLOCKED in some arm is counted blocked in all (PREREG §7)."""
    from bicentennial.contracts.run import validate

    identities, blocked, blocked_items, keep_items = None, set(), set(), set(singleton_lives or {})
    for items, bundles in arms.values():
        indexed, _ = _validated(items, bundles, validate)
        keep_items -= {i for i in keep_items if i in indexed and indexed[i]["score_milli"] is None}
        identity = {b["bundle_id"]: (b["life"], b["cell_id"], b["items"]) for b in bundles}
        if identities is not None and identity != identities:
            raise ValueError("comparison arms must share bundle identities, lives, cells and items")
        identities = identity
        blocked.update(b["bundle_id"] for b in bundles if b["failure_class"] == "BLOCKED")
        blocked_items.update(i["item_id"] for i in indexed.values() if i["failure_class"] == "BLOCKED")
    keep = common_valid(arms)
    return {name: reduce(items, bundles, keep=keep, blocked=blocked, blocked_items=blocked_items,
                         singleton_lives=singleton_lives, keep_items=frozenset(keep_items),
                         duty_items=duty_items)
            for name, (items, bundles) in arms.items()}
