#!/usr/bin/env bash
# Spike S2, Claude Code half.
#   NODE_PKG     installed @anthropic-ai/claude-code Node build (a version that ships cli.js)
#   NATIVE_PKG   installed @anthropic-ai/claude-code native build (bin/claude.exe)
#   BULK_DIR     regenerable isolated HOME/config roots (created)
#   EVIDENCE_DIR ledgers, stdout/stderr, per-run check.json (created)
set -euo pipefail
: "${NODE_PKG:?}" "${NATIVE_PKG:?}" "${BULK_DIR:?}" "${EVIDENCE_DIR:?}"
HERE="$(cd "$(dirname "$0")" && pwd)"
NICE=(nice -n 19 taskpolicy -b)
T0_PAST=1740992400     # 2025-03-03T09:00:00Z
T0_FUTURE=1803891600   # 2027-03-01T09:00:00Z

run() {  # name, preload, t0, entry...
  local name="$1" preload="$2" t0="$3"; shift 3
  rm -rf "$BULK_DIR/cc/$name"
  "${NICE[@]}" python3 "$HERE/run_claude.py" --root "$BULK_DIR/cc/$name" --evidence-dir "$EVIDENCE_DIR/cc-$name" \
    --t0 "$t0" --preload "$preload" --entry "$@"
  local proj
  proj="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["project_dir_name"])' "$EVIDENCE_DIR/cc-$name/run.json")"
  "${NICE[@]}" python3 "$HERE/check_claude.py" --run-dir "$EVIDENCE_DIR/cc-$name" --root "$BULK_DIR/cc/$name" \
    --project-dir "${TMPDIR%/}/$proj" --out "$EVIDENCE_DIR/cc-$name/check.json" > /dev/null
  # transcripts left after both sessions (the retention cleanup compares file times with Date.now)
  find "$BULK_DIR/cc/$name/config/projects" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ' > "$EVIDENCE_DIR/cc-$name/transcripts.count"
}

mkdir -p "$BULK_DIR/cc" "$EVIDENCE_DIR"
NODE_ENTRY=(node "$NODE_PKG/cli.js")
NATIVE_ENTRY=("$NATIVE_PKG/bin/claude.exe")
run node-control none 0 "${NODE_ENTRY[@]}"
run node-past node "$T0_PAST" "${NODE_ENTRY[@]}"
run node-future node "$T0_FUTURE" "${NODE_ENTRY[@]}"
run native-node-options node "$T0_PAST" "${NATIVE_ENTRY[@]}"
run native-bun-preload bun "$T0_PAST" "${NATIVE_ENTRY[@]}"
echo done
