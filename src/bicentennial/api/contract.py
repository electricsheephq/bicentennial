"""Memory-layer boundary; bytes are measured externally, never via stats.

Events contain event_id (nonempty str), t_sim (nonnegative int), kind
(message/tool_call/tool_result), actor (str), text (str), and, only for a
tool_result, call_id (the event_id of its already ingested tool_call).
K12 is not merged: DESIGN §4 describes time, channel, actor, audience,
visibility and salience. Project its event_id, t_sim, actor and text directly;
map its channel/kind to one of these three kinds before ingest. Other stream
metadata stays outside this API; no channel names or K12 schema are invented.
Tasks contain task_id, prompt and optional oracle_evidence (distinct event ids).
Queries return output, citations (event ids, not quote spans), confidence_milli
in [0, 1000]. JSON scalar leaves are strings or integers, never floats/bools;
containers, None from void methods, bool from settle, and bytes from checkpoint
are method-level shapes. now is a nonnegative simulated integer timestamp.
"""

from abc import ABC, abstractmethod
from typing import NotRequired, TypedDict


class Event(TypedDict):
    event_id: str
    t_sim: int
    kind: str
    actor: str
    text: str
    call_id: NotRequired[str]


class Task(TypedDict):
    task_id: str
    prompt: str
    oracle_evidence: NotRequired[list[str]]


class Answer(TypedDict):
    output: str
    citations: list[str]
    confidence_milli: int


def shape(value, fields, optional=()):
    if type(value) is not dict or not fields.keys() <= value.keys() <= fields.keys() | set(optional):
        raise ValueError("invalid fields")
    if any(type(value[key]) is not kind for key, kind in fields.items()):
        raise TypeError("invalid scalar type")


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer")


def event_copy(event):
    shape(event, dict(event_id=str, t_sim=int, kind=str, actor=str, text=str), ("call_id",))
    integer(event["t_sim"])
    if not event["event_id"] or event["kind"] not in ("message", "tool_call", "tool_result"):
        raise ValueError("invalid event id or kind")
    if event["kind"] == "tool_result":
        if type(event.get("call_id")) is not str or not event["call_id"]:
            raise ValueError("tool_result requires call_id")
    elif "call_id" in event:
        raise ValueError("call_id only belongs to tool_result")
    return dict(event)


def task_ids(task, now):
    shape(task, dict(task_id=str, prompt=str), ("oracle_evidence",))
    integer(now)
    ids = task.get("oracle_evidence", [])
    if not task["task_id"] or type(ids) is not list or any(type(i) is not str or not i for i in ids):
        raise ValueError("invalid task or evidence ids")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence id")
    return ids


def answer(events=()):
    return dict(output="\n".join(e["text"] for e in events) if events else "UNKNOWN",
                citations=[e["event_id"] for e in events], confidence_milli=1000 if events else 0)


class Adapter(ABC):
    @abstractmethod
    def reset(self) -> None: ...
    @abstractmethod
    def ingest(self, event: Event) -> None: ...
    @abstractmethod
    def query(self, task: Task, now: int) -> Answer: ...
    @abstractmethod
    def checkpoint(self) -> bytes: ...
    @abstractmethod
    def restore(self, data: bytes) -> None: ...
    @abstractmethod
    def forget(self, selector: dict[str, list[str]]) -> None: ...
    def maintain(self) -> None:
        """Perform the adapter's background work; synchronously idle by default."""
        return None
    @abstractmethod
    def settle(self, bound_s: int) -> bool:
        """True only after observing the queue drained within bound_s."""
    @abstractmethod
    def stats(self) -> dict[str, int]: ...
