#!/bin/bash
# Fresh-seed follow-up: run each step at the recorded commit.
# prep <sha> <PR> [...] [--import none]  fix local settings and prerequisites.
# rehearse                              exercise the committed tools before a beacon.
# post-commit                           adopt or post the counted commitment.
# beacon                                wait for the counted round through the draw record.
# draw                                  derive and verify the committed draw.
# post-draw                             match or post the second commitment.
# place                                 independently reproduce placement or its void.
# build                                 build and install A, B and C in order.
# tasks                                 freeze the three task lists.
# rebuild                               retry one failed build attempt from the beacon.
# post-tasks                            match or post all pack and task-list hashes.
# check3                                retain up to two control-test attempts.
# run <label>                           run the next first attempt.
# table [--after-reruns]                 retain a reading of the attempts on disk.
# rerun <label>                         run the one rerun the latest reading names.
# abandon <tag>                         close a dead invocation and its stale lock.
# cards                                 cut used cards and replaced first cards.
# stop beacon|build                     post only a recorded declaration stop.
# release                               publish records after a declared terminal event.
# Refusals before output and machine-guard refusals before any unit are invocations,
# not attempts. Every other invocation that created output is an attempt.
set -uo pipefail
ORDER=(A.F1 A.R1 A.O1 A.H1 A.H2 A.O2 A.R2 A.F2 A.O3 A.B1 A.G1 A.W1
       B.F1 B.R1 B.O1 B.H1 B.H2 B.O2 B.R2 B.F2 B.O3 B.G1 B.W1 B.B1
       C.F1 C.R1 C.O1 C.H1 C.H2 C.O2 C.R2 C.F2 C.O3 C.W1 C.B1 C.G1)
CAP=1000
REPO=electricsheephq/bicentennial
S=${FOLLOWUP_STATE:-}; R=${FOLLOWUP_REPO:-}; H=${FOLLOWUP_HERMES:-}
ENVW=${FOLLOWUP_WRAPPER:-}; LOGIN=${FOLLOWUP_LOGIN_HOME:-}; MARKER=${FOLLOWUP_MARKER:-}
BASEPY=${FOLLOWUP_PYTHON:-}; SLOT=${FOLLOWUP_SLOT:-}
ORIGIN_MARKER=${ORIGIN_MARKER:-}
P=$S/private; PY=$S/venv/bin/python
TABLE=results/followup/run/table.py
TASKS_PY=results/followup/run/tasks.py
DR_PY=results/followup/run/draw_record.py
OFFICIAL_RECORD=${HOME:?}/.bicentennial-followup-official
TEST_MARKER=.followup-test-dir
STEP=${1:-}; shift $(( $# > 0 ? 1 : 0 ))
PREPARING=0
ASYNC_TOOL=0
while IFS= read -r git_name; do unset "$git_name"; done < <(trap - EXIT; compgen -v GIT_)
export PYTHONHASHSEED=0
refuse() { local message="$*"; printf 'refused: %s\n' "${message#refused: }" >&2
  [[ $PREPARING == 1 ]] && printf '%s\n' 'move the unrecorded state directory aside before retrying' >&2
  exit 2; }
readfile() { [[ -f $1 ]] && { local line; IFS= read -r line < "$1" || :; printf '%s' "$line"; }; }
hex64() { [[ $1 =~ ^[0-9a-f]{64}$ ]]; }
hex40() { [[ $1 =~ ^[0-9a-f]{40}$ ]]; }
# A guard may consume only a checked record. Interrupted writes keep a partial.
record_try() { local target=$1 value=$2 recorded format='%s\n'
  [[ -n $value ]] || format='%s'
  tool files printf "$format" "$value" > "$target.part" &&
    recorded=$(tool files cat "$target.part") && [[ $recorded == "$value" ]] &&
    tool files mv -f "$target.part" "$target" &&
    recorded=$(tool files cat "$target") && [[ $recorded == "$value" ]]; }
record() { record_try "$1" "$2" || refuse "${3:-private} record write failed"; }

copy_record() { local source=$1 target=$2
  tool files cp "$source" "$target.part" && tool files cmp -s "$source" "$target.part" &&
    tool files mv -f "$target.part" "$target" && tool files cmp -s "$source" "$target" || refuse "record copy failed"; }
old_enough() { local current age
  current=$(clock_now); age=$(tool files stat -f %m "$1") || refuse "cannot read record age"
  (( current - age >= 60 )); }

# Only this gateway starts a tool. A stand-in can never run in an official state.
fake() { local official=""; [[ -f $OFFICIAL_RECORD ]] && official=$(readfile "$OFFICIAL_RECORD")
  [[ -n ${FOLLOWUP_STANDIN:-} && -f $S/$TEST_MARKER && $S != "$official" ]]; }
tool() {
  if [[ $ASYNC_TOOL != 1 ]]; then (ASYNC_TOOL=1; tool "$@"); return $?; fi
  trap - EXIT
  local kind=$1; shift
  if fake; then exec "$FOLLOWUP_STANDIN" "$kind" "$@"; fi
  case $kind in
    gh|git-fetch)
      local bound=60; [[ $kind == git-fetch ]] && bound=300
      exec "$BASEPY" -I -c 'import subprocess,sys
try: code=subprocess.run(sys.argv[2:],timeout=int(sys.argv[1]),check=False).returncode
except subprocess.TimeoutExpired: code=124
except OSError: code=127
sys.exit(code)' "$bound" "$@" ;;
    *) exec "$@" ;;
  esac
}
sha() { local line; line=$(tool sha shasum -a 256 "$1") || return $?; printf '%s\n' "${line%% *}"; }
clock_now() { tool clock "$BASEPY" -I -c 'import time; print(int(time.time()))'; }
stamp() { tool stamp "$BASEPY" -I -c 'import datetime,sys; print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$(clock_now)"; }
# Structured private records and JSON checks; no item, seed or text is printed.
meta() { tool meta "$BASEPY" -I - "$@" <<'PY'
import datetime, hashlib, importlib.util, json, os, re, shlex, sys
from pathlib import Path
op, *a = sys.argv[1:]
def load(p): return json.loads(Path(p).read_bytes())
def hashfile(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x): Path(p).write_text(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n")
def valid(v,n=64): return isinstance(v,str) and re.fullmatch("[0-9a-f]{"+str(n)+"}",v) is not None
try:
    if op=="settings":
        names=a[1:]; target=Path(a[0]); values={n:os.environ.get(n,"") for n in names}
        for name in ("gh","curl","git"):
            import shutil
            value=shutil.which(name)
            if value is None: raise ValueError
            values["resolved_"+name]=str(Path(value).resolve())
        values["resolved_python"]=str(Path(shutil.which(values["FOLLOWUP_PYTHON"]) or values["FOLLOWUP_PYTHON"]).resolve())
        with target.open("x") as f:
            for n,v in values.items(): f.write("PIN_"+n+"="+shlex.quote(v)+"\n")
        target.chmod(0o600)
    elif op=="resolved":
        import shutil
        print(str(Path(shutil.which(a[0]) or a[0]).resolve()))
    elif op=="index":
        raw=Path(a[0]).read_bytes()
        if any(not line.startswith(b"H ") for line in raw.split(b"\0") if line): raise ValueError
    elif op=="pr":
        p=load(a[0]); commit=p["mergeCommit"]["oid"]
        if p["state"]!="MERGED" or not valid(commit,40): raise ValueError
        print(commit)
    elif op=="admissions":
        text=Path(a[0]).read_text(); obj=json.loads(text)
        if any(name not in text for name in ("drift-chain-fault-v3","drift-config-v3","drift-quote-v3")): raise ValueError
    elif op=="new-directory":
        data=load(a[0])
        if any(r.get("reason")!="not after the merge" for r in data["first_posts"]): raise ValueError
        if any(r["after_merge"] for r in data["markers"]): raise ValueError
    elif op=="own-post":
        folder,kind,round_number,wanted=a
        posts=set(); matches=[]
        for path in sorted((Path(folder)/"records").iterdir()):
            m=re.fullmatch(r"([0-9]{6})-([a-z][a-z-]*)\.(json|body)",path.name)
            if not m or m[3]!="json": continue
            row=load(path)
            if m[2]=="post":
                if type(row["id"]) is not int: raise ValueError
                posts.add(str(row["id"]))
            elif m[2]=="match":
                if not isinstance(row["matches"],list) or any(type(i) is not int for i in row["matches"]): raise ValueError
                if row["kind"]==kind and row["round"]==int(round_number): matches=row["matches"]
        eligible=posts if kind=="first" else posts.intersection(map(str,matches))
        if wanted: eligible.intersection_update([wanted])
        if eligible: print(min(eligible,key=int))
    elif op=="lost-after-draw":
        if not any(r.get("after_merge") and r.get("first_line") in
                   ("Follow-up draw: second post","Follow-up draw: task lists") for r in load(a[0])["markers"]): sys.exit(1)
    elif op=="counted":
        rows=[r for r in load(a[0])["first_posts"] if r.get("counted") and str(r["id"])==a[1]]
        if len(rows)!=1: raise ValueError
        save(a[2],rows[0])
    elif op=="values":
        row=load(a[0]); values=row["values"]
        for name in ("registry_entry_sha256","fresh_install_hash","artifact_sha256","system_hash","harness_hash","route_table_hash"):
            value=values.get(name)
            print(name,value if isinstance(value,str) and not any(c.isspace() for c in value) else "missing")
    elif op=="h-hashes":
        values=load(a[0])["values"]; faults=[]
        for name in ("system_hash","harness_hash","route_table_hash"):
            value=values.get(name)
            if not valid(value): value="0"*64; faults.append(name)
            print("--"+name.replace("_","-"),value)
        save(a[1],dict(invalid=faults))
    elif op=="commit":
        commit=load(a[0])["commit"]
        if not valid(commit,40): raise ValueError
        print(commit)
    elif op=="disjoint":
        paths=[Path(p).resolve() for p in a]
        for i,p in enumerate(paths):
            if any(p==q or p in q.parents or q in p.parents for q in paths[i+1:]): raise ValueError
    elif op=="sanitize":
        source,public=map(Path,a)
        spec=importlib.util.spec_from_file_location("public_paths",public); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        raw=source.read_bytes()
        if module.PATHS.search(raw.decode("utf-8",errors="replace")):
            source.write_text("sha256 "+hashfile(source)+"\nwithheld: local path pattern\n")
    elif op=="beacon-round":
        if load(a[0])["round"]!=int(a[1]): raise ValueError
    elif op=="second-body":
        draw,beacon=load(a[0]),load(a[1])
        if beacon["round"]!=int(a[2]): raise ValueError
        Path(a[3]).write_text("Follow-up draw: second post\nround "+a[2]+"\ndraw_sha256 "+hashfile(a[0])+"\ndrawn_at "+draw["drawn_at"]+"\nrandomness "+beacon["randomness"]+"\n"+a[4]+"\n")
    elif op=="tasks":
        path,commit,pack,packhash,draw,spec=a
        t=load(path); expected=dict(commit=commit,edition=3,pack=pack,pack_hash=packhash,draw_sha256=hashfile(draw),spec_sha256=hashfile(spec))
        if t["header"]!=expected or len(t["rows"])!=40 or len(t["descriptive"])!=10: raise ValueError
    elif op=="failure-reason":
        err,target,code,cut=a
        reason=(Path(cut).read_text().strip() if Path(cut).is_file() else
                next((line for line in Path(err).read_text(errors="replace").splitlines()
                      if line.startswith(("refused:","REFUSED:"))),"exit "+code))
        Path(target).write_text(reason+"\n")
    elif op=="placement":
        out,draw,log,code=a; root=Path(out); lines=Path(log).read_text().splitlines()
        expected=hashfile(draw)
        if "draw_sha256 "+expected not in lines: raise ValueError
        if code=="0":
            names={f"{kind}-{p}.{ext}" for p in "ABC" for kind,ext in (("pack","toml"),("placement","json"))}
            if {p.name for p in root.iterdir()}!=names: raise ValueError
            for name in sorted(names): print(name,hashfile(root/name))
        else:
            if {p.name for p in root.iterdir()}!={"void.json"}: raise ValueError
            v=load(root/"void.json")
            if v.get("void") is not True or v["rule"] not in ("design_failures","replacements","pool") or v["draw_sha256"]!=expected or v["pack"] not in ("A","B","C"): raise ValueError
            line="void "+v["rule"]+" pack "+v["pack"]
            if line not in lines or "receipt_sha256 "+hashfile(root/"void.json") not in lines: raise ValueError
            print(line); print("receipt_sha256",hashfile(root/"void.json"))
    elif op=="voids":
        for r in load(a[0])["first_posts"]:
            if r.get("reason")=="void round": print(r["round"])
    elif op=="void-receipt":
        rows=[load(p) for p in (Path(a[0])/"records").glob("*-void.json")]
        values={r["receipt_sha256"] for r in rows if r["round"]==int(a[1])}
        if len(values)!=1: raise ValueError
        print(values.pop())
    elif op=="guard":
        out,diag=map(Path,a)
        if out.is_symlink() or not out.is_dir() or {p.name for p in out.iterdir()}!={"refusal.json"}: raise ValueError
        refusal=out/"refusal.json"
        if refusal.is_symlink() or not refusal.is_file(): raise ValueError
        r=load(refusal); code=r.get("code") if isinstance(r,dict) else None
        ok=isinstance(code,str) and set(r)=={"code"} and (code in ("roots_below_min","machine busy: heavy work refused") or re.fullmatch(r"machine guard refused: marker exit (None|[0-9]+)",code) is not None)
        if not ok: raise ValueError
        if os.path.lexists(diag):
            if diag.is_symlink() or not diag.is_dir() or {p.name for p in diag.iterdir()}!={"manifest.json"}: raise ValueError
            m=diag/"manifest.json"
            if m.is_symlink() or not m.is_file(): raise ValueError
            m=load(m)
            if not isinstance(m,dict) or m.get("commit") is not None or any(m.get(k)!=[] for k in ("files","failures","skips")): raise ValueError
    elif op=="safe-copy":
        source,target,public=a; source,target=Path(source),Path(target)
        spec=importlib.util.spec_from_file_location("public_paths",public); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        raw=source.read_bytes()
        try: text=raw.decode("utf-8")
        except UnicodeDecodeError: text=""
        if module.PATHS.search(text): raw=("sha256 "+hashfile(source)+"\nwithheld: local path pattern\n").encode()
        target.write_bytes(raw)
    else: raise ValueError
except (OSError,ValueError,KeyError,TypeError,IndexError):
    print("refused: private record check",file=sys.stderr); sys.exit(2)
PY
}
control_of() { case ${1:0:1} in F) echo no_memory ;; R) echo naive_rag ;; B) echo bm25 ;; G) echo grep ;;
  W) echo recent_window ;; O) echo oracle_evidence ;; *) return 1 ;; esac; }
idle() { local m i; for ((i=1;i<=61;i++)); do tool marker /bin/bash "$MARKER" >/dev/null 2>&1; m=$?
  [[ $m == 0 ]] && return 0
  (( i == 1 )) && echo "busy marker; waiting for idle"
  tool sleep sleep 60; done; echo "busy marker still not idle after 60 min"; exit 4; }
atcommit() { local wt=${1:-$S/wt} expected=${2:-$(readfile "$S/commit.txt")} name flags
  cd "$wt" 2>/dev/null || refuse "worktree unavailable"
  while IFS= read -r name; do unset "$name"; done < <(trap - EXIT; compgen -v GIT_)
  export PYTHONHASHSEED=0 PYTHONPATH="$wt/src"
  [[ -z $(tool git git status --porcelain) ]] || refuse "worktree is not clean"
  [[ $(tool git git rev-parse HEAD) == "$expected" ]] || refuse "worktree is not at the recorded commit"
  flags=$P/index-flags; tool git git ls-files -v -z > "$flags" || refuse "cannot inspect index flags"
  meta index "$flags" || refuse "worktree has non-H index entries"
  tool import-check "$PY" -c 'import bicentennial, pathlib, sys
assert pathlib.Path(bicentennial.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())' "$wt" >/dev/null 2>&1 || refuse "worktree Python imports another source"; }
lock() { tool files mkdir "$S/lock" 2>/dev/null || refuse "another step holds lock"
  tool files mkdir "$S/lock/$$" || exit 2
  trap 'tool files rm -f "$S/lock/$$/start" "$S/lock/$$/start.part"; tool files rmdir "$S/lock/$$" "$S/lock" >/dev/null 2>&1' EXIT
  local owner_start; owner_start=$(tool ps ps -o lstart= -p "$$" 2>/dev/null)
  record "$S/lock/$$/start" "$owner_start" lock-owner-start
  [[ -s $S/lock/$$/start ]] || refuse "cannot record lock owner start"; }
arm_alive() { tool pgrep pgrep -f 'bicentennial(\.cli)? t2( |$)' >/dev/null && return 0
  local lockf=$LOGIN/.t2lite.lock official=""; [[ -f $OFFICIAL_RECORD ]] && official=$(readfile "$OFFICIAL_RECORD")
  [[ $S == "$official" ]] || lockf=$S/.t2lite.lock
  ! tool lock-probe python3 -c 'import fcntl,os,sys
fcntl.flock(os.open(sys.argv[1],os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),fcntl.LOCK_EX|fcntl.LOCK_NB)' "$lockf" 2>/dev/null; }
guard_refused() { meta guard "$1" "$2" >/dev/null 2>&1; }
# Settings are private shell assignments, written last by prep. Never print values.
setting_names=(FOLLOWUP_STATE FOLLOWUP_REPO FOLLOWUP_HERMES FOLLOWUP_WRAPPER FOLLOWUP_LOGIN_HOME FOLLOWUP_MARKER FOLLOWUP_PYTHON FOLLOWUP_SLOT ORIGIN_MARKER)
check_identity() {
  local official="" name pin resolved
  [[ -n $S ]] || refuse "FOLLOWUP_STATE is required"
  [[ -f $OFFICIAL_RECORD ]] && official=$(readfile "$OFFICIAL_RECORD")
  if [[ $S == "$official" ]]; then
    if [[ -e $S/$TEST_MARKER ]]; then record "$P/official-tainted" tainted official-taint; fi
    [[ ! -e $P/official-tainted ]] || refuse "official state was marked as a test directory"
  elif [[ ! -e $S/$TEST_MARKER ]]; then refuse "unmarked state is not the recorded official directory"; fi
  [[ -s $P/settings && -f $S/mode ]] || refuse "prep is incomplete; move the unrecorded state directory aside"
  # This file is private, not input from a post or a relay.
  source "$P/settings"
  for name in "${setting_names[@]}"; do pin=PIN_$name
    [[ ${!name:-} == "${!pin}" ]] || refuse "local setting changed: $name"; done
  [[ $(readfile "$S/mode") != official || $S == "$official" ]] || refuse "official-directory record differs"
  for name in gh curl git; do pin=PIN_resolved_$name
    resolved=$(meta resolved "$name") || refuse "cannot resolve tool"
    [[ $resolved == "${!pin}" ]] || refuse "resolved tool changed: $name"; done
  resolved=$(meta resolved "$BASEPY") || refuse "cannot resolve base Python"
  [[ $resolved == "$PIN_resolved_python" ]] || refuse "resolved base Python changed"; }
next_number() { local n=0 f value
  for f in "$S/counter" "$S"/logs/*.seq; do
    [[ -f $f ]] || continue
    value=$(readfile "$f")
    [[ -n $value || $f != "$S/counter" ]] || continue
    [[ $value =~ ^[0-9]{1,18}$ ]] || refuse "sequence record is invalid"
    if (( 10#$value > n )); then n=$((10#$value)); fi
  done
  n=$((n+1))
  record "$S/counter" "$n" sequence
  printf '%s' "$n"; }
any_attempt() { local l; for l in "${ORDER[@]}"; do [[ -e $S/logs/$l.seq || -e $S/runs/$l || -e $S/runs/$l.rerun ]] && return 0; done; return 1; }
all_attempts() { local l; for l in "${ORDER[@]}"; do [[ -e $S/runs/$l && -s $S/logs/$l.seq ]] || refuse "$l has no first attempt"; done; }
check3_file() { C3=$P/check3-1.txt; [[ -e $P/check3-2.txt ]] && C3=$P/check3-2.txt; [[ -e $C3 ]]; }
check3_failed_twice() { [[ -e $P/check3-2.txt ]] && ! check3_matches "$P/check3-2.txt" 0; }
frozen_tasks() { local p; for p in A B C; do
  [[ -f $P/TASKS-$p.json && -s $P/TASKS-$p.sha256 ]] || refuse "task list $p is not frozen"
  [[ $(sha "$P/TASKS-$p.json") == $(readfile "$P/TASKS-$p.sha256") ]] || refuse "task list $p differs from its frozen hash"; done; }
posted_values() { local p; case $1 in
  draw) [[ -f $P/DRAW.json ]] || return 2; sha "$P/DRAW.json" ;;
  tasks) for p in A B C; do printf '%s %s\n' "$(readfile "$S/pack-$p.hash")" "$(readfile "$P/TASKS-$p.sha256")" || return 2; done ;;
  esac; }
need_posted() { local kind=$1 values
  [[ -s $S/posted/$kind.rec ]] || refuse "$kind post is not recorded"
  values=$(posted_values "$kind") || refuse "current posted values unavailable"
  record "$P/current-$kind.values" "$values" posted-values
  tool files cmp -s "$P/current-$kind.values" "$S/posted/$kind.values" || refuse "recorded $kind values differ from current values"; }
new_worktree() { local prefix=$1 expected=${2:-$(readfile "$S/commit.txt")} n=1
  while [[ -e $S/worktrees/$prefix-$n ]]; do n=$((n+1)); done
  WT=$S/worktrees/$prefix-$n
  tool git-worktree git -C "$R" -c core.hooksPath=/dev/null worktree add --detach "$WT" "$expected" > "$P/worktree-$prefix-$n.log" 2>&1 || refuse "new worktree failed"
  record "$P/worktree-$prefix-$n.commit" "$expected" worktree-commit
  atcommit "$WT" "$expected"; }
dr() { local command=$1; shift; tool dr "$BASEPY" -I "$S/wt/$DR_PY" "$command" --state "$P/draw" "$@"; }
# All reads of S4 state are commands or exported copies. Its record folder is opaque.
draw_status() { local x
  dr read > "$P/read.out" 2> "$P/read.err"; x=$?; [[ $x == 0 ]] || refuse "draw-record read refused"
  dr evaluate > "$P/evaluate.out" 2> "$P/evaluate.err"; EVAL=$?
  reconcile_voids
  if [[ $EVAL == 14 ]]; then copy_record "$P/evaluate.out" "$P/stopped"; refuse "draw stopped"; fi
  if [[ $EVAL == 2 ]]; then
    if [[ $STEP == post-commit ]] && tool files grep -qE '^refused: reading module (differs|unavailable) at [0-9a-f]{40}$' "$P/evaluate.err"; then
      copy_record "$P/evaluate.err" "$P/reading-commit-refusal"
      local line; IFS= read -r line < "$P/evaluate.err"
      if [[ ${line##* } != $(readfile "$S/commit.txt") ]]; then
        record "$P/counted-not-own" "$line" counted-not-own
      fi
      dr publish-list > "$P/counted-list.json" 2> "$P/counted-list.err" || refuse "counted list unavailable"
      refuse "$line"; fi
    refuse "draw-record evaluation refused"; fi
  [[ $EVAL == 0 || $EVAL == 10 ]] || refuse "unexpected draw-record evaluation"
  if [[ $EVAL == 0 ]]; then
    local word id roundword dueword commitword
    read -r word COUNT_ID roundword ROUND dueword DUE commitword COUNT_COMMIT < "$P/evaluate.out"
    [[ $word == counted && $roundword == round && $dueword == due && $commitword == commit ]] || refuse "counted line is malformed"
  fi
  [[ ! -e $P/void-unconfirmed ]] || refuse "void record not confirmed by step 6: under §2 the earlier draw stands"
  [[ ! -e $P/stopped ]] || refuse "draw stopped"; }
need_counted() { [[ $EVAL == 0 && -s $P/counted.json ]] || refuse "post-commit has not recorded a counted post"
  [[ $(readfile "$P/counted-round") == "$ROUND" ]] || refuse "round differs from the counted post"
  [[ $COUNT_COMMIT == $(readfile "$S/commit.txt") ]] || refuse "counted commit differs from the run commit"; }
void_move() { local source=$1 target=$2 original=$2 n=1
  while [[ -e $target ]]; do target=$original.resume-$n; n=$((n+1)); done
  tool files mv -n "$source" "$target" || exit 2
  [[ ! -e $source ]] || refuse "void archive move is incomplete"; }
finish_void() { local number=$1 receipt=$2 V=$P/void-$1 f dest name
  any_attempt && return 0
  tool files mkdir -p "$V" || exit 2
  for name in BEACON DRAW.json draw.sha256 counted.json counted-round second.body second.match first.body first-post.out first-post.err \
      beacon-cutoff placed-1 placed-2 place-consensus void-confirm-$number void-record.exit void-record.out void-record.err failure first-failure rebuild-started rebuild-used rebuild-failed rebuild-complete tools \
      draw-worktree place-worktree-1 place-worktree-2 place-work-1 place-work-2 reproduced-DRAW.json \
      place-1.summary place-2.summary consensus-fixed placement-passed first-attempt counted-h.values h-differences \
      counted-other-commit reading-commit-refusal second.post second.post.err second.match.err second.read \
      draw-list.json evaluate.err choose-round.out choose-round.err beacon.out beacon.err; do
    f=$P/$name; dest=$V/$name
    if [[ -e $f ]]; then void_move "$f" "$dest"; fi
  done
  [[ ! -f $P/evaluate.out ]] || copy_record "$P/evaluate.out" "$V/evaluate.out"
  for f in "$P"/TASKS-* "$P"/worktree-*.commit "$P"/worktree-*.log "$P"/current-*.values; do
    [[ -e $f ]] || continue; dest=$V/${f##*/}
    void_move "$f" "$dest"; done
  tool files mkdir -p "$V/posted"
  for f in "$S"/posted/*; do [[ -e $f ]] || continue; dest=$V/posted/${f##*/}
    void_move "$f" "$dest"; done
  for name in build-A build-B build-C packs-A packs-B packs-C pack-A.hash pack-B.hash pack-C.hash; do
    [[ -e $S/$name ]] || continue
    void_move "$S/$name" "$V/$name"; done
  [[ -e $V/BEACON && -e $V/DRAW.json && -e $V/placed-1/void.json && -e $V/placed-2/void.json ]] || refuse "void archive is missing inputs"
  record "$V/complete" "$number $receipt" void-complete
  echo "void archive complete; next: post-commit"; }
reconcile_voids() { local number receipt check n confirm
  dr publish-list > "$P/draw-list.json" 2> "$P/draw-list.err" || refuse "draw-record publish-list refused"
  meta voids "$P/draw-list.json" > "$P/void-rounds" || refuse "cannot read void rounds"
  while IFS= read -r number; do
    [[ -e $P/void-$number/complete ]] && continue
    if any_attempt; then
      record "$P/void-unconfirmed" 'void record not confirmed by step 6: under §2 the earlier draw stands' void-unconfirmed
      return 0
    fi
    confirm=$P/void-confirm-$number; [[ -e $confirm ]] || confirm=$P/void-$number/void-confirm-$number
    if [[ ! -s $confirm ]]; then
      record "$P/void-unconfirmed" 'void record not confirmed by step 6: under §2 the earlier draw stands' void-unconfirmed; return 0; fi
    n=1; while [[ -e $P/void-check-$number-$n ]]; do n=$((n+1)); done
    check=$P/void-check-$number-$n
    dr publish-records "$check" > "$P/void-check.out" 2> "$P/void-check.err" || refuse "void export refused"
    receipt=$(meta void-receipt "$check" "$number") || refuse "void receipt unavailable in export"
    if [[ $(readfile "$confirm") != "$number $receipt" ]]; then
      record "$P/void-unconfirmed" 'void record not confirmed by step 6: under §2 the earlier draw stands' void-unconfirmed; return 0; fi
    finish_void "$number" "$receipt"
  done < "$P/void-rounds"; }
no_failed_attempt() { [[ ! -e $P/rebuild-started || -e $P/rebuild-used ]] || refuse "rebuild archive incomplete; only rebuild continues"
  [[ ! -e $P/failure ]] || refuse "attempt failed; only rebuild continues the build path"; }
fail_attempt() { local name=$1 code=$2 T=$P/tools/$1 prior="" entry
  meta failure-reason "$T.err" "$T.reason" "$code" "$T.cutoff-failure" || refuse "failure reason could not be recorded"
  entry="$name $code $(sha "$T.out") $(sha "$T.err")"
  if [[ -f $P/failure ]]; then prior=$(tool files cat "$P/failure") || refuse "failure record unreadable"; fi
  record "$P/failure" "${prior:+$prior$'\n'}$entry" failure
  if [[ -e $P/rebuild-used ]]; then copy_record "$P/failure" "$P/rebuild-failed"; stop_run build; fi
  echo "build attempt failed; rebuild is the next step" >&2; return "$code"; }
# A completed tool is never replayed. Interrupted output is kept separately; a
# live tool must finish before its records can be resumed.
run_tool() { local name=$1; shift; local outputs=() path T pid x n current fork_failed=0
  while [[ $1 != -- ]]; do outputs+=("$1"); shift; done; shift
  T=$P/tools/$name; tool files mkdir -p "$P/tools" || exit 2
  if [[ -s $T.exit ]]; then return "$(readfile "$T.exit")"; fi
  if [[ -e $T.intent || -e $T.pid || -e $T.pid.part ]]; then
    path=$T.pid; [[ -e $path ]] || path=$T.pid.part
    [[ -e $path ]] || path=$T.intent
    pid=$(readfile "$path")
    if [[ $path == "$T.intent" || $path == "$T.pid.part" || ! $pid =~ ^[0-9]+$ || ! -s $T.process-start ]]; then
      old_enough "$path" || refuse "recorded tool may be starting"
    else
      tool ps ps -o lstart= -p "$pid" > "$T.live" 2>/dev/null
      if [[ -s $T.live ]]; then
        tool files cmp -s "$T.process-start" "$T.live"; current=$?
        [[ $current != 0 ]] || refuse "recorded tool process still runs"
        [[ $current == 1 ]] || refuse "recorded tool start cannot be compared"
      fi
    fi
    n=$(readfile "$T.cuts"); n=$(( ${n:-0}+1 )); record "$T.cuts" "$n" cutoff-count
    if (( n > 3 )); then
      record "$T.cutoff-failure" "cut-off budget exhausted" cutoff-failure; record "$T.exit" 1 tool-exit
      [[ -e $T.err ]] || : > "$T.err"
      [[ -e $T.out ]] || : > "$T.out"
      return 1; fi
    tool files mkdir "$T.cut-$n" || exit 2
    for path in "${outputs[@]+"${outputs[@]}"}"; do
      [[ -e $path ]] || continue; [[ ! -e $path.cut-$n ]] || refuse "cut archive exists"
      tool files mv -n "$path" "$path.cut-$n" || exit 2; done
    for path in intent intent.part start pid pid.part process-start process-start.part start.part out err; do [[ -e $T.$path ]] && tool files mv -n "$T.$path" "$T.cut-$n/$path"; done
  fi
  meta disjoint "${outputs[@]+"${outputs[@]}"}" || refuse "tool output and work overlap"
  for path in "${outputs[@]+"${outputs[@]}"}"; do [[ ! -e $path && ! -L $path ]] || refuse "tool output or work already exists"; done
  record "$T.intent" "$(clock_now)" tool-intent
  ASYNC_TOOL=1 tool "$@" > "$T.out" 2> "$T.err" & pid=$!
  record_try "$T.pid" "$pid" || fork_failed=1
  current=$(tool ps ps -o lstart= -p "$pid" 2>/dev/null) || :
  record_try "$T.process-start" "$current" || fork_failed=1
  record_try "$T.start" "$(clock_now)" || fork_failed=1
  wait "$pid"; x=$?; record "$T.exit" "$x" tool-exit; record "$T.end" "$(clock_now)" tool-end
  [[ $fork_failed == 0 ]] || refuse "tool fork record write failed"
  return "$x"; }
# A failed tool's diagnostics are private. Posts carry step, exit and log hashes.
stop_run() { local reason=${1:-} x name code out err i=0 body failure
  any_attempt && refuse "a draw stop is forbidden after an arm attempt"
  case $reason in
    beacon) [[ $(readfile "$P/beacon-cutoff") == "$ROUND 13" ]] || refuse "no cutoff for the counted round" ;;
    build)
      if [[ -e $P/rebuild-used && -e $P/failure && ! -e $P/rebuild-failed ]]; then
        copy_record "$P/failure" "$P/rebuild-failed"; fi
      [[ -s $P/first-failure && -s $P/rebuild-failed && -e $P/rebuild-used ]] || refuse "build stop needs two failed attempts" ;;
    *) refuse "stop reason must be beacon or build" ;;
  esac
  body=$({ printf 'Follow-up draw: stop\nreason %s\n' "$reason"
    if [[ $reason == build ]]; then
      for f in "$P/first-failure" "$P/rebuild-failed"; do
        while read -r name code out err; do i=$((i+1)); printf 'failed_step_%s %s\nexit_%s %s\nstdout_sha256_%s %s\nstderr_sha256_%s %s\n' "$i" "$name" "$i" "$code" "$i" "$out" "$i" "$err"; done < "$f"; done
    else printf 'failed_step_1 beacon\nexit_1 13\nstdout_sha256_1 %s\nstderr_sha256_1 %s\n' "$(sha "$P/beacon.out")" "$(sha "$P/beacon.err")"; fi
    printf '%s\n' "$ORIGIN_MARKER"
  }) || refuse "stop body unavailable"
  record "$P/stop.body" "$body" post-body
  if [[ $reason == build ]]; then
    failure=$(tool files cat "$P/first-failure" "$P/rebuild-failed") || refuse "stop failure records unavailable"
    record "$P/stop-failure" "$failure" stop-failure
    dr post stop --reason build --failure-sha256 "$(sha "$P/stop-failure")" "$P/stop.body" > "$P/stop.out" 2> "$P/stop.err"; x=$?
  else dr post stop --reason beacon "$P/stop.body" > "$P/stop.out" 2> "$P/stop.err"; x=$?; fi
  [[ $x == 0 ]] || refuse "draw-record stop refused"
  record "$P/stopped" "$reason" stopped; echo "draw stopped"; return 0; }
# Every ownership decision uses a fresh export. Even a failed export consumes its
# number through its output files; S4 itself creates the numbered folder.
own_post() { local kind=$1 wanted=${2:-} n=1 folder
  tool files mkdir -p "$P/exports" || refuse "own post records unavailable"
  while [[ -e $P/exports/$n || -e $P/exports/$n.out || -e $P/exports/$n.err ]]; do n=$((n+1)); done
  folder=$P/exports/$n
  dr publish-records "$folder" > "$folder.out" 2> "$folder.err" || refuse "own post records unavailable"
  OWN_ID=$(meta own-post "$folder" "$kind" "$ROUND" "$wanted" 2> "$folder.parse.err") || refuse "own post records unavailable"; }
record_counted() { local x key value old
  own_post first "$COUNT_ID"
  if [[ -z $OWN_ID ]]; then
    copy_record "$P/evaluate.out" "$P/counted-not-own"
    refuse "counted first post was not made by this directory"
  fi
  dr publish-list > "$P/counted-list.json" 2> "$P/counted-list.err" || refuse "counted values unavailable"
  meta counted "$P/counted-list.json" "$COUNT_ID" "$P/counted.json" || refuse "counted values unavailable"
  meta values "$P/counted.json" > "$P/counted-h.values" || refuse "counted values unreadable"
  [[ $COUNT_COMMIT == $(readfile "$S/commit.txt") ]] || {
    copy_record "$P/evaluate.out" "$P/counted-other-commit"; refuse "counted commit differs from the run commit"; }
  : > "$P/h-differences"
  while read -r key value; do
    old=$(tool files awk -v key="$key" '$1==key {print $2}' "$S/rehearsal/h.values")
    [[ $value == "$old" ]] || printf '%s differs\n' "$key" >> "$P/h-differences"
  done < "$P/counted-h.values"
  record "$P/counted-round" "$ROUND" counted-round
  copy_record "$P/evaluate.out" "$S/posted/commit.rec"
  echo "counted commitment recorded"; }
match_post() { local kind=$1 body=$2 x id word rest
  dr match "$kind" "$body" > "$P/$kind.match" 2> "$P/$kind.match.err"; x=$?
  OWN_ID=""
  if [[ $x == 0 ]]; then
    own_post "$kind"
  elif [[ $x != 10 ]]; then refuse "draw-record match refused"; fi
  if [[ -z $OWN_ID ]]; then
    dr post "$kind" "$body" > "$P/$kind.post" 2> "$P/$kind.post.err"; x=$?
    [[ $x == 0 ]] || refuse "draw-record post refused"
    read -r word id rest < "$P/$kind.post"
    dr read > "$P/$kind.read" 2> "$P/$kind.read.err" || refuse "draw-record readback refused"
    dr match "$kind" "$body" > "$P/$kind.match" 2> "$P/$kind.match.err"; x=$?
    [[ $x == 0 ]] || refuse "posted comment was not matched"
    own_post "$kind" "$id"
    [[ -n $OWN_ID ]] || refuse "posted comment was not matched"
  fi
  local posted_kind=tasks; [[ $kind != second ]] || posted_kind=draw
  local values matched; values=$(posted_values "$posted_kind") || refuse "posted values record failed"
  record "$S/posted/$posted_kind.values" "$values" posted-values
  matched=$(tool files cat "$P/$kind.match") || refuse "match record unavailable"
  record "$S/posted/$posted_kind.rec" "$matched"$'\n'"own $OWN_ID" posted-match; }

post_commit() { local x body
  [[ $(readfile "$S/rehearsal/passed") == $(readfile "$S/commit.txt") ]] || refuse "rehearse at this commit first"
  if [[ $EVAL == 0 ]]; then record_counted; return $?; fi
  dr choose-round > "$P/choose-round.out" 2> "$P/choose-round.err" || refuse "draw-record choose-round refused"
  read -r word ROUND dueword DUE choice < "$P/choose-round.out"
  body=$({ printf 'Follow-up draw: first post\nround %s\nrun_commit %s\n' "$ROUND" "$(readfile "$S/commit.txt")"
    tool files cat "$S/rehearsal/h.values"; printf '%s\n' "$ORIGIN_MARKER"; }) || refuse "first body unavailable"
  record "$P/first.body" "$body" post-body
  dr post first "$P/first.body" > "$P/first-post.out" 2> "$P/first-post.err"; x=$?
  if [[ $x == 13 ]]; then copy_record "$P/first-post.out" "$P/blocked"; refuse "first posting is blocked; release records"; fi
  [[ $x == 0 ]] || refuse "draw-record first post refused"
  dr evaluate > "$P/evaluate.out" 2> "$P/evaluate.err"; EVAL=$?
  [[ $EVAL == 10 ]] && return 1
  [[ $EVAL == 0 ]] || refuse "draw-record post evaluation refused"
  read -r word COUNT_ID roundword ROUND dueword DUE commitword COUNT_COMMIT < "$P/evaluate.out"
  record_counted; }
beacon_retry() { local line
  line=$(readfile "$1")
  case $line in
    'refused: round not due'|'refused: GitHub timeout'|'refused: GitHub HTTP status'|'refused: GitHub GraphQL errors'|'refused: GitHub time unavailable'|'refused: missing HTTP status'|'refused: missing HTTP header block'|'refused: relay timeout'|'refused: clock skew exceeds 60 seconds') return 0 ;;
    'refused: malformed or unavailable record')
      (( MALFORMED < 2 )) || refuse "$line"; MALFORMED=$((MALFORMED+1)); return 0 ;;
  esac
  [[ $line =~ ^refused:\ reading\ module\ unavailable\ at\ [0-9a-f]{40}$ ]] && return 0
  refuse "${line:-draw-record refusal has no reason}"; }
beacon_step() { local x now MALFORMED=0
  need_counted
  [[ $# == 0 ]] || refuse "beacon takes the counted round only"
  ASYNC_TOOL=1 tool caffeinate caffeinate -i -w "$$" > "$P/caffeinate.out" 2> "$P/caffeinate.err" &
  while :; do
    dr now > "$P/now.out" 2> "$P/now.err"; x=$?
    if [[ $x == 2 ]]; then beacon_retry "$P/now.err"; tool sleep sleep 30; continue; fi
    [[ $x == 0 ]] || refuse "unexpected draw-record clock result"
    read -r word now rest < "$P/now.out"
    if (( now < DUE )); then tool sleep sleep 30; continue; fi
    dr beacon --round "$ROUND" --out "$P/BEACON" > "$P/beacon.out" 2> "$P/beacon.err"; x=$?
    case $x in
      0) meta beacon-round "$P/BEACON" "$ROUND" || refuse "beacon is for another round"; echo "beacon accepted"; return 0 ;;
      10) tool sleep sleep 30 ;;
      2) beacon_retry "$P/beacon.err"; tool sleep sleep 30 ;;
      13) record "$P/beacon-cutoff" "$ROUND 13" beacon-cutoff; stop_run beacon; return $? ;;
      *) refuse "unexpected draw-record beacon result" ;;
    esac
  done; }
draw_step() { local x
  need_counted; no_failed_attempt
  [[ $# == 0 ]] || refuse "draw takes the counted round only"
  [[ -f $P/BEACON ]] || refuse "counted beacon is missing"
  meta beacon-round "$P/BEACON" "$ROUND" || refuse "beacon is for another round"
  if [[ ! -s $P/draw-worktree ]]; then new_worktree draw; record "$P/draw-worktree" "$WT" draw-worktree; fi
  WT=$(readfile "$P/draw-worktree"); atcommit "$WT"
  run_tool draw "$P/DRAW.json" -- draw "$PY" "$WT/scripts/validity_roster.py" draw --packs 3 --beacon "$P/BEACON" --out "$P/DRAW.json"; x=$?
  [[ $x == 0 ]] || { fail_attempt draw "$x"; return $?; }
  run_tool verify -- verify "$PY" "$WT/scripts/validity_roster.py" verify --packs 3 --beacon "$P/BEACON" --draw "$P/DRAW.json"; x=$?
  if [[ $x != 0 ]] || ! tool files grep -qx "verified sha256 $(sha "$P/DRAW.json") at $(readfile "$S/commit.txt")" "$P/tools/verify.out"; then
    [[ $x != 0 ]] || x=1; fail_attempt verify "$x"; return $?; fi
  record "$P/draw.sha256" "$(sha "$P/DRAW.json")" draw-hash
  if [[ -s $S/posted/draw.values ]]; then
    record "$P/current-draw.values" "$(posted_values draw)" posted-values
    tool files cmp -s "$P/current-draw.values" "$S/posted/draw.values" || { fail_attempt verify 1; return 1; }; fi
  echo "draw verified"; }
post_draw() { need_counted; [[ $# == 0 ]] || refuse "post-draw takes the counted round only"
  [[ -s $P/draw.sha256 && -f $P/DRAW.json ]] || refuse "no verified draw"
  [[ $(sha "$P/DRAW.json") == $(readfile "$P/draw.sha256") ]] || refuse "draw differs from its recorded hash"
  meta second-body "$P/DRAW.json" "$P/BEACON" "$ROUND" "$P/second.body" "$ORIGIN_MARKER" || refuse "second body could not be formed"
  match_post second "$P/second.body"; echo "second post recorded"; }
place_step() { local x y i wt first_second=$P/place-first.summary second=$P/place-second.summary receipt
  need_counted; no_failed_attempt; need_posted draw
  [[ -s $P/draw.sha256 && $(sha "$P/DRAW.json") == $(readfile "$P/draw.sha256") ]] || refuse "draw hash differs"
  if [[ -s $P/void-confirm-$ROUND ]]; then
    dr record-void --round "$ROUND" --receipt-sha256 "$(tool files awk '{print $2}' "$P/void-confirm-$ROUND")" > "$P/void-record.out" 2> "$P/void-record.err"; x=$?
    [[ $x == 0 ]] || refuse "void recording refused"
    reconcile_voids; return 1; fi
  for i in 1 2; do
    if [[ ! -s $P/place-worktree-$i ]]; then
      if [[ $i == 1 ]]; then WT=$(readfile "$P/draw-worktree"); [[ -n $WT && -d $WT ]] || refuse "draw worktree is missing"
      else new_worktree place-$i; fi
      record "$P/place-worktree-$i" "$WT" place-worktree
    fi
    wt=$(readfile "$P/place-worktree-$i"); atcommit "$wt"
    if [[ $i == 2 && ${x:-0} == 1 ]]; then
      run_tool reproduce-draw "$P/reproduced-DRAW.json" -- draw "$PY" "$wt/scripts/validity_roster.py" draw --packs 3 --beacon "$P/BEACON" --out "$P/reproduced-DRAW.json"; y=$?
      if [[ $y != 0 ]] || ! tool files cmp -s "$P/DRAW.json" "$P/reproduced-DRAW.json"; then [[ $y != 0 ]] || y=1; fail_attempt reproduce-draw "$y"; return $?; fi
    fi
    run_tool place-$i "$P/place-work-$i" "$P/placed-$i" -- place "$PY" "$wt/scripts/validity_roster.py" place --packs 3 --draw "$P/DRAW.json" --work "$P/place-work-$i" --out-dir "$P/placed-$i"; y=$?
    if [[ $y != 0 && $y != 1 ]]; then fail_attempt place-$i "$y"; return $?; fi
    meta placement "$P/placed-$i" "$P/DRAW.json" "$P/tools/place-$i.out" "$y" > "$P/place-$i.summary" || { fail_attempt place-$i 1; return 1; }
    if [[ $i == 1 ]]; then x=$y
    elif [[ $x != "$y" ]] || ! tool files cmp -s "$P/place-1.summary" "$P/place-2.summary"; then fail_attempt place-$i 1; return 1; fi
  done
  if [[ $x == 1 ]]; then
    [[ ! -e $P/consensus-fixed ]] || { fail_attempt place-2 1; return 1; }
    receipt=$(sha "$P/placed-1/void.json")
    record "$P/void-confirm-$ROUND" "$ROUND $receipt" "void confirmation"
    dr record-void --round "$ROUND" --receipt-sha256 "$receipt" > "$P/void-record.out" 2> "$P/void-record.err"; y=$?
    [[ $y == 0 ]] || refuse "void recording refused"
    printf '0\n' > "$P/void-record.exit"
    reconcile_voids; return 1
  fi
  if [[ -e $P/consensus-fixed ]]; then
    tool files cmp -s "$P/consensus-fixed" "$P/place-1.summary" || { fail_attempt place-1 1; return 1; }
  else copy_record "$P/place-1.summary" "$P/consensus-fixed"; fi
  record "$P/placement-passed" placed placement; echo "placements agree"; }
build_step() { local p x wt
  need_counted; no_failed_attempt; need_posted draw
  [[ -e $P/placement-passed ]] || refuse "two placements have not agreed"
  wt=$(readfile "$P/place-worktree-1"); atcommit "$wt"
  for p in A B C; do
    run_tool build-$p "$S/build-$p" -- build caffeinate -i python3 "$SLOT" -- nice -n 19 "$S/venv/bin/bicentennial" build --tier T2 --spec "$P/placed-1/pack-$p.toml" --edition 3 --out "$S/build-$p"; x=$?
    [[ $x == 0 ]] || { fail_attempt build-$p "$x"; return $?; }
    run_tool install-$p "$S/packs-$p" -- install caffeinate -i "$PY" -m bicentennial.packs.install install "$S/build-$p/T2" "$S/packs-$p"; x=$?
    [[ $x == 0 ]] || { fail_attempt install-$p "$x"; return $?; }
    hex64 "$(readfile "$P/tools/install-$p.out")" || { fail_attempt install-$p 1; return 1; }
    copy_record "$P/tools/install-$p.out" "$S/pack-$p.hash" || exit 2
  done
  echo "three packs built and installed"; }
tasks_step() { local p x wt partial digest
  need_counted; no_failed_attempt; need_posted draw
  any_attempt && refuse "an arm has an attempt; lists must be frozen before arm 1"
  wt=$(readfile "$P/place-worktree-1"); [[ -n $wt ]] || refuse "placement is missing"; atcommit "$wt"
  for p in A B C; do
    hex64 "$(readfile "$S/pack-$p.hash")" || refuse "pack $p is not built"
    if [[ -e $P/TASKS-$p.json ]]; then
      if [[ ! -s $P/TASKS-$p.sha256 && $(readfile "$P/tools/tasks-$p.exit") == 0 ]]; then
        meta tasks "$P/TASKS-$p.json" "$(readfile "$S/commit.txt")" "$p" "$(readfile "$S/pack-$p.hash")" "$P/DRAW.json" "$P/placed-1/pack-$p.toml" || refuse "task-list recovery check failed"
        digest=$(sha "$P/TASKS-$p.json") && hex64 "$digest" || refuse "task-list hash failed"
        record "$P/TASKS-$p.sha256" "$digest" task-hash
      fi
      [[ -s $P/TASKS-$p.sha256 && $(sha "$P/TASKS-$p.json") == $(readfile "$P/TASKS-$p.sha256") ]] || refuse "frozen task list differs"; continue; fi
    partial=$P/TASKS-$p.json.part
    run_tool tasks-$p "$partial" -- tasks "$PY" "$wt/$TASKS_PY" --pack "$p" --packs "$S/packs-$p" --spec "$P/placed-1/pack-$p.toml" --draw "$P/DRAW.json" --commit "$(readfile "$S/commit.txt")" --edition 3 --out "$partial"; x=$?
    [[ $x == 0 ]] || { fail_attempt tasks-$p "$x"; return $?; }
    meta tasks "$partial" "$(readfile "$S/commit.txt")" "$p" "$(readfile "$S/pack-$p.hash")" "$P/DRAW.json" "$P/placed-1/pack-$p.toml" || { fail_attempt tasks-$p 1; return 1; }
    digest=$(sha "$partial") && hex64 "$digest" || refuse "task-list hash failed"
    record "$P/TASKS-$p.sha256" "$digest" task-hash
    tool files mv -n "$partial" "$P/TASKS-$p.json" || exit 2
    [[ ! -e $partial ]] || refuse "task-list rename is incomplete"
  done
  echo "three task lists frozen"; }
post_tasks() { local p lower body pair
  need_counted; need_posted draw; frozen_tasks
  for p in A B C; do hex64 "$(readfile "$S/pack-$p.hash")" || refuse "no pack hash"; done
  body=$({ printf 'Follow-up draw: task lists\nround %s\n' "$ROUND"
    for pair in A:a B:b C:c; do p=${pair%:*}; lower=${pair#*:}
      printf 'pack_hash_%s %s\ntasks_sha256_%s %s\n' "$lower" "$(readfile "$S/pack-$p.hash")" "$lower" "$(readfile "$P/TASKS-$p.sha256")"; done
    printf '%s\n' "$ORIGIN_MARKER"; }) || refuse "tasks body unavailable"
  record "$P/tasks.body" "$body" post-body
  match_post tasks "$P/tasks.body"; echo "task-list post recorded"; }
rebuild_step() { local f name x old=$P/first-attempt
  need_counted; any_attempt && refuse "rebuild is forbidden after an arm attempt"
  [[ -s $P/failure || -e $P/rebuild-started || -e $P/rebuild-used ]] || refuse "no failed attempt to rebuild"
  [[ ! -e $P/rebuild-used || ! -e $P/failure ]] || refuse "the one rebuild failed; stop build is next"
  [[ ! -e $P/rebuild-complete && ! -e $P/rebuild-failed ]] || refuse "the one rebuild has already been used"
  if [[ ! -e $P/rebuild-used ]]; then
  if [[ ! -e $P/rebuild-started ]]; then
    copy_record "$P/failure" "$P/first-failure"
    record "$P/rebuild-started" started rebuild-started
  fi
  tool files mkdir -p "$old" || refuse "first attempt archive unavailable"
  for name in tools DRAW.json draw.sha256 draw-worktree reproduced-DRAW.json placed-1 placed-2 place-work-1 place-work-2 place-worktree-1 place-worktree-2 placement-passed place-1.summary place-2.summary failure; do
    [[ ! -e $P/$name ]] || tool files mv -n "$P/$name" "$old/$name" || exit 2; done
  for f in "$P"/TASKS-*; do [[ ! -e $f ]] || tool files mv -n "$f" "$old/${f##*/}" || exit 2; done
  for name in build-A build-B build-C packs-A packs-B packs-C pack-A.hash pack-B.hash pack-C.hash; do
    [[ ! -e $S/$name ]] || tool files mv -n "$S/$name" "$old/$name" || exit 2; done
  record "$P/rebuild-used" used rebuild-used
  fi
  draw_step; x=$?; [[ $x == 0 ]] || return "$x"
  [[ -s $S/posted/draw.rec ]] || post_draw || return $?
  place_step; x=$?; [[ $x == 0 ]] || return "$x"
  build_step || return $?
  tasks_step; x=$?; [[ $x == 0 ]] || return "$x"
  record "$P/rebuild-complete" complete rebuild-complete; }
check3_matches() { local file=$1 code=$2
  [[ $(readfile "$file") == "commit $(readfile "$S/commit.txt")" && $(tool files tail -1 "$file") == "exit $code" ]]; }
check3_receipt() { check3_matches "$1" "$2" || refuse "check 3 receipt write failed"; }
check3_cmd() { tool check3 python3 "$SLOT" -- env PYTHONPATH="$S/wt/src" nice -n 19 "$PY" -m pytest -v -p no:cacheprovider -o tmp_path_retention_policy=failed --basetemp="$1" tests/runner/test_control_arms.py; }
rehearse_step() { local Rh=$P/rehearsal n=1 x p wt args=() hashname value hashes=""
  [[ ! -e $P/BEACON ]] || refuse "real beacon saved; rehearsal is too late"
  [[ ! -e $Rh/passed ]] || refuse "already rehearsed at this commit"
  if [[ -e $Rh ]]; then
    while [[ -e $P/rehearsal.failed-$n ]]; do n=$((n+1)); done
    tool files mv -n "$Rh" "$P/rehearsal.failed-$n" || exit 2; fi
  tool files mkdir -m 700 "$Rh" || exit 2
  new_worktree rehearsal; wt=$WT
  tool draw "$PY" "$wt/scripts/validity_roster.py" draw --packs 3 --rehearsal --out "$Rh/DRAW.json" > "$Rh/draw.out" 2> "$Rh/draw.err" || refuse "rehearsal draw failed"
  tool place "$PY" "$wt/scripts/validity_roster.py" place --packs 3 --draw "$Rh/DRAW.json" --work "$Rh/place-work" --out-dir "$Rh/placed" > "$Rh/place.out" 2> "$Rh/place.err" || refuse "rehearsal placement failed"
  for p in A B C; do
    tool build caffeinate -i python3 "$SLOT" -- nice -n 19 "$S/venv/bin/bicentennial" build --tier T2 --spec "$Rh/placed/pack-$p.toml" --edition 3 --out "$Rh/build-$p" > "$Rh/build-$p.log" 2>&1 || refuse "rehearsal build failed"
    tool install caffeinate -i "$PY" -m bicentennial.packs.install install "$Rh/build-$p/T2" "$Rh/packs-$p" > "$Rh/pack-$p.hash" 2> "$Rh/install-$p.err" || refuse "rehearsal install failed"
    hex64 "$(readfile "$Rh/pack-$p.hash")" || refuse "rehearsal install hash is malformed"
  done
  idle
  tool gate "$PY" "$wt/results/followup/run/gate_prepare.py" --packs "$Rh/packs-A" --pack-hash "$(readfile "$Rh/pack-A.hash")" --hermes "$H" > "$Rh/gate.out" 2> "$Rh/gate.err" || refuse "rehearsal preparation refused"
  tool files grep -qx "benchmark_commit $(readfile "$S/commit.txt")" "$Rh/gate.out" || refuse "rehearsal preparation names another commit"
  tool pins "$S/venv/bin/bicentennial" pins --system hermes-native --hermes "$H" > "$Rh/pins.out" 2> "$Rh/pins.err" || refuse "rehearsal install pins refused"
  for hashname in registry_entry_sha256 fresh_install_hash artifact_sha256 system_hash harness_hash route_table_hash; do
    case $hashname in
      fresh_install_hash) value=$(tool files awk '$1=="fresh_install_hash" {print $2}' "$Rh/pins.out") ;;
      artifact_sha256) value=$(tool files awk '$1=="artifact.sha256" {print $2}' "$Rh/pins.out") ;;
      *) value=$(tool files awk -v key="$hashname" '$1==key {print $2}' "$Rh/gate.out") ;;
    esac
    hex64 "$value" || refuse "rehearsal hash is missing or malformed"
    hashes="$hashes$hashname $value"$'\n'
  done
  record "$Rh/h.values" "${hashes%$'\n'}" rehearsal-hashes
  for p in A B C; do
    tool tasks "$PY" "$wt/$TASKS_PY" --pack "$p" --packs "$Rh/packs-$p" --spec "$Rh/placed/pack-$p.toml" --draw "$Rh/DRAW.json" --commit "$(readfile "$S/commit.txt")" --edition 3 --out "$Rh/TASKS-$p.json" > "$Rh/tasks-$p.out" 2> "$Rh/tasks-$p.err" || refuse "rehearsal task list refused"
    meta tasks "$Rh/TASKS-$p.json" "$(readfile "$S/commit.txt")" "$p" "$(readfile "$Rh/pack-$p.hash")" "$Rh/DRAW.json" "$Rh/placed/pack-$p.toml" || refuse "rehearsal task list check failed"
    args+=(--pack "$p" "$Rh/packs-$p" "$Rh/TASKS-$p.json" "$(sha "$Rh/TASKS-$p.json")")
  done
  for hashname in system_hash harness_hash route_table_hash; do value=$(tool files awk -v key="$hashname" '$1==key {print $2}' "$Rh/h.values")
    case $hashname in system_hash) args+=(--system-hash "$value") ;; harness_hash) args+=(--harness-hash "$value") ;; route_table_hash) args+=(--route-table-hash "$value") ;; esac; done
  args+=(--order "$(IFS=,; echo "${ORDER[*]}")" --attempts "$(IFS=,; echo "${ORDER[*]}")")
  for p in "${ORDER[@]}"; do args+=("$p=$Rh/no-arms/$p"); done
  tool table "$PY" "$wt/$TABLE" "${args[@]}" > "$Rh/table.out" 2> "$Rh/table.err"; x=$?
  [[ $x == 4 ]] || refuse "rehearsal no-arms reading must exit 4"
  { printf 'commit %s\n' "$(readfile "$S/commit.txt")"; check3_cmd "$Rh/check3-tmp"; x=$?; printf 'exit %s\n' "$x"; } > "$Rh/check3.txt" 2>&1
  check3_receipt "$Rh/check3.txt" "$x"
  [[ $x == 0 ]] || refuse "rehearsal check 3 failed"
  tool followup-tests python3 "$SLOT" -- env PYTHONPATH="$wt/src" nice -n 19 "$PY" -m pytest -q -p no:cacheprovider -o tmp_path_retention_policy=failed --basetemp="$Rh/followup-tmp" results/followup/run/test_*.py tests/test_developer_doc.py > "$Rh/followup-tests.log" 2>&1 || refuse "rehearsal follow-up tests failed"
  tool derivation-tests python3 "$SLOT" -- env PYTHONPATH="$wt/src" nice -n 19 "$PY" -m pytest -q -p no:cacheprovider -o tmp_path_retention_policy=failed --basetemp="$Rh/derivation-tmp" tests/test_validity_roster.py tests/test_developer_doc.py > "$Rh/derivation-tests.log" 2>&1 || refuse "rehearsal derivation tests failed"
  tool dr "$BASEPY" -I "$wt/$DR_PY" init --state "$Rh/draw" > "$Rh/dr-init.out" 2> "$Rh/dr-init.err" || refuse "rehearsal draw-record init refused"
  tool dr "$BASEPY" -I "$wt/$DR_PY" beacon --state "$Rh/draw" --rehearsal > "$Rh/beacon.out" 2> "$Rh/beacon.err"; x=$?
  [[ $x == 0 ]] && tool files grep -qx 'rehearsal-beacon pass' "$Rh/beacon.out" || refuse "rehearsal beacon derivation failed"
  record "$Rh/passed" "$(readfile "$S/commit.txt")" rehearsal-pass
  printf 'run_commit %s\n' "$(readfile "$S/commit.txt")"; tool files cat "$Rh/h.values"; echo "rehearsal passed"; }
prep_step() { local SHA=${1:-} import="" mode=official pr merge path official="" entries name value required=() prs=()
  [[ -n $SHA ]] || refuse "prep needs a main commit and prerequisite pull requests"; shift
  hex40 "$SHA" || refuse "main commit must be forty lowercase hex characters"
  while (( $# )); do
    case $1 in
      --import) (( $# >= 2 )) || refuse "import needs an old state or none"
        [[ $2 == none ]] || refuse "import of a state directory is not supported: a directory runs only the draw it posted"
        import=$2; shift 2 ;;
      *) [[ $1 =~ ^[1-9][0-9]*$ ]] || refuse "prerequisites must be pull-request numbers"; prs+=("$1"); shift ;;
    esac
  done
  (( ${#prs[@]} > 0 )) || refuse "prep needs at least one prerequisite pull request"
  for name in "${setting_names[@]}"; do [[ -n ${!name:-} ]] || refuse "required setting is missing: $name"; done
  [[ $ORIGIN_MARKER == '<!-- agent-origin:v1 '* && $ORIGIN_MARKER == *' -->' && $ORIGIN_MARKER != *$'\n'* ]] || refuse "ORIGIN_MARKER has the wrong form"
  [[ -f $OFFICIAL_RECORD ]] && official=$(readfile "$OFFICIAL_RECORD")
  if [[ $S == "$official" && -e $S/$TEST_MARKER ]]; then
    [[ ! -d $P ]] || record "$P/official-tainted" tainted official-taint
    refuse "official state was marked as a test directory"
  fi
  if [[ -e $S ]]; then
    [[ -d $S && -f $S/$TEST_MARKER ]] || refuse "prep needs a new directory or only a test marker"
    entries=$(tool files ls -A "$S")
    [[ $entries == "$TEST_MARKER" ]] || refuse "prep directory holds more than the test marker"
    mode=test
  elif [[ -n $official && -z $import ]]; then refuse "another official directory is recorded"; fi
  PREPARING=1
  tool files mkdir -p "$S/runs" "$S/logs" "$S/diag" "$S/posted" "$S/worktrees" "$P" || exit 2
  tool files chmod 700 "$S" "$P" || exit 2
  if [[ $import == none ]]; then
    [[ -n $official && ! -e $official ]] || refuse "old state directory still exists or is not recorded"
    record "$P/import.record" "old state lost" import
  fi
  tool gh env -i PATH="$PATH" HOME="$HOME" gh auth status > "$P/auth.out" 2> "$P/auth.err" || refuse "stored gh login required: S4 removes every GH_ variable"
  tool git-fetch git -C "$R" fetch -q origin main > "$P/fetch.out" 2> "$P/fetch.err" || refuse "main fetch failed"
  tool git git -C "$R" merge-base --is-ancestor "$SHA" origin/main >/dev/null 2>&1 || refuse "run commit is not on main"
  required=(results/followup/DECLARATION.md scripts/validity_roster.py src/bicentennial/items/editions.py specs/ring0/template-admissions.json)
  for name in run-followup.sh gate_prepare.py tasks.py table.py cut_cards.py draw_record.py; do required+=("results/followup/run/$name"); done
  for path in "${required[@]}"; do tool git git -C "$R" cat-file -e "$SHA:$path" >/dev/null 2>&1 || refuse "required file missing at run commit"; done
  tool git git -C "$R" show "$SHA:scripts/validity_roster.py" > "$P/roster-check"
  tool files grep -q -- '"--packs"' "$P/roster-check" || refuse "seed tool lacks three-pack mode"
  tool git git -C "$R" show "$SHA:src/bicentennial/items/editions.py" > "$P/edition-check"
  tool files grep -q '^    3: ' "$P/edition-check" || refuse "edition 3 is not registered"
  tool git git -C "$R" show "$SHA:specs/ring0/template-admissions.json" > "$P/admissions-check"
  meta admissions "$P/admissions-check" || refuse "v3 template admissions are missing"
  for pr in "${prs[@]}" 573; do
    tool gh gh pr view "$pr" --repo "$REPO" --json state,mergeCommit > "$P/pr-$pr.json" 2> "$P/pr-$pr.err" || refuse "prerequisite pull request cannot be read"
    merge=$(meta pr "$P/pr-$pr.json") || refuse "prerequisite pull request is not merged"
    tool git git -C "$R" merge-base --is-ancestor "$merge" "$SHA" >/dev/null 2>&1 || refuse "prerequisite merge is outside the run history"
    [[ $pr != 573 ]] || record "$P/declaration.commit" "$merge" declaration-commit
  done
  tool git git -C "$R" show "$SHA:results/followup/DECLARATION.md" > "$P/declaration.run"
  tool git git -C "$R" show "$(readfile "$P/declaration.commit"):results/followup/DECLARATION.md" > "$P/declaration.merged" || refuse "merged declaration unavailable"
  tool files cmp -s "$P/declaration.run" "$P/declaration.merged" || refuse "run declaration differs from the merged declaration"
  tool git-worktree git -C "$R" worktree prune > "$P/prep-prune.log" 2>&1 || refuse "stale worktree registrations could not be pruned"
  tool git-worktree git -C "$R" -c core.hooksPath=/dev/null worktree add --detach "$S/wt" "$SHA" > "$P/prep-worktree.log" 2>&1 || refuse "run worktree could not be created"
  record "$S/commit.txt" "$SHA" run-commit
  tool venv "$BASEPY" -m venv "$S/venv" > "$P/venv.log" 2>&1 || refuse "venv creation failed"
  tool pip nice -n 19 "$PY" -m pip install -q -e "$S/wt[dev]" > "$P/pip.log" 2>&1 || refuse "venv install failed"
  tool pytest-import "$PY" -c 'import pytest' > "$P/pytest-import.log" 2>&1 || refuse "pytest is missing from the venv"
  atcommit
  dr init > "$P/init.out" 2> "$P/init.err" || refuse "draw-record init refused"
  dr read > "$P/prep-read.out" 2> "$P/prep-read.err" || refuse "draw-record read refused"
  dr publish-list > "$P/prep-list.json" 2> "$P/prep-list.err" || refuse "draw-record list refused"
  if [[ -z $import ]]; then meta new-directory "$P/prep-list.json" || refuse "draw already began in another state directory"
  elif [[ $import == none ]]; then
    meta lost-after-draw "$P/prep-list.json"; local lost=$?
    [[ $lost == 0 || $lost == 1 ]] || refuse "lost-state draw list unavailable"
    if [[ $lost == 0 ]]; then record "$P/state-lost-after-draw" "state lost after the draw: no arm can run; readings unresolved (§10, missing data)" lost-state; fi
  fi
  printf '%s\n' "${prs[@]}" > "$S/prerequisites"
  tool files ln -s private/rehearsal "$S/rehearsal" || refuse "rehearsal link creation failed"
  record "$S/mode" "$mode" mode
  meta settings "$P/settings" "${setting_names[@]}" || refuse "settings could not be fixed"
  if [[ $mode == official ]]; then record "$OFFICIAL_RECORD" "$S" official-state; fi
  PREPARING=0
  echo "prepared run commit"; }
# One sequence counter orders attempts and readings. Refused invocations retain
# their own number but contribute no attempt record.
rerun_named() { local last="" number=0 f n label=$3
  for f in "$1"/table-*.seq; do [[ -e $f ]] || continue; n=$(readfile "$f")
    if (( n > number )); then number=$n; last=${f%.seq}; fi; done
  [[ -n $last && -e $last.txt ]] || { echo "no completed reading names the label"; return 1; }
  for f in "$1"/*.seq; do
    [[ -e $f ]] || continue
    case ${f##*/} in *.inv-*|table-*) continue ;; esac
    (( $(readfile "$f") < number )) || { echo "latest reading predates an attempt"; return 1; }; done
  { tool files sed -n 's/^pending before any score: \(.*\) - rerun once.*/\1/p' "$last.txt" | tool files tr ' ' '\n'
    tool files sed -n 's/^INVALID CONTROL ROW //p' "$last.txt"; } | tool files grep -Fqx -- "$label" || { echo "latest reading does not name the label"; return 1; }; }
reading_terminal() { local f
  for f in "$S"/logs/table-*.exit; do [[ -e $f ]] || continue
    case $(readfile "$f") in 0|5) return 0 ;; esac; done
  for f in "$S"/logs/table-*.pre-exit; do [[ -e $f && $(readfile "$f") == 5 ]] && return 0; done
  for f in "$S"/logs/table-*.txt; do [[ -e $f ]] || continue
    tool files grep -qE '^(== 3\. Scores|RUN ENDS:|fault: (run order|card pins|pack code pins)$)' "$f" && return 0; done
  check3_failed_twice; }
arm_cmd() { local out=$1 diag=$2 control=$3 pack=$4 cache=$5 args=()
  args=(caffeinate -i /bin/bash "$ENVW" "$S/venv/bin/bicentennial" t2 --system hermes-native --packs "$S/packs-$pack" --pack-hash "$(readfile "$S/pack-$pack.hash")" --hermes "$H" --login-home "$LOGIN" --max-sends "$CAP" --out "$out")
  if [[ -n $control ]]; then args+=(--control "$control" --diagnostics "$diag"); else args+=(--cache "$cache"); fi
  tool arm "${args[@]}"; }
finish_invocation() { local tag=$1 I="" f n newest=0 out=$S/runs/$1 diag=$S/diag/$1 part
  [[ ! -s $S/logs/$tag.seq ]] || return 0
  for f in "$S"/logs/"$tag".inv-*.start; do
    [[ -e $f ]] || continue; n=${f##*.inv-}; n=${n%.start}
    if (( n > newest )); then newest=$n; I=${f%.start}; fi
  done
  [[ -n $I && -s $I.exit ]] || return 0
  if [[ -e $I.guard-out ]] || { [[ $(readfile "$I.exit") == exit=3 ]] && guard_refused "$out" "$diag"; }; then
    [[ ! -e $out ]] || tool files mv -n "$out" "$I.guard-out" || refuse "guard output move failed"
    [[ ! -e $diag ]] || tool files mv -n "$diag" "$I.guard-diag" || refuse "guard diagnostics move failed"
  elif [[ -e $out ]]; then
    for part in start end exit killed; do
      [[ ! -f $I.$part ]] || copy_record "$I.$part" "$S/logs/$tag.$part"
    done
    copy_record "$I.seq" "$S/logs/$tag.seq"
  fi
  if [[ ! -e $out && -e $diag ]]; then
    tool files mv -n "$diag" "$I.orphan-diag" || refuse "orphan diagnostics move failed"; fi
}
arm_step() { local mode=$1 label=${2:-} control="" p arm tag l why out diag cache="" k=1 I seq x s f official=""
  [[ -n $label ]] || refuse "arm label is required"
  tool files printf '%s\n' "${ORDER[@]}" | tool files grep -Fqx -- "$label" || refuse "unknown arm label"
  p=${label%%.*}; arm=${label#*.}; control=$(control_of "$arm") || [[ $arm == H1 || $arm == H2 ]] || refuse "unknown arm label"
  for l in "${ORDER[@]}"; do finish_invocation "$l"; finish_invocation "$l.rerun"; done
  for f in "$S"/logs/*.inv-*.start; do
    if [[ -e $f && ! -e ${f%.start}.exit ]]; then
      s=${f##*/}; refuse "abandon open invocation ${s%.inv-*} first"; fi; done
  for l in "${ORDER[@]}"; do
    for tag in "$l" "$l.rerun"; do
      [[ ! -e $S/runs/$tag || -s $S/logs/$tag.seq ]] || refuse "attempt lacks its sequence: $tag"; done; done
  need_counted; frozen_tasks; need_posted draw; need_posted tasks
  [[ $(readfile "$S/posted/commit.rec") == "$(readfile "$P/evaluate.out")" ]] || refuse "counted post record differs"
  check3_file && check3_matches "$C3" 0 || refuse "check 3 must pass before an arm"
  check3_failed_twice && refuse "check 3 failed twice; run ended"
  if [[ $mode == run ]]; then
    for l in "${ORDER[@]}"; do [[ $l == "$label" ]] && break
      [[ -e $S/runs/$l && -s $S/logs/$l.seq ]] || refuse "$l has no attempt yet"; done
    [[ ! -e $S/runs/$label && ! -e $S/logs/$label.seq ]] || refuse "label already has its first attempt"
    tag=$label
  else
    all_attempts
    [[ -e $S/runs/$label && -s $S/logs/$label.seq ]] || refuse "label has no first attempt"
    [[ ! -e $S/runs/$label.rerun && ! -e $S/logs/$label.rerun.seq ]] || refuse "label already has its one rerun"
    reading_terminal && refuse "scores opened or run ended; no rerun"
    why=$(rerun_named "$S/logs" "$S/runs" "$label") || refuse "$why"
    tag=$label.rerun
  fi
  out=$S/runs/$tag; diag=$S/diag/$tag
  [[ ! -e $diag ]] || refuse "diagnostics exist without their attempt"
  [[ -f $OFFICIAL_RECORD ]] && official=$(readfile "$OFFICIAL_RECORD")
  fake || [[ $S == "$official" && ! -e $S/$TEST_MARKER ]] || refuse "real arms require the recorded official directory"
  arm_alive && refuse "an arm process is already running"
  if [[ -z $control ]]; then
    cache=$S/cache-$p
    if [[ $arm == H1 && $mode == rerun ]]; then cache=$S/cache-$p-H1-rerun; fi
    if [[ $arm == H1 ]]; then
      [[ ! -e $cache ]] || [[ -d $cache && -z $(tool files ls -A "$cache") ]] || refuse "H1 floor cache is not empty"
      tool files mkdir -p "$cache" || refuse "floor cache could not be created"
    else [[ -d $cache ]] || refuse "H1 first-attempt cache is missing"; fi
  fi
  idle
  while [[ -e $S/logs/$tag.inv-$k.start ]]; do k=$((k+1)); done
  seq=$(next_number) || refuse "sequence reservation failed"; I=$S/logs/$tag.inv-$k
  record "$I.seq" "$seq" "invocation sequence"; record "$I.start" "$(clock_now)" invocation-start
  [[ $(readfile "$I.seq") == "$seq" ]] || refuse "invocation sequence record write failed"
  arm_cmd "$out" "$diag" "$control" "$p" "$cache" > "$I.out" 2> "$I.err"; x=$?
  record "$I.end" "$(clock_now)" invocation-end; record "$I.exit" "exit=$x" invocation-exit
  finish_invocation "$tag"
  if [[ -e $I.guard-out ]]; then echo "machine guard refused before any unit: invocation kept, not an attempt"
  elif [[ -e $out ]]; then echo "$tag attempt recorded"
  else echo "invocation refused before output: not an attempt"; fi
  return "$x"; }
check3_step() { local n=1 x
  need_counted; need_posted tasks; frozen_tasks
  any_attempt && refuse "check 3 cannot run after an arm attempt"
  while [[ -e $P/check3-$n.txt ]]; do n=$((n+1)); done
  (( n <= 2 )) || refuse "check 3 has run twice"
  if (( n == 2 )); then
    ! check3_matches "$P/check3-1.txt" 0 || refuse "check 3 already passed"; fi
  { printf 'commit %s\n' "$(readfile "$S/commit.txt")"; check3_cmd "$S/check3-tmp-$n"; x=$?; printf 'exit %s\n' "$x"; } > "$P/check3-$n.txt" 2>&1
  check3_receipt "$P/check3-$n.txt" "$x"
  printf 'check 3 attempt %s exit %s\n' "$n" "$x"; return "$x"; }
stale_lock() { local owner="" f current age
  if [[ -d $S/lock ]]; then
    [[ ! -L $S/lock ]] || refuse "lock shape is invalid"
    for f in "$S"/lock/*; do [[ -e $f ]] && owner=${f##*/}; done
    if [[ -n $owner ]]; then
      [[ $owner =~ ^[0-9]+$ && -d $S/lock/$owner && ! -L $S/lock/$owner ]] || refuse "lock owner shape is invalid"
      if [[ -s $S/lock/$owner/start ]]; then
        tool ps ps -o lstart= -p "$owner" > "$P/lock-owner-probe" 2>/dev/null
        if [[ -s $P/lock-owner-probe ]] && tool files cmp -s "$S/lock/$owner/start" "$P/lock-owner-probe"; then refuse "a step still holds the lock"; fi
      else old_enough "$S/lock/$owner" || refuse "lock owner may be starting"; fi
    else
      current=$(clock_now); age=$(tool files stat -f %m "$S/lock") || refuse "cannot read lock age"
      (( current - age >= 60 )) || refuse "ownerless lock may be starting"
    fi
    arm_alive && refuse "an arm process is still running"
    if [[ -n $owner ]]; then
      tool files rm -f "$S/lock/$owner/start" "$S/lock/$owner/start.part" 2>/dev/null || refuse "lock owner changed"
      tool files rmdir "$S/lock/$owner" 2>/dev/null || refuse "lock owner changed"; fi
    tool files rmdir "$S/lock" 2>/dev/null || refuse "stale lock changed"
    echo "removed stale lock"
  fi; }
abandon_step() { local tag=${1:-} f open="" s
  [[ $tag =~ ^[ABC]\.(F[12]|R[12]|O[123]|H[12]|B1|G1|W1)(\.rerun)?$ ]] || refuse "unknown invocation label"
  arm_alive && refuse "an arm process is still running"
  finish_invocation "$tag"
  for f in "$S"/logs/"$tag".inv-*.start; do [[ -e $f && ! -e ${f%.start}.exit ]] && open=${f%.start}; done
  [[ -n $open ]] || { echo "no open invocation; stale lock checked"; return 0; }
  if [[ ! -e $S/runs/$tag && -f $open.seq ]] && ! [[ $(readfile "$open.seq") =~ ^[0-9]{1,18}$ ]]; then
    tool files mv -n "$open.seq" "$open.seq.failed" && [[ ! -e $open.seq ]] || refuse "unstarted sequence archive failed"
  fi
  record "$open.end" "$(clock_now)" abandoned-end
  copy_record "$open.end" "$open.killed"
  record "$open.exit" exit=abandoned abandoned-exit
  finish_invocation "$tag"
  echo "abandoned invocation recorded"; }
table_once() { local suffix=$1; shift; local n x flag flags=()
  n=$(next_number) || refuse "sequence reservation failed"; T=$S/logs/table-$n
  [[ $suffix != pre ]] || T=$T.pre
  record "$T.seq" "$n" table-sequence
  for flag in "$@"; do
      case $flag in
        "$S"/*) flag=${flag#"$S"/} ;;
        *="$S"/*) flag="${flag%%=*}=${flag#*="$S"/}" ;;
      esac
      flags+=("$flag")
    done
  tool files printf '%s\n' "${flags[@]+"${flags[@]}"}" > "$T.flags" || refuse "table flags record write failed"
  tool table "$PY" "$S/wt/$TABLE" "$@" --filter-out "$P/FILTER-$n.json" > "$T.txt" 2> "$T.err"; x=$?
  if [[ $suffix == pre ]]; then record "${T%.pre}.pre-exit" "$x" table-exit
  else record "$T.exit" "$x" table-exit; fi
  # The reader's own output is public-safe; no private command line is echoed.
  tool files cat "$T.txt"
  return "$x"; }
table_step() { local after="" p l tag seq f b order attempts reruns="" x pre pending
  local args=() labels=() used=() every=() used_records="" all_records=""
  need_counted; all_attempts; frozen_tasks
  check3_file || refuse "check 3 receipt is missing"
  for f in "$S"/logs/*.inv-*.start; do [[ -e $f && ! -e ${f%.start}.exit ]] && refuse "abandon open invocation first"; done
  arm_alive && refuse "an arm process is still running"
  while (( $# )); do case $1 in --after-reruns) after=1 ;; *) refuse "unknown table flag" ;; esac; shift; done
  for p in A B C; do args+=(--pack "$p" "$S/packs-$p" "$P/TASKS-$p.json" "$(readfile "$P/TASKS-$p.sha256")"); done
  meta h-hashes "$P/counted.json" "$P/h-hash-faults.json" > "$P/h-hash-options" || refuse "counted H values unavailable"
  while read -r f b; do args+=("$f" "$b"); done < "$P/h-hash-options"
  for l in "${ORDER[@]}"; do
    tag=$l
    if [[ -e $S/runs/$l.rerun ]]; then tag=$l.rerun; reruns="$reruns,$l"; fi
    [[ -s $S/logs/$tag.seq ]] || refuse "used attempt lacks its sequence"
    used_records="$used_records$(readfile "$S/logs/$tag.seq") $l"$'\n'
    labels+=("$l=$S/runs/$tag")
    all_records="$all_records$(readfile "$S/logs/$l.seq") $l"$'\n'
    if [[ $tag != "$l" ]]; then all_records="$all_records$(readfile "$S/logs/$tag.seq") $tag"$'\n'; fi
  done
  record "$P/used-sequences" "${used_records%$'\n'}" reading-order
  record "$P/all-sequences" "${all_records%$'\n'}" reading-attempts
  order=$(tool files sort -n "$P/used-sequences" | tool files awk '{print $2}' | tool files paste -sd, -)
  attempts=$(tool files sort -n "$P/all-sequences" | tool files awk '{print $2}' | tool files paste -sd, -)
  args+=(--order "$order" --attempts "$attempts" --check3 "$C3")
  reruns=${reruns#,}; [[ -z $reruns ]] || args+=(--reruns "$reruns")
  if [[ -n $after ]]; then
    table_once pre "${args[@]}" --checks-only "${labels[@]}"; pre=$?
    if check3_failed_twice || [[ $pre == 5 ]]; then :
    elif [[ $pre == 4 ]]; then
      pending=$(tool files sed -n 's/^pending before any score: \(.*\) - rerun once.*/\1/p' "$T.txt" | tool files tail -1)
      [[ -n $pending ]] || refuse "pending reading named no arm"
      for l in $pending; do [[ -e $S/runs/$l.rerun ]] || refuse "pending arm still owes its rerun"; done
    elif [[ $pre == 0 ]]; then refuse "nothing pending; table without after-reruns"
    else refuse "checks must be fixed before after-reruns"; fi
    args+=(--after-reruns)
  fi
  table_once final "${args[@]}" "${labels[@]}"; x=$?; return "$x"; }
score_opened() { local f
  for f in "$S"/logs/table-*.exit; do [[ -e $f && $(readfile "$f") == 0 ]] && return 0; done; return 1; }
next_folder() { local root=$1 n=1; FOLDER=$root
  while [[ -e $FOLDER || -e $FOLDER.hashes || -e $FOLDER.outcome ]]; do FOLDER=$root-$n; n=$((n+1)); done; }
cut_group() { local p=$1 group=$2 label tag root out x fault f n args=() remaining=() missing=() faults=()
  root=$S/publish/cards-$p; [[ $group != first ]] || root=$root-first
  for label in "${ORDER[@]}"; do
    [[ ${label%%.*} == "$p" ]] || continue
    tag=$label
    if [[ $group == first ]]; then [[ -e $S/runs/$label.rerun ]] || continue
    elif [[ -e $S/runs/$label.rerun ]]; then tag=$label.rerun; fi
    if [[ -f $S/runs/$tag/card.json ]]; then args+=("$label=$S/runs/$tag"); else missing+=("$label"); fi
  done
  while :; do
    next_folder "$root"; out=$FOLDER
    printf '%s\n' "${missing[@]+"${missing[@]}"}" > "$out.missing"
    printf '%s\n' "${faults[@]+"${faults[@]}"}" > "$out.faulted"
    if (( ${#args[@]} == 0 )); then printf 'no cards\n' > "$out.outcome"; return 0; fi
    tool cutter python3 -I "$S/wt/results/followup/run/cut_cards.py" "$P/TASKS-$p.json" "$out" "${args[@]}" > "$out.hashes" 2> "$out.fault"; x=$?
    printf 'exit %s\n' "$x" > "$out.outcome"
    [[ $x != 3 ]] && return 0
    fault=$(readfile "$out.fault")
    [[ $fault != card ]] || return 0
    remaining=(); n=0
    for f in "${args[@]}"; do
      if [[ ${f%%=*} == "$fault" ]]; then n=$((n+1)); else remaining+=("$f"); fi
    done
    (( n == 1 )) || return 0
    faults+=("$fault"); args=("${remaining[@]+"${remaining[@]}"}")
  done; }
cards_step() { local p label replaced
  score_opened || refuse "cards needs a table exit 0"
  frozen_tasks; tool files mkdir -p "$S/publish"
  for p in A B C; do
    cut_group "$p" used; replaced=""
    for label in "${ORDER[@]}"; do [[ ${label%%.*} == "$p" && -e $S/runs/$label.rerun ]] && replaced=1; done
    [[ -z $replaced ]] || cut_group "$p" first
    record "$P/cards-$p.done" recorded cards
  done
  echo "card outcomes recorded"; }
release_allowed() { local f x output
  [[ -e $P/stopped || -e $P/blocked || -e $P/void-unconfirmed || -e $P/state-lost-after-draw || -e $P/counted-not-own ]] && return 0
  check3_failed_twice && return 0
  [[ -e $P/cards-A.done && -e $P/cards-B.done && -e $P/cards-C.done ]] && return 0
  for f in "$S"/logs/table-*.exit "$S"/logs/table-*.pre-exit; do
    [[ -e $f ]] || continue; x=$(readfile "$f")
    output=${f%.exit}.txt; [[ $f != *.pre-exit ]] || output=${f%.pre-exit}.pre.txt
    [[ $x == 5 ]] && return 0
    [[ $x == 3 ]] && tool files grep -qE '^fault: (run order|card pins|pack code pins)$' "$output" && return 0
  done
  return 1; }
publish_file() { local source=$1 target=$S/publish/$2 candidate=$P/public-candidate n=1 original
  meta safe-copy "$source" "$candidate" "$S/wt/scripts/public_check.py" || refuse "publication copy failed"
  original=$target
  while [[ -e $target ]]; do
    tool files cmp -s "$candidate" "$target" && return 0
    target=$original.$n; n=$((n+1))
  done
  tool files mkdir -p "${target%/*}" || refuse "publication directory failed"
  tool files cp -n "$candidate" "$target" || refuse "publication copy failed"
  [[ $target == "$original" ]] || echo "published difference"; }
release_draw() { local folder=$1 name=$2 is_void=${3:-0} commit wt x number second y draw rel index=0
  if [[ $is_void == 1 && ( ! -f $folder/BEACON || ! -f $folder/DRAW.json || ! -f $folder/placed-1/void.json || ! -f $folder/placed-2/void.json ) ]]; then
    record "$P/void-release.outcome" 'void not reproduced: under §2 the earlier draw stands' void-outcome
    publish_file "$P/void-release.outcome" "$name/void.outcome"
    echo 'void not reproduced: under §2 the earlier draw stands'; return 0
  fi
  [[ -f $folder/BEACON ]] || return 0
  next_folder "$P/release-beacon-$name"; local check=$FOLDER
  tool files mkdir -p "$check"
  tool dr "$BASEPY" -I "$S/wt/$DR_PY" init --state "$check/state" > "$check/init.out" 2> "$check/init.err"; x=$?
  if [[ $x == 0 ]]; then
    tool dr "$BASEPY" -I "$S/wt/$DR_PY" beacon --state "$check/state" --rehearsal --fixture "$folder/BEACON" > "$check/check.out" 2> "$check/check.err"; x=$?
  fi
  printf 'exit %s\n' "$x" > "$check/exit"
  [[ ! -e $check/check.out ]] || publish_file "$check/check.out" "beacon-check-$name.txt"
  publish_file "$check/exit" "beacon-check-$name.exit"
  commit=$(readfile "$S/commit.txt")
  if [[ -f $folder/counted.json ]]; then commit=$(meta commit "$folder/counted.json") || refuse "release counted commit unavailable"; fi
  # Retained failed and interrupted draws belong to this same counted round.
  # Verification faults are published and never hide their saved input.
  while IFS= read -r -d '' draw; do
    rel=${draw#"$folder/"}
    case $rel in draw/*|rehearsal*|void-*/*|release-beacon-*/*) continue ;; esac
    index=$((index+1))
    (new_worktree release-$name "$commit"; wt=$WT
      tool verify "$PY" "$wt/scripts/validity_roster.py" verify --packs 3 --beacon "$folder/BEACON" --draw "$draw") > "$check/verify-$index.out" 2> "$check/verify-$index.err"; x=$?
    printf 'exit %s\n' "$x" > "$check/verify-$index.exit"
    if [[ $draw == "$folder/DRAW.json" ]]; then rel=draw-check-$name
    else rel=draw-check-$name-retained-$index; fi
    publish_file "$check/verify-$index.out" "$rel.txt"; publish_file "$check/verify-$index.exit" "$rel.exit"
    [[ $x == 0 ]] || echo "draw verification disagrees; still published"
  done < <(trap - EXIT; tool files find "$folder" -type f \( -name '*DRAW*.json' -o -name '*DRAW*.json.cut-*' \) -print0)
  [[ $is_void == 1 ]] || return 0
  (new_worktree void-release-$name "$commit"; wt=$WT
    tool draw "$PY" "$wt/scripts/validity_roster.py" draw --packs 3 --beacon "$folder/BEACON" --out "$check/DRAW.json" || exit $?
    tool files cmp -s "$folder/DRAW.json" "$check/DRAW.json" || exit 1
    tool place "$PY" "$wt/scripts/validity_roster.py" place --packs 3 --draw "$check/DRAW.json" --work "$check/place-work" --out-dir "$check/placed" > "$check/place.out" 2> "$check/place.err"; y=$?
    [[ $y == 1 ]] || exit 1
    tool files cmp -s "$folder/placed-1/void.json" "$check/placed/void.json" &&
    tool files cmp -s "$folder/placed-2/void.json" "$check/placed/void.json") > "$check/reproduce.out" 2> "$check/reproduce.err"; x=$?
  if [[ $x == 0 ]]; then printf 'void reproduced\n' > "$check/void.outcome"
  else printf 'void not reproduced: under §2 the earlier draw stands\n' > "$check/void.outcome"; echo 'void not reproduced: under §2 the earlier draw stands'; fi
  publish_file "$check/void.outcome" "$name/void.outcome"; }
release_step() { local x f rel folder n name
  dr read > "$P/release-read.out" 2> "$P/release-read.err" || refuse "release draw read refused"
  dr evaluate > "$P/release-evaluate.out" 2> "$P/release-evaluate.err"; x=$?
  [[ $x != 14 ]] || copy_record "$P/release-evaluate.out" "$P/stopped"
  # A void discovered before the usual evaluation refused must also be publishable.
  reconcile_voids
  release_allowed || refuse "release needs a declared terminal event or all card outcomes"
  tool files mkdir -p "$S/publish"
  dr evaluate --recheck > "$P/recheck.out" 2> "$P/recheck.err" || refuse "release recheck refused"
  tool files cat "$P/recheck.out"
  publish_file "$P/recheck.out" recheck.txt
  dr publish-list > "$P/publish-list.json" 2> "$P/publish-list.err" || refuse "release list refused"
  publish_file "$P/publish-list.json" draw-list.json
  n=1; while [[ -e $S/publish/draw-record-$n ]]; do n=$((n+1)); done
  dr publish-records "$S/publish/draw-record-$n" > "$P/publish-records.out" 2> "$P/publish-records.err" || refuse "release record export refused"
  # Sanitize exported text in place only if needed; retain its original hash.
  for f in "$S/publish/draw-record-$n/records/"*; do
    [[ -f $f ]] || continue
    meta sanitize "$f" "$S/wt/scripts/public_check.py" || refuse "export sanitation failed"
  done
  while IFS= read -r -d '' f; do
    rel=${f#"$P/"}
    case $rel in
      exports/*|draw/*|rehearsal*|*place-work*|build-[ABC]|build-[ABC]/*|*/build-[ABC]|*/build-[ABC]/*|*packs-*|*tools*|*release-beacon*|*.log|*.err|*void-check*) continue ;;
      *DRAW.json*|*/BEACON|*/DRAW.json|*/draw.sha256|*/TASKS-*|*/placed-*/*|worktree-*.commit|*/worktree-*.commit|BEACON|DRAW.json|draw.sha256|TASKS-*|FILTER-*|placed-*/*|void-*/*|*counted*|*reading-commit*|*blocked*|*differences*|import.record|state-lost-after-draw|*confirm*|*unconfirmed*|check3-*|*.body|*match*|*stop*|first-failure|rebuild-failed|consensus-fixed) publish_file "$f" "$rel" ;;
    esac
  done < <(trap - EXIT; tool files find "$P" -type f -print0)
  : > "$P/log-hashes"
  for f in "$S"/logs/*; do
    [[ -f $f ]] || continue; rel=${f##*/}
    case $rel in table-*.txt|table-*.exit|table-*.pre-exit|table-*.seq|table-*.flags|*.start|*.end|*.seq|*.exit|*.killed) publish_file "$f" "records/$rel" ;;
      *) printf '%s %s\n' "$rel" "$(sha "$f")" >> "$P/log-hashes" ;;
    esac
  done
  for f in "$S"/posted/*; do [[ ! -f $f ]] || publish_file "$f" "posted/${f##*/}"; done
  # Tool logs stay private; hashes of both attempts and voids remain checkable.
  tool files find "$P" -type f -name '*.out' -o -type f -name '*.err' -o -type f -name '*.log' -o -type f -name '*.reason' -o -type f -name '*.cutoff-failure' > "$P/tool-log-paths"
  : > "$P/tool-log-hashes"
  while IFS= read -r f; do printf '%s %s\n' "${f#"$P/"}" "$(sha "$f")" >> "$P/tool-log-hashes"; done < "$P/tool-log-paths"
  publish_file "$P/tool-log-hashes" tool-log-hashes.txt
  [[ ! -f $P/log-hashes ]] || publish_file "$P/log-hashes" log-hashes.txt
  release_draw "$P" current
  meta voids "$P/publish-list.json" > "$P/release-void-rounds" || refuse "release void rounds unavailable"
  while IFS= read -r number; do
    release_draw "$P/void-$number" "void-$number" 1
  done < "$P/release-void-rounds"
  echo "publication recorded"; }
case $STEP in
  prep) prep_step "$@"; exit $? ;;
  rehearse|post-commit|beacon|draw|post-draw|place|build|tasks|rebuild|post-tasks|check3|run|rerun|abandon|table|cards|stop|release) ;;
  *) echo "usage: run-followup.sh prep|rehearse|post-commit|beacon|draw|post-draw|place|build|tasks|rebuild|post-tasks|check3|run|table|rerun|abandon|cards|stop|release"; exit 2 ;;
esac
check_identity
if [[ $STEP != release && $STEP != abandon && -e $P/counted-not-own ]]; then refuse "counted first post was not made by this directory"; fi
if [[ $STEP != release && -e $P/state-lost-after-draw ]]; then refuse "$(readfile "$P/state-lost-after-draw")"; fi
if [[ ( $STEP == run || $STEP == rerun ) && -e $S/$TEST_MARKER && -z ${FOLLOWUP_STANDIN:-} ]]; then
  refuse "real arms require the recorded official directory"
fi
if [[ $STEP == abandon || $STEP == release ]]; then stale_lock; fi
atcommit; lock
if [[ $STEP != release && $STEP != abandon ]]; then draw_status; fi
case $STEP in
  rehearse) rehearse_step "$@" ;;
  post-commit) post_commit "$@" ;;
  beacon) beacon_step "$@" ;;
  draw) draw_step "$@" ;;
  post-draw) post_draw "$@" ;;
  place) place_step "$@" ;;
  build) build_step "$@" ;;
  tasks) tasks_step "$@" ;;
  rebuild) rebuild_step "$@" ;;
  post-tasks) post_tasks "$@" ;;
  check3) check3_step "$@" ;;
  run|rerun) arm_step "$STEP" "$@" ;;
  abandon) abandon_step "$@" ;;
  table) table_step "$@" ;;
  cards) cards_step "$@" ;;
  stop) need_counted; stop_run "$@" ;;
  release) release_step "$@" ;;
esac
