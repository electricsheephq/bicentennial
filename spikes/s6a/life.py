"""Synthetic G1 (software partner) micro-life for spike S6a.

Every line is written from the templates below with a fixed seed. Nothing here comes from a
real transcript, and the project, services and values are invented. Run it to regenerate
``micro_life.json`` (the replay script) next to this file:

    python3 life.py            # writes micro_life.json
    python3 life.py --check    # exits 1 if micro_life.json is stale
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

SEED = 6101
PROJECT = "tidewater"  # an invented log-shipping CLI

# Facts the life tells; `session` is where each is told (1-based). `kind` is fact, correction or
# commitment. A correction supersedes the fact named in `supersedes` (the newest value wins).
FACTS = [
    {"id": "F1", "session": 1, "kind": "fact", "text": "staging Postgres listens on port 6432"},
    {"id": "F2", "session": 1, "kind": "fact", "text": "deploys go out from the release/ember branch"},
    {"id": "F3", "session": 2, "kind": "fact", "text": "CI runs on Python 3.12 only"},
    {"id": "F4", "session": 2, "kind": "fact", "text": "every log line must be JSON lines (one object per line)"},
    {"id": "F5", "session": 2, "kind": "fact", "text": "the quiet_retry feature flag defaults to off"},
    {"id": "F6", "session": 3, "kind": "fact", "text": "commit subjects stay under 50 characters, imperative mood"},
    {"id": "C1", "session": 3, "kind": "commitment", "due_session": 7,
     "text": "the assistant will bring the cache-key rotation checklist once the release freeze ends"},
    {"id": "F1b", "session": 5, "kind": "correction", "supersedes": "F1",
     "text": "staging Postgres moved to port 6543"},
]

# Life events the SPEC requires, with where they happen.
EVENTS = {
    "restart_wake": {"session": 5, "after_turn": 2,
                     "how": "the harness process is SIGKILLed at a turn boundary and cold-restarted"},
    "long_gap": {"before_session": 8, "how": "told in the text (three weeks away); S6a runs on wall time"},
    "long_session": {"session": 6, "how": "pasted logs push the prompt past the lowered compaction trigger"},
}


def _log_block(rng: random.Random, n: int, svc: str) -> str:
    """A synthetic log excerpt: invented services, ids and messages."""
    msgs = ["batch flush timeout", "retry scheduled", "upstream closed connection", "spool file rotated",
            "checksum mismatch on segment", "backpressure engaged", "ack window exceeded"]
    lines = []
    for i in range(n):
        lines.append(
            f'{{"ts":"T+{i * 7 + rng.randint(0, 6):05d}s","level":"{rng.choice(["warn", "error", "info"])}",'
            f'"svc":"{svc}","msg":"{rng.choice(msgs)}","batch":{rng.randint(1000, 9999)},'
            f'"segment":"seg-{rng.randint(100, 999)}","retry":{rng.randint(0, 4)}}}')
    return "\n".join(lines)


def build() -> dict:
    rng = random.Random(SEED)
    s = []  # sessions: list of {"turns": [{"user", "assistant"}], ...}

    def sess(turns, **extra):
        s.append({"index": len(s) + 1, "turns": [{"user": u, "assistant": a} for u, a in turns], **extra})

    sess([
        (f"Morning. I'm starting the {PROJECT} shipper rewrite today and want you as my pair for the next few weeks.",
         "Happy to pair on it. Tell me how the pieces fit and I'll keep track as we go."),
        ("Quick environment notes first: staging Postgres listens on port 6432, not the default.",
         "Noted: staging Postgres is on 6432. I'll use that whenever we touch the staging database."),
        ("And deploys only ever go out from the release/ember branch. Never from main.",
         "Understood. Deploys come from release/ember only, never from main."),
        ("First task: sketch the module layout for the new shipper.",
         "Proposed layout: cli/, spool/, transport/, and config/, with spool owning the on-disk queue."),
        ("Good enough for day one. Let's stop here.", "Sounds good. Next time we can start on the spool."),
    ])
    sess([
        ("Back on the spool. One constraint I forgot: CI runs on Python 3.12 only, so no 3.13 syntax.",
         "Got it: CI is Python 3.12 only. I'll keep the code to 3.12 features."),
        ("Also, every log line we emit must be JSON lines, one object per line. Ops parses them.",
         "Understood: all logging is JSON lines, one object per line."),
        ("The quiet_retry feature flag should default to off until ops signs it off.",
         "Noted: quiet_retry defaults to off."),
        ("Write me the spool's append path in outline.",
         "Outline: open the segment, append a length-prefixed record, fsync on the batch boundary, rotate at 64 MB."),
        ("Fine. That's it for today.", "Talk soon. Next up is the transport retry loop."),
    ])
    sess([
        ("Style rule before we commit anything: commit subjects stay under 50 characters, imperative mood.",
         "Noted: commit subjects under 50 characters, imperative mood."),
        ("We're entering a release freeze. After it ends I need to rotate the cache signing key, and I'll forget.",
         "I'll bring the cache-key rotation checklist when we meet after the freeze ends."),
        ("Draft a commit subject for the spool work.", "Suggested subject: \"Add length-prefixed spool append\"."),
        ("Now the transport retry loop: exponential backoff, capped.",
         "Backoff starts at 200 ms, doubles to a 30 s cap, with full jitter and a retry budget per batch."),
        ("Good. Done for today.", "Done. The retry loop is ready for review next time."),
    ])
    sess([
        ("Reviewing the retry loop. Does it respect the quiet_retry flag?",
         "Yes: with quiet_retry off, every retry logs a warn line; with it on, only the final failure logs."),
        ("Make the warn lines match our logging rule.", "They are emitted as single JSON objects, one per line."),
        ("What should the integration test target?", "The staging database on port 6432 and a stub collector."),
        ("Add a test for the backoff cap.", "Added: a test asserting no sleep exceeds 30 s across 12 retries."),
        ("Wrap up.", "Wrapped. Tests are green locally."),
    ])
    sess([
        ("Heads-up: ops moved staging Postgres to port 6543 this morning. The old 6432 port is gone.",
         "Thanks. Staging Postgres is now on 6543; I'll stop using 6432."),
        ("Update the integration test config accordingly.", "Updated: the integration test now targets port 6543."),
        ("Sorry, my machine crashed and I had to restart everything. Where were we?",
         "We had just moved the integration tests to staging port 6543 after ops changed it."),
        ("Right. Next: config loading from a TOML file.", "Config loads from tidewater.toml, with env vars overriding keys."),
        ("Enough for today.", "Okay. Next session we can harden the transport."),
    ], restart_after_turn=2)
    long_turns = []
    for i in range(14):
        svc = rng.choice(["transport", "spool", "collector"])
        long_turns.append((
            f"Long debugging sprint, chunk {i + 1}. Here is the next log excerpt from the soak run:\n"
            + _log_block(rng, 20, svc) + "\nWhat stands out?",
            f"In chunk {i + 1} the {svc} errors cluster around batch flush timeouts after backpressure engages; "
            "the retry counts climb to 4, which means the per-batch budget is exhausted before the collector acks."))
    long_turns.append(("Let's stop the sprint here.",
                       "Agreed. The fix is to raise the ack window and cap concurrent flushes."))
    sess(long_turns, long_session=True)
    sess([
        ("The release freeze is over as of today.",
         "Then here is the cache-key rotation checklist I promised: generate the new key, dual-sign for a day, "
         "switch readers, retire the old key."),
        ("Let's do the rotation tomorrow. Draft the commit subject.", "Suggested subject: \"Rotate cache signing key\"."),
        ("Does the deploy for this go from main?", "No. Deploys go out from release/ember only."),
        ("Good catch. Any CI concerns?", "None, as long as the rotation script stays on Python 3.12 features."),
        ("Done for now.", "Done. Rotation is planned for tomorrow."),
    ])
    sess([
        ("I'm back after three weeks away. Remind me what the shipper's logging rule is?",
         "Every log line is JSON lines, one object per line."),
        ("And which branch do we deploy from?", "release/ember."),
        ("Let's add a metrics endpoint.", "Proposed: a /metrics endpoint exposing spool depth and retry counts."),
        ("Ship it behind a flag.", "Added behind a new flag, metrics_endpoint, defaulting to off."),
        ("Wrap up.", "Wrapped."),
    ], gap_before=True)
    sess([
        ("Let's tidy the transport module.", "I suggest splitting the retry policy into its own file."),
        ("Do it.", "Split done: transport/retry_policy.py now owns the backoff."),
        ("Commit subject?", "Suggested subject: \"Split retry policy from transport\"."),
        ("Run the staging tests.", "Running against staging Postgres on port 6543 now."),
        ("Okay, stop.", "Stopped."),
    ])
    sess([
        ("Last session before the beta. What's left?", "Only the metrics endpoint review and the release notes."),
        ("Draft the release notes headline.", "Headline: \"Tidewater shipper beta: durable spool and capped retries\"."),
        ("Anything about quiet_retry in the notes?", "Yes: it ships off by default, pending the ops sign-off."),
        ("Good. Final check on logging.", "All emitters write JSON lines."),
        ("That's the beta. Thanks.", "Congratulations on the beta."),
    ])
    probes = [  # live-model probe sessions after the life; latency only, nothing is scored
        {"index": "P1", "turns": [{"user": "Quick check before I touch staging: which port does staging Postgres use?"},
                                  {"user": "What format do our log lines have to be in?"}]},
        {"index": "P2", "turns": [{"user": "Which Python version does CI run, and which branch do we deploy from?"},
                                  {"user": "Did you deliver what you promised for after the release freeze?"}]},
    ]
    return {"genre": "G1 software partner", "seed": SEED, "project": PROJECT, "synthetic": True,
            "facts": FACTS, "events": EVENTS, "sessions": s, "probes": probes}


def bundles_hostable(life: dict) -> dict:
    """Distinct (fact, probe point) pairs where the fact was told at least two sessions before the probe.

    A probe point j sits after session j (j = 1..S). A fact told in session t qualifies at j when
    j - t >= 2. Corrections and commitments count as facts (the correction's newest value)."""
    n = len(life["sessions"])
    pairs = [(f["id"], j) for f in life["facts"] for j in range(1, n + 1) if j - f["session"] >= 2]
    end_only = [f["id"] for f in life["facts"] if n - f["session"] >= 2]
    return {"probe_points": n, "pairs_all_boundaries": len(pairs), "pairs_end_of_life_only": len(end_only)}


if __name__ == "__main__":
    out = Path(__file__).with_name("micro_life.json")
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if out.exists() and out.read_text() == text else 1)
    out.write_text(text)
    print(json.dumps(bundles_hostable(build())))
