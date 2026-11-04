"""#391 slice 10: summarize a live T2 card for RESULT.md, numbers and labels only.

Usage: python3 -I t2live_card_summary.py <run dir>
Prints the card's counts, items per genre, life and branch, mean score per track and genre, failure classes, stages,
items not scored live (by genre and stage), broken controls and the floor's units. Prints no answers, no served identity value
(only whether the floor's equals the system's), and no paths.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def main(run):
    card = json.loads((run / "card.json").read_text())
    items = card["items"]
    print("tier", card["tier"], "system", card["system"], "model", card["model"], "effort", card["effort"],
          "aa_prime", card["aa_prime"])
    print("pack_hash", card["pack_hash"][:12], "seed_hash", card["seed_hash"][:12])
    print("pins", json.dumps({k: (v[:12] if isinstance(v, str) else v) for k, v in sorted(card["pins"].items())}))
    print("counts", json.dumps(card["counts"], sort_keys=True))
    print("items", len(items), "lives", len({i["life"] for i in items}),
          "life x branch", len({(i["life"], i["branch"]) for i in items}))
    by_genre = Counter(i["genre"] for i in items)
    print("items by genre", dict(sorted(by_genre.items())))
    by_track = defaultdict(list)
    by_track_genre = defaultdict(list)
    for i in items:
        if isinstance(i.get("score_milli"), int):
            by_track[i["track"]].append(i["score_milli"])
            by_track_genre[(i["track"], i["genre"])].append(i["score_milli"])
    for track, scores in sorted(by_track.items()):
        print(f"track {track}: n={len(scores)} mean_score_milli={mean(scores):.1f}")
    for (track, genre), scores in sorted(by_track_genre.items()):
        print(f"  {track} {genre}: n={len(scores)} mean={mean(scores):.1f}")
    print("unscored (no integer score_milli)", sum(not isinstance(i.get("score_milli"), int) for i in items))
    print("failure_class", dict(sorted(Counter(str(i.get("failure_class")) for i in items).items())))
    print("stage", dict(sorted(Counter(str(i.get("stage")) for i in items).items())))
    print("infra_reruns total", sum(i.get("infra_reruns") or 0 for i in items))
    keys = {tuple(row) for row in card["not_scored_live"]}
    where = Counter(f"{i['genre']} {i['stage']}" for i in items if (i["life"], i["branch"], i["item_id"]) in keys)
    print("not_scored_live", len(card["not_scored_live"]), "by genre and stage", dict(sorted(where.items())))
    print("controls_broken", json.dumps(card["controls_broken"], sort_keys=True))
    floor = card["floor"]
    print("floor units", len(floor.get("units", [])), "floor identity equals system's",
          floor.get("served_identity") == card.get("served_identity"))
    unit_kinds = Counter()
    for unit in floor.get("units", []):
        if isinstance(unit, dict):
            unit_kinds[str(unit.get("source") or unit.get("cached") or unit.get("kind"))] += 1
    if unit_kinds:
        print("floor unit sources", dict(sorted(unit_kinds.items())))
    scores = Counter((i["track"], i["genre"], i["stage"], i.get("score_milli"), str(i.get("failure_class"))) for i in items)
    print("items by track, genre, stage, score_milli and failure class:")
    for key, n in sorted(scores.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        print("  ", *key, n)
    print("groups", len(card["groups"]), "labels.t2", json.dumps(card["labels"].get("t2"), sort_keys=True)[:300])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
