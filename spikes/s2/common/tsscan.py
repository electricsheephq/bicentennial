"""Timestamp extraction and classification shared by the S2 checkers.

A value is classified against the run's windows:
  sim1, sim2, ...  inside a session's simulated window (with slack)
  wall             inside the real wall-clock window of the whole run
  other            anything else (bundled content, fixed dates, far past)
In a no-shim control run the sim windows equal the wall windows, so "sim" wins.
"""

import json
import re
from datetime import datetime, timezone

SLACK = 180.0
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
COMPACT = re.compile(r"\b(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\b")
DATE_ONLY = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
EPOCH_TXT = re.compile(r"(?<![\d.])(1[5-9]\d{8}(?:\.\d+)?|1[5-9]\d{11})(?![\d])")


class Windows:
    def __init__(self, run):
        self.sim = [(s["index"], s["sim_start"] - SLACK, s["sim_end"] + SLACK) for s in run["sessions"]]
        self.wall = (min(s["wall_start"] for s in run["sessions"]) - SLACK,
                     max(s["wall_end"] for s in run["sessions"]) + SLACK)
        self.sim_days = {i: {datetime.fromtimestamp(t, timezone.utc).date().isoformat()
                             for t in (a + SLACK, b - SLACK)} for i, a, b in self.sim}
        self.wall_days = {datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in self.wall}

    def classify(self, t):
        for i, a, b in self.sim:
            if a <= t <= b:
                return f"sim{i}"
        if self.wall[0] <= t <= self.wall[1]:
            return "wall"
        return "other"

    def classify_day(self, day):
        for i, days in self.sim_days.items():
            if day in days:
                return f"sim{i}_day"
        return "wall_day" if day in self.wall_days else "other"


def epoch_of_number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if 9.0e8 <= v <= 4.2e9:
        return float(v)
    if 9.0e11 <= v <= 4.2e12:
        return v / 1e3
    if 9.0e17 <= v <= 4.2e18:
        return v / 1e9
    return None


def _iso_candidates(m):
    y, mo, d, hh, mi, ss, frac, tz = m.groups()
    try:
        base = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), int(float(frac or 0) * 1e6))
    except ValueError:
        return []
    if tz:
        tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        return [datetime.fromisoformat(base.isoformat() + tz).timestamp()]
    return [base.replace(tzinfo=timezone.utc).timestamp(), base.timestamp()]  # naive: try UTC, then local


def classify_text(text, win, counts, where=None):
    """Add every timestamp found in *text* to *counts* {class: n}; returns the classes seen."""
    seen = []

    def add(cls):
        counts[cls] = counts.get(cls, 0) + 1
        seen.append(cls)

    spans = []
    for m in ISO.finditer(text):
        cands = [win.classify(t) for t in _iso_candidates(m)]
        add(next((c for c in cands if c != "other"), "other"))
        spans.append(m.span())
    for m in COMPACT.finditer(text):
        try:
            t = datetime(*(int(g) for g in m.groups())).timestamp()
        except ValueError:
            continue
        add(win.classify(t))
    for m in DATE_ONLY.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        add(win.classify_day(m.group(0)))
    for m in EPOCH_TXT.finditer(text):
        t = epoch_of_number(float(m.group(1)))
        if t is not None:
            add(win.classify(t))
    return seen


def classify_json(obj, win, counts):
    """Walk parsed JSON: numbers by epoch range, strings by text patterns."""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
        elif isinstance(o, str):
            classify_text(o, win, counts)
        else:
            t = epoch_of_number(o)
            if t is not None:
                c = win.classify(t)
                counts[c] = counts.get(c, 0) + 1


def classify_value(v, win, counts):
    if isinstance(v, (bytes, bytearray)):
        return
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{":
            try:
                return classify_json(json.loads(s), win, counts)
            except ValueError:
                pass
        try:
            t = epoch_of_number(float(s))
        except ValueError:
            t = None
        if t is not None:
            c = win.classify(t)
            counts[c] = counts.get(c, 0) + 1
            return
        classify_text(v, win, counts)
        return
    t = epoch_of_number(v)
    if t is not None:
        c = win.classify(t)
        counts[c] = counts.get(c, 0) + 1
