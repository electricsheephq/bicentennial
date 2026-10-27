"""Cross-field invariants for sealed scripted-reader keys."""

import unicodedata

from .run import register_check


def check_reader_keys(value):
    groups = [value["required"], value["forbidden"], [c["token"] for c in value["competing"]]]
    if any(group != sorted(set(group)) for group in groups):
        raise ValueError("reader keys: token lists must strictly increase")
    spans = value["oracle_spans"]
    if len(spans) != len(set(spans)):
        raise ValueError("reader keys: duplicate oracle span")
    tokens = [token for group in groups for token in group]
    if len(tokens) != len(set(tokens)):
        raise ValueError("reader keys: overlapping token sets")
    query = unicodedata.normalize("NFC", value["recall_query"])
    if any(unicodedata.normalize("NFC", token) != token or token in query for token in tokens):
        raise ValueError("reader keys: non-NFC token or token in query")


register_check("reader_keys", check_reader_keys)
