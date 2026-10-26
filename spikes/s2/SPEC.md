# S2: simulated clocks

**Question.** Can each harness run on simulated time, so that a 3-day gap in a life is seen consistently by the harness and its memory, with no wall-time guard tripped?

## Method
- **Hermes.** A `sitecustomize` shim on the interpreter's path patches `time.time`, `time.time_ns`, `time.localtime` and `time.gmtime` (no-argument forms), `datetime.datetime.now`, `utcnow` and `today`, and `datetime.date.today`, reading the simulated instant from a `clock.json` the director writes. The spike checks:
  - the date Hermes puts in its own prompts, captured by a local recording stub that stands in for the model;
  - every timestamp Hermes stores (session rows, message rows, memory files), against the session's simulated window;
  - SQLite's own `now`, which a Python shim cannot reach. Each such column is listed, with a proposed handling;
  - Hermes' own time module and any wall-time guard (idle resets, cooldowns, schedulers), and how each behaves across a simulated 3-day jump.
- **Claude Code.** Whether the pinned version ships a Node build. If it does: run it with `NODE_OPTIONS=--require` and a `Date` shim, against the same local recording stub, with a placeholder API key, an isolated configuration directory and non-essential traffic disabled. Check the date it puts in its system prompt and the timestamps in its session files. If no Node build exists, record that and the fallback.
- **Fallback, in every case:** the director rewrites dates in requests, the generator sets git and file times, and the card discloses wall-compressed timestamps. The spike lists what the fallback cannot cover.

No real model is called: the stub returns canned responses.

## Done when
`spikes/s2/REPORT.md` shows, for Hermes and for Claude Code, whether a simulated 3-day gap is seen consistently (prompt date, stored timestamps), lists every timestamp the shim cannot reach, and lists every wall-time guard found and its behaviour.

## Does not prove
- That every memory plug-in honours the shim: each plug-in's own clocks are checked when it is onboarded.
- Anything about Codex, whose clock needs a VM and is deferred.
