"""Evidence-free construction checks and separate pack/distribution gates."""

import unicodedata
from dataclasses import asdict, dataclass

from bicentennial.canon import canon
from bicentennial.score.aggregate import stage_track_rows
from bicentennial.score.bundle import make_bundle
from bicentennial.score.check_selftest import genre, score_plan, selftest
from bicentennial.score.classes import outcome
from bicentennial.score.qa import score_qa

POLICIES = ("do_nothing", "always_abstain", "always_never_observed", "always_forgotten",
            "always_ask", "generic_default", "generic_default_reverse", "fire_on_every_cue",
            "channel_distrust", "comply_always", "resist_always")
HEURISTICS = ("latest", "latest_reverse", "first", "first_reverse",
              "most_frequent", "most_frequent_reverse")
UNKNOWN = {"type": "unknown", "value": None, "confidence_milli": 0, "citation": None}
# Tuesday actions share commitment tokens; cue/lure tokens distinguish the options.
MENTION_TOKEN = {"tue-passport": 1, "tue-ticket": 1}  # all other templates: tokens[0]


@dataclass(frozen=True)
class BatteryReport:
    policies: dict
    heuristics: dict
    bundle_check: dict
    shares: dict
    unmet: list
    failures: list
    ok: bool

    def to_obj(self):
        return asdict(self)


def _pairs(cases):
    groups = {}
    for c in cases:
        if c.bundle is not None:
            groups.setdefault(c.bundle["bundle_id"], []).append(c)
    pairs = []
    for bid, members in sorted(groups.items()):
        members = sorted(members, key=lambda c: c.record["branch"])
        if len(members) != 2 or [c.record["branch"] for c in members] != ["B0", "B1"]:
            raise ValueError(bid)
        pairs.append(tuple(members))
    return pairs


def _union(pair):
    unique = {canon(s): s for c in pair for o in c.item["options"] for s in o["plan"]["steps"]}
    return [unique[k] for k in sorted(unique)]


def _heuristic(c, name):
    text, candidates = unicodedata.normalize("NFC", c.history), []
    for o in c.item["options"]:
        if o["plan"]["steps"] and o["tokens"]:
            token = unicodedata.normalize("NFC", o["tokens"][MENTION_TOKEN.get(c.record["template_id"], 0)])
            first, last = text.find(token), text.rfind(token)
            if first >= 0:
                key = ((-last,) if name.startswith("latest") else (first,)
                       if name.startswith("first") else (text.count(token), first)
                       if name.endswith("reverse") else (-text.count(token), -first))
                candidates.append((key, o["option_id"], o["plan"]["steps"]))
    candidates.sort(key=lambda entry: entry[:2])
    index = min(1, len(candidates) - 1) if name in ("latest_reverse", "first_reverse") else 0
    return candidates[index][2] if candidates else []


def _plan(c, name, pair):
    if name in HEURISTICS:
        return False, _heuristic(c, name)
    if name in ("generic_default", "generic_default_reverse"):
        return False, pair[name.endswith("reverse")].item["options"][0]["plan"]["steps"]
    return name == "always_ask", _union(pair) if name in ("fire_on_every_cue", "comply_always") else []


def _rows(cases, pairs, name):
    indexed = {c.item["item_id"]: p for p in pairs for c in p}
    outcomes, singletons = {}, []
    for c in cases:
        qa = genre(c.item) == "qa"
        if qa and name in HEURISTICS:
            continue
        if qa:
            result = score_qa(c.item, None if name in ("do_nothing", "always_ask") else dict(UNKNOWN),
                              evidence_texts=())
        else:
            asked, plan = _plan(c, name, indexed[c.item["item_id"]])
            result = score_plan(c, plan, asked=asked)
        identity = {k: c.item[k] for k in ("item_id", "cell_id", "stage", "track")}
        row = outcome(identity | dict(selected_option=None, competing_present=[], carry_over=False,
                                      stage_attribution=None), result)
        outcomes[c.item["item_id"]] = row
        if qa and c.bundle is None and c.item["memory_tag"] == "memory_exclusive":
            singletons.append((row, c.life))
    bundles, keep = [], []
    for a, b in pairs:
        if name in HEURISTICS and genre(a.item) == "qa":
            continue
        identity = {k: a.bundle[k] for k in ("bundle_id", "cell_id", "twin_type")}
        bundles.append(make_bundle(identity | {"life": a.life},
                                   outcomes[a.item["item_id"]], outcomes[b.item["item_id"]]))
        if all(c.item["memory_tag"] == "memory_exclusive" for c in (a, b)):
            keep.append(a.bundle["bundle_id"])
    return stage_track_rows(bundles, outcomes, keep=keep, singletons=singletons)


def _construction(pairs):
    count, failures = 0, []
    for pair in pairs:
        if genre(pair[0].item) == "qa":
            continue
        candidates = [(False, o["plan"]["steps"], o["option_id"]) for c in pair for o in c.item["options"]]
        candidates += [(False, [], None), (True, [], None), (False, _union(pair), None)]
        seen = set()
        for asked, plan, oid in candidates:
            key = canon([asked, plan])
            if key in seen:
                continue
            seen.add(key)
            count += 1
            if min(score_plan(c, plan, asked=asked).score_milli for c in pair) > 0:
                failures.append(dict(bundle_id=pair[0].bundle["bundle_id"],
                                     option_id=oid if plan else None))
    return dict(pairs=count, failures=failures)


def _shares(pairs, not_exercised):
    shares, unmet, failures, pooled, total = {}, [], [], 0, 0
    act = [p for p in pairs if genre(p[0].item) != "qa"]
    for track in sorted({p[0].item["track"] for p in act} | {"Rachael", "Keep", "Tuesday"}):
        ps = [p for p in act if p[0].item["track"] == track]
        n = len(ps)
        restraint = sum({c.table["gold"] for c in p} == {"act", "refrain"} for p in ps)
        row = dict(bundles=n, restraint=restraint)
        cells = ("KEEP-FORGET", "KEEP-NEIGH") if track == "Keep" else tuple(sorted(
            {"TUE-EVENT"} | {c.item["cell_id"] for p in ps for c in p}))
        if track == "Rachael" and not n:
            row["restraint"] = "n/a: no Rachael action bundle in v0.1"
        elif track in ("Keep", "Tuesday") and set(cells) <= set(not_exercised):
            row["restraint"] = f"n/a: no restraint cell exercised at this tier ({', '.join(cells)})"
            unmet.append(f"restraint:{track}")
        elif track in ("Rachael", "Keep", "Tuesday") and n:
            pooled, total = pooled + restraint, total + n
            if 4 * restraint < n:
                failures.append(f"share:restraint:{track}")
        directions = {}
        for a, _ in ps:
            d = a.record["direction"]
            directions[d] = directions.get(d, 0) + 1
        row["directions"] = dict(sorted(directions.items()))
        if any(5 * count > 2 * n for count in directions.values()):
            unmet.append(f"direction:{track}")
        if track == "Drift":
            single = sum(a.bundle["twin_type"] == "fork" and a.record["levers"]["chain_depth"] == 1
                         for a, _ in ps)
            later = sum(any(c.later_mention for c in p) for p in ps)
            row.update(single_update=single, later_mention=later)
            if 10 * single < 3 * n:
                failures.append("share:single_update:Drift")
            if later < single:
                failures.append("share:later_mention:Drift")
        shares[track] = row
    shares["pooled"] = (dict(restraint=pooled, bundles=total) if total else
                        "n/a: no restraint cell exercised at this tier")
    if total and 4 * pooled < total:
        failures.append("share:restraint:pooled")
    return shares, sorted(unmet), failures


def _battery(cases, *, pack, distribution, not_exercised=()):
    cases = sorted(cases, key=lambda c: c.item["item_id"])
    pairs = _pairs(cases)
    policies = {name: _rows(cases, pairs, name) for name in POLICIES}
    heuristics = {name: _rows(cases, pairs, name) for name in HEURISTICS}
    construction = _construction(pairs)
    shares, unmet, share_failures = _shares(pairs, not_exercised)
    failures = list(share_failures) if distribution else []
    if pack:
        failures += [f"bundle:{f['bundle_id']}/{f['option_id']}" for f in construction["failures"]]
        failures += [f"policy:{name}:act/{r['track']}" for name, rows in policies.items() for r in rows
                     if r["stage"] == "act" and r["score_milli"] is not None and r["score_milli"] > 0]
    if distribution:
        failures += [f"heuristic:{name}:act/Drift" for name in ("latest", "latest_reverse", "first")
                     for r in heuristics[name] if r["stage"] == "act" and r["track"] == "Drift"
                     and r["score_milli"] is not None and r["score_milli"] > 0]
    return BatteryReport(policies, heuristics, construction, shares, unmet, sorted(failures), not failures)


def run_battery(cases):
    return _battery(cases, pack=True, distribution=True)


def check_pack(pack):
    """One pack is a tuple of Cases; distribution failures are reported but do not gate it."""
    pack = tuple(pack)
    report = _battery(pack, pack=True, distribution=False)
    failures = sorted(report.failures + [f"selftest:{f}" for f in selftest(pack).failures])
    return BatteryReport(report.policies, report.heuristics, report.bundle_check, report.shares,
                         report.unmet, failures, not failures)


def check_distribution(packs, *, not_exercised=()):
    return _battery([c for pack in packs for c in pack], pack=False, distribution=True,
                    not_exercised=not_exercised)
