"""Sealed events and session schedules, never harness-visible script data."""

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .run import register_check
from .world import Contract, unique


def check_stream(value):
    if ("text" in value) == ("payload" in value):
        raise ValueError("stream: exactly one of text or payload is required")
    try:
        ZoneInfo(value["tz"])
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("stream: tz must be an IANA zone name") from error
    if value["tool"] is not None and not value["call_id"]:
        raise ValueError("stream: a tool call needs a call_id")
    unique(value["fact_ids"], "fact_ids")


def check_session(value):
    unique(value["wake_before"], "wake_before")
    if any(point["session"] != value["index"] for point in value["fault_points"]):
        raise ValueError("session: fault point belongs to a different session")


@dataclass(frozen=True, kw_only=True)
class StreamEvent(Contract):
    _name = "stream"
    canary: str
    event_id: str
    session_id: str
    seq: int
    t_sim: int
    tz: str
    channel: str
    kind: str
    actor: str
    audience: list[str]
    visibility: str
    call_id: str | None
    tool: dict | None
    expected_result_sha256: str | None
    fact_ids: list[str]
    gold_critical: bool
    render: dict
    turn_key: str
    sha256: str
    text: str | None = None
    payload: dict | None = None

    def to_json(self) -> bytes:
        # Absent alternatives must remain absent on the wire, rather than null.
        from dataclasses import asdict

        from bicentennial.canon import canon

        from .run import validate

        value = {k: v for k, v in asdict(self).items()
                 if k not in {"text", "payload"} or v is not None}
        validate(self._name, value)
        return canon(value)


@dataclass(frozen=True)
class Session(Contract):
    _name = "session"
    canary: str
    index: int
    kind: str
    wake_before: list[str]
    fault_points: list[dict]
    long_sprint: bool
    est_tokens: int
    probe_point: bool
    expected_state: dict


register_check("stream", check_stream)
register_check("session", check_session)
