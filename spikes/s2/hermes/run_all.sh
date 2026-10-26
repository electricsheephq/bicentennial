#!/usr/bin/env bash
# Spike S2, Hermes half: four runs, their checks, and the guard probes.
#   HERMES_DIR    pinned Hermes checkout (read-only; its .venv runs Hermes)
#   BULK_DIR      regenerable homes and clones (created)
#   EVIDENCE_DIR  ledgers, stdout/stderr, per-run check.json (created)
# Every process runs under nice/taskpolicy. No network beyond the 127.0.0.1 stub.
set -euo pipefail
: "${HERMES_DIR:?}" "${BULK_DIR:?}" "${EVIDENCE_DIR:?}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SHIM="$(cd "$HERE/../clockshim" && pwd)"
NICE=(nice -n 19 taskpolicy -b)
PY="$HERMES_DIR/.venv/bin/python"

T0_PAST=1740992400     # 2025-03-03T09:00:00Z (a Monday)
T0_FUTURE=1803891600   # 2027-03-01T09:00:00Z (a Monday)

run() {  # name, extra args...
  local name="$1"; shift
  "${NICE[@]}" python3 "$HERE/run_hermes.py" --hermes-dir "$HERMES_DIR" --home "$BULK_DIR/homes/$name" \
    --evidence-dir "$EVIDENCE_DIR/hermes-$name" "$@"
  "${NICE[@]}" python3 "$HERE/check_hermes.py" --run-dir "$EVIDENCE_DIR/hermes-$name" \
    --home "$BULK_DIR/homes/$name" --out "$EVIDENCE_DIR/hermes-$name/check.json" > /dev/null
}

probe() {  # name, sim_start or "wall"
  local name="$1" sim="$2" clone="$BULK_DIR/probe-homes/$1"
  rm -rf "$clone"
  cp -cR "$BULK_DIR/homes/$name" "$clone"
  if [ "$sim" = wall ]; then
    env -u PYTHONPATH -u BICENTENNIAL_CLOCK_FILE HERMES_HOME="$clone" PYTHONDONTWRITEBYTECODE=1 \
      "${NICE[@]}" "$PY" "$HERE/guard_probe.py" "$(date +%s)" > "$EVIDENCE_DIR/hermes-$name/guards.json"
  else
    HERMES_HOME="$clone" PYTHONPATH="$SHIM" BICENTENNIAL_CLOCK_FILE="$BULK_DIR/probe-homes/$name.clock.json" \
      PYTHONDONTWRITEBYTECODE=1 "${NICE[@]}" "$PY" "$HERE/guard_probe.py" "$sim" \
      > "$EVIDENCE_DIR/hermes-$name/guards.json"
  fi
}

mkdir -p "$BULK_DIR/homes" "$BULK_DIR/probe-homes" "$EVIDENCE_DIR"
for n in control past-default past future; do rm -rf "$BULK_DIR/homes/$n" "$BULK_DIR/homes/$n.clock.json"; done

run control --t0 0 --no-shim
run past-default --t0 "$T0_PAST"
run past --t0 "$T0_PAST" --passthrough
run future --t0 "$T0_FUTURE" --passthrough

for n in past future; do
  t0=$([ "$n" = past ] && echo "$T0_PAST" || echo "$T0_FUTURE")
  # the shim needs a valid clock file at interpreter start; the probe then moves it itself
  printf '{"sim_start": %s, "wall_anchor": %s, "rate": 1.0}' "$t0" "$(date +%s)" > "$BULK_DIR/probe-homes/$n.clock.json"
  probe "$n" "$t0"
done
probe control wall
echo "done"
