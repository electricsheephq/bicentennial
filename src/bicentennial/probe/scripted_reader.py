"""Exact presence policy and report-only evidence diagnostics."""

import json
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

from bicentennial.api.contract import shape
from bicentennial.canon import canon, milli
from bicentennial.contracts.run import validate
from bicentennial.sandbox.spansearch import span_search
from bicentennial.score.exposure import context_text, present

K = 5
KINDS = ("stale", "planted", "twin")
UNKNOWN = {"type": "unknown", "value": None, "confidence_milli": 0, "citation": None}


def _copy(value):
    return json.loads(canon(value))


def _inputs(view, keys):
    if type(view) is not dict or view.keys() != {"item_id", "prompt", "options"}:
        raise ValueError("reader view required")
    validate("reader_keys", keys)
    if keys["item_id"] != view["item_id"]:
        raise ValueError("reader item ids differ")
    options = view["options"]
    if not isinstance(options, list) or not options:
        raise ValueError("reader options required")
    for kind, field, other in (("act", "plan", "envelope"), ("qa", "envelope", "plan")):
        if all(isinstance(o, dict) and field in o and other not in o for o in options):
            return kind
    raise ValueError("mixed option payloads")


@dataclass(frozen=True)
class PlanHandoff:
    item_id: str
    option_id: str | None
    steps: tuple[dict, ...]

    def to_obj(self):
        return _copy({"item_id": self.item_id, "option_id": self.option_id, "steps": self.steps})


@dataclass(frozen=True)
class ReaderResult:
    item_id: str
    mode: str
    kind: str
    selected_option: str | None
    envelope: dict | None
    plan: PlanHandoff | None
    competing_present: tuple[str, ...]
    carry_over: bool
    in_context: bool | None
    missing_required: int
    competing: dict
    forbidden_in_context: bool | None
    recall: dict | None


def select(options, context):
    available = [o for o in options if o["tokens"] and present(o["tokens"], context)]
    selected = available[0] if available else next((o for o in options if not o["tokens"]), None)
    return selected, tuple(sorted(o["option_id"] for o in available if o is not selected))


def envelope_for(selected, context) -> dict:
    if selected is None or not selected["tokens"]:
        return _copy(UNKNOWN)
    quote = unicodedata.normalize("NFC", selected["tokens"][0])
    return dict(_copy(selected["envelope"]), citation={"quote": quote, "context_offset": context.find(quote)})


def read(view, keys, context, *, mode, citations=None, earlier="") -> ReaderResult:
    kind = _inputs(view, keys)
    if mode not in ("api", "hermes"):
        raise ValueError("invalid reader mode")
    context = context_text(context)
    selected, competing_present = select(view["options"], context)
    option_id = selected["option_id"] if selected is not None else None
    active = selected is not None and bool(selected["tokens"])
    steps = tuple(_copy(selected["plan"]["steps"])) if kind == "act" and active else ()
    missing = sum(not present([t], context) for t in keys["required"])
    competing = {kind: sum(c["kind"] == kind and present([c["token"]], context)
                           for c in keys["competing"]) for kind in KINDS}
    spans, recall = keys["oracle_spans"], None
    if mode == "api" and spans:
        hits = len(set(spans) & set((citations or [])[:K]))
        recall = {"k": K, "hits": hits, "of": len(spans), "milli": milli(Fraction(hits, len(spans)))}
    return ReaderResult(
        view["item_id"], mode, kind, option_id,
        envelope_for(selected, context) if kind == "qa" else None,
        PlanHandoff(view["item_id"], option_id, steps) if kind == "act" else None,
        competing_present, bool(mode == "hermes" and kind == "qa" and active
                                and present(selected["tokens"], context_text(earlier))),
        missing == 0 if keys["required"] else None, missing, competing,
        any(present([t], context) for t in keys["forbidden"]) if keys["forbidden"] else None, recall)


def api_task(view, keys, *, oracle=False) -> dict:
    _inputs(view, keys)
    task = {"task_id": view["item_id"], "prompt": keys["recall_query"]}
    if oracle:
        task["oracle_evidence"] = list(keys["oracle_spans"])
    return task


def read_api(adapter, view, keys, now, *, oracle=False, injected=()) -> ReaderResult:
    answer = adapter.query(api_task(view, keys, oracle=oracle), now)
    try:
        shape(answer, {"output": str, "citations": list, "confidence_milli": int})
        if any(type(c) is not str for c in answer["citations"]):
            raise ValueError("invalid citation")
    except (ValueError, TypeError) as error:
        raise ValueError("invalid reader answer") from error
    return read(view, keys, context_text([answer["output"], *injected]),
                mode="api", citations=answer["citations"])


def surface_hits(roots, tokens) -> dict[str, bool] | None:
    if roots is None:
        return None
    roots = tuple(roots)
    return {t: any(span_search(root, [unicodedata.normalize("NFC", t).encode()])[
        unicodedata.normalize("NFC", t).encode()] for root in roots) for t in tokens}


def failing_stage(result, keys, *, failed, stored_roots=None, retained_roots=None) -> str | None:
    if not failed:
        return None
    if result.in_context is not False:
        return "unknown"
    retained = surface_hits(retained_roots, keys["required"])
    if retained is not None and all(retained.values()):
        return "retrieved"
    stored = surface_hits(stored_roots, keys["required"])
    if stored is not None and all(stored.values()) and retained is not None and not all(retained.values()):
        return "retained"
    return "unknown"


def item_report(result, keys, *, failed, stored_roots=None, retained_roots=None) -> dict:
    forget = None
    if keys["forbidden"]:
        hits = surface_hits(retained_roots, keys["forbidden"])
        in_store = any(hits.values()) if hits is not None else None
        pair = result.forbidden_in_context, in_store
        held = False if any(v is True for v in pair) else True if pair == (False, False) else None
        forget = {"in_context": pair[0], "in_store": in_store, "held": held}
    return _copy({"item_id": result.item_id, "mode": result.mode, "selected_option": result.selected_option,
                  "competing_present": result.competing_present, "carry_over": result.carry_over,
                  "in_context": result.in_context, "missing_required": result.missing_required,
                  "competing": result.competing, "recall": result.recall, "forget": forget,
                  "stage_attribution": failing_stage(result, keys, failed=failed,
                      stored_roots=stored_roots, retained_roots=retained_roots)})
