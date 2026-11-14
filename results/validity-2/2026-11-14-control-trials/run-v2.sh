#!/bin/bash
# Published copy: local paths are replaced by /path/to placeholders, four of them with a comment saying what the path holds,
# and one comment names the live-settings wrapper instead of its file; every other byte is the script that ran.
# Validity round 2 (#536; declaration results/validity-2/DECLARATION.md): the draw, the edition-3 validation pack of ten
# G1 lives, the frozen task list, the thirteen control arms in the declared order, check 3, and the table.
# Adapted from round 1's reviewed run-v2.sh; the changes are the round's parameters (labels, rows, edition, issue,
# paths, the roster's --round 2 and the task count) and the rehearsal's seeds and run-gate check.
# Private until the results PR: the draw, the spec, the placement table and TASKS.json live in $S/private ($S is 0700).
# The live settings' values are never printed: the live-settings wrapper ($ENVW) exports them into the command's own environment.
# Usage (run each long step with Bash run_in_background):
#   run-v2.sh prep <main sha>     fresh detached worktree at <sha> (must hold the declaration, edition 3, #529, the
#                                 roster's round 2 and the reading script), venv with [dev]
#   run-v2.sh rehearse            place/build/install/run gate/tasks/table/check 3 on the committed screening seeds, before the draw
#   run-v2.sh draw                the seed draw (needs a passed rehearsal at this commit); prints its sha256
#   run-v2.sh posted draw|tasks <#536 comment url>   checks the posted comment carries the hashes, and records it
#   run-v2.sh place               the round-2 placement dry run on the draw (ten G1 lives, edition 3), once its commitment is posted
#   run-v2.sh void                after a void placement: keep the void draw's files in private/void-N, for a new draw
#   run-v2.sh build               the edition-3 T2 build and install, once the draw is posted; prints the pack hash
#   run-v2.sh tasks               TASKS.json from the pack, written whole, then frozen; prints its sha256
#   run-v2.sh run <label>         one arm (F1 R1 B1 G1 W1 O1 O2 W2 G2 B2 R2 F2 O3, in that order) into runs/<label>,
#                                 once TASKS is posted
#   run-v2.sh rerun <label>       the one rerun of an arm that ran, into runs/<label>.rerun (after the arms already done)
#   run-v2.sh abandon <tag>       close an invocation whose wrapper was killed (no exit recorded), when no arm runs
#   run-v2.sh check3              the runner's control-arm tests at the run commit (at most two attempts, §4)
#   run-v2.sh table [--after-reruns]   the reading (table.py); the reruns used are the ones on disk, never chosen
# An invocation that the runner refuses before it creates its output directory is logged under its own number and is
# not an attempt (t2.py: "these refusals create no output, so the same command can run again"); the results disclose
# every invocation. So is a refusal by the runner's machine guard, which comes after the output folder but before any
# unit (guard_refused); its output is kept beside the invocation. Any other invocation that created output is the
# label's attempt; a label has one attempt and one rerun.
# Exit codes: the command's own; 4 = machine busy; 2 = a precondition failed.
set -uo pipefail
S=${V2_DIR:-/path/to/v2run}
OFFICIAL=/path/to/v2run
R=/path/to/bicentennial
REPO=electricsheephq/bicentennial
H=/path/to/hermes-agent  # the pinned Hermes source
ENVW=/path/to/live-env.sh  # exports the live settings into the command's own environment
LOGIN=/path/to/reader-login  # the benchmark's own reader login
MARKER=/path/to/busy-marker.sh
BASEPY=/path/to/python3.14
SLOT=/path/to/testslot.py  # the machine's one-at-a-time test slot
TABLE=results/validity-2/control-trials/table.py
TASKS_PY=results/validity-2/control-trials/tasks.py
ISSUE=536
ORDER=(F1 R1 B1 G1 W1 O1 O2 W2 G2 B2 R2 F2 O3)
# Each arm's send cap, as results/validity-2/DECLARATION.md §3 states it (#507): from measured counts, with headroom.
CAP=1000
refuse() { echo "$*"; exit 2; }
control_of() { case ${1:0:1} in F) echo no_memory ;; R) echo naive_rag ;; B) echo bm25 ;; G) echo grep ;;
  W) echo recent_window ;; O) echo oracle_evidence ;; *) return 1 ;; esac; }
idle() { local m i; for i in $(seq 1 61); do bash "$MARKER" >/dev/null 2>&1; m=$?; [[ $m == 0 ]] && return 0
  (( i == 1 )) && echo "busy marker reads $m; waiting for 0 ($(date -u +%TZ))"; sleep 60; done
  echo "busy marker still reads $m after 60 min, not 0"; exit 4; }
atcommit() { cd "$S/wt" || exit 2; export PYTHONHASHSEED=0
  [[ -z $(git status --porcelain) ]] || refuse "worktree is not clean"
  [[ $(git rev-parse HEAD) == $(cat "$S/commit.txt") ]] || refuse "worktree is not at the recorded commit"; }
lock() { mkdir "$S/lock" 2>/dev/null || refuse "another step holds $S/lock ($(ls "$S/lock" 2>/dev/null))"
  mkdir "$S/lock/$$" || exit 2; trap 'rmdir "$S/lock/$$" "$S/lock"' EXIT; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
# A running arm: the CLI re-executes itself as "python -m bicentennial.cli t2", so match both spellings; and every t2
# arm holds the login's account lock for its whole run (t2.py), so a lock that cannot be taken means an arm runs. The
# check opens only that lock file, the way t2.py does, and only from the official directory (any other uses its own).
arm_alive() { pgrep -f 'bicentennial(\.cli)? t2( |$)' >/dev/null && return 0
  local lockf=$LOGIN/.t2lite.lock; [[ $S -ef $OFFICIAL ]] || lockf=$S/.t2lite.lock
  ! python3 -c 'import fcntl, os, sys
fcntl.flock(os.open(sys.argv[1], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), fcntl.LOCK_EX | fcntl.LOCK_NB)' "$lockf" 2>/dev/null; }
hex64() { [[ $1 =~ ^[0-9a-f]{64}$ ]]; }
# Target items (§3): one twin pair per target template per life, ten lives; tasks.py's TARGET_TEMPLATES is the one list.
# (Edition 3 keeps every v3 in the pack even when the smoke drops one from that list, so a system run is still refused.)
target_count() { "$PY" -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("round2_tasks", sys.argv[1]); m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m); print(20 * len(m.TARGET_TEMPLATES))' "$TASKS_PY"; }
# §3 Reruns: an arm is rerun only when the latest table output (a table run or its --after-reruns pre-check) names it as
# pending or invalid, and that output is newer than every attempt so far: another arm's rerun can change the reference
# identity (check 4), so a reading made before it no longer stands. Usage: rerun_named LOGS_DIR RUNS_DIR LABEL.
rerun_named() { local f d last=""; for f in "$1"/table-*.txt; do [[ -e $f ]] || continue
    [[ -z $last || $f -nt $last ]] && last=$f; done
  [[ -n $last ]] || { echo "no table run has named $3: a rerun needs a recorded failure (§4); run run-v2.sh table first"; return 1; }
  for d in "$2"/*; do [[ -e $d ]] || continue; [[ $last -nt $d ]] \
    || { echo "the latest table output ($(basename "$last")) predates attempt $(basename "$d"): run run-v2.sh table again first"; return 1; }; done
  { sed -n 's/^pending before any score: \(.*\) - rerun once.*/\1/p' "$last" | tr ' ' '\n'
    sed -n 's/^INVALID CONTROL ROW //p' "$last"; } | grep -qx -- "$3" \
    || { echo "$(basename "$last") does not name $3 as pending or invalid: a passing arm is never rerun (§3, §4)"; return 1; }; }
posted_values() { case $1 in draw) echo "$(cat "$P/draw.sha256" 2>/dev/null) $(cat "$S/commit.txt")" ;;
  tasks) echo "$(cat "$P/TASKS.sha256" 2>/dev/null) $(cat "$S/pack-hash.txt" 2>/dev/null)" ;; esac; }
# A posting record binds the post to the exact values it carried: it is valid only while they are the current ones.
need_posted() { [[ -s $S/posted/$1.rec ]] || refuse "the $1 commitment is not recorded as posted on #$ISSUE (run-v2.sh posted $1 <url>)"
  [[ $(sed -n 2p "$S/posted/$1.rec") == "$(posted_values "$1")" ]] || refuse "the recorded $1 post carries other values than the current ones"; }
frozen_tasks() { [[ -e $P/TASKS.json && -s $P/TASKS.sha256 ]] || refuse "TASKS.json is not frozen yet"
  [[ $(sha "$P/TASKS.json") == $(cat "$P/TASKS.sha256") ]] || refuse "TASKS.json differs from its frozen sha256"; }
# Test hooks: V2_FAKE stands in for the arm, check 3 and table.py, but only in a directory carrying the test marker,
# which prep never writes, so no path, alias or variable can turn them on for the official run.
fake() { [[ -n ${V2_FAKE:-} && -e $S/.v2-test-dir && ! $S -ef $OFFICIAL ]]; }
# The runner's machine guard (t1.prepare's admission check, which reads the busy marker itself) refuses after the
# runner creates the output folder but before any pack read, unit or send. Its output is then a regular file
# refusal.json alone, holding only a guard code (guard.py's reasons, or roots_below_min), and the diagnostics folder is
# absent or holds only a regular manifest.json with no commit, files, failures or skips. Such an invocation is not an
# attempt: the marker changed between idle() and the runner's own read. Any other refusal or shape is unchanged.
guard_refused() { # out diag
  [[ -d $1 && ! -L $1 && $(ls -A "$1") == refusal.json && -f $1/refusal.json && ! -L $1/refusal.json ]] || return 1
  [[ ! -e $2 && ! -L $2 ]] || [[ -d $2 && ! -L $2 && $(ls -A "$2") == manifest.json && -f $2/manifest.json \
    && ! -L $2/manifest.json ]] || return 1
  python3 -I - "$1/refusal.json" "$2/manifest.json" 2>/dev/null <<'EOF'
import json, os, re, sys
refusal = json.load(open(sys.argv[1]))
code = refusal.get("code") if isinstance(refusal, dict) else None
guard = isinstance(code, str) and set(refusal) == {"code"} and (
    code in ("roots_below_min", "machine busy: heavy work refused")
    or re.fullmatch(r"machine guard refused: marker exit (None|[0-9]+)", code) is not None)
if guard and os.path.lexists(sys.argv[2]):
    manifest = json.load(open(sys.argv[2]))
    guard = isinstance(manifest, dict) and manifest.get("commit") is None and all(
        manifest.get(key) == [] for key in ("files", "failures", "skips"))
sys.exit(0 if guard else 1)
EOF
}
arm_cmd() { # out diag control
  if fake; then "$V2_FAKE" arm "$@"; return $?; fi
  bash "$ENVW" "$S/venv/bin/bicentennial" t2 --system hermes-native --packs "$S/packs" --pack-hash "$(cat "$S/pack-hash.txt")" \
    --hermes "$H" --login-home "$LOGIN" --max-sends "$CAP" --control "$3" --diagnostics "$2" --out "$1"; }
check3_cmd() { # basetemp
  if fake; then "$V2_FAKE" check3 "$@"; return $?; fi
  python3 "$SLOT" -- env PYTHONPATH="$S/wt/src" nice -n 19 "$PY" -m pytest -v -p no:cacheprovider \
    -o tmp_path_retention_policy=failed --basetemp="$1" tests/runner/test_control_arms.py; }
table_cmd() { if fake; then "$V2_FAKE" table "$@"; return $?; fi; "$PY" "$TABLE" "$@"; }
PY=$S/venv/bin/python; P=$S/private
case ${1:-} in
prep)
  SHA=${2:?main sha}
  git -C "$R" fetch -q origin main
  git -C "$R" merge-base --is-ancestor "$SHA" origin/main || refuse "$SHA is not on origin/main"
  for f in results/validity-2/DECLARATION.md src/bicentennial/items/editions.py scripts/validity_roster.py \
           specs/ring0/c7-edition3.json specs/ring0/control-only-packs.json "$TASKS_PY" "$TABLE"; do
    git -C "$R" cat-file -e "${SHA}:$f" 2>/dev/null || refuse "missing at $SHA: $f"; done
  git -C "$R" show "${SHA}:scripts/validity_roster.py" | grep -q -- '"--round"' || refuse "the roster at $SHA cannot place round 2"
  git -C "$R" show "${SHA}:src/bicentennial/items/editions.py" | grep -q '^    3: ' || refuse "edition 3 is not registered at $SHA"
  [[ -e $S ]] && refuse "$S already exists"
  mkdir -p "$S/runs" "$S/logs" "$S/diag" "$S/posted" "$P" && chmod 700 "$S" "$P" || exit 2
  git -C "$R" worktree add -q --detach "$S/wt" "$SHA" || exit 2
  git -C "$S/wt" rev-parse HEAD > "$S/commit.txt"
  "$BASEPY" -m venv "$S/venv" && nice -n 19 "$PY" -m pip install -q -e "$S/wt[dev]" || refuse "venv install failed"
  "$PY" -c 'import pytest' || refuse "pytest is missing from the venv"
  echo "prepared $SHA" ;;
rehearse)
  # Before the draw, at the run commit: place (round 2) -> build (edition 3) -> install -> the run gate's checks -> tasks
  # -> table's refusal path -> check 3, on the committed screening seeds (results/validity-2/screening: design seeds
  # 2001-2010; spares from 2021 by its README's rule), so an integration fault cannot void a real draw. Nothing here is
  # drawn, published or run by a reader. A failed rehearsal is kept aside, never deleted.
  atcommit; Rh=$S/rehearsal
  [[ -e $Rh/passed ]] && refuse "already rehearsed at $(cat "$Rh/passed")"
  [[ -e $P/draw.json ]] && refuse "the real draw exists; rehearse before it"
  if [[ -e $Rh ]]; then n=1; while [[ -e $Rh.failed-$n ]]; do n=$((n+1)); done
    mv -n "$Rh" "$Rh.failed-$n" && [[ ! -e $Rh ]] || exit 2; echo "an earlier failed rehearsal is kept in $Rh.failed-$n"; fi
  mkdir "$Rh" || exit 2
  "$PY" - "$Rh/draw.json" <<'EOF' || exit 2
import sys
from bicentennial.canon import canon
from bicentennial.world.targeted import load_tier
seeds = [row["seed"] for row in load_tier("results/validity-2/screening/t2-screen.toml")["lives"]][:10]
assert seeds == list(range(2001, 2011)), "the screening set's first ten seeds are not 2001-2010"
open(sys.argv[1], "wb").write(canon(dict(design=seeds, spares=list(range(2021, 2037)),
                                         drawn_at="rehearsal, committed screening seeds")) + b"\n")
print("rehearsal draw: committed screening seeds", len(seeds))
EOF
  "$PY" scripts/validity_roster.py place --round 2 --draw "$Rh/draw.json" --work "$Rh/place-work" --spec-out "$Rh/spec.toml" \
    --table-out "$Rh/placement.json" || refuse "rehearsal place failed"
  python3 "$SLOT" -- nice -n 19 "$S/venv/bin/bicentennial" build --tier T2 --spec "$Rh/spec.toml" --edition 3 \
    --out "$Rh/build" > "$Rh/build.log" 2>&1 || refuse "rehearsal build failed ($Rh/build.log)"
  "$PY" -m bicentennial.packs.install install "$Rh/build/T2" "$Rh/packs" > "$Rh/pack-hash.txt" || exit 2
  "$PY" - "$Rh/packs" "$(cat "$Rh/pack-hash.txt")" <<'EOF' || refuse "rehearsal run gate refused"
import sys
from pathlib import Path
from bicentennial.packs.install import verify
from bicentennial.runner import t1
from bicentennial.runner.units import T2_SPEC
packs, pack_hash = Path(sys.argv[1]), sys.argv[2]
index = verify(packs, pack_hash=pack_hash)
assert index["tier"] == T2_SPEC.pack_tier == "T2", index["tier"]
rels = sorted(index["packs"])
genres = sorted(t1._json(packs / rel / "sealed/meta.json")["genre"] for rel in rels)
# prepare's composition rule (runner/t1.py): ten G1 lives pass only for a control run; a system run stops here.
assert genres == ["G1"] * 10, genres
assert genres != sorted(T2_SPEC.composition)
assert any(genres == sorted(c) for c in T2_SPEC.control_compositions)
packed = tuple(t1._pack(packs, rel) for rel in rels)
t1._check_c7(packed, control=True)  # a control run: every C-7 entry accepted
try:
    t1._check_c7(packed, control=False)
except t1.T1Refused as error:
    assert str(error) == "template_not_admitted", str(error)
else:
    raise AssertionError("a non-control run passed the C-7 admission check on an edition-3 pack")
print("run gate: pack verified, tier T2, ten G1 lives (control composition only),",
      "C-7 accepted for a control run and template_not_admitted for a system run")
EOF
  "$PY" "$TASKS_PY" --packs "$Rh/packs" --spec "$Rh/spec.toml" --draw "$Rh/draw.json" \
    --commit "$(cat "$S/commit.txt")" --edition 3 --out "$Rh/TASKS.json" || refuse "rehearsal tasks refused"
  n=$(target_count) || refuse "cannot read the target templates from $TASKS_PY"
  "$PY" -c 'import json, sys; t = json.load(open(sys.argv[1])); assert len(t["rows"]) == int(sys.argv[2]), len(t["rows"])' \
    "$Rh/TASKS.json" "$n" || refuse "the rehearsal task list does not hold $n target items (§3)"
  mkdir -p "$Rh/no-arms"
  noarms=""; for l in "${ORDER[@]}"; do noarms="$noarms $l=$Rh/no-arms/$l"; done
  "$PY" "$TABLE" --tasks "$Rh/TASKS.json" --tasks-sha256 "$(sha "$Rh/TASKS.json")" --packs "$Rh/packs" \
    --order "$(IFS=,; echo "${ORDER[*]}")" $noarms; x=$?
  [[ $x == 4 ]] || refuse "table.py on no arms exited $x, not 4"
  { echo "commit $(git rev-parse HEAD)"; check3_cmd "$Rh/check3-tmp"; x=$?; echo "exit $x"; } > "$Rh/check3.txt" 2>&1
  [[ $x == 0 ]] || refuse "rehearsal check 3 failed ($Rh/check3.txt)"
  git rev-parse HEAD > "$Rh/passed"
  echo "rehearsal passed at $(cat "$Rh/passed"): place (round 2), build (edition 3), install, run gate, tasks ($n), table refusal path, check 3" ;;
draw)
  atcommit
  [[ $(cat "$S/rehearsal/passed" 2>/dev/null) == $(cat "$S/commit.txt") ]] || refuse "rehearse at the run commit first"
  [[ -e $P/draw.json || -e $P/draw.sha256 ]] && refuse "already drawn"
  [[ -e $S/posted/draw.rec || -e $S/posted/draw.body || -e $P/placement.json || -e $S/place-work ]] && refuse "a void draw is not fully archived; run-v2.sh void"
  for v in "$P"/void-*; do [[ -d $v && ! -e $v/complete ]] && refuse "$(basename "$v") is incomplete; run-v2.sh void"; done
  "$PY" scripts/validity_roster.py draw --out "$P/draw.json" || exit $?
  sha "$P/draw.json" > "$P/draw.sha256"
  echo "$(date -u +%FT%TZ) draw sha256 $(cat "$P/draw.sha256")" >> "$P/draws.log"
  echo "post on #$ISSUE: run commit $(cat "$S/commit.txt") and draw sha256 $(cat "$P/draw.sha256"); then run-v2.sh posted draw <url>" ;;
posted)
  kind=${2:?draw or tasks}; url=${3:?the #$ISSUE comment url}
  atcommit
  case $kind in
    draw) [[ -s $P/draw.sha256 && -e $P/draw.json ]] || refuse "no draw" ;;
    tasks) frozen_tasks; hex64 "$(cat "$S/pack-hash.txt")" || refuse "no pack hash" ;;
    *) refuse "posted draw|tasks <url>" ;;
  esac
  need=$(posted_values "$kind")
  [[ -e $S/posted/$kind.rec ]] && refuse "the $kind post is already recorded: $(head -1 "$S/posted/$kind.rec")"
  [[ $url =~ ^https://github\.com/electricsheephq/bicentennial/issues/${ISSUE}#issuecomment-([0-9]+)$ ]] || refuse "not a #$ISSUE comment url"
  id=${BASH_REMATCH[1]}
  other=draw; [[ $kind == draw ]] && other=tasks
  [[ -e $S/posted/$other.rec && $(head -1 "$S/posted/$other.rec") == "$url" ]] && refuse "that comment is already the $other post"
  got=$(gh api "repos/$REPO/issues/comments/$id" --jq '.issue_url + " " + .created_at + " " + .updated_at + "\n" + .body') \
    || refuse "the comment cannot be read"
  read -r iurl created updated <<< "${got%%$'\n'*}"; body=${got#*$'\n'}
  [[ $iurl == "https://api.github.com/repos/$REPO/issues/$ISSUE" ]] || refuse "the comment is not on #$ISSUE"
  for h in $need; do [[ $body == *"$h"* ]] || refuse "the comment does not carry $h"; done
  # A commitment is the comment as first posted: one GitHub shows as edited is refused (post a new one; comments are never
  # deleted). The times have one-second resolution, so this cannot exclude an edit within that second; the body checked
  # is kept beside the record.
  [[ -n $created && $created == "$updated" ]] || refuse "the comment was edited after it was posted ($created, $updated); post a new one"
  printf '%s\n' "$body" > "$S/posted/$kind.body"
  printf '%s\n%s\n%s\n' "$url" "$need" "posted $created" > "$S/posted/$kind.rec"; echo "recorded: the $kind commitment is posted ($url, $created)" ;;
place)
  atcommit; [[ -e $P/draw.json ]] || refuse "no draw"; need_posted draw
  [[ $(sha "$P/draw.json") == $(cat "$P/draw.sha256") ]] || refuse "draw.json differs from its recorded sha256"
  # Each placement's printout (its counts and the spec and table sha256) is kept, numbered across draws.
  k=1; while [[ -e $S/logs/place-$k.txt ]]; do k=$((k+1)); done
  "$PY" scripts/validity_roster.py place --round 2 --draw "$P/draw.json" --work "$S/place-work" \
    --spec-out "$P/t2-validity.toml" --table-out "$P/placement.json" 2>&1 | tee "$S/logs/place-$k.txt"; st=("${PIPESTATUS[@]}")
  [[ ${st[1]} == 0 ]] || { echo "the placement log logs/place-$k.txt was not written whole (placement exit ${st[0]})"; exit 2; }
  exit "${st[0]}" ;;
void)
  # After a void placement (§2): keep the void draw, its hash, its posting, its receipt and its work dir together and
  # apart, so a new draw follows by the same rules (run-v2.sh draw, then its own post on #536). Nothing is deleted;
  # private/draws.log keeps every draw's sha256.
  # An interrupted void resumes into its own void-N (the one without a complete marker); the posting record moves first,
  # so a new draw can never meet the old post.
  atcommit; lock
  n=""; for v in "$P"/void-*; do [[ -d $v && ! -e $v/complete ]] && n=${v##*/void-}; done
  if [[ -z $n ]]; then
    [[ -e $P/placement.json ]] || refuse "no placement receipt"
    "$PY" -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) and d.get("void") is True else 1)' \
      "$P/placement.json" || refuse "the placement is not void"
    [[ -e $P/t2-validity.toml ]] && refuse "a spec exists beside a void receipt"
    n=1; while [[ -e $P/void-$n ]]; do n=$((n+1)); done; mkdir "$P/void-$n" || exit 2
  fi
  V=$P/void-$n
  for pair in "$S/posted/draw.rec:posted-draw.rec" "$S/posted/draw.body:posted-draw.body" "$P/draw.json:draw.json" "$P/draw.sha256:draw.sha256" \
              "$P/placement.json:placement.json" "$S/place-work:place-work"; do
    src=${pair%%:*}; dst=$V/${pair##*:}
    if [[ -e $src ]]; then [[ -e $dst ]] && refuse "both $src and $dst exist"; mv -n "$src" "$dst" || exit 2; fi
    [[ -e $src ]] && refuse "the move is incomplete: $src"; done
  [[ -e $V/draw.json && -e $V/placement.json ]] || refuse "$V lacks its draw or its receipt"
  date -u +%FT%TZ > "$V/complete"
  echo "void draw kept in $V; next: run-v2.sh draw, and post the new commitment on #$ISSUE" ;;
build)
  atcommit; need_posted draw; [[ -e $P/t2-validity.toml ]] || refuse "no spec"
  [[ -e $S/pack-hash.txt ]] && refuse "already built"
  for d in build packs; do if [[ -e $S/$d ]]; then n=1; while [[ -e $S/$d.failed-$n ]]; do n=$((n+1)); done
    mv -n "$S/$d" "$S/$d.failed-$n" && [[ ! -e $S/$d ]] || exit 2; echo "an earlier failed $d is kept in $S/$d.failed-$n"; fi; done
  b=1; while [[ -e $S/logs/build-$b.log ]]; do b=$((b+1)); done
  python3 "$SLOT" -- nice -n 19 "$S/venv/bin/bicentennial" build --tier T2 --spec "$P/t2-validity.toml" --edition 3 \
    --out "$S/build" > "$S/logs/build-$b.log" 2>&1 || refuse "T2 build failed (logs/build-$b.log)"
  "$PY" -m bicentennial.packs.install install "$S/build/T2" "$S/packs" > "$S/logs/pack-hash.part" || refuse "install failed"
  hex64 "$(cat "$S/logs/pack-hash.part")" || refuse "install printed no pack hash"
  mv -n "$S/logs/pack-hash.part" "$S/pack-hash.txt" && [[ ! -e $S/logs/pack-hash.part ]] || exit 2
  echo "edition-3 validation pack hash $(cat "$S/pack-hash.txt")" ;;
tasks)
  atcommit; need_posted draw; hex64 "$(cat "$S/pack-hash.txt" 2>/dev/null)" || refuse "no pack hash"
  [[ -e $P/TASKS.json || -e $P/TASKS.json.part || -e $P/TASKS.sha256 ]] && refuse "already frozen, or a partial write exists"
  ls "$S/runs" | grep -q . && refuse "an arm has already run; the list must be frozen before arm 1"
  n=$(target_count) || refuse "cannot read the target templates from $TASKS_PY"
  "$PY" "$TASKS_PY" --packs "$S/packs" --spec "$P/t2-validity.toml" \
    --draw "$P/draw.json" --commit "$(cat "$S/commit.txt")" --edition 3 --out "$P/TASKS.json.part" || exit $?
  "$PY" - "$P/TASKS.json.part" "$(cat "$S/commit.txt")" "$(cat "$S/pack-hash.txt")" "$(cat "$P/draw.sha256")" \
    "$(sha "$P/t2-validity.toml")" "$n" <<'EOF' || refuse "the written task list fails its check"
import json, sys
t = json.load(open(sys.argv[1]))
h = t["header"]
assert (h["commit"], h["edition"], h["pack_hash"], h["draw_sha256"], h["spec_sha256"]) == (sys.argv[2], 3, *sys.argv[3:6]), h
assert len(t["rows"]) == int(sys.argv[6]), len(t["rows"])  # §3: one twin pair per target template per life
EOF
  mv -n "$P/TASKS.json.part" "$P/TASKS.json" && [[ ! -e $P/TASKS.json.part ]] || exit 2
  sha "$P/TASKS.json" > "$P/TASKS.sha256"
  echo "frozen: TASKS.json sha256 $(cat "$P/TASKS.sha256"), pack hash $(cat "$S/pack-hash.txt"); post both on #$ISSUE, then run-v2.sh posted tasks <url>" ;;
run|rerun)
  label=${2:?label}; control=$(control_of "$label") || refuse "unknown label $label"
  printf '%s\n' "${ORDER[@]}" | grep -qx "$label" || refuse "unknown label $label"
  atcommit; lock; frozen_tasks; need_posted tasks
  if [[ $1 == run ]]; then
    for l in "${ORDER[@]}"; do [[ $l == "$label" ]] && break
      [[ -e $S/runs/$l ]] || refuse "$l has no attempt yet; the declared order is ${ORDER[*]}"; done
    [[ -e $S/runs/$label ]] && refuse "$label already has its attempt; its one rerun is run-v2.sh rerun $label"
    tag=$label
  else
    [[ -e $S/runs/$label ]] || refuse "$label has no attempt, so there is nothing to rerun"
    [[ -e $S/runs/$label.rerun ]] && refuse "$label has had its one rerun (§4)"
    for e in "$S"/logs/table-*.exit; do [[ -e $e ]] || continue
      case $(cat "$e") in 0|5) refuse "the scores are open or the round has ended ($(basename "$e")): no rerun after that (§4)" ;; esac; done
    for e in "$S"/logs/table-*.pre-exit; do [[ -e $e && $(cat "$e") == 5 ]] && refuse "the round has ended ($(basename "$e")): no rerun after that (§4)"; done
    for e in "$S"/logs/table-*.txt; do [[ -e $e ]] && grep -qE '^(== 3\. Scores by template|ROUND ENDS:)' "$e" \
      && refuse "$(basename "$e") opened the scores or ended the round: no rerun after that (§4)"; done
    [[ -e $P/check3-2.txt && $(tail -1 "$P/check3-2.txt") != "exit 0" ]] && refuse "check 3 failed its second attempt: the round has ended (§4)"
    why=$(rerun_named "$S/logs" "$S/runs" "$label") || refuse "$why"
    tag=$label.rerun
  fi
  out=$S/runs/$tag; diag=$S/diag/$tag
  [[ -e $diag ]] && refuse "$diag exists without its run; inspect it before going on"
  for f in "$S"/logs/"$tag".inv-*.start; do [[ -e $f && ! -e ${f%.start}.exit ]] && refuse "$(basename "$f") has no exit; run-v2.sh abandon $tag"; done
  # A real arm runs only in the official directory (a test directory holds packs no reader may see).
  fake || [[ $S -ef $OFFICIAL ]] || refuse "a real arm runs only in $OFFICIAL"
  arm_alive && refuse "an arm process is already running"
  idle
  k=1; while [[ -e $S/logs/$tag.inv-$k.start ]]; do k=$((k+1)); done
  # The run order's sequence number: one more than every number already recorded (no counter file to lose).
  seq=$(cat "$S"/logs/*.seq 2>/dev/null | sort -n | tail -1); seq=$(( ${seq:-0} + 1 ))
  I=$S/logs/$tag.inv-$k; echo "$seq" > "$I.seq"; date -u +%FT%TZ > "$I.start"
  arm_cmd "$out" "$diag" "$control" > "$I.out" 2> "$I.err"; x=$?
  date -u +%FT%TZ > "$I.end"; echo "exit=$x" > "$I.exit"
  if [[ $x == 3 ]] && guard_refused "$out" "$diag"; then
    # Kept beside the invocation, never deleted; the label has made no attempt.
    mv -n "$out" "$I.guard-out" && [[ ! -e $out ]] || exit 2
    if [[ -e $diag ]]; then mv -n "$diag" "$I.guard-diag" && [[ ! -e $diag ]] || exit 2; fi
    echo "$tag invocation $k exit 3, refused by the runner's machine guard ($(cat "$I.guard-out/refusal.json")) before any unit ran: not an attempt; run the same command again"
    exit $x
  fi
  if [[ -e $out ]]; then
    for s in seq start end exit; do cp -n "$I.$s" "$S/logs/$tag.$s" || exit 2; done
    echo "$tag ($control) attempt (invocation $k) exit $x; outputs: $(ls "$out" | wc -l | tr -d ' ') files; diagnostics: $(ls "$diag" 2>/dev/null | wc -l | tr -d ' ') entries"
  else
    echo "$tag invocation $k exit $x, refused before creating its output: not an attempt; see $I.err, fix the cause and run the same command again"
  fi
  exit $x ;;
abandon)
  # A wrapper killed mid-arm leaves an invocation with no exit. With no arm process left, record it as abandoned; if it
  # created output it is the label's attempt (its rerun is then the next step), otherwise it is not an attempt.
  # The live-wrapper check comes first: only a wrapper starts an arm, so with none alive the arm probe cannot race one.
  tag=${2:?tag}; atcommit
  owner=$(ls "$S/lock" 2>/dev/null)
  [[ -n $owner ]] && ps -p "$owner" >/dev/null 2>&1 && refuse "a step (pid $owner) still holds the lock"
  [[ -d $S/lock && -z $owner && $(( $(date +%s) - $(stat -f %m "$S/lock") )) -lt 60 ]] && refuse "the lock has no owner yet (a step may be starting); retry in a minute"
  arm_alive && refuse "an arm process is still running"
  # Remove only the lock read above as stale: a dead owner's, or an ownerless one at least 60 s old (never a lock that
  # appeared after the read, which a starting step may hold).
  removed=""; if [[ -d $S/lock ]]; then
    if [[ -n $owner ]]; then rmdir "$S/lock/$owner" && rmdir "$S/lock" && removed=1
    elif (( $(date +%s) - $(stat -f %m "$S/lock") >= 60 )); then rmdir "$S/lock" && removed=1; fi
    [[ -n $removed ]] && echo "removed the stale lock of pid ${owner:-unknown}"; fi
  open=""; for f in "$S"/logs/"$tag".inv-*.start; do [[ -e $f && ! -e ${f%.start}.exit ]] && open=${f%.start}; done
  if [[ -z $open ]]; then [[ -n $removed ]] && { echo "$tag has no open invocation; only the stale lock was removed"; exit 0; }
    refuse "$tag has no invocation without an exit"; fi
  date -u +%FT%TZ > "$open.end"; echo "exit=abandoned" > "$open.exit"
  if [[ -e $S/runs/$tag ]]; then for s in seq start end exit; do cp -n "$open.$s" "$S/logs/$tag.$s" || exit 2; done; fi
  echo "abandoned $(basename "$open")$([[ -e $S/runs/$tag ]] && echo "; it created output, so it is $tag's attempt")" ;;
check3)
  # Each attempt keeps its own file and temp folder (§4: a second failure ends the round, so both are evidence).
  atcommit; lock
  n=1; while [[ -e $P/check3-$n.txt ]]; do n=$((n+1)); done
  (( n > 2 )) && refuse "check 3 has run twice; §4 allows no third attempt"
  (( n == 2 )) && [[ $(tail -1 "$P/check3-1.txt") == "exit 0" ]] && refuse "check 3 passed on its first attempt; no second attempt"
  { echo "commit $(git rev-parse HEAD)"; check3_cmd "$S/check3-tmp-$n"; x=$?; echo "exit $x"; } > "$P/check3-$n.txt" 2>&1
  echo "check 3 attempt $n: $(tail -1 "$P/check3-$n.txt")"; exit $x ;;
table)
  shift; atcommit; lock; frozen_tasks
  for f in "$S"/logs/*.inv-*.start; do [[ -e $f && ! -e ${f%.start}.exit ]] && refuse "$(basename "$f") has no exit; run-v2.sh abandon first"; done
  arm_alive && refuse "an arm process is still running"
  after=""
  while (( $# )); do case $1 in --after-reruns) after=1 ;; *) refuse "unknown option $1" ;; esac; shift; done
  c3=$P/check3-1.txt; [[ -e $P/check3-2.txt ]] && c3=$P/check3-2.txt; [[ -e $c3 ]] || refuse "run check3 first"
  reruns=""; args=""; for l in "${ORDER[@]}"; do
    if [[ -e $S/runs/$l.rerun ]]; then reruns="$reruns,$l"; args="$args $l=$S/runs/$l.rerun"; else args="$args $l=$S/runs/$l"; fi; done
  reruns=${reruns#,}
  # --order: the used attempts (a rerun stands in for its label) in the order they ran, by the run's own sequence numbers;
  # --attempts: every attempt in that order, for the exact row centres (§3). Refused invocations are not attempts.
  order=$(for l in "${ORDER[@]}"; do t=$l; [[ -e $S/runs/$l.rerun ]] && t=$l.rerun
      [[ -e $S/logs/$t.seq ]] || { echo "no attempt record for $t" >&2; exit 2; }
      echo "$(cat "$S/logs/$t.seq") $l"; done | sort -n | awk '{print $2}' | paste -sd, -) || exit 2
  attempts=$(for f in "$S"/logs/*.seq; do [[ -e $f ]] || continue; b=$(basename "$f" .seq)
      [[ $b == *.inv-* ]] && continue; echo "$(cat "$f") $b"; done | sort -n | awk '{print $2}' | paste -sd, -) || exit 2
  echo "order the used attempts ran: $order | every attempt: $attempts | reruns used: ${reruns:-none}"
  # Each table run reserves its number before it starts, so an interrupted run keeps its own files.
  n=1; while [[ -e $S/logs/table-$n.flags ]]; do n=$((n+1)); done
  rflag=""; [[ -n $reruns ]] && rflag="--reruns $reruns"
  flags=$rflag; [[ -n $after ]] && flags="--after-reruns $rflag"
  echo "${flags:-none}" > "$S/logs/table-$n.flags"
  common="--tasks $P/TASKS.json --tasks-sha256 $(cat "$P/TASKS.sha256") --packs $S/packs --order $order --attempts $attempts --check3 $c3"
  if [[ -n $after ]]; then
    # --after-reruns only when the reruns it closes have run. The pending arms are recomputed now, by table.py's own
    # checks without the flag on the current attempts (a rerun can change the reference identity), and every pending
    # arm must have its rerun on disk; or check 3 has failed its second attempt, which ends the round (§4).
    table_cmd $common --checks-only $rflag $args > "$S/logs/table-$n.pre.txt" 2>&1; pre=$?; echo "$pre" > "$S/logs/table-$n.pre-exit"
    if [[ -e $P/check3-2.txt && $(tail -1 "$P/check3-2.txt") != "exit 0" ]]; then :
    elif [[ $pre == 5 ]]; then :  # a rerun failed its check again: the round has ended (§4); the run below records it
    elif [[ $pre == 4 ]]; then
      pending=$(sed -n 's/^pending before any score: \(.*\) - rerun once.*/\1/p' "$S/logs/table-$n.pre.txt" | tail -1)
      [[ -n $pending ]] || refuse "table.py exited 4 but listed no pending arm (logs/table-$n.pre.txt)"
      for l in $pending; do [[ -e $S/runs/$l.rerun ]] || refuse "$l is pending now and has not been rerun (logs/table-$n.pre.txt)"; done
    elif [[ $pre == 0 ]]; then refuse "nothing is pending: run table without --after-reruns"
    else refuse "table.py's checks without --after-reruns exit $pre (logs/table-$n.pre.txt): read them first"; fi
  fi
  # $common, $flags and $args hold no spaces inside a word (labels, hashes and scratch paths), so splitting is intended.
  table_cmd $common --filter-out "$P/FILTER-$n.json" $flags $args | tee "$S/logs/table-$n.txt"
  x=${PIPESTATUS[0]}; echo "$x" > "$S/logs/table-$n.exit"; exit $x ;;
*) echo "usage: run-v2.sh prep <sha> | rehearse | draw | posted draw|tasks <url> | place | void | build | tasks | run <label> | rerun <label> | abandon <tag> | check3 | table [--after-reruns]"; exit 2 ;;
esac
