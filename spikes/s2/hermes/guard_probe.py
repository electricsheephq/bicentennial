"""Spike S2 guard probe: call Hermes' own wall-time guards under the shim, across a 3-day jump.

Run with the pinned Hermes venv python, the shim on PYTHONPATH, BICENTENNIAL_CLOCK_FILE set
and HERMES_HOME pointing at a throwaway CLONE of a run's home (the probe writes to it).
The probe rewrites clock.json itself to move simulated time (the shim re-reads it), so one
process sees sim A, A + 3 days and A + 8 days. Prints one JSON object (no paths, no content).

Guards probed (all reached through Hermes' own functions):
  curator_interval   agent.curator.should_run_now(): sim now vs stored last_run_at (7-day interval)
  curator_claim      agent.curator._claim_run(): sim now vs a fresh lock file's kernel mtime (1 h)
  scratch_prune      hermes_constants.prune_scratch_dir(): sim now vs kernel mtimes (24 h idle)
  metadata_cache_age agent.model_metadata._model_metadata_disk_cache_age_seconds(): sim vs mtime
"""

import json
import os
import sys
import time
from pathlib import Path


def set_clock(sim):
    path = Path(os.environ["BICENTENNIAL_CLOCK_FILE"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sim_start": sim, "wall_anchor": wall_now(), "rate": 1.0}))
    os.replace(tmp, path)
    time.sleep(0.4)  # past the shim's re-read throttle


def wall_now():
    # The real clock, for reporting the offset: the shim never patches os.stat on a fresh file.
    probe = Path(os.environ["HERMES_HOME"]) / ".s2_wall_probe"
    probe.write_text("x")
    return probe.stat().st_mtime


def main():
    sim_a = float(sys.argv[1])
    shimmed = bool(os.environ.get("BICENTENNIAL_CLOCK_FILE"))
    out = {"shimmed": shimmed, "guards": {}}
    if shimmed:
        set_clock(sim_a)
    out["offset_hours_sim_minus_wall"] = round((time.time() - wall_now()) / 3600, 2)

    import hermes_constants
    from agent import curator, model_metadata

    # curator_interval: the first call seeds last_run_at; later calls compare sim now against it.
    seq = []
    for label, delta_days in (("A", 0), ("A+3d", 3), ("A+8d", 8)):
        if shimmed:
            set_clock(sim_a + delta_days * 86400)
        seq.append({"at": label, "should_run": curator.should_run_now()})
        if not shimmed:
            break
    out["guards"]["curator_interval"] = {"interval_hours": curator.get_interval_hours(), "sequence": seq}

    # curator_claim: a lock created just now (kernel mtime = wall) must NOT be taken over.
    for label, delta_days in (("A", 0), ("A+3d", 3)):
        if shimmed:
            set_clock(sim_a + delta_days * 86400)
        lock = curator._run_claim_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.unlink(missing_ok=True)
        lock.write_text("held-by-another-process")
        took_over = curator._claim_run()
        out["guards"].setdefault("curator_claim", []).append({"at": label, "fresh_lock_taken_over": took_over})
        curator._release_run_claim()

    # scratch_prune: an entry written just now must survive; an entry backdated by 2 sim days
    # (via os.utime from sim time) should be pruned.
    for label, delta_days in (("A", 0), ("A+3d", 3)):
        if shimmed:
            set_clock(sim_a + delta_days * 86400)
        scratch = hermes_constants.get_scratch_dir(prune=False)
        fresh, old = scratch / f"s2-fresh-{label}", scratch / f"s2-old-{label}"
        fresh.write_text("x")
        old.write_text("x")
        two_days_ago = time.time() - 2 * 86400
        os.utime(old, (two_days_ago, two_days_ago))
        removed = hermes_constants.prune_scratch_dir(scratch)
        out["guards"].setdefault("scratch_prune", []).append(
            {"at": label, "removed": removed, "fresh_survived": fresh.exists(), "old_pruned": not old.exists()})

    # metadata_cache_age: a cache file written just now should read as ~0 s old.
    cache = model_metadata._get_model_metadata_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{}")
    age = model_metadata._model_metadata_disk_cache_age_seconds()
    out["guards"]["metadata_cache_age"] = {"fresh_file_age_seconds": None if age is None else round(age, 1)}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
