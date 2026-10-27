"""The director's answer source for every request it does not serve from the script (R09, S04, R17a). A Call
carries only the harness's own request body (for a write turn, the write body): never the script, gold or manifest."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Call:
    role: str  # the ledger role: write_turn, probe_main, summariser, aux, memory_write or embeddings
    subrole: str
    wire: str  # chat | responses | responses_compact | embeddings
    body: dict
    model: str  # the route's model for this role
    cursor: dict | None  # {session, turn} of the scripted turn, or None
    run_key: str  # the session's attempt id


@dataclass(frozen=True)
class Reply:
    status: int
    served: str  # the responder's name, ^[a-z0-9_]+$; the ledger records responder_<served>
    served_by: str  # scripted | live
    model: str  # the model that produced the reply
    text: str = ""
    tool_calls: tuple = ()  # ({"name": str, "arguments": JSON string}, ...)
    embedding: list | None = None  # integer vectors; the HTTP edge divides by scale
    scale: int | None = None
    usage: dict | None = None
    upstream: tuple = ()  # canonical diagnostic objects, no floats


class Responder(Protocol):
    def respond(self, call: Call) -> Reply: ...
