"""Build verdict-free T2 cards with explicit life and unit identities."""

import json

import bicentennial.contracts.run as run
from bicentennial.canon import canon
from bicentennial.report.t2lite_card import _check_item

_COUNTS = {"units", "lives", "floor_cached_units", "null_citation",
           "not_scored_live", "infra", "kept_copies"}
_ITEM_EXTRAS = {"life", "genre", "branch", "probe_point", "repro"}


def _schema():
    return json.loads((run.SCHEMAS / "card_t2.schema.json").read_bytes())


def _identity(item):
    return item["life"], item["branch"], item["item_id"]


def _row_counts(card):
    items, units = card["items"], card["floor"]["units"]
    counts = dict(units=len(units), lives=len({item["life"] for item in items}),
                  not_scored_live=len(card["not_scored_live"]),
                  floor_cached_units=sum(unit["cached"] for unit in units.values()),
                  kept_copies=sum(item["repro"] is not None for item in items),
                  # T2-lite's null-citation escape (runner/t2lite.py): an unknown answer always has a null citation.
                  null_citation=sum(item["envelope"] is not None and item["envelope"]["type"] != "unknown"
                                    and item["envelope"]["citation"] is None for item in items))
    for item in items:
        key = f"items.{item['genre']}.{item['stage']}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def validate_t2_card(card) -> None:
    """Validate structure and the card's result-independent identity and exclusions."""
    if type(card) is not dict:
        raise ValueError("t2_card:object")
    if card.get("tier") != "T2":
        raise ValueError("t2_card:tier")
    if "gate_verdict" in card:
        raise ValueError("t2_card:gate_verdict")
    required_labels = _schema()["properties"]["labels"]["required"]
    if type(card.get("labels")) is not dict or not set(required_labels) <= card["labels"].keys():
        raise ValueError("t2_card:labels")
    if type(card.get("counts")) is not dict or not _COUNTS <= card["counts"].keys():
        raise ValueError("t2_card:counts")
    run.validate("card_t2", card)
    seed = card["seed_source"]
    expected_seed = {"kind"} if seed["kind"] == "public" else {"kind", "draw_sha256"}
    if seed.keys() != expected_seed:
        raise ValueError("t2_card:seed_source")
    identities = [_identity(item) for item in card["items"]]
    if any(a >= b for a, b in zip(identities, identities[1:], strict=False)):
        raise ValueError("t2_card:items")
    triples = card["not_scored_live"]
    if any(len(triple) != 3 for triple in triples):
        raise ValueError("t2_card:not_scored_live")
    unscored = [tuple(triple) for triple in triples]
    if unscored != sorted(set(unscored)) or not set(unscored) <= set(identities):
        raise ValueError("t2_card:not_scored_live")
    expected_unscored = {_identity(i) for i in card["items"]
                         if i["genre"] == "G2" and i["stage"] == "act"}
    if set(unscored) != expected_unscored:
        raise ValueError("t2_card:not_scored_live_g2")
    groups = sorted({(i["cell_id"], i["stage"]) for i in card["items"]})
    if card["groups"] != [list(group) for group in groups]:
        raise ValueError("t2_card:groups")
    # One order for the same rows: controls/cache.py's broken_rows sorts by (stage, track).
    broken = [(row["stage"], row["track"]) for row in card["controls_broken"]]
    if broken != sorted(set(broken)):
        raise ValueError("t2_card:controls_broken")
    genre_stages = {f"items.{i['genre']}.{i['stage']}" for i in card["items"]}
    if not genre_stages <= card["counts"].keys():
        raise ValueError("t2_card:counts_items")
    units = {f"{i['life']}/{i['branch']}" for i in card["items"]}
    if card["floor"]["units"].keys() != units:
        raise ValueError("t2_card:floor_units")
    genres = {}
    for item in card["items"]:
        if genres.setdefault(item["life"], item["genre"]) != item["genre"]:
            raise ValueError("t2_card:life_genre")
        excluded = _identity(item) in expected_unscored
        # BLOCKED and N/A rows carry a null score (contracts/bundle.py), so a number below 1000 is a failure.
        failed = type(item["score_milli"]) is int and item["score_milli"] < 1000 and not excluded
        if item["repro"] is not None:
            if not failed:
                raise ValueError("t2_card:repro_ineligible")
            if item["repro"] != "kept/" + "/".join(_identity(item)):
                raise ValueError("t2_card:repro_path")
        # Null G2 action rows use the frozen unscored form. Cause-generated outcomes
        # keep their ordinary semantics, including a crash's zero, while still excluded.
        row = {key: value for key, value in item.items() if key not in _ITEM_EXTRAS}
        _check_item(row, not_scored_live=excluded and item["failure_class"] is None)
    # Counts the rows define must agree with them; `infra` is the runner's own count.
    derived = _row_counts(card)
    if any(card["counts"][key] != value for key, value in derived.items()) or any(
            key.startswith("items.") and key not in derived and value != 0 for key, value in card["counts"].items()):
        raise ValueError("t2_card:counts_values")


def build_t2_card(*, system, pack_hash, seed_hash, pins, model, effort, served_identity,
                  aa_prime, items, counts, answer_contract_sha256, not_scored_live,
                  seed_source, groups, floor, controls_broken, control=None, anchor=None) -> dict:
    """Return fresh canonical JSON data, sorting items without mutating caller fields.

    Counts, fixed groups, exclusions and floor provenance are supplied by the caller.
    Repro pointers describe retained copies; store bytes and session ids are not inputs.
    A live control arm's card names the arm in `control`; a system card has no such field.
    Anchor arms also name their pre-run definition in `anchor`.
    """
    if anchor is not None and (control is None or anchor.get("name") != control):
        raise ValueError("t2_card:anchor_control")
    labels = {name: prop["enum"][0]
              for name, prop in _schema()["properties"]["labels"]["properties"].items()}
    card = dict(tier="T2", system=system, pack_hash=pack_hash, seed_hash=seed_hash,
                pins=pins, model=model, effort=effort, served_identity=served_identity,
                profile="probe-live", live_roles=["probe_main"],
                answer_contract_sha256=answer_contract_sha256, aa_prime=aa_prime,
                labels=labels, items=sorted(items, key=_identity), counts=counts,
                not_scored_live=not_scored_live, seed_source=seed_source, groups=groups,
                floor=floor, controls_broken=controls_broken)
    if control is not None:
        card["control"] = control
    if anchor is not None:
        card["anchor"] = anchor
    validate_t2_card(card)
    return json.loads(canon(card))
