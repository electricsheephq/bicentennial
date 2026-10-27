"""Standalone catalog: generators and the environment server stay independent."""

from types import MappingProxyType

G2_ENV_ID = "g2-assistant-v1"
COLLECTIONS = ("bookings", "calendar", "inventory", "mail", "notes")
_FIELDS = ("name", "description", "op", "collection", "key_arg", "value_arg")
SEED_TOOLS = tuple(MappingProxyType(dict(zip(_FIELDS, row, strict=True))) for row in (
    ("get_mail", "Read one mail message.", "get", "mail", "id", None),
    ("get_note", "Read one note.", "get", "notes", "id", None),
    ("get_calendar_entry", "Read one calendar entry.", "get", "calendar", "id", None),
    ("get_booking", "Read one booking.", "get", "bookings", "id", None),
    ("get_option", "Read one bookable option.", "get", "inventory", "id", None),
    ("book", "Create or change a booking.", "set", "bookings", "id", "booking"),
    ("cancel_booking", "Cancel a booking.", "remove", "bookings", "id", None),
    ("add_note", "Add a note.", "add", "notes", "id", "note"),
    ("send_mail", "Send a mail message.", "add", "mail", "id", "message"),
    ("add_calendar_entry", "Add a calendar entry.", "add", "calendar", "id", "entry"),
))
ACTION_TOOLS = ("book", "cancel_booking", "add_note", "send_mail", "add_calendar_entry")
VALUE_SCHEMAS = {
    name: {
        "type": "object", "minProperties": 1,
        "propertyNames": {"type": "string", "minLength": 1,
                          "not": {"enum": ["items", "t_sim", "from"]}},
        "additionalProperties": {"type": "string", "minLength": 1},
    }
    for name in ("book", "send_mail", "add_note", "add_calendar_entry")
}
SEARCH_TOOLS = tuple(MappingProxyType(dict(zip(_FIELDS, row, strict=True))) for row in (
    ("search_mail", "List mail messages that contain the query; an empty query lists every message.",
     "search", "mail", "query", None),
    ("search_notes", "List notes that contain the query; an empty query lists every note.",
     "search", "notes", "query", None),
    ("search_calendar", "List calendar entries that contain the query; an empty query lists every entry.",
     "search", "calendar", "query", None),
    ("search_bookings", "List bookings that contain the query; an empty query lists every booking.",
     "search", "bookings", "query", None),
    ("search_options", "List bookable options that contain the query; an empty query lists every option.",
     "search", "inventory", "query", None),
))
