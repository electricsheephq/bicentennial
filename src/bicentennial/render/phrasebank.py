"""The phrase bank: one exactly keyed phrase list per gold-critical rendering cell."""

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from functools import cache
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

SPEECH_ACTS = ("assert", "hedge", "propose", "quote")
MODALITIES = ("stated", "observed", "inferred_allowed", "retracted", "planted")
POLARITIES = ("affirm", "negate")
BANDS = ("soft", "hard")
RENDERED = ("stated", "observed", "retracted")
STYLES = ("chat", "mail", "log", "none")
MARKERS = {
    "assert": ("always", "confirmed", "definitely", "for sure", "from now on", "must"),
    "hedge": ("maybe", "might", "not sure", "perhaps", "possibly"),
    "propose": ("could we", "how about", "i suggest", "what if"),
    "quote": ("quote", "said", "wrote"),
}
CHANNELS = ("chat", "issue_thread", "review_comment", "standup_note", "mail", "email_digest",
            "ci_log", "tool_result", "file_content", "commit", "calendar", "notes", "tracker")
SLOT = re.compile(r"\{(subject|predicate|object|when)\}")
KEYS = {"bank_id", "calibrated", "markers", "channels", "when", "factless", "cells"}


class Phrase(NamedTuple):
    phrase_id: str
    text: str


@dataclass(frozen=True)
class PhraseBank:
    bank_id: str
    calibrated: bool
    sha256: str
    markers: dict[str, tuple[str, ...]]
    channels: dict[str, str]
    when: Phrase
    factless: tuple[Phrase, ...]
    cells: dict[tuple[str, str, str, str], tuple[Phrase, ...]]

    def cell(self, speech_act: str, modality: str, strength: int, polarity: str) -> tuple[Phrase, ...]:
        if speech_act not in SPEECH_ACTS or modality not in MODALITIES or polarity not in POLARITIES:
            raise ValueError(f"no phrase cell for {speech_act!r}, {modality!r}, {polarity!r}")
        if modality == "inferred_allowed":
            raise ValueError("an inferred_allowed fact has no asserting text")
        # A plant shares its genuine twin's wording, phrase ids included (DESIGN §5.1a).
        modality = "stated" if modality == "planted" else modality
        return self.cells[speech_act, modality, band(strength), polarity]


def band(strength: int) -> str:
    """Only the maximum strength renders as hard, so a render never overstates strength."""
    if type(strength) is not int or not 0 <= strength <= 1000:
        raise ValueError("strength must be an int in 0..1000")
    return "hard" if strength == 1000 else "soft"


def has_marker(segments: list[str], kind: str) -> bool:
    """Casefolded whole-phrase matching on literal segments, so a marker never spans a slot."""
    return any(re.search(r"(?<!\w)" + re.escape(m) + r"(?!\w)", s.casefold())
               for m in MARKERS[kind] for s in segments)


def _phrase(text: object, slots: dict[str, int], banned: tuple[str, ...], soft: bool = False,
            need: str | None = None) -> str:
    if type(text) is not str or not text or "\n" in text or unicodedata.normalize("NFC", text) != text:
        raise ValueError(f"phrase must be a nonempty single-line NFC string: {text!r}")
    segments = SLOT.split(text)[::2]
    if any("{" in s or "}" in s for s in segments):
        raise ValueError(f"phrase has a stray brace: {text!r}")
    found = SLOT.findall(text)
    if any(found.count(name) != count for name, count in slots.items()):
        raise ValueError(f"phrase has the wrong slots: {text!r}")
    if any(has_marker(segments, kind) for kind in banned) or (need and not has_marker(segments, need)):
        raise ValueError(f"phrase breaks the marker rule: {text!r}")
    if soft and has_marker(segments, "assert"):
        raise ValueError(f"soft phrase carries an assert marker: {text!r}")
    return text


def _list(value: object) -> list:
    if type(value) is not list or not value or len(set(map(str, value))) != len(value):
        raise ValueError("phrase lists must be nonempty and duplicate-free")
    return value


def _exact(table: object, keys: tuple[str, ...], where: str) -> dict:
    if type(table) is not dict or set(table) != set(keys):
        raise ValueError(f"{where}: expected exactly {sorted(keys)}")
    return table


def load(path: str | Path | None = None) -> PhraseBank:
    raw = Path(path or Path(__file__).with_name("phrasebank") / "en.toml").read_bytes()
    data = _exact(tomllib.loads(raw.decode("utf-8")), tuple(KEYS), "bank")
    if type(data["bank_id"]) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", data["bank_id"]):
        raise ValueError("bank_id must be a lowercase identifier")
    if type(data["calibrated"]) is not bool:
        raise ValueError("calibrated must be a boolean")
    markers = _exact(data["markers"], tuple(MARKERS), "markers")
    if any(markers[k] != list(v) for k, v in MARKERS.items()):
        raise ValueError("markers differ from the fixed marker lists")
    channels = _exact(data["channels"], CHANNELS, "channels")
    if any(style not in STYLES for style in channels.values()):
        raise ValueError("channel style must be chat, mail, log or none")
    none = {"subject": 0, "predicate": 0, "object": 0, "when": 0}
    when = _phrase(data["when"], {**none, "when": 1}, tuple(MARKERS))
    factless = [_phrase(p, none, tuple(MARKERS)) for p in _list(data["factless"])]
    cells = {}
    for act, by_modality in _exact(data["cells"], SPEECH_ACTS, "cells").items():
        banned = {"assert": ("hedge", "propose"), "hedge": ("assert",), "propose": ("assert",)}.get(act, ())
        for modality, by_band in _exact(by_modality, RENDERED, f"cells.{act}").items():
            for band_, by_polarity in _exact(by_band, BANDS, f"cells.{act}.{modality}").items():
                lists = _exact(by_polarity, POLARITIES, f"cells.{act}.{modality}.{band_}")
                for polarity, phrases in lists.items():
                    key = f"{act}.{modality}.{band_}.{polarity}"
                    cells[act, modality, band_, polarity] = tuple(
                        Phrase(f"{key}#{i}", _phrase(p, {**none, "subject": 1, "predicate": 1, "object": 1},
                                                     banned, band_ == "soft",
                                                     None if act == "assert" else act))
                        for i, p in enumerate(_list(phrases)))
    return PhraseBank(data["bank_id"], data["calibrated"], sha256(raw).hexdigest(),
                      {k: tuple(v) for k, v in markers.items()}, dict(channels), Phrase("when", when),
                      tuple(Phrase(f"factless#{i}", p) for i, p in enumerate(factless)), cells)


@cache
def default_bank() -> PhraseBank:
    return load()
