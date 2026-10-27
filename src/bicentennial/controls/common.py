"""Shared validation and scripted-reader arm execution."""

import re
from dataclasses import dataclass

from bicentennial.api.contract import event_copy
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import validate
from bicentennial.probe.scripted_reader import item_report, read_api
from bicentennial.score.bundle import make_bundle
from bicentennial.score.classes import outcome


@dataclass(frozen=True)
class ControlInput:
    pack: dict
    keys: tuple[dict, ...]
    events: dict
    now: dict[str, int]
    scoring_sha256: str


def check(inp):
    validate("pack", inp.pack)
    ids = {i["item_id"] for i in inp.pack["items"]}
    keys = {}
    for key in sorted(inp.keys, key=lambda k: k["item_id"]):
        validate("reader_keys", key)
        if key["item_id"] in keys:
            raise ValueError("duplicate reader key")
        keys[key["item_id"]] = key
        if key["branch"] not in inp.events.get(key["life"], {}):
            raise ValueError("missing event stream")
    if set(keys) != ids or set(inp.now) != ids:
        raise ValueError("item, key and time identities differ")
    if any(type(inp.now[i]) is not int or inp.now[i] < 0 for i in sorted(inp.now)):
        raise ValueError("invalid probe time")
    for life in sorted(inp.events):
        for branch in sorted(inp.events[life]):
            if branch not in ("B0", "B1") or type(inp.events[life][branch]) is not list:
                raise ValueError("invalid event stream")
            for event in inp.events[life][branch]:
                try:
                    event_copy(event)
                except TypeError as error:
                    raise ValueError("invalid event") from error
    for bundle in sorted(inp.pack["bundles"], key=lambda b: b["bundle_id"]):
        a, b = (keys[i] for i in bundle["items"])
        if a["life"] != b["life"] or a["branch"] == b["branch"]:
            raise ValueError("twins require one life and distinct branches")
    if not isinstance(inp.scoring_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", inp.scoring_sha256):
        raise ValueError("invalid scoring digest")


def run_arm(inp, factory, *, score, oracle=False, keep=None) -> dict:
    check(inp)
    adapters, items, reports, bundles = {}, {}, {}, []
    keys = {k["item_id"]: k for k in sorted(inp.keys, key=lambda k: k["item_id"])}
    for life in sorted(inp.events):
        for branch in sorted(inp.events[life]):
            adapter = adapters[(life, branch)] = factory()
            for event in inp.events[life][branch]:
                adapter.ingest(event)
    for item in sorted(inp.pack["items"], key=lambda i: i["item_id"]):
        iid = item["item_id"]
        key, now = keys[iid], inp.now[iid]
        adapter = adapters[(key["life"], key["branch"])]
        if keep is not None and not keep(adapter, now):
            continue
        result = read_api(adapter, reader_view(item), key, now, oracle=oracle)
        identity = {k: item[k] for k in ("cell_id", "item_id", "stage", "track")}
        identity.update(selected_option=result.selected_option, competing_present=list(result.competing_present),
                        carry_over=result.carry_over, stage_attribution=None)
        items[iid] = outcome(identity, score(item, result))
        reports[iid] = item_report(result, key, failed=False)
    dropped, members = set(), set()
    for bundle in sorted(inp.pack["bundles"], key=lambda b: b["bundle_id"]):
        a, b = bundle["items"]
        members.update((a, b))
        if a not in items or b not in items:
            dropped.update((a, b))
            continue
        identity = {k: bundle[k] for k in ("bundle_id", "cell_id", "twin_type")}
        bundles.append(make_bundle(dict(identity, life=keys[a]["life"]), items[a], items[b]))
    retained = sorted(set(items) - dropped)
    return dict(items=[items[i] for i in retained], bundles=bundles,
                reports=[reports[i] for i in retained],
                singleton_lives={i: keys[i]["life"] for i in retained if i not in members})
