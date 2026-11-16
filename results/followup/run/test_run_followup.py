"""Offline operator-script guards; synthetic records never reach a reader."""

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_name("run-followup.sh")
ARMS = ("F1", "R1", "O1", "H1", "H2", "O2", "R2", "F2", "O3")
ORDER = tuple(
    f"{p}.{a}"
    for p, anchors in (
        ("A", ("B1", "G1", "W1")),
        ("B", ("G1", "W1", "B1")),
        ("C", ("W1", "B1", "G1")),
    )
    for a in (*ARMS, *anchors)
)
HASH = "a" * 64
COMMIT = "b" * 40
MARKER = ".followup-test-dir"


def by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r1_declared_order():
    assert SCRIPT.is_file(), "operator script is absent"
    table = by_path("followup_order", SCRIPT.with_name("table.py"))
    text = SCRIPT.read_text()
    match = re.search(r"^ORDER=\((.*?)\)", text, re.M | re.S)
    assert match
    assert tuple(match[1].split()) == table.DECLARED_ORDER == ORDER


def test_r11_public_text_and_bash_syntax():
    assert SCRIPT.is_file(), "operator script is absent"
    public = by_path("followup_public", ROOT / "scripts/public_check.py")
    assert not public.PATHS.search(SCRIPT.read_text())
    assert (
        subprocess.run(["/bin/bash", "-n", SCRIPT], capture_output=True).returncode == 0
    )
    assert SCRIPT.read_text().startswith("#!/bin/bash\n")


# The dispatcher receives the operation label and the complete real argv. File
# operations and repository reads are forwarded; modeled operations retain all
# arguments and their environment so tests can inspect commands without sends.
STANDIN = r"""#!/usr/bin/env python3
import hashlib, json, os, pathlib, signal, subprocess, sys, time
here = pathlib.Path(__file__).resolve().parent
config_file = here / "scenario.json"
c = json.loads(config_file.read_text())
kind, *argv = sys.argv[1:]
with (here / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(dict(kind=kind, argv=argv, pid=os.getpid(), locked=pathlib.Path(os.environ["FOLLOWUP_STATE"],"lock").is_dir(), cwd=os.getcwd(),
        hashseed=os.environ.get("PYTHONHASHSEED"), cache_empty=(not any(pathlib.Path(argv[argv.index("--cache")+1]).iterdir())) if kind=="arm" and "--cache" in argv else None,
        git=sorted(k for k in os.environ if k.startswith("GIT_")))) + "\n")
def save(): config_file.write_text(json.dumps(c))
state_root=pathlib.Path(os.environ["FOLLOWUP_STATE"])
def inject(phase):
    fault=c.get("inject",{})
    if fault.get("kind")!=kind or fault.get("phase","before")!=phase: return
    if not all(part in " ".join(argv) for part in fault.get("match",[])): return
    if fault.get("requires") and not (state_root/fault["requires"]).exists(): return
    c.pop("inject"); save()
    if fault.get("empty"): (state_root/fault["empty"]).write_text("")
    if fault.get("unlink"): (state_root/fault["unlink"]).unlink(missing_ok=True)
    if fault.get("full"):
        c["full_write"]=True; save()
    if fault.get("kill"):
        owners=list((state_root/"lock").iterdir())
        c.setdefault("dead_pids",[]).append(owners[0].name); save()
        if fault.get("young"):
            os.utime(state_root/fault["young"],(c["clock"],c["clock"]))
        os.kill(int(owners[0].name),signal.SIGKILL)
        sys.exit(1)
    if "stdout" in fault: print(fault["stdout"]); sys.exit(0)
    if fault.get("fail"): sys.exit(1)
inject("before")
if kind=="files" and argv[0]=="printf" and c.pop("full_write",False):
    save(); print("synthetic write: No space left on device",file=sys.stderr); sys.exit(1)
def option(flag): return argv[argv.index(flag)+1]
def write(path, text):
    path=pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def canonical(x): return json.dumps(x, sort_keys=True, separators=(",", ":"))+"\n"
if kind==c.get("fail_kind"): sys.exit(1)
if kind in c.get("real_tools",[]) or kind=="import-check" and "dr" in c.get("real_tools",[]):
    if kind=="gh": pass
    elif kind=="build":
        program="from pathlib import Path; import sys; from bicentennial.packs.build import build_tier; from bicentennial.systems.registry import REGISTRY,load; build_tier('T2',Path(sys.argv[1]),spec_path=Path(sys.argv[2]),harness_artifacts=[load(REGISTRY/'hermes-native.toml')['artifact']],edition=3); print('built rehearsal pack')"
        argv=[sys.executable,"-c",program,argv[argv.index("--out")+1],argv[argv.index("--spec")+1]]
    elif kind=="install":
        argv=[sys.executable,*argv[3:]]
    elif kind!="dr": argv=[sys.executable,*argv[1:]]
    sys.exit(subprocess.call(argv))
if kind in ("git", "git-worktree", "git-fetch"):
    if "ls-files" in argv and c.get("index_fault"):
        print(c["index_fault"]+" tracked"); sys.exit(0)
    if "status" in argv and c.get("dirty"):
        print(" M tracked"); sys.exit(0)
    if "fetch" in argv: sys.exit(c.get("fetch_exit", 0))
    sys.exit(subprocess.call(argv))
if kind == "gh":
    if "auth" in argv: sys.exit(c.get("auth_exit", 0))
    if "pr" in argv:
        pr=argv[argv.index("view")+1]
        print(json.dumps(dict(state=c.get("pr_state", "MERGED"),
                             mergeCommit=dict(oid=c.get("pr_merge_overrides",{}).get(pr,c.get("merge_commit",c["commit"]))))))
        sys.exit(0)
if kind == "dr":
    i=next(i for i,a in enumerate(argv) if a.endswith("draw_record.py"))
    command=argv[i+1]; args=argv[i+2:]
    state=pathlib.Path(args[args.index("--state")+1])
    args=[a for i,a in enumerate(args) if i not in (args.index("--state"),args.index("--state")+1)]
    if c.get("dr_refuse") == command:
        print("refused: synthetic", file=sys.stderr); sys.exit(2)
    if command=="init":
        state.mkdir(parents=True, exist_ok=True); write(state/"synthetic", "unchanged\n")
        print("initialized"); sys.exit(c.get("init_exit", 0))
    if command=="read": print("read 1"); sys.exit(0)
    if command=="evaluate":
        if "--recheck" in args: print("unchanged 1"); sys.exit(0)
        if c.get("reading_refusal"):
            print("refused: reading module "+c["reading_refusal"]+" at "+c.get("counted_commit",c["commit"]), file=sys.stderr); sys.exit(2)
        if c.get("stopped"): print("stopped 3"); sys.exit(14)
        if c.get("counted"):
            print("counted 1 round",c["round"],"due",c["due"],"commit",c.get("counted_commit",c["commit"])); sys.exit(0)
        print("none"); sys.exit(10)
    if command=="publish-list":
        rows=[]
        if c.get("counted"):
            rows.append(dict(id=1, created_at=c.get("counted_created_at","2026-01-02T00:00:00Z"), round=c["round"], counted=True, reason="counted",commit=c.get("counted_commit", c["commit"]),values=c.get("h_values",dict.fromkeys(
                ("registry_entry_sha256","fresh_install_hash","artifact_sha256","system_hash","harness_hash","route_table_hash"), "a"*64))))
        rows.extend(dict(round=n, reason="void round", counted=False) for n in c.get("voids",[]))
        print(canonical(dict(first_posts=rows, markers=c.get("markers",[]),other_comments=0)),end=""); sys.exit(0)
    if command=="choose-round": print("round",c["round"],"due",c["due"],"new"); sys.exit(0)
    if command=="now":
        codes=c.get("now_exits",[])
        if codes:
            code=codes.pop(0); save()
            if code: print("refused: "+c.get("now_reason","GitHub timeout"),file=sys.stderr); sys.exit(code)
        print("github",c["clock"],"skew 0"); sys.exit(0)
    if command=="beacon":
        if "--rehearsal" in args:
            print("rehearsal-beacon",c.get("rehearsal_beacon","pass")); sys.exit(c.get("rehearsal_beacon_exit",0 if c.get("rehearsal_beacon","pass")=="pass" else 10))
        codes=c.get("beacon_exits",[0]); code=codes.pop(0) if codes else 0; c["beacon_exits"]=codes; save()
        if code==0:
            n=int(args[args.index("--round")+1]); signature="abcd"
            write(args[args.index("--out")+1],canonical(dict(round=n,signature=signature,randomness=hashlib.sha256(bytes.fromhex(signature)).hexdigest())))
            print("accepted round",n)
        elif code==13: print("cutoff round",c["round"])
        else:
            reasons=c.get("beacon_reasons",[]); reason=reasons.pop(0) if reasons else c.get("beacon_reason","GitHub timeout"); save()
            print("not-accepted synthetic" if code==10 else "refused: "+reason,file=sys.stderr if code==2 else sys.stdout)
        sys.exit(code)
    if command=="post":
        k=args[0]
        file=pathlib.Path(args[-1]); text=file.read_text()
        c.setdefault("posts",[]).append(text)
        if k=="first" and c.get("blocked"):
            save(); print("blocked 9"); sys.exit(13)
        if k=="first" and not c.get("late"): c["counted"]=True
        if k=="stop": c["stopped"]=True
        c.setdefault("matched",[]).append(k); save(); print("posted 2 synthetic"); sys.exit(0)
    if command=="match":
        k=args[0]
        if k in c.get("matched",[]): print("matched",c.get("match_id",2)); sys.exit(0)
        print("none"); sys.exit(10)
    if command=="record-void":
        n=int(args[args.index("--round")+1]); c.setdefault("voids",[]).append(n)
        c["void_receipt"]=args[args.index("--receipt-sha256")+1]; c["counted"]=False; save(); print("void round",n); sys.exit(0)
    if command=="publish-records":
        out=pathlib.Path(args[-1]); (out/"records").mkdir(parents=True)
        for n in c.get("voids",[]):
            write(out/"records"/"000001-void.json", canonical(dict(round=n,receipt_sha256=c["void_receipt"])))
        print("published records"); sys.exit(0)
if kind=="ps":
    if c.get("empty_tool_start") and not (state_root/"lock"/argv[-1]).is_dir():
        print(""); sys.exit(0)
    if argv[-1] in c.get("dead_pids",[]): sys.exit(1)
    if c.get("process_live") or ("-o" in argv and argv[-1]!="99999999"):
        print(c.get("process_start","synthetic start")); sys.exit(0)
    sys.exit(1)
if kind=="caffeinate": sys.exit(0)
if kind=="clock": print(c["clock"]); sys.exit(0)
if kind=="sleep": c["clock"]+=int(argv[-1]); save(); sys.exit(0)
if kind=="marker": sys.exit(c.get("marker_exit",0))
if kind=="pgrep": sys.exit(1)
if kind=="lock-probe": sys.exit(0)
if kind=="import-check":
    print("import pass"); sys.exit(c.get("import_exit",0))
if kind=="gate":
    for name in ("registry_entry_sha256","system_hash","harness_hash","route_table_hash"): print(name,"a"*64)
    print("benchmark_commit",c.get("gate_commit",c["commit"])); print("prepared: system run accepted; nothing sent"); sys.exit(0)
if kind=="pins":
    print("fresh_install_hash","a"*64); print("artifact.sha256","a"*64); print("entry hermes-native"); sys.exit(0)
if kind=="draw":
    if c.get("hold_draw"): time.sleep(3)
    if c.get("draw_exit",0):
        print(c.get("draw_refusal","refused: synthetic"),file=sys.stderr); sys.exit(c["draw_exit"])
    write(option("--out"),canonical(dict(design=list(range(8001,8031)),spares=list(range(8031,8079)),drawn_at="changed" if c.get("draw_variant") else "synthetic")))
    if c.get("draw_refusal"): print(c["draw_refusal"],file=sys.stderr)
    print("sha256",digest(option("--out"))); print("design 30 spares 48"); sys.exit(c.get("draw_exit",0))
if kind=="verify":
    print("verified sha256",c.get("verify_hash",digest(option("--draw"))),"at",c.get("verify_commit",c["commit"])); sys.exit(c.get("verify_exit",0))
if kind=="place":
    if c.get("place_exit",0)==2: print("refused: synthetic",file=sys.stderr); sys.exit(2)
    out=pathlib.Path(option("--out-dir")); out.mkdir()
    d=digest(option("--draw")); n=c.get("place_calls",0)+1; c["place_calls"]=n; save()
    code=c.get("place_exit",0)
    if code==1:
        payload=dict(void=True,rule=c.get("void_rule","pool"),pack=c.get("void_pack","A"),draw_sha256=c.get("place_draw",d),packs=dict(A=dict(table=[],replacements=[])))
        if c.get("void_difference") and n%2==0: payload["packs"]["A"]["table"]=[{}]
        if c.get("void_extra"): write(out/"extra","synthetic")
        write(out/"void.json",canonical(payload)); print("void",payload["rule"],"pack",payload["pack"]); print("draw_sha256",payload["draw_sha256"]); print("receipt_sha256",digest(out/"void.json")); sys.exit(1)
    if code: sys.exit(code)
    print("draw_sha256",c.get("place_draw",d))
    for p in "ABC":
        write(out/("pack-"+p+".toml"),"synthetic "+p+c.get("spec_suffix","")+("changed" if c.get("place_difference") and n%2==0 else ""))
        write(out/("placement-"+p+".json"),"[]\n")
        print("pack",p,"spec_sha256",digest(out/("pack-"+p+".toml")),"table_sha256",digest(out/("placement-"+p+".json")),"lives 10 replacements 0 table_rows 0")
    print("spares_used 0 of 48"); sys.exit(0)
if kind=="build":
    codes=c.get("build_exits",[]); code=codes.pop(0) if codes else c.get("build_exit",0); save()
    if not code: pathlib.Path(option("--out"),"T2").mkdir(parents=True)
    print("synthetic build"); sys.exit(code)
if kind=="install":
    pathlib.Path(argv[-1]).mkdir(parents=True)
    p=pathlib.Path(argv[-1]).name[-1]
    print(dict(A="a"*64,B="b"*64,C="c"*64)[p]); sys.exit(c.get("install_exit",0))
if kind=="tasks":
    if c.get("tasks_exit",0): print("REFUSED: synthetic"); sys.exit(3)
    p=option("--pack")
    payload=dict(header=dict(commit=option("--commit"),edition=3,pack=p,pack_hash=dict(A="a"*64,B="b"*64,C="c"*64)[p],draw_sha256=digest(option("--draw")),spec_sha256=digest(option("--spec"))),rows=[{}]*40,descriptive=[{}]*10)
    if c.get("task_fault")=="header": payload["header"]["commit"]="d"*40
    if c.get("task_fault")=="rows": payload["rows"].pop()
    if c.get("task_fault")=="descriptive": payload["descriptive"].pop()
    write(option("--out"),canonical(payload)); print(p,"target items 40 descriptive items 10"); sys.exit(c.get("tasks_exit",0))
if kind=="table":
    if "--filter-out" in argv: write(option("--filter-out"),canonical(dict(packs={})))
    print(c.get("table_final_output") if "--after-reruns" in argv and c.get("table_final_output") else c.get("table_output","pending before any score: "+" ".join(c["order"])+" - rerun once (§3, §4), then run again with --after-reruns"))
    sys.exit(c.get("table_exit",4))
if kind in ("check3","followup-tests","derivation-tests"):
    print("synthetic PASSED"); sys.exit(c.get(kind+"_exit",0))
if kind=="arm":
    code=c.get("arm_exit",0); out=pathlib.Path(option("--out"))
    if c.get("no_output"): sys.exit(code)
    out.mkdir(parents=True)
    if c.get("guard_refusal"):
        write(out/"refusal.json",json.dumps(dict(code="roots_below_min")))
        if "--diagnostics" in argv:
            write(pathlib.Path(option("--diagnostics"))/"manifest.json",canonical(dict(commit=None,files=[],failures=[],skips=[])))
        sys.exit(3)
    write(out/"card.json","{}")
    if "--diagnostics" in argv: pathlib.Path(option("--diagnostics")).mkdir(parents=True)
    if "--cache" in argv: write(pathlib.Path(option("--cache"))/"synthetic.t2-floor.json","{}")
    sys.exit(code)
if kind=="cutter":
    fault=c.get("cutter_fault")
    if fault and any(a.startswith(fault+"=") for a in argv) or fault=="card": print(fault,file=sys.stderr); sys.exit(3)
    i=next(i for i,a in enumerate(argv) if a.endswith("cut_cards.py"))
    out=pathlib.Path(argv[i+2]); out.mkdir()
    print(json.dumps({a.split("=",1)[0]: "a"*64 for a in argv[i+3:]})); sys.exit(0)
# All remaining calls, including metadata, venv and file probes, execute their
# real argv unless they are explicitly modeled installation operations.
if kind in ("venv", "pip", "pytest-import"): sys.exit(0)
code=subprocess.call(argv)
inject("after")
sys.exit(code)
"""


def make_harness(tmp_path):
    assert SCRIPT.is_file(), "operator script is absent"
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gh", "curl"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    files = {
        ".gitignore": "__pycache__/\n*.pyc\n",
        "results/followup/DECLARATION.md": "synthetic declaration\n",
        "src/bicentennial/__init__.py": "",
        "src/bicentennial/items/editions.py": "EDITIONS = {\n    3: (),\n}\n",
        "specs/ring0/template-admissions.json": json.dumps(
            {
                k: {}
                for k in ("drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3")
            }
        ),
        "scripts/public_check.py": (ROOT / "scripts/public_check.py").read_text(),
        "scripts/validity_roster.py": '"--packs"\n',
    }
    for name in (
        "tasks.py",
        "table.py",
        "cut_cards.py",
        "gate_prepare.py",
        "draw_record.py",
        "run-followup.sh",
    ):
        files["results/followup/run/" + name] = "synthetic\n"
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    env = dict(
        os.environ,
        HOME=str(home),
        PYTHONHASHSEED="random",
        PATH=f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        TMPDIR=str(tmp_path),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Synthetic",
        GIT_AUTHOR_EMAIL="synthetic@example.invalid",
        GIT_COMMITTER_NAME="Synthetic",
        GIT_COMMITTER_EMAIL="synthetic@example.invalid",
    )
    located = subprocess.run(
        ["xcrun", "--find", "git"], env=env, capture_output=True, text=True, timeout=10
    )
    if located.returncode == 0:
        (bin_dir / "git").symlink_to(located.stdout.strip())
    for args in (
        ("init", "-q", "--template=", "--initial-branch=main"),
        ("add", "."),
        (
            "-c",
            "core.hooksPath=" + os.devnull,
            "commit",
            "-q",
            "--no-gpg-sign",
            "-m",
            "synthetic",
        ),
    ):
        subprocess.run(
            ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True
        )
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, text=True
    ).strip()
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", commit],
        env=env,
        check=True,
        capture_output=True,
    )
    config = dict(
        commit=commit,
        round=40000000,
        due=1812803364,
        clock=1812802464,
        order=list(ORDER),
    )
    scenario = bin_dir / "scenario.json"
    scenario.write_text(json.dumps(config))
    standin = bin_dir / "standin"
    prefix = (
        '#!/bin/bash\nexport FOLLOWUP_TEST_BIN="${0%/*}"\n'
        'printf "%s\\0" "$@" >> "$FOLLOWUP_TEST_BIN/allcalls.raw"\n'
        'case $1 in files|meta|stamp|sha) if [[ ! -f $FOLLOWUP_TEST_BIN/inject-enabled ]]; then shift; exec "$@"; fi ;; esac\n'
        "exec "
        + shlex.quote(sys.executable)
        + ' "$FOLLOWUP_TEST_BIN/standin.py" "$@"\n'
    )
    body = STANDIN.split("\n", 1)[1].replace(
        "here = pathlib.Path(__file__).resolve().parent",
        'here = pathlib.Path(os.environ["FOLLOWUP_TEST_BIN"])',
    )
    (bin_dir / "standin.py").write_text(body)
    standin.write_text(prefix)
    standin.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    (state / MARKER).touch()
    env.update(
        FOLLOWUP_STATE=str(state),
        FOLLOWUP_REPO=str(repo),
        FOLLOWUP_HERMES=str(tmp_path / "hermes"),
        FOLLOWUP_WRAPPER=str(tmp_path / "wrapper"),
        FOLLOWUP_LOGIN_HOME=str(tmp_path / "login"),
        FOLLOWUP_MARKER=str(tmp_path / "marker"),
        FOLLOWUP_PYTHON=sys.executable,
        FOLLOWUP_SLOT=str(tmp_path / "slot"),
        FOLLOWUP_STANDIN=str(standin),
        ORIGIN_MARKER="<!-- agent-origin:v1 synthetic -->",
    )

    observed_seeds = set()

    class Harness:
        def set(self, **changes):
            value = json.loads(scenario.read_text())
            value.update(changes)
            if "inject" in changes:
                (bin_dir / "inject-enabled").touch()
            scenario.write_text(json.dumps(value))

        def run(self, *args, code=0):
            result = subprocess.run(
                ["/bin/bash", os.environ.get("FOLLOWUP_SCRIPT", str(SCRIPT)), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )
            assert code is None or result.returncode == code, (
                f"step {args[0]} returned {result.returncode}: {result.stdout} {result.stderr}"
            )
            output = result.stdout + result.stderr
            assert not re.search(r"\b80(?:0[1-9]|[1-7][0-9])\b", output)
            for path in (self.state / "private").rglob("*DRAW*.json"):
                try:
                    value = json.JSONDecoder().raw_decode(path.read_text())[0]
                except ValueError:
                    continue
                observed_seeds.update(value.get("design", []) + value.get("spares", []))
            leaked = any(
                re.search(r"\b" + str(seed) + r"\b", output) for seed in observed_seeds
            )
            assert not leaked, "draw seed appeared in step output"
            return result

        def calls(self, kind=None):
            path = bin_dir / "calls.jsonl"
            calls = (
                [json.loads(line) for line in path.read_text().splitlines()]
                if path.exists()
                else []
            )
            return [c for c in calls if kind is None or c["kind"] == kind]

        def due(self):
            counted = self.state / "private/counted.json"
            if counted.exists():
                number = json.loads(counted.read_text())["round"]
                self.set(clock=1692803367 + (number - 1) * 3)

        def ready(self):
            self.run("prep", commit, "1")
            for step in (
                "rehearse",
                "post-commit",
                "beacon",
                "draw",
                "post-draw",
                "place",
                "build",
                "tasks",
                "post-tasks",
                "check3",
            ):
                if step == "beacon":
                    self.due()
                self.run(step)

    h = Harness()
    h.state, h.env, h.repo, h.commit, h.scenario = state, env, repo, commit, scenario
    return h


@pytest.fixture
def harness(tmp_path):
    return make_harness(tmp_path)


def test_r12_prep_requires_pr(harness):
    harness.run("prep", harness.commit, code=2)
    assert not harness.calls("git-fetch")


@pytest.mark.parametrize(
    "changes",
    [
        dict(pr_state="OPEN"),
        dict(merge_commit="c" * 40),
        dict(init_exit=2),
        dict(auth_exit=1),
    ],
)
def test_r12_prep_pr_and_init_failures(harness, changes):
    harness.set(**changes)
    harness.run("prep", harness.commit, "1", code=2)
    assert not (harness.state / "private/settings").exists()


def test_r10_origin_marker_and_existing_directory(harness):
    harness.env["ORIGIN_MARKER"] = "invalid"
    harness.run("prep", harness.commit, "1", code=2)
    harness.env["ORIGIN_MARKER"] = "<!-- agent-origin:v1 synthetic -->"
    (harness.state / "unexpected").touch()
    harness.run("prep", harness.commit, "1", code=2)


def test_r16_private_modes(harness):
    harness.run("prep", harness.commit, "1")
    assert (harness.state / "private").stat().st_mode & 0o777 == 0o700
    assert (harness.state / "private/settings").stat().st_mode & 0o777 == 0o600


def test_r1_r2_r3_all_commands_and_caches(harness):
    harness.ready()
    harness.run("run", "A.R1", code=2)
    harness.run("run", "unknown", code=2)
    for label in ORDER:
        harness.run("run", label)
    harness.run("run", "A.F1", code=2)
    calls = harness.calls("arm")
    assert len(calls) == 36
    controls = dict(
        F="no_memory",
        R="naive_rag",
        B="bm25",
        G="grep",
        W="recent_window",
        O="oracle_evidence",
    )
    caches = {}
    for label, call in zip(ORDER, calls, strict=True):
        args = call["argv"]
        assert args[:2] == ["caffeinate", "-i"]
        assert args[args.index("--max-sends") + 1] == "1000"
        assert Path(args[args.index("--packs") + 1]).name == f"packs-{label[0]}"
        assert args[2:4] == ["/bin/bash", harness.env["FOLLOWUP_WRAPPER"]]
        assert args[args.index("--hermes") + 1] == harness.env["FOLLOWUP_HERMES"]
        assert (
            args[args.index("--login-home") + 1] == harness.env["FOLLOWUP_LOGIN_HOME"]
        )
        assert (
            args[args.index("--pack-hash") + 1]
            == {"A": "a" * 64, "B": "b" * 64, "C": "c" * 64}[label[0]]
        )
        if label[2] == "H":
            assert "--control" not in args and "--diagnostics" not in args
            caches[label] = args[args.index("--cache") + 1]
        else:
            assert "--cache" not in args and "--diagnostics" in args
            assert args[args.index("--control") + 1] == controls[label[2]]
    assert all(caches[f"{p}.H1"] == caches[f"{p}.H2"] for p in "ABC")
    assert len({caches[f"{p}.H1"] for p in "ABC"}) == 3
    for call in harness.calls("git-worktree"):
        assert call["hashseed"] == "0" and call["git"] == []


def first_attempts(h):
    for n, label in enumerate(ORDER, 1):
        (h.state / "runs" / label).mkdir(exist_ok=True)
        (h.state / "logs" / f"{label}.seq").write_text(str(n))
    (h.state / "counter").write_text("36")
    for pack in "ABC":
        (h.state / f"cache-{pack}").mkdir(exist_ok=True)


def test_r4_each_prerequisite_and_stopped(harness):
    h = harness
    h.run("prep", h.commit, "1")
    for step in (
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
        "check3",
        "run",
    ):
        args = (step, "A.F1") if step == "run" else (step,)
        h.run(*args, code=2)
    h.set(stopped=True)
    h.run("rehearse", code=2)
    h.set(stopped=False)
    h.run("rehearse", code=2)


@pytest.mark.parametrize("kind", ["differs", "unavailable"])
def test_r4_counted_other_reading_commit(harness, kind):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("rehearse")
    h.set(reading_refusal=kind, counted_commit="c" * 40)
    result = h.run("post-commit", code=2)
    assert "c" * 40 in result.stdout + result.stderr
    assert not h.calls("arm")


def test_r4_counted_post_posts_nothing_and_other_h_values(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("rehearse")
    h.set(counted=True, h_values=dict(system_hash="d" * 64))
    h.run("post-commit")
    assert not json.loads(h.scenario.read_text()).get("posts")
    assert (h.state / "private/h-differences").read_text().splitlines() == [
        name + " differs"
        for name in (
            "registry_entry_sha256",
            "fresh_install_hash",
            "artifact_sha256",
            "system_hash",
            "harness_hash",
            "route_table_hash",
        )
    ]


def test_r4_late_then_counted_and_exact_bodies(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("rehearse")
    h.set(late=True)
    h.run("post-commit", code=1)
    h.set(late=False)
    h.run("post-commit")
    posts = json.loads(h.scenario.read_text())["posts"]
    lines = posts[-1].splitlines()
    assert lines[0] == "Follow-up draw: first post"
    assert [line.split(" ")[0] for line in lines[1:-1]] == [
        "round",
        "run_commit",
        "registry_entry_sha256",
        "fresh_install_hash",
        "artifact_sha256",
        "system_hash",
        "harness_hash",
        "route_table_hash",
    ]
    assert lines[-1] == h.env["ORIGIN_MARKER"]
    count = len(posts)
    h.run("post-commit")
    assert len(json.loads(h.scenario.read_text())["posts"]) == count


@pytest.mark.parametrize(
    "change",
    [
        dict(table_exit=0),
        dict(rehearsal_beacon="fail", rehearsal_beacon_exit=0),
        dict(gate_commit="c" * 40),
        dict(build_exit=1),
        dict(tasks_exit=3),
    ],
)
def test_r6_failed_rehearsal_kept(harness, change):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(**change)
    h.run("rehearse", code=2)
    h.run("post-commit", code=2)
    h.set(
        table_exit=4,
        rehearsal_beacon="pass",
        gate_commit=h.commit,
        build_exit=0,
        tasks_exit=0,
    )
    h.run("rehearse")
    assert list((h.state / "private").glob("rehearsal.failed-*"))


def test_r6_sequence_no_live_round(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("rehearse")
    calls = h.calls()
    assert next(i for i, c in enumerate(calls) if c["kind"] == "marker") < next(
        i for i, c in enumerate(calls) if c["kind"] == "gate"
    )
    assert not h.calls("arm")
    dr = [c["argv"] for c in h.calls("dr")]
    rehearsal = next(i for i, c in enumerate(dr) if "--rehearsal" in c)
    assert "init" in dr[rehearsal - 1]
    assert not any("--round" in c or "stop" in c for c in dr)
    h.run("post-commit")
    h.run("beacon")
    h.run("rehearse", code=2)


@pytest.mark.parametrize("value", ["Follow-up draw: synthetic", "Follow-up draw: stop"])
def test_r12_new_directory_marker_guard(harness, value):
    h = harness
    h.set(markers=[dict(first_line=value, after_merge=True)])
    h.run("prep", h.commit, "1", code=2)
    assert not (h.state / "private/settings").exists()


def test_r13_clock_retries_and_cutoff(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("rehearse")
    h.run("post-commit")
    h.set(
        now_exits=[2, 0],
        now_reason="GitHub timeout",
        beacon_exits=[10, 2, 0],
        beacon_reason="relay timeout",
    )
    h.run("beacon")
    assert (h.state / "private/BEACON").exists()
    assert len(h.calls("sleep")) >= 3
    assert any(c["argv"][:2] == ["caffeinate", "-i"] for c in h.calls("caffeinate"))


@pytest.mark.parametrize("control", [True, False])
def test_r8_guard_refusal_not_an_attempt(harness, control):
    h = harness
    h.ready()
    label = "A.F1" if control else "A.H1"
    if not control:
        for previous in ORDER[:3]:
            h.run("run", previous)
    h.set(guard_refusal=True)
    h.run("run", label, code=3)
    assert not (h.state / "runs" / label).exists()
    assert not (h.state / "logs" / f"{label}.seq").exists()
    if control:
        assert (h.state / "logs" / f"{label}.inv-1.guard-diag/manifest.json").exists()
        assert not (h.state / "diag" / label).exists()
    h.set(guard_refusal=False)
    h.run("run", label)


def test_r8_preoutput_refusal_can_repeat(harness):
    h = harness
    h.ready()
    h.set(no_output=True, arm_exit=3)
    h.run("run", "A.F1", code=3)
    assert not (h.state / "logs/A.F1.seq").exists()
    h.set(no_output=False, arm_exit=0)
    h.run("run", "A.F1")


def test_r7_r9_rerun_uses_fresh_reading_and_posted_hashes(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.run("rerun", "A.H1", code=2)
    h.run("table", code=4)
    h.run("rerun", "A.H1")
    h.run("rerun", "A.H2", code=2)
    h.run("table", code=4)
    h.run("rerun", "A.H2")
    h.run("rerun", "A.H1", code=2)
    arms = h.calls("arm")
    assert len(arms) == 2
    caches = [c["argv"][c["argv"].index("--cache") + 1] for c in arms]
    assert caches == [str(h.state / "cache-A-H1-rerun"), str(h.state / "cache-A")]
    assert arms[0]["cache_empty"] is True
    h.run("table", "--after-reruns", code=2)
    h.run("table", code=4)
    table = h.calls("table")[-1]["argv"]
    assert table.count("--pack") == 3
    assert table[table.index("--reruns") + 1] == "A.H1,A.H2"
    assert any("A.H1=" in a and a.endswith(".rerun") for a in table)


@pytest.mark.parametrize(
    "text,exit_code",
    [
        ("== 3. Scores", 4),
        ("RUN ENDS: synthetic", 4),
        ("fault: run order", 3),
        ("fault: card pins", 3),
        ("fault: pack code pins", 3),
        ("synthetic", 0),
        ("synthetic", 5),
    ],
)
def test_r7_terminal_reading_closes_reruns(harness, text, exit_code):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(table_output=text, table_exit=exit_code)
    h.run("table", code=exit_code)
    h.run("rerun", "A.F1", code=2)


def test_r7_passing_label_never_rerun(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(
        table_output="pending before any score: A.H1 - rerun once (§3, §4), then run again with --after-reruns"
    )
    h.run("table", code=4)
    h.run("rerun", "A.F1", code=2)


@pytest.mark.parametrize(
    "name",
    [
        "FOLLOWUP_REPO",
        "FOLLOWUP_HERMES",
        "FOLLOWUP_WRAPPER",
        "FOLLOWUP_LOGIN_HOME",
        "FOLLOWUP_MARKER",
        "FOLLOWUP_PYTHON",
        "FOLLOWUP_SLOT",
        "ORIGIN_MARKER",
    ],
)
def test_r10_settings_are_frozen(harness, name):
    h = harness
    h.run("prep", h.commit, "1")
    before = len(h.calls())
    h.env[name] += "-changed"
    h.run("rehearse", code=2)
    assert not any(
        c["kind"] in ("dr", "arm", "build", "git-fetch") for c in h.calls()[before:]
    )


def test_r17_check3_bounds_and_order(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.run("check3", code=2)
    for step in (
        "rehearse",
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
    ):
        h.run(step)
    h.run("run", "A.F1", code=2)
    h.set(check3_exit=1)
    h.run("check3", code=1)
    h.run("check3", code=1)
    h.run("check3", code=2)
    h.run("run", "A.F1", code=2)
    h.run("release")


def test_r15_cards_missing_replaced_and_repeated(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.run("cards", code=2)
    for label in ORDER[1:]:
        (h.state / "runs" / label / "card.json").write_text("{}")
    rerun = h.state / "runs/A.H1.rerun"
    rerun.mkdir()
    (rerun / "card.json").write_text("{}")
    (h.state / "logs/A.H1.rerun.seq").write_text("37")
    (h.state / "counter").write_text("37")
    h.set(table_exit=0, table_output="== 3. Scores")
    h.run("table")
    h.run("cards")
    before = {
        str(p.relative_to(h.state / "publish")): p.read_bytes()
        for p in (h.state / "publish").rglob("*")
        if p.is_file()
    }
    h.run("cards")
    assert all(
        (h.state / "publish" / name).read_bytes() == raw for name, raw in before.items()
    )
    calls = h.calls("cutter")
    assert not any(a.startswith("A.F1=") for c in calls for a in c["argv"])
    assert any("cards-A-first" in a for c in calls for a in c["argv"])
    h.run("release")


# S4's subprocesses deliberately do not use the operator gateway: these local
# executables model the public service protocol, including immutable contents.
SERVICE = r"""#!/usr/bin/env python3
import hashlib, json, pathlib, subprocess, sys
from datetime import UTC, datetime
from email.utils import format_datetime
root=pathlib.Path(__file__).resolve().parent
cfg=root/"scenario.json"
c=json.loads(cfg.read_text()); args=sys.argv[1:]
def stamp(t): return datetime.fromtimestamp(t,UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
def save(): cfg.write_text(json.dumps(c))
def page(nodes): return dict(nodes=nodes,pageInfo=dict(hasNextPage=False,endCursor=None))
def http(value,status=200):
    raw=value if isinstance(value,bytes) else json.dumps(value).encode()
    header=f"HTTP/2.0 {status} Synthetic\r\nDate: {format_datetime(datetime.fromtimestamp(c['clock'],UTC),usegmt=True)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode()+raw); sys.exit(0)
with (root/"service-calls.jsonl").open("a") as f:
    f.write(json.dumps(dict(tool=pathlib.Path(sys.argv[0]).name,args=args))+"\n")
if pathlib.Path(sys.argv[0]).name=="curl":
    number=int(args[-1].rsplit("/",1)[1])
    if number==33965389:
        raw=pathlib.Path(c["repo"],"results/followup/run/known-answer-round.json").read_bytes()
    elif c.get("relay_unavailable"): sys.exit(1)
    else:
        raw=json.dumps(dict(round=number,signature="abcd",randomness=hashlib.sha256(bytes.fromhex("abcd")).hexdigest())).encode()
    sys.stdout.buffer.write(raw); sys.exit(0)
if args[:2]==["auth","status"]: sys.exit(0)
if args[:2]==["pr","view"]:
    oid=c.get("decl_commit",c["commit"]) if args[2]=="573" else c["commit"]
    print(json.dumps(dict(state="MERGED",mergeCommit=dict(oid=oid)))); sys.exit(0)
if "graphql" in args:
    nodes=[dict(id="node-"+str(n["id"]),fullDatabaseId=str(n["id"]),author=dict(login="synthetic",databaseId=n.get("author",71)),createdAt=n["created_at"],lastEditedAt=None,includesCreatedEdit=False,body=n["body"],userContentEdits=page([])) for n in c.get("comments",[])]
    if any("node(id:" in a for a in args): http(dict(data=dict(node=dict(userContentEdits=page([])))))
    http(dict(data=dict(repository=dict(issue=dict(comments=page(nodes))))))
endpoint=next((a for a in args if a=="rate_limit" or a=="user" or a.startswith("repos/")),"")
if endpoint=="rate_limit": http({})
if endpoint=="user": http(dict(id=71,login="synthetic"))
if "/contents/" in endpoint:
    path=endpoint.split("/contents/",1)[1].split("?ref=",1)[0]
    ref=endpoint.rsplit("?ref=",1)[1]
    if path.endswith("draw_record.py") and ref==c.get("other_commit"):
        if c.get("module_variant")=="unavailable": http({},404)
        raw=pathlib.Path(c["repo"],path).read_bytes()+b" "
    else: raw=subprocess.check_output(["git","-C",c["repo"],"show",ref+":"+path]) if ref!=c.get("other_commit") else pathlib.Path(c["repo"],path).read_bytes()
    http(raw)
if endpoint.endswith("/pulls/573"):
    http(dict(merged=True,merged_by=dict(id=71,login="synthetic"),merged_at=stamp(c["merge_time"]),merge_commit_sha=c.get("decl_commit",c["commit"])))
if "/commits/" in endpoint:
    ref=endpoint.split("/commits/",1)[1].split("/",1)[0]
    http([dict(number=1,base=dict(ref="main"),merged_at=stamp(c["merge_time"]),merge_commit_sha=ref)])
if "/compare/" in endpoint: http(dict(status="identical"))
if endpoint.endswith("/issues/394/comments") and "POST" in args:
    body=next(a[5:] for a in args if a.startswith("body="))
    item=dict(id=len(c.get("comments",[]))+1,author=71,body=body,created_at=stamp(c["clock"]))
    c.setdefault("comments",[]).append(item); save()
    http(dict(id=item["id"],body=body,created_at=item["created_at"],user=dict(id=71,login="synthetic")),201)
if endpoint=="repos/electricsheephq/bicentennial": http(dict(default_branch="main"))
http({},404)
"""

BASE_WRAPPER = r"""#!/usr/bin/env python3
import importlib.util, json, os, pathlib, subprocess, sys
root=pathlib.Path(__file__).resolve().parent
cfg=root/"scenario.json"
def clock(): return json.loads(cfg.read_text())["clock"]
def sleep(n):
    c=json.loads(cfg.read_text()); c["clock"]+=n; cfg.write_text(json.dumps(c))
if len(sys.argv)>2 and sys.argv[1]=="-I" and sys.argv[2].endswith("draw_record.py"):
    spec=importlib.util.spec_from_file_location("draw_record",sys.argv[2]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    sys.exit(m.main(sys.argv[3:],clock=clock,sleep=sleep))
os.execv(REAL_PYTHON,[REAL_PYTHON,*sys.argv[1:]])
"""


@pytest.fixture(scope="module")
def integration_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("integration-source") / "repo"
    env = dict(
        os.environ,
        TMPDIR=str(repo.parent),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Synthetic",
        GIT_AUTHOR_EMAIL="synthetic@example.invalid",
        GIT_COMMITTER_NAME="Synthetic",
        GIT_COMMITTER_EMAIL="synthetic@example.invalid",
    )
    for key in list(env):
        if key.startswith("GIT_") and key not in (
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            env.pop(key)

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=" + os.devnull, *args], env=env, text=True
        ).strip()

    source = Path(os.environ.get("FOLLOWUP_TEST_SOURCE_REPO", str(ROOT)))
    git("clone", "--quiet", "--shared", "--no-checkout", str(source), str(repo))
    source_commit = git("-C", str(source), "rev-parse", "HEAD")
    git("-C", str(repo), "checkout", "--quiet", "--detach", source_commit)
    for name in (
        "run-followup.sh",
        "gate_prepare.py",
        "test_gate_prepare.py",
        "test_run_followup.py",
        "README.md",
    ):
        shutil.copyfile(SCRIPT.with_name(name), repo / "results/followup/run" / name)
    git("-C", str(repo), "add", "results/followup/run")
    git(
        "-C",
        str(repo),
        "commit",
        "--quiet",
        "--allow-empty",
        "--no-gpg-sign",
        "-m",
        "synthetic packet",
    )
    commit = git("-C", str(repo), "rev-parse", "HEAD")
    git("-C", str(repo), "update-ref", "refs/remotes/origin/main", commit)
    return repo, commit


def integrate(h, integration_repo):
    repo, commit = integration_repo
    h.repo, h.commit = repo, commit
    h.env["FOLLOWUP_REPO"] = str(repo)
    bin_dir = h.scenario.parent
    for name in ("gh", "curl"):
        path = bin_dir / name
        path.write_text(
            SERVICE.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1)
        )
        path.chmod(0o755)
    wrapper = bin_dir / "base-python"
    wrapper.write_text(
        BASE_WRAPPER.replace(
            "#!/usr/bin/env python3", "#!" + sys.executable, 1
        ).replace("REAL_PYTHON", repr(sys.executable))
    )
    wrapper.chmod(0o755)
    h.env["FOLLOWUP_PYTHON"] = str(wrapper)
    decl_commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", commit + "^"], env=h.env, text=True
    ).strip()
    h.set(
        commit=commit,
        decl_commit=decl_commit,
        repo=str(repo),
        merge_time=1812800000,
        real_tools=["gh", "dr", "draw", "verify", "import-check"],
    )
    return h


@pytest.fixture
def integrated(harness, integration_repo):
    return integrate(harness, integration_repo)


def through(h, last):
    steps = (
        "prep",
        "rehearse",
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
        "check3",
    )
    for step in steps[: steps.index(last) + 1]:
        if step == "beacon":
            h.due()
        h.run(step, h.commit, "1") if step == "prep" else h.run(step)


def test_i2_real_draw_and_three_posts(integrated):
    h = integrated
    through(h, "post-tasks")
    h.run("post-commit")
    comments = json.loads(h.scenario.read_text())["comments"]
    assert [c["body"].splitlines()[0] for c in comments] == [
        "Follow-up draw: first post",
        "Follow-up draw: second post",
        "Follow-up draw: task lists",
    ]
    assert "\nround " in comments[-1]["body"]
    assert json.loads((h.state / "private/counted-list.json").read_text())[
        "first_posts"
    ][0]["counted"]
    assert any(
        "verified sha256" in f.read_text()
        for f in (h.state / "private/tools").glob("verify.out")
    )


def test_i3_real_void_record_and_next_round(integrated):
    h = integrated
    through(h, "post-draw")
    h.set(place_exit=1)
    h.run("place", code=1)
    old = json.loads(h.scenario.read_text())["round"]
    assert (h.state / f"private/void-{old}/complete").is_file()
    h.run("post-commit")
    comments = json.loads(h.scenario.read_text())["comments"]
    assert len(comments) == 3
    assert comments[2]["body"].splitlines()[0] == "Follow-up draw: first post"
    assert (
        int(
            next(
                line.split()[1]
                for line in comments[2]["body"].splitlines()
                if line.startswith("round ")
            )
        )
        != old
    )
    assert not (h.state / "private/BEACON").exists()


def test_i4_real_build_stop_and_release(integrated):
    h = integrated
    through(h, "place")
    h.set(build_exit=1)
    h.run("build", code=1)
    h.run("rebuild", code=1)
    for step in ("draw", "place", "build", "tasks", "run"):
        h.run(step, "A.F1", code=2) if step == "run" else h.run(step, code=2)
    h.run("release")
    assert (h.state / "publish/draw-record-1/records").is_dir()
    assert (
        h.state / "publish/beacon-check-current.txt"
    ).read_text() == "rehearsal-beacon pass\n"
    assert json.loads(h.scenario.read_text())["comments"][-1]["body"].startswith(
        "Follow-up draw: stop\nreason build\n"
    )


def test_i6_stop_after_tasks_is_a_published_marker(integrated):
    h = integrated
    through(h, "check3")
    c = json.loads(h.scenario.read_text())
    c["comments"].append(
        dict(
            id=77,
            author=71,
            body="Follow-up draw: stop",
            created_at=by_path("dr_stamp", SCRIPT.with_name("draw_record.py")).stamp(
                c["clock"] + 1
            ),
        )
    )
    h.set(comments=c["comments"], clock=c["clock"] + 1)
    h.run("run", "A.F1")
    first_attempts(h)
    h.set(table_exit=5, table_output="RUN ENDS: synthetic (§4); no score is opened")
    h.run("table", code=5)
    h.run("release")
    markers = json.loads((h.state / "publish/draw-list.json").read_text())["markers"]
    assert any(r["id"] == 77 for r in markers)


def test_i7_real_beacon_cutoff_stops(integrated):
    h = integrated
    through(h, "post-commit")
    c = json.loads((h.state / "private/counted.json").read_text())
    due = 1692803367 + (c["round"] - 1) * 3
    h.set(clock=due + 86400, relay_unavailable=True)
    h.run("beacon")
    for step in (
        "rehearse",
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "rebuild",
        "post-tasks",
        "check3",
        "run",
        "rerun",
        "table",
        "cards",
        "stop",
    ):
        result = (
            h.run(step, "A.F1", code=2)
            if step in ("run", "rerun")
            else h.run(step, code=2)
        )
        assert "draw stopped" in result.stderr
    h.run("release")
    comments = json.loads(h.scenario.read_text())["comments"]
    assert comments[-1]["body"].startswith("Follow-up draw: stop\nreason beacon\n")


@pytest.mark.parametrize("variant", ["unavailable", "differs"])
def test_i8_other_commit_reader_then_hand_stop_publishes(integrated, variant):
    h = integrated
    through(h, "rehearse")
    dr = by_path("dr_i8", SCRIPT.with_name("draw_record.py"))
    c = json.loads(h.scenario.read_text())
    other = "c" * 40
    body = (
        "Follow-up draw: first post\nround "
        + str(c["round"])
        + "\nrun_commit "
        + other
        + "\n"
    )
    h.set(
        other_commit=other,
        module_variant=variant,
        comments=[dict(id=91, author=71, created_at=dr.stamp(c["clock"]), body=body)],
    )
    refused = h.run("post-commit", code=2)
    assert other in refused.stdout + refused.stderr
    h.run("release", code=2)
    due = 1692803367 + (c["round"] - 1) * 3
    c = json.loads(h.scenario.read_text())
    c["comments"].append(
        dict(
            id=92,
            author=71,
            created_at=dr.stamp(due),
            body="Follow-up draw: stop\nreason build\n",
        )
    )
    h.set(comments=c["comments"], clock=due)
    for step in (
        "rehearse",
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "rebuild",
        "post-tasks",
        "check3",
        "run",
        "rerun",
        "table",
        "cards",
        "stop",
    ):
        h.run(step, "A.F1", code=2) if step in ("run", "rerun") else h.run(step, code=2)
    h.run("release")
    listing = json.loads((h.state / "publish/draw-list.json").read_text())
    assert listing["reading_module"] == variant + " at " + other
    assert (h.state / "publish/draw-record-1/records").is_dir()


@pytest.fixture(scope="module")
def real_rehearsal(tmp_path_factory, integration_repo):
    h = integrate(
        make_harness(tmp_path_factory.mktemp("real-rehearsal")), integration_repo
    )
    h.set(
        real_tools=[
            "gh",
            "dr",
            "draw",
            "verify",
            "place",
            "build",
            "install",
            "tasks",
            "table",
            "import-check",
        ]
    )
    through(h, "rehearse")
    return h


def test_i1_three_real_rehearsal_builds(real_rehearsal):
    h = real_rehearsal
    assert (h.state / "private/rehearsal/passed").read_text().strip() == h.commit
    assert len(h.calls("build")) == 3
    assert len(h.calls("install")) == 3
    assert len(h.calls("tasks")) == 3
    assert (
        "pending before any score:"
        in (h.state / "private/rehearsal/table.out").read_text()
    )
    assert not h.calls("arm")


def test_i5_real_cut_cards(integrated, real_rehearsal):
    h = integrated
    through(h, "check3")
    first_attempts(h)
    cutter = by_path("cut_fixture", SCRIPT.with_name("test_cut_cards.py"))
    for pack in "ABC":
        frozen = real_rehearsal.state / f"private/rehearsal/TASKS-{pack}.json"
        shutil.copyfile(frozen, h.state / f"private/TASKS-{pack}.json")
        import hashlib

        (h.state / f"private/TASKS-{pack}.sha256").write_text(
            hashlib.sha256(frozen.read_bytes()).hexdigest()
        )
        rows = json.loads(frozen.read_text())
        found = [
            {k: r[k] for k in ("life", "branch", "item_id")}
            for r in rows["rows"] + rows["descriptive"]
        ]
        for label in ORDER:
            if label[0] != pack or label == "A.F1":
                continue
            card = cutter.full_card(found, system=label[2] == "H")
            (h.state / "runs" / label / "card.json").write_bytes(cutter.canon(card))
    rerun = h.state / "runs/A.H1.rerun"
    rerun.mkdir()
    shutil.copyfile(h.state / "runs/A.H1/card.json", rerun / "card.json")
    (h.state / "logs/A.H1.rerun.seq").write_text("37")
    h.set(
        table_exit=0,
        table_output="== 3. Scores",
        real_tools=["gh", "dr", "draw", "verify", "cutter"],
    )
    h.run("table")
    h.run("cards")
    assert (h.state / "publish/cards-A/A.H1.json").exists()
    assert (h.state / "publish/cards-A-first/A.H1.json").exists()
    assert "A.F1" in (h.state / "publish/cards-A.missing").read_text()


@pytest.mark.parametrize(
    "fault",
    ["dirty", "index-upper", "index-lower", "import", "verify-commit", "verify-hash"],
)
def test_r5_worktree_and_verify_identity(harness, fault):
    h = harness
    through(h, "beacon")
    changes = {
        "dirty": dict(dirty=True),
        "index-upper": dict(index_fault="S"),
        "index-lower": dict(index_fault="h"),
        "import": dict(import_exit=1),
        "verify-commit": dict(verify_commit="c" * 40),
        "verify-hash": dict(verify_hash="d" * 64),
    }
    h.set(**changes[fault])
    h.run("draw", code=1 if fault.startswith("verify") else 2)
    assert not (h.state / "private/draw.sha256").exists()


@pytest.mark.parametrize(
    "fault", ["rule", "hash", "files", "reproduction", "success-hash", "success-files"]
)
def test_r5_bad_placement_is_failed_attempt(harness, fault):
    h = harness
    through(h, "post-draw")
    changes = {
        "rule": dict(place_exit=1, void_rule="other"),
        "hash": dict(place_exit=1, place_draw="d" * 64),
        "files": dict(place_exit=1, void_extra=True),
        "reproduction": dict(place_exit=1, void_difference=True),
        "success-hash": dict(place_draw="e" * 64),
        "success-files": dict(place_difference=True),
    }
    h.set(**changes[fault])
    h.run("place", code=1)
    assert (h.state / "private/failure").exists()
    assert not any("record-void" in c["argv"] for c in h.calls("dr"))
    for step in ("draw", "place", "build", "tasks"):
        h.run(step, code=2)


def test_r5_void_preserves_draw_record_and_recovers_move(harness):
    h = harness
    through(h, "post-draw")
    draw = h.state / "private/draw"
    before = {
        str(p.relative_to(draw)): p.read_bytes() for p in draw.rglob("*") if p.is_file()
    }
    h.set(place_exit=1)
    h.run("place", code=1)
    number = json.loads(h.scenario.read_text())["round"]
    folder = h.state / f"private/void-{number}"
    assert folder.joinpath("complete").exists()
    assert all((draw / p).read_bytes() == raw for p, raw in before.items())
    assert folder.joinpath("tools/place-1.exit").exists()
    folder.joinpath("complete").unlink()
    shutil.move(folder / "DRAW.json", h.state / "private/DRAW.json")
    h.run("build", code=2)
    assert folder.joinpath("complete").exists()
    h.run("post-commit")


def test_r5_unconfirmed_void_only_releases(harness):
    h = harness
    through(h, "post-draw")
    c = json.loads(h.scenario.read_text())
    h.set(counted=False, voids=[c["round"]], void_receipt="a" * 64)
    h.run("build", code=2)
    assert (h.state / "private/BEACON").exists()
    h.run("release")
    assert "earlier draw stands" in (h.state / "publish/void-unconfirmed").read_text()


def test_r14_rebuild_success_and_once(harness):
    h = harness
    through(h, "place")
    h.run("rebuild", code=2)
    h.set(build_exits=[1])
    h.run("build", code=1)
    h.run("rebuild")
    h.run("rebuild", code=2)
    assert (h.state / "private/first-attempt/tools/build-A.out").exists()
    assert len(h.calls("place")) == 5  # rehearsal, first pair, rebuild pair
    assert not any("stop" in c["argv"] for c in h.calls("dr"))


def test_r14_rebuild_fails_and_stops(harness):
    h = harness
    through(h, "place")
    h.set(build_exit=1)
    h.run("build", code=1)
    h.run("rebuild", code=1)
    text = (h.state / "private/stop.body").read_text()
    assert "reason build\n" in text and "exit_1 1\n" in text
    assert "stdout_sha256_1 " in text and "synthetic build" not in text
    h.run("release")
    assert (h.state / "publish/draw-record-1").is_dir()


@pytest.mark.parametrize("field", ["system_hash", "harness_hash", "route_table_hash"])
def test_r9_counted_h_values_are_the_only_hashes(harness, field):
    h = harness
    through(h, "rehearse")
    h.set(counted=True, h_values={field: "d" * 64})
    for step in (
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
        "check3",
    ):
        h.run(step)
    first_attempts(h)
    h.run("table", code=4)
    args = h.calls("table")[-1]["argv"]
    for name in ("system_hash", "harness_hash", "route_table_hash"):
        assert args[args.index("--" + name.replace("_", "-")) + 1] == (
            "d" * 64 if name == field else "0" * 64
        )
    h.set(
        table_output="pending before any score: A.H1 - rerun once (§3, §4), then run again with --after-reruns"
    )
    h.run("table", code=4)
    h.run("rerun", "A.H1")
    h.run("table", "--after-reruns", code=4)
    h.set(
        table_output="pending before any score: A.H2 - rerun once (§3, §4), then run again with --after-reruns"
    )
    h.run("table", code=4)
    h.run("rerun", "A.H2")


@pytest.mark.parametrize("fault", ["control", "h"])
def test_r8_abandon_keeps_attempt_and_times(harness, fault):
    h = harness
    h.ready()
    label = "A.F1" if fault == "control" else "A.H1"
    if fault == "h":
        for previous in ORDER[:3]:
            h.run("run", previous)
    (h.state / "runs" / label).mkdir()
    logs = h.state / "logs"
    for suffix, content in (("start", "100"), ("seq", "4")):
        (logs / f"{label}.inv-1.{suffix}").write_text(content)
    lock = h.state / "lock"
    lock.mkdir()
    lock.joinpath("99999999").mkdir()
    h.run("abandon", label)
    assert (logs / f"{label}.killed").exists()
    assert (logs / f"{label}.exit").read_text() == "exit=abandoned\n"
    h.run("run", label, code=2)
    h.set(table_exit=5, table_output="RUN ENDS: synthetic")
    first_attempts(h)
    h.run("table", code=5)
    h.run("release")
    assert (h.state / f"publish/records/{label}.killed").exists()


@pytest.mark.parametrize("kind", ["draw", "place"])
def test_r14_interrupted_tool_is_preserved_and_retried(harness, kind):
    h = harness
    through(h, "beacon" if kind == "draw" else "post-draw")
    name = "draw" if kind == "draw" else "place-1"
    tools = h.state / "private/tools"
    tools.mkdir(exist_ok=True)
    for suffix, text in (
        ("start", "100"),
        ("pid", "99999999"),
        ("process-start", "old start"),
        ("out", "partial"),
        ("err", "partial"),
    ):
        (tools / f"{name}.{suffix}").write_text(text)
    output = h.state / ("private/DRAW.json" if kind == "draw" else "private/placed-1")
    output.write_text("partial") if kind == "draw" else output.mkdir()
    h.run(kind)
    assert output.with_name(output.name + ".cut-1").exists()
    assert (tools / f"{name}.cut-1/start").exists()
    assert not (h.state / "private/failure").exists()


def test_r14_live_tool_never_cut(harness):
    h = harness
    through(h, "beacon")
    tools = h.state / "private/tools"
    tools.mkdir()
    for suffix, text in (
        ("start", "100"),
        ("pid", "99999999"),
        ("process-start", "synthetic start\n"),
    ):
        (tools / f"draw.{suffix}").write_text(text)
    h.set(process_live=True)
    h.run("draw", code=2)
    assert not (tools / "draw.cuts").exists()
    h.set(process_start="reused start")
    h.run("draw")
    assert (tools / "draw.cut-1/start").exists()


@pytest.mark.parametrize("fault", ["out", "work", "overlap"])
def test_r14_tool_preconditions_are_not_runs(harness, fault):
    h = harness
    through(h, "post-draw")
    out = h.state / "private/placed-1"
    work = h.state / "private/place-work-1"
    if fault == "out":
        out.mkdir()
    elif fault == "work":
        work.mkdir()
    else:
        out.symlink_to(work)
    h.run("place", code=2)
    assert not (h.state / "private/tools/place-1.start").exists()
    assert not (h.state / "private/failure").exists()


@pytest.mark.parametrize(
    "code,text",
    [
        (3, "fault: run order"),
        (3, "fault: card pins"),
        (3, "fault: pack code pins"),
        (5, "RUN ENDS: synthetic"),
    ],
)
def test_r14_release_terminal_reader_fault(harness, code, text):
    h = harness
    h.ready()
    first_attempts(h)
    h.run("release", code=2)
    h.set(table_exit=code, table_output=text)
    h.run("table", code=code)
    h.run("release")
    assert (h.state / "publish/draw-list.json").exists()
    first = (h.state / "publish/draw-record-1").is_dir()
    h.run("release")
    assert first and (h.state / "publish/draw-record-2").is_dir()


@pytest.mark.parametrize("fault", ["A.F1", "card"])
def test_r15_cutter_faults_have_outcomes(harness, fault):
    h = harness
    h.ready()
    first_attempts(h)
    for label in ORDER:
        (h.state / "runs" / label / "card.json").write_text("{}")
    h.set(table_exit=0, table_output="== 3. Scores", cutter_fault=fault)
    h.run("table")
    h.run("cards")
    assert (h.state / "private/cards-A.done").exists()
    calls = h.calls("cutter")
    if fault != "card":
        assert len(calls) == 4
        assert not any(a.startswith("A.F1=") for a in calls[1]["argv"])
        assert "A.F1" in (h.state / "publish/cards-A-1.faulted").read_text()
    else:
        assert len(calls) == 3


def blocking_python(h):
    path = h.scenario.parent / "blocked-python"
    path.write_text("""#!/bin/bash
printf '%s\\0' "$@" >> "${0}.called"
if [[ ${FOLLOWUP_TEST_ALLOW_AUTH:-} == 1 && ${4:-} == 60 ]]; then exit 0; fi
exit 99
""")
    path.chmod(0o755)
    h.env["FOLLOWUP_PYTHON"] = str(path)
    return path.with_name(path.name + ".called")


def test_r10_official_guards_before_external_tools(harness):
    h = harness
    called = blocking_python(h)
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(h.state))
    private = h.state / "private"
    private.mkdir(mode=0o700)
    names = (
        "FOLLOWUP_STATE",
        "FOLLOWUP_REPO",
        "FOLLOWUP_HERMES",
        "FOLLOWUP_WRAPPER",
        "FOLLOWUP_LOGIN_HOME",
        "FOLLOWUP_MARKER",
        "FOLLOWUP_PYTHON",
        "FOLLOWUP_SLOT",
        "ORIGIN_MARKER",
    )
    pins = {name: h.env[name] for name in names}
    for name in ("gh", "curl", "git"):
        pins["resolved_" + name] = str(
            Path(shutil.which(name, path=h.env["PATH"])).resolve()
        )
    pins["resolved_python"] = h.env["FOLLOWUP_PYTHON"]
    (private / "settings").write_text(
        "".join(
            "PIN_" + name + "=" + shlex.quote(value) + "\n"
            for name, value in pins.items()
        )
    )
    (private / "settings").chmod(0o600)
    (h.state / "mode").write_text("official\n")
    (h.state / "commit.txt").write_text(h.commit + "\n")
    h.run("draw", code=2)
    assert not h.calls() and not called.exists()
    (h.state / MARKER).unlink()
    h.run("draw", code=2)
    assert not h.calls() and not called.exists()
    other = h.state.with_name("other-state")
    h.env["FOLLOWUP_STATE"] = str(other)
    h.run("prep", h.commit, "1", code=2)
    assert not called.exists() and not other.exists()
    h.run("draw", code=2)
    assert not called.exists()


def test_r10_standins_inert_without_marker(harness):
    h = harness
    called = blocking_python(h)
    h.env["FOLLOWUP_TEST_ALLOW_AUTH"] = "1"
    target = h.state.with_name("unmarked-official")
    h.state = target
    h.env["FOLLOWUP_STATE"] = str(target)
    h.run("prep", h.commit, "1", code=2)
    assert called.exists()
    arguments = called.read_bytes().split(b"\0")
    starts = [i for i, value in enumerate(arguments) if value == b"-I"]
    assert [arguments[i + 3] for i in starts] == [b"60", b"300"]
    assert all(b"timeout=int(sys.argv[1])" in arguments[i + 2] for i in starts)
    assert not (h.scenario.parent / "allcalls.raw").exists()
    assert not (target / "private/settings").exists()


def test_r10_marker_removal_never_enables_standins(harness):
    h = harness
    h.run("prep", h.commit, "1")
    before = len(h.calls())
    (h.state / MARKER).unlink()
    h.run("rehearse", code=2)
    assert len(h.calls()) == before


@pytest.mark.parametrize("name", ["gh", "curl", "git", "python"])
def test_r10_resolved_tools_are_frozen(harness, name):
    h = harness
    if name == "python":
        alias = h.scenario.parent / "python-alias"
        alias.symlink_to(sys.executable)
        h.env["FOLLOWUP_PYTHON"] = str(alias)
    h.run("prep", h.commit, "1")
    if name == "python":
        alias.unlink()
        different = alias.with_name("different-python")
        different.write_text(
            "#!/bin/bash\nexec " + shlex.quote(sys.executable) + ' "$@"\n'
        )
        different.chmod(0o755)
        alias.symlink_to(different)
    else:
        alt = h.scenario.parent / "changed-bin"
        alt.mkdir()
        path = alt / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        h.env["PATH"] = str(alt) + ":" + h.env["PATH"]
    h.run("rehearse", code=2)


def test_r12_import_copies_before_init_and_preserves_old(harness):
    h = harness
    through(h, "post-draw")
    old = h.state
    new_test_state(h, "same-commit")
    result = h.run("prep", h.commit, "1", "--import", str(old), code=2)
    assert "import commit must differ" in result.stderr
    assert not (h.state / "private/settings").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "draw",
        "place",
        "build",
        "install",
        "gate",
        "pins",
        "tasks",
        "table",
        "check3",
        "followup-tests",
        "derivation-tests",
    ],
)
def test_r6_every_rehearsal_tool_failure_is_kept(harness, kind):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(fail_kind=kind)
    h.run("rehearse", code=2)
    assert not (h.state / "private/rehearsal/passed").exists()
    h.set(fail_kind=None)
    h.run("rehearse")
    assert (h.state / "private/rehearsal.failed-1").exists()


def test_r14_fourth_cutoff_counts_as_failure(harness):
    h = harness
    through(h, "beacon")
    tools = h.state / "private/tools"
    tools.mkdir()
    for suffix, text in (
        ("start", "100"),
        ("pid", "99999999"),
        ("process-start", "old start"),
        ("cuts", "3"),
    ):
        (tools / f"draw.{suffix}").write_text(text)
    h.run("draw", code=1)
    assert (h.state / "private/failure").exists()
    assert not h.calls("draw")[-1]["argv"][-1].endswith("private/DRAW.json")


def test_r14_tasks_partial_resumes_without_replay(harness):
    h = harness
    through(h, "tasks")
    before = len(h.calls("tasks"))
    final = h.state / "private/TASKS-A.json"
    final.rename(final.with_name("TASKS-A.json.part"))
    h.run("tasks")
    assert final.exists() and len(h.calls("tasks")) == before


def test_r5_void_record_refusal_resumes_only_record(harness):
    h = harness
    through(h, "post-draw")
    h.set(place_exit=1, dr_refuse="record-void")
    h.run("place", code=2)
    before = len(h.calls("place"))
    h.set(dr_refuse=None)
    h.run("place", code=1)
    assert len(h.calls("place")) == before


@pytest.mark.parametrize("change", ["header", "rows", "descriptive"])
def test_r4_task_validation_is_failure(harness, change):
    h = harness
    through(h, "build")
    h.set(task_fault=change)
    h.run("tasks", code=1)
    assert not (h.state / "private/TASKS-A.json").exists()
    assert (h.state / "private/failure").exists()


@pytest.mark.parametrize("author", [71, 72])
def test_r12_real_new_directory_guard_uses_merging_author(integrated, author):
    h = integrated
    dr = by_path("guard_stamp", SCRIPT.with_name("draw_record.py"))
    c = json.loads(h.scenario.read_text())
    h.set(
        comments=[
            dict(
                id=1,
                author=author,
                created_at=dr.stamp(c["clock"]),
                body="Follow-up draw: synthetic",
            )
        ]
    )
    h.run("prep", h.commit, "1", code=2 if author == 71 else 0)


def test_r10_real_arm_refused_in_marked_directory(integrated):
    h = integrated
    through(h, "check3")
    binary = h.state / "venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(sys.executable)
    h.env.pop("FOLLOWUP_STANDIN")
    answer = h.run("run", "A.F1", code=2)
    assert "real arms require" in answer.stderr
    assert not (h.state / "runs/A.F1").exists()


def test_r14_release_sanitizes_and_keeps_versions(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(table_exit=5, table_output="RUN ENDS: synthetic")
    h.run("table", code=5)
    # Construct the path token instead of putting a home path in public source.
    private_path = "/" + "Users" + "/" + "invented" + "/" + "log"
    (h.state / "private/counted-other-commit").write_text(private_path)
    h.run("release")
    result = h.state / "publish/counted-other-commit"
    assert "withheld: local path pattern" in result.read_text()
    hashes = {
        str(p.relative_to(h.state / "publish")): p.read_bytes()
        for p in (h.state / "publish").rglob("*")
        if p.is_file()
    }
    h.run("release")
    assert all(
        (h.state / "publish" / p).read_bytes() == raw for p, raw in hashes.items()
    )
    assert not result.with_name(result.name + ".1").exists()
    (h.state / "private/counted-other-commit").write_text("changed\n")
    h.run("release")
    assert result.with_name(result.name + ".1").read_text() == "changed\n"


def test_r3_nonempty_h1_cache_is_refused(harness):
    h = harness
    h.ready()
    for label in ORDER[:3]:
        h.run("run", label)
    cache = h.state / "cache-A"
    cache.mkdir()
    cache.joinpath("synthetic").touch()
    before = len(h.calls("arm"))
    h.run("run", "A.H1", code=2)
    assert len(h.calls("arm")) == before


def test_r4_blocked_then_counted_and_matching(harness):
    h = harness
    through(h, "rehearse")
    h.set(blocked=True)
    h.run("post-commit", code=2)
    for step in (
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
    ):
        h.run(step, code=2)
    h.set(blocked=False, counted=True)
    h.run("post-commit")
    h.run("beacon")
    h.run("draw")
    h.run("post-draw")
    before = len(json.loads(h.scenario.read_text())["posts"])
    h.run("post-draw")
    assert len(json.loads(h.scenario.read_text())["posts"]) == before
    h.run("place")
    h.run("build")
    h.run("tasks")
    h.run("post-tasks")
    before = len(json.loads(h.scenario.read_text())["posts"])
    h.run("post-tasks")
    assert len(json.loads(h.scenario.read_text())["posts"]) == before
    h.run("check3")
    h.run("run", "A.F1")
    h.run("tasks", code=2)


@pytest.mark.parametrize(
    "file", ["private/DRAW.json", "private/TASKS-A.json", "pack-A.hash"]
)
def test_r4_posted_values_must_stay_frozen(harness, file):
    h = harness
    h.ready()
    target = h.state / file
    target.write_text(
        "d" * 64 + "\n" if file == "pack-A.hash" else target.read_text() + "changed"
    )
    h.run("run", "A.F1", code=2)


def test_r4_round_arguments_and_match_id(harness):
    h = harness
    through(h, "beacon")
    h.run("beacon", "other", code=2)
    h.run("draw", "other", code=2)
    h.run("draw")
    h.run("post-draw", "other", code=2)
    h.set(match_id=99)
    h.run("post-draw", code=2)
    assert not (h.state / "posted/draw.rec").exists()


def test_r14_stop_admission_and_cutoff(harness):
    h = harness
    through(h, "post-commit")
    for reason in ("other", "beacon", "build"):
        h.run("stop", reason, code=2)
    h.set(beacon_exits=[13])
    h.run("beacon")
    assert (h.state / "private/stopped").exists()
    assert "stdout_sha256_1 " in (h.state / "private/stop.body").read_text()
    h.run("release")


def test_r7_all_first_attempts_before_any_rerun(harness):
    h = harness
    h.ready()
    (h.state / "runs/A.F1").mkdir()
    (h.state / "logs/A.F1.seq").write_text("1")
    (h.state / "logs/table-2.seq").write_text("2")
    (h.state / "logs/table-2.txt").write_text(
        "pending before any score: A.F1 - rerun once (§3, §4), then run again with --after-reruns\n"
    )
    h.run("rerun", "A.F1", code=2)
    assert not h.calls("arm")


def test_r7_old_score_opening_closes_new_pending(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(table_exit=0, table_output="== 3. Scores")
    h.run("table")
    h.set(
        table_exit=4,
        table_output="pending before any score: A.F1 - rerun once (§3, §4), then run again with --after-reruns",
    )
    h.run("table", code=4)
    h.run("rerun", "A.F1", code=2)


def test_r6_beacon_without_rehearsal_pass_is_too_late(harness):
    h = harness
    h.run("prep", h.commit, "1")
    (h.state / "private/BEACON").write_text("{}")
    h.run("rehearse", code=2)
    assert not h.calls("draw")


def test_r17_passed_first_check3_cannot_repeat(harness):
    h = harness
    h.ready()
    h.run("check3", code=2)
    h.run("run", "A.F1")
    h.run("check3", code=2)
    assert not (h.state / "private/check3-2.txt").exists()


@pytest.mark.parametrize("value", ["", "ABC", "A" * 64])
def test_r9_malformed_posted_hash_is_zero(harness, value):
    h = harness
    through(h, "rehearse")
    h.set(
        counted=True,
        h_values=dict(system_hash=value, harness_hash=HASH, route_table_hash=HASH),
    )
    for step in (
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
        "check3",
    ):
        h.run(step)
    first_attempts(h)
    h.run("table", code=4)
    args = h.calls("table")[-1]["argv"]
    assert args[args.index("--system-hash") + 1] == "0" * 64


@pytest.mark.parametrize("fault", ["history", "declaration"])
def test_r12_declaration_merge_and_bytes(harness, fault):
    h = harness
    old = h.commit
    if fault == "history":
        h.set(pr_merge_overrides={"573": "c" * 40})
    else:
        (h.repo / "results/followup/DECLARATION.md").write_text(
            "synthetic changed declaration\n"
        )
        for args in (
            ("add", "results/followup/DECLARATION.md"),
            (
                "-c",
                "core.hooksPath=" + os.devnull,
                "commit",
                "-qm",
                "synthetic changed declaration",
                "--no-gpg-sign",
            ),
        ):
            subprocess.run(
                ["git", "-C", str(h.repo), *args],
                env=h.env,
                check=True,
                capture_output=True,
            )
        h.commit = subprocess.check_output(
            ["git", "-C", str(h.repo), "rev-parse", "HEAD"], env=h.env, text=True
        ).strip()
        subprocess.run(
            [
                "git",
                "-C",
                str(h.repo),
                "update-ref",
                "refs/remotes/origin/main",
                h.commit,
            ],
            env=h.env,
            check=True,
            capture_output=True,
        )
        h.set(commit=h.commit, pr_merge_overrides={"573": old})
    h.run("prep", h.commit, "1", code=2)
    assert not (h.state / "private/settings").exists()
    assert (h.state / "private/pr-573.json").exists()


@pytest.mark.parametrize(
    "change", [dict(place_exit=1), dict(spec_suffix="changed"), dict(draw_variant=True)]
)
def test_r14_rebuild_keeps_posted_draw_and_agreed_specs(harness, change):
    h = harness
    through(h, "place")
    h.set(build_exit=1)
    h.run("build", code=1)
    h.set(build_exit=0, **change)
    h.run("rebuild", code=1)
    assert (h.state / "private/stopped").exists()
    assert not any("record-void" in c["argv"] for c in h.calls("dr"))


def test_r13_counted_beacon_round_must_match(harness):
    h = harness
    through(h, "beacon")
    p = h.state / "private/BEACON"
    value = json.loads(p.read_text())
    value["round"] += 1
    p.write_text(json.dumps(value))
    h.run("draw", code=2)
    assert not (h.state / "private/tools/draw.start").exists()


def test_r5_void_after_arm_never_advances_or_moves(harness):
    h = harness
    h.ready()
    h.run("run", "A.F1")
    c = json.loads(h.scenario.read_text())
    before = len(c["posts"])
    h.set(counted=False, voids=[c["round"]], void_receipt=HASH)
    h.run("post-commit", code=2)
    assert len(json.loads(h.scenario.read_text())["posts"]) == before
    assert (h.state / "private/BEACON").exists()
    assert not (h.state / f"private/void-{c['round']}/complete").exists()
    h.run("release")
    assert "earlier draw stands" in (h.state / "publish/void-unconfirmed").read_text()


def test_r14_exhausted_cutoff_keeps_partial_logs(harness):
    h = harness
    through(h, "beacon")
    tools = h.state / "private/tools"
    tools.mkdir()
    for suffix, text in (
        ("start", "100"),
        ("pid", "99999999"),
        ("process-start", "old start"),
        ("cuts", "3"),
        ("out", "partial output\n"),
        ("err", "partial error\n"),
    ):
        (tools / f"draw.{suffix}").write_text(text)
    h.run("draw", code=1)
    assert (tools / "draw.out").read_text() == "partial output\n"
    assert (tools / "draw.err").read_text() == "partial error\n"


def test_r14_reused_lock_owner_does_not_hold_lock(harness):
    h = harness
    h.ready()
    owner = h.state / "lock/99999999"
    owner.mkdir(parents=True)
    (owner / "start").write_text("old process start\n")
    h.set(process_live=True, process_start="new process start")
    h.run("abandon", "A.F1")
    assert not (h.state / "lock").exists()


def test_r14_live_lock_owner_holds_lock(harness):
    h = harness
    h.ready()
    owner = h.state / "lock/99999999"
    owner.mkdir(parents=True)
    (owner / "start").write_text("synthetic start\n")
    h.set(process_live=True)
    h.run("abandon", "A.F1", code=2)
    assert owner.exists()


def test_r10_named_base_python_resolves_from_path(harness):
    h = harness
    (h.scenario.parent / "named-python").symlink_to(sys.executable)
    h.env["FOLLOWUP_PYTHON"] = "named-python"
    h.run("prep", h.commit, "1")
    h.run("rehearse")


def test_r5_void_pack_is_one_letter(harness):
    h = harness
    through(h, "post-draw")
    h.set(place_exit=1, void_pack="")
    h.run("place", code=1)
    assert (h.state / "private/failure").exists()
    assert not any("record-void" in c["argv"] for c in h.calls("dr"))


def test_r14_seed_tool_failure_reason_is_saved(harness):
    h = harness
    through(h, "beacon")
    reason = "refused: three-pack operation failed (RuntimeError)"
    h.set(draw_exit=2, draw_refusal=reason)
    result = h.run("draw", code=2)
    assert (h.state / "private/tools/draw.reason").read_text() == reason + "\n"
    assert reason not in result.stdout + result.stderr


def test_r14_recorded_pid_is_the_dispatched_tool(harness):
    h = harness
    through(h, "beacon")
    h.run("draw")
    own = h.calls("draw")[-1]["pid"]
    assert int((h.state / "private/tools/draw.pid").read_text()) == own
    assert h.calls("draw")[-1]["locked"] and h.calls("verify")[-1]["locked"]


def test_r7_counter_recovers_from_recorded_sequences(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.run("table", code=4)
    previous = int((h.state / "counter").read_text())
    (h.state / "counter").unlink()
    h.run("rerun", "A.H1")
    assert int((h.state / "logs/A.H1.rerun.seq").read_text()) > previous


@pytest.mark.parametrize("shape", ["parent", "owner"])
def test_r14_stale_lock_never_follows_symlinks(harness, shape):
    h = harness
    h.ready()
    target = h.state.with_name("preserved-lock-data")
    target.mkdir()
    if shape == "parent":
        owner = target / "99999999"
        owner.mkdir()
        (owner / "start").write_text("preserve\n")
        (h.state / "lock").symlink_to(target)
    else:
        (target / "start").write_text("preserve\n")
        (h.state / "lock").mkdir()
        (h.state / "lock/99999999").symlink_to(target)
        owner = target
    h.run("abandon", "A.F1", code=2)
    assert (owner / "start").read_text() == "preserve\n"


def test_r15_empty_pack_and_last_fault_have_outcomes(harness):
    h = harness
    h.ready()
    first_attempts(h)
    (h.state / "runs/A.F1/card.json").write_text("{}")
    h.set(table_exit=0, table_output="== 3. Scores", cutter_fault="A.F1")
    h.run("table")
    h.run("cards")
    assert len(h.calls("cutter")) == 1
    assert (h.state / "publish/cards-A-1.outcome").read_text() == "no cards\n"
    assert (h.state / "publish/cards-B.outcome").read_text() == "no cards\n"
    assert not (h.state / "publish/cards-B").exists()


def test_r6_idle_failure_keeps_rehearsal(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(marker_exit=10)
    h.run("rehearse", code=4)
    assert not h.calls("gate")
    h.set(marker_exit=0)
    h.run("rehearse")
    assert (h.state / "private/rehearsal.failed-1").exists()


def test_r12_real_import_adopts_counted_commit(integrated):
    h = integrated
    through(h, "rehearse")
    old_commit = h.commit
    subprocess.run(
        [
            "git",
            "-C",
            str(h.repo),
            "-c",
            "core.hooksPath=" + os.devnull,
            "commit",
            "--allow-empty",
            "--no-gpg-sign",
            "-qm",
            "synthetic second run commit",
        ],
        env=h.env,
        check=True,
        capture_output=True,
    )
    adopted = subprocess.check_output(
        ["git", "-C", str(h.repo), "rev-parse", "HEAD"], env=h.env, text=True
    ).strip()
    subprocess.run(
        ["git", "-C", str(h.repo), "update-ref", "refs/remotes/origin/main", adopted],
        env=h.env,
        check=True,
        capture_output=True,
    )
    c = json.loads(h.scenario.read_text())
    dr = by_path("import_stamp", SCRIPT.with_name("draw_record.py"))
    body = (
        "Follow-up draw: first post\nround "
        + str(c["round"])
        + "\nrun_commit "
        + adopted
        + "\n"
        + (h.state / "private/rehearsal/h.values").read_text()
    )
    h.set(comments=[dict(id=91, author=71, created_at=dr.stamp(c["clock"]), body=body)])
    refused = h.run("post-commit", code=2)
    assert adopted in refused.stderr and adopted != old_commit
    old = h.state
    before = {
        str(p.relative_to(old)): p.read_bytes()
        for p in old.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    target = old.with_name("adopted")
    target.mkdir()
    (target / MARKER).touch()
    h.state = target
    h.commit = adopted
    h.env["FOLLOWUP_STATE"] = str(target)
    h.set(commit=adopted)
    h.run("prep", adopted, "1", "--import", str(old))
    assert all((old / name).read_bytes() == raw for name, raw in before.items())
    h.run("rehearse")
    assert (target / "private/rehearsal/passed").read_text().strip() == adopted
    h.run("post-commit")
    h.due()
    h.run("beacon")
    h.run("rehearse", code=2)
    assert len(json.loads(h.scenario.read_text())["comments"]) == 1


def test_r5_first_placement_uses_draw_worktree(harness):
    h = harness
    through(h, "place")
    draw = h.calls("draw")[-1]
    first, second = h.calls("place")[-2:]
    assert bool(first["cwd"] == draw["cwd"]), (
        "first placement must use the draw worktree"
    )
    assert bool(second["cwd"] != first["cwd"]), "second placement must be independent"


def test_r1_label_is_literal(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.run("run", "A.F[12]", code=2)
    assert not (h.state / "runs/A.F[12]").exists()


def test_r7_pending_label_is_literal(harness):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(
        table_exit=4,
        table_output="pending before any score: A-F1 - rerun once (§3, §4), then run again with --after-reruns",
    )
    h.run("table", code=4)
    h.run("rerun", "A.F1", code=2)
    assert not (h.state / "runs/A.F1.rerun").exists()


def test_r14_live_pid_without_start_is_not_abandoned(harness):
    h = harness
    through(h, "beacon")
    tools = h.state / "private/tools"
    tools.mkdir()
    (tools / "draw.start").write_text("100")
    (tools / "draw.pid").write_text("99999999")
    now = json.loads(h.scenario.read_text())["clock"]
    os.utime(tools / "draw.pid", (now, now))
    h.set(process_live=True)
    prior = len(h.calls("draw"))
    h.run("draw", code=2)
    assert not (tools / "draw.cuts").exists()
    assert len(h.calls("draw")) == prior


def test_r14_release_checks_every_retained_draw(harness):
    h = harness
    through(h, "place")
    p = h.state / "private"
    shutil.copyfile(p / "DRAW.json", p / "DRAW.json.cut-1")
    shutil.copyfile(p / "DRAW.json", p / "reproduced-DRAW.json")
    h.set(build_exit=1)
    h.run("build", code=1)
    h.run("rebuild", code=1)
    before = len(h.calls("verify"))
    h.run("release")
    checked = [
        Path(c["argv"][c["argv"].index("--draw") + 1]).relative_to(p).as_posix()
        for c in h.calls("verify")[before:]
    ]
    expected = {
        "DRAW.json",
        "DRAW.json.cut-1",
        "first-attempt/DRAW.json",
        "first-attempt/reproduced-DRAW.json",
    }
    assert set(checked) == expected
    for name in expected:
        assert (h.state / "publish" / name).is_file()


@pytest.mark.parametrize("change", [dict(init_exit=2), dict(rehearsal_beacon="fail")])
def test_r6_draw_record_refusals_fail_rehearsal(harness, change):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(**change)
    h.run("rehearse", code=2)
    assert not (h.state / "private/rehearsal/passed").exists()


# Round 3: every fault uses synthetic state and the existing D3 gateway.
def new_test_state(h, name):
    target = h.state.with_name(name)
    target.mkdir()
    (target / MARKER).touch()
    h.state = target
    h.env["FOLLOWUP_STATE"] = str(target)
    return target


def fixture_commit(h, *, side=False):
    args = ["git", "-C", str(h.repo)]
    if side:
        subprocess.run(
            [*args, "checkout", "-qb", "side"],
            env=h.env,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        [
            *args,
            "-c",
            "core.hooksPath=" + os.devnull,
            "commit",
            "--allow-empty",
            "--no-gpg-sign",
            "-qm",
            "synthetic successor",
        ],
        env=h.env,
        check=True,
        capture_output=True,
    )
    commit = subprocess.check_output(
        [*args, "rev-parse", "HEAD"], env=h.env, text=True
    ).strip()
    subprocess.run(
        [*args, "checkout", "-q", "main"]
        if side
        else [*args, "update-ref", "refs/remotes/origin/main", commit],
        env=h.env,
        check=True,
        capture_output=True,
    )
    return commit


@pytest.mark.parametrize(
    "source", ["unrecorded", "beacon", "run", "sequence", "official-for-test"]
)
def test_r3_import_source_guards(harness, source):
    h = harness
    through(h, "rehearse")
    old = h.state
    adopted = fixture_commit(h)
    h.set(counted=True, counted_commit=adopted)
    if source == "unrecorded":
        (old / MARKER).unlink()
    elif source == "official-for-test":
        (old / MARKER).unlink()
        (Path(h.env["HOME"]) / ".bicentennial-followup-official").write_text(str(old))
    elif source == "beacon":
        (old / "private/BEACON").write_text("{}")
    elif source == "run":
        (old / "runs/A.F1").mkdir()
    else:
        (old / "logs/A.F1.seq").write_text("1")
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    before = record.read_bytes() if record.exists() else None
    new_test_state(h, "rejected-import")
    result = h.run("prep", adopted, "1", "--import", str(old), code=2)
    assert (
        "import source"
        if source in ("unrecorded", "official-for-test")
        else "import has"
    ) in result.stderr
    assert (record.read_bytes() if record.exists() else None) == before


def test_r3_import_counted_commit_and_published_records(harness):
    h = harness
    through(h, "rehearse")
    old = h.state
    adopted = fixture_commit(h)
    for name in (
        "counted-other-commit",
        "reading-commit-refusal",
        "blocked",
        "counted-list.json",
        "evaluate.out",
        "evaluate.err",
        "first-post.out",
        "first-post.err",
    ):
        (old / "private" / name).write_text("synthetic step-2 record\n")
    # The old files deliberately name nothing: only S4's fresh reading authorizes adoption.
    h.set(counted=True, counted_commit=adopted)
    before = {
        p.relative_to(old): p.read_bytes()
        for p in old.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    new_test_state(h, "adopted-r3")
    h.run("prep", adopted, "1", "--import", str(old))
    assert all((old / name).read_bytes() == raw for name, raw in before.items())
    h.set(blocked=True)
    (h.state / "private/blocked").write_text("blocked 9\n")
    h.run("release")
    for name in (
        "counted-other-commit",
        "reading-commit-refusal",
        "blocked",
        "counted-list.json",
        "evaluate.out",
        "evaluate.err",
        "first-post.out",
        "first-post.err",
    ):
        assert (
            h.state / "publish/imported" / name
        ).read_text() == "synthetic step-2 record\n"


def test_r3_import_requires_s4_commit(harness):
    h = harness
    through(h, "rehearse")
    old = h.state
    adopted = fixture_commit(h)
    (old / "private/counted-other-commit").write_text(adopted)
    h.set(counted=True, counted_commit=h.commit)
    new_test_state(h, "wrong-counted")
    result = h.run("prep", adopted, "1", "--import", str(old), code=2)
    assert "import counted post must name" in result.stderr


@pytest.mark.parametrize("exists", [True, False])
def test_r3_lost_state_before_draw(harness, exists):
    h = harness
    old = h.state.with_name("old-official")
    if exists:
        old.mkdir()
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(old))
    h.run("prep", h.commit, "1", "--import", "none", code=2 if exists else 0)
    assert record.read_text() == str(old)
    if exists:
        assert not (h.state / "private/settings").exists()
    else:
        assert (h.state / "private/import.record").read_text() == "old state lost\n"
        h.run(
            "rehearse"
        )  # Positive control: before the draw the operating path remains open.


@pytest.mark.parametrize(
    "line", ["Follow-up draw: second post", "Follow-up draw: task lists"]
)
def test_r3_lost_state_after_draw_release_only(harness, line):
    h = harness
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(h.state.with_name("lost-official")))
    h.set(markers=[dict(after_merge=True, first_line=line)])
    h.run("prep", h.commit, "1", "--import", "none")
    message = "state lost after the draw: no arm can run; readings unresolved (§10, missing data)"
    for step in (
        "rehearse",
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "rebuild",
        "post-tasks",
        "check3",
        "run",
        "rerun",
        "abandon",
        "table",
        "cards",
        "stop",
    ):
        result = (
            h.run(step, "A.F1", code=2)
            if step in ("run", "rerun", "abandon")
            else h.run(step, code=2)
        )
        assert message in result.stderr
    h.run("release")
    assert (h.state / "publish/state-lost-after-draw").read_text().strip() == message
    assert (h.state / "publish/import.record").read_text() == "old state lost\n"
    assert (h.state / "publish/draw-record-1/records").is_dir()
    assert not (h.state / "private/stopped").exists()


@pytest.mark.parametrize(
    "variant",
    [
        "reproduced",
        "differs",
        "missing-beacon",
        "missing-draw",
        "missing-first",
        "missing-second",
        "missing-folder",
        "second-differs",
    ],
)
def test_r3_release_every_void(harness, variant):
    h = harness
    through(h, "post-draw")
    h.set(place_exit=1)
    h.run("place", code=1)
    c = json.loads(h.scenario.read_text())
    number = c["round"]
    folder = h.state / f"private/void-{number}"
    if variant.startswith("missing-"):
        names = dict(
            beacon="BEACON",
            draw="DRAW.json",
            first="placed-1/void.json",
            second="placed-2/void.json",
        )
        if variant == "missing-folder":
            folder.rename(folder.with_name("retained-void"))
        else:
            (folder / names[variant.removeprefix("missing-")]).unlink()
    if variant == "second-differs":
        (folder / "placed-2/void.json").write_text("{}")
    if variant == "differs":
        h.set(place_exit=0)
    (h.state / "private/blocked").write_text("blocked 9\n")
    (h.state / "private/rebuild-failed").write_text("synthetic failure\n")
    h.run("release")
    outcome = (h.state / f"publish/void-{number}/void.outcome").read_text().strip()
    assert outcome == (
        "void reproduced"
        if variant == "reproduced"
        else "void not reproduced: under §2 the earlier draw stands"
    )
    assert (h.state / "publish/rebuild-failed").read_text() == "synthetic failure\n"
    if variant == "reproduced":
        for name in ("BEACON", "DRAW.json", "placed-1/void.json", "placed-2/void.json"):
            assert (h.state / f"publish/void-{number}" / name).is_file(), name
        assert (h.state / f"publish/void-{number}/void-confirm-{number}").is_file()


def test_r3_check3_exact_command(harness):
    h = harness
    through(h, "check3")
    for call in h.calls("check3"):
        args = call["argv"]
        assert args[:3] == ["python3", h.env["FOLLOWUP_SLOT"], "--"]
        assert args[args.index("-m") + 1 : args.index("-m") + 4] == [
            "pytest",
            "-v",
            "-p",
        ]
        assert [
            a for a in args if a.endswith(".py") and a != h.env["FOLLOWUP_SLOT"]
        ] == ["tests/runner/test_control_arms.py"]


@pytest.mark.parametrize("fault", ["run order", "card pins", "pack code pins"])
def test_r3_release_after_prerun_fault(harness, fault):
    h = harness
    h.ready()
    first_attempts(h)
    h.set(table_exit=3, table_output="fault: " + fault)
    h.run("table", "--after-reruns", code=2)
    assert not list((h.state / "logs").glob("table-*.exit"))
    h.run("release")
    assert list((h.state / "publish/records").glob("table-*.pre-exit"))


def test_r3_reading_refusal_prefix(harness):
    h = harness
    through(h, "rehearse")
    h.set(reading_refusal="unavailable", counted_commit="c" * 40)
    result = h.run("post-commit", code=2)
    assert result.stderr == "refused: reading module unavailable at " + "c" * 40 + "\n"


TRANSIENTS = [
    "round not due",
    "GitHub timeout",
    "GitHub HTTP status",
    "GitHub GraphQL errors",
    "GitHub time unavailable",
    "missing HTTP status",
    "missing HTTP header block",
    "relay timeout",
    "clock skew exceeds 60 seconds",
    "reading module unavailable at " + "c" * 40,
]


@pytest.mark.parametrize("where", ["now", "beacon"])
@pytest.mark.parametrize(
    "reason",
    TRANSIENTS
    + [
        "malformed or unavailable record",
        "draw stopped",
        "beacon timing receipt missing",
    ],
)
def test_r3_beacon_retry_classification(harness, where, reason):
    """Transient cases are positive controls; permanent/catch-all cases fail the base."""
    h = harness
    through(h, "post-commit")
    h.due()
    catchall = reason == "malformed or unavailable record"
    terminal = reason in ("draw stopped", "beacon timing receipt missing") or catchall
    count = 4 if catchall else 1
    h.set(**{where + "_exits": [2] * count + [0], where + "_reason": reason})
    before = len(h.calls("sleep"))
    result = h.run("beacon", code=2 if terminal else 0)
    calls = [
        call
        for call in h.calls("dr")
        if where in call["argv"] and "--rehearsal" not in call["argv"]
    ]
    assert len(calls) == (3 if catchall else 1 if terminal else 2)
    assert len(h.calls("sleep")) - before == (2 if catchall else 0 if terminal else 1)
    if terminal:
        assert result.stderr == "refused: " + reason + "\n"
    else:
        assert (h.state / "private/BEACON").exists()


def test_r3_kill_after_fork_before_start(harness):
    h = harness
    through(h, "beacon")
    h.set(
        hold_draw=True,
        inject=dict(
            kind="ps",
            requires="private/tools/draw.pid",
            young="private/tools/draw.pid",
            kill=True,
        ),
    )
    h.run("draw", code=-9)
    assert not (h.state / "private/tools/draw.start").exists()
    h.run("abandon", "A.F1")
    result = h.run("draw", code=2)
    assert "recorded tool may be starting" in result.stderr
    assert len([c for c in h.calls("draw") if "--rehearsal" not in c["argv"]]) == 1


def test_r3_kill_task_hash_after_rename(harness):
    h = harness
    through(h, "build")
    h.set(
        inject=dict(
            kind="files",
            match=["mv", "TASKS-A.json"],
            phase="after",
            unlink="private/TASKS-A.sha256",
            kill=True,
        )
    )
    h.run("tasks", code=-9)
    assert (h.state / "private/TASKS-A.json").exists()
    assert not (h.state / "private/TASKS-A.sha256").exists()
    h.run("abandon", "A.F1")
    h.run("tasks")
    assert (
        len(
            [
                c
                for c in h.calls("tasks")
                if "A" in c["argv"] and not any("/rehearsal/" in a for a in c["argv"])
            ]
        )
        == 1
    )
    assert len((h.state / "private/TASKS-A.sha256").read_text().strip()) == 64


@pytest.mark.parametrize("phase", ["before", "after"])
def test_r3_kill_mid_rebuild_archive(harness, phase):
    h = harness
    through(h, "place")
    h.set(build_exit=1)
    h.run("build", code=1)
    h.set(
        build_exit=0,
        inject=dict(kind="files", match=["mv", "/failure"], phase=phase, kill=True),
    )
    h.run("rebuild", code=-9)
    assert (h.state / "private/rebuild-started").read_text() == "started\n"
    h.run("abandon", "A.F1")
    assert "rebuild archive incomplete" in h.run("draw", code=2).stderr
    h.run("rebuild")
    assert (h.state / "private/first-attempt/failure").exists()
    assert (h.state / "private/rebuild-complete").exists()
    h.run("rebuild", code=2)


@pytest.mark.parametrize("resume", ["run", "rerun", "abandon"])
@pytest.mark.parametrize("guard", [False, True])
def test_r3_kill_after_arm_exit_before_copy(harness, resume, guard):
    h = harness
    h.ready()
    h.set(
        guard_refusal=guard,
        inject=dict(
            kind="files",
            match=["mv" if guard else "cp", "A.F1.inv-1."],
            requires="logs/A.F1.inv-1.exit",
            kill=True,
        ),
    )
    h.run("run", "A.F1", code=-9)
    assert (h.state / "logs/A.F1.inv-1.exit").exists()
    assert not (h.state / "logs/A.F1.seq").exists()
    h.run("abandon", "A.R1")  # Clear only the stale wrapper lock.
    if guard:
        h.set(guard_refusal=False)
    h.run(
        resume,
        "A.F1",
        code=2 if resume in ("run", "rerun") and not guard or resume == "rerun" else 0,
    )
    if guard:
        assert (h.state / "logs/A.F1.inv-1.guard-diag/manifest.json").exists()
    else:
        assert (h.state / "logs/A.F1.seq").read_text() == (
            h.state / "logs/A.F1.inv-1.seq"
        ).read_text()
    assert len(h.calls("arm")) == (2 if guard and resume == "run" else 1)


def test_r3_failed_void_confirmation_write(harness):
    h = harness
    through(h, "post-draw")
    number = json.loads(h.scenario.read_text())["round"]
    h.set(
        place_exit=1,
        inject=dict(
            kind="sha",
            match=["placed-1/void.json"],
            full=f"private/void-confirm-{number}",
        ),
    )
    result = h.run("place", code=2)
    assert "void confirmation record" in result.stderr
    assert not any("record-void" in call["argv"] for call in h.calls("dr"))
    assert not json.loads(h.scenario.read_text()).get("voids")


def test_r3_failed_invocation_sequence_write(harness):
    h = harness
    h.ready()
    h.set(
        inject=dict(
            kind="clock", requires="logs/A.F1.inv-1.seq", empty="logs/A.F1.inv-1.seq"
        )
    )
    result = h.run("run", "A.F1", code=2)
    assert "invocation sequence" in result.stderr
    assert not h.calls("arm")
    h.run("abandon", "A.F1")
    assert (h.state / "logs/A.F1.inv-1.seq.failed").exists()
    h.run("run", "A.F1")
    assert len(h.calls("arm")) == 1


@pytest.mark.parametrize("age", [59, 60])
@pytest.mark.parametrize("shape", ["ownerless", "empty-owner", "empty-tool"])
def test_r3_missing_start_age(harness, age, shape):
    h = harness
    through(h, "beacon")
    now = json.loads(h.scenario.read_text())["clock"]
    if shape == "empty-tool":
        folder = h.state / "private/tools"
        folder.mkdir()
        path = folder / "draw.pid"
        path.write_text("99999999")
        (folder / "draw.process-start").touch()
        os.utime(path, (now - age, now - age))
        h.set(process_live=True)
        result = h.run("draw", code=2 if age < 60 else 0)
    else:
        path = h.state / "lock"
        path.mkdir()
        if shape == "empty-owner":
            path = path / "99999999"
            path.mkdir()
            (path / "start").touch()
        os.utime(path, (now - age, now - age))
        h.set(process_live=True)
        result = h.run("abandon", "A.F1", code=2 if age < 60 else 0)
    if age < 60:
        assert "may be starting" in result.stderr
    elif shape != "empty-tool":
        assert not (h.state / "lock").exists()


def test_r3_void_archive_preserves_counted_evaluation(harness):
    h = harness
    through(h, "post-draw")
    h.set(place_exit=1, dr_refuse="record-void")
    h.run("place", code=2)
    number = json.loads(h.scenario.read_text())["round"]
    receipt = (h.state / f"private/void-confirm-{number}").read_text().split()[1]
    h.set(
        dr_refuse=None,
        voids=[number],
        void_receipt=receipt,
        counted=True,
        round=number + 1,
    )
    # S4 counts a later on-time post while finishing the previous void's archive.
    h.run("post-commit")
    assert (h.state / "private/evaluate.out").exists()
    assert (h.state / f"private/void-{number}/evaluate.out").exists()


@pytest.mark.parametrize(
    "step,previous,reason",
    [
        ("place", "draw", "draw post is not recorded"),
        ("build", "post-draw", "two placements"),
        ("tasks", "place", "not built"),
        ("post-tasks", "build", "not frozen"),
        ("check3", "tasks", "tasks post is not recorded"),
    ],
)
def test_r3_immediate_prerequisite(harness, step, previous, reason):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    through(h, previous)
    assert reason in h.run(step, code=2).stderr


@pytest.mark.parametrize(
    "command,previous,step",
    [
        ("read", "rehearse", "post-commit"),
        ("evaluate", "rehearse", "post-commit"),
        ("choose-round", "rehearse", "post-commit"),
        ("post", "rehearse", "post-commit"),
        ("match", "draw", "post-draw"),
    ],
)
def test_r3_s4_refusal_at_each_call(harness, command, previous, step):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    through(h, previous)
    h.set(dr_refuse=command)
    result = h.run(step, code=2)
    reason = {
        "read": "draw-record read refused",
        "evaluate": "draw-record evaluation refused",
        "choose-round": "draw-record choose-round refused",
        "post": "draw-record first post refused",
        "match": "draw-record match refused",
    }[command]
    assert result.stderr == "refused: " + reason + "\n"
    assert not h.calls("arm")


@pytest.mark.parametrize("step", ["beacon", "post-draw"])
@pytest.mark.parametrize("field", ["round", "counted_commit"])
def test_r3_counted_identity_changes(harness, step, field):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    through(h, "draw" if step == "post-draw" else "post-commit")
    c = json.loads(h.scenario.read_text())
    h.set(**{field: c["round"] + 1 if field == "round" else "c" * 40})
    assert ("round differs" if field == "round" else "counted commit differs") in h.run(
        step, code=2
    ).stderr


def test_r3_exact_table_sequence_options(harness):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    h.ready()
    first_attempts(h)
    for number, label in enumerate(reversed(ORDER), 1):
        (h.state / "logs" / (label + ".seq")).write_text(str(number))
    (h.state / "runs/A.F1.rerun").mkdir()
    (h.state / "logs/A.F1.rerun.seq").write_text("37")
    h.run("table", code=4)
    argv = h.calls("table")[-1]["argv"]
    assert argv[argv.index("--order") + 1] == ",".join([*reversed(ORDER[1:]), "A.F1"])
    assert argv[argv.index("--attempts") + 1] == ",".join(
        [*reversed(ORDER), "A.F1.rerun"]
    )
    assert argv[argv.index("--check3") + 1] == str(h.state / "private/check3-1.txt")
    assert argv[argv.index("--filter-out") + 1] == str(
        h.state / "private/FILTER-38.json"
    )


def test_r3_rerun_immediately_after_after_reruns_pending(harness):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    h.ready()
    first_attempts(h)
    h.set(
        table_output="pending before any score: A.H1 - rerun once (§3, §4), then run again with --after-reruns"
    )
    h.run("table", code=4)
    h.run("rerun", "A.H1")
    h.set(
        table_final_output="pending before any score: A.H2 - rerun once (§3, §4), then run again with --after-reruns"
    )
    h.run("table", "--after-reruns", code=4)
    h.run("rerun", "A.H2")


def test_r3_release_blocked_verify_and_d19_files(harness):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    through(h, "rehearse")
    h.set(blocked=True)
    h.run("post-commit", code=2)
    h.run("release")
    assert (h.state / "publish/blocked").exists()
    h.set(blocked=False)
    for step in (
        "post-commit",
        "beacon",
        "draw",
        "post-draw",
        "place",
        "build",
        "tasks",
        "post-tasks",
        "check3",
    ):
        h.run(step)
    first_attempts(h)
    h.set(table_exit=3, table_output="fault: pack code pins", verify_exit=1)
    h.run("table", code=3)
    h.run("release")
    published = h.state / "publish"
    for name in [
        "BEACON",
        "DRAW.json",
        "draw.sha256",
        "counted.json",
        "h-differences",
        "FILTER-37.json",
        *[
            f"{stem}-{p}.{suffix}"
            for p in "ABC"
            for stem, suffix in (("TASKS", "json"), ("TASKS", "sha256"))
        ],
        *[
            f"placed-{i}/{stem}-{p}.{suffix}"
            for i in (1, 2)
            for p in "ABC"
            for stem, suffix in (("pack", "toml"), ("placement", "json"))
        ],
    ]:
        assert (published / name).is_file(), name
    for suffix in ("txt", "flags", "exit", "seq"):
        assert (published / f"records/table-37.{suffix}").is_file()
    assert (published / "draw-check-current.exit").read_text() == "exit 1\n"


def test_r3_real_non573_pr_outside_history(harness):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    outside = fixture_commit(h, side=True)
    h.set(pr_merge_overrides={"1": outside})
    result = h.run("prep", h.commit, "1", code=2)
    assert "prerequisite merge is outside the run history" in result.stderr
    assert not (h.state / "private/settings").exists()


def test_r3_new_worktree_environment(harness):
    """Positive control: exercise an already-correct round-2 path."""
    h = harness
    through(h, "place")
    calls = [call for call in h.calls() if "/worktrees/" in call["cwd"]]
    assert {call["kind"] for call in calls} >= {
        "draw",
        "verify",
        "place",
        "import-check",
    }
    assert all(call["hashseed"] == "0" and call["git"] == [] for call in calls)
    assert (h.state / "private/h-differences").read_text() == ""


def test_r3_real_s4_first_post_blocks_new_directory(integrated):
    """Positive control: exercise an already-correct round-2 path."""
    h = integrated
    dr = by_path("r3_first", SCRIPT.with_name("draw_record.py"))
    c = json.loads(h.scenario.read_text())
    h.set(
        comments=[
            dict(
                id=77,
                author=71,
                created_at=dr.stamp(c["clock"]),
                body=f"Follow-up draw: first post\nround {c['round']}\nrun_commit {h.commit}\n",
            )
        ]
    )
    assert "draw already began" in h.run("prep", h.commit, "1", code=2).stderr


def test_r3_official_import_source_before_external_tools(harness):
    h = harness
    through(h, "rehearse")
    old = h.state
    adopted = fixture_commit(h)
    called = blocking_python(h)
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(old.with_name("authorized-source")))
    h.state = old.with_name("unmarked-target")
    h.env["FOLLOWUP_STATE"] = str(h.state)
    result = h.run("prep", adopted, "1", "--import", str(old), code=2)
    assert "import source is not the recorded official directory" in result.stderr
    assert not called.exists()
    assert record.read_text() == str(old.with_name("authorized-source"))


def test_r3_record_copy_failure_resumes(harness):
    h = harness
    h.ready()
    h.set(inject=dict(kind="files", match=["cp", "A.F1.inv-1.start"], fail=True))
    h.run("run", "A.F1", code=2)
    assert not (h.state / "logs/A.F1.seq").exists()
    assert len(h.calls("arm")) == 1
    h.run("abandon", "A.F1")
    assert (h.state / "logs/A.F1.seq").exists()
    assert len(h.calls("arm")) == 1


def test_r3_check3_receipt_write_failure(harness):
    h = harness
    through(h, "post-tasks")
    # The open receipt already has its commit line. Truncate it inside check3,
    # independently of whether the caller later validates that receipt.
    h.set(inject=dict(kind="check3", empty="private/check3-1.txt"))
    result = h.run("check3", code=None)
    assert not (h.state / "private/check3-1.txt").read_text().startswith("commit ")
    assert result.returncode == 2
    assert "check 3 receipt write failed" in result.stderr
    assert not h.calls("arm")
    assert "check 3 must pass" in h.run("run", "A.F1", code=2).stderr
    h.run("check3")
    h.run("run", "A.F1")
    assert len(h.calls("arm")) == 1


def test_r3_second_check3_receipt_write_failure_releases(harness):
    h = harness
    through(h, "post-tasks")
    h.set(check3_exit=1)
    h.run("check3", code=1)
    h.set(check3_exit=0, inject=dict(kind="check3", empty="private/check3-2.txt"))
    result = h.run("check3", code=None)
    assert result.returncode == 2
    assert "check 3 receipt write failed" in result.stderr
    assert "check 3 must pass" in h.run("run", "A.F1", code=2).stderr
    assert "check 3 has run twice" in h.run("check3", code=2).stderr
    h.run("release")
    assert (h.state / "publish/check3-2.txt").is_file()
    assert not h.calls("arm")


def test_r3_same_commit_import_before_beacon(harness):
    h = harness
    through(h, "post-commit")
    old = h.state
    new_test_state(h, "same-before-beacon")
    result = h.run("prep", h.commit, "1", "--import", str(old), code=2)
    assert "import commit must differ" in result.stderr


def test_r3_import_requires_successful_evaluate(harness):
    h = harness
    through(h, "rehearse")
    old = h.state
    adopted = fixture_commit(h)
    h.set(counted=True, counted_commit=adopted, reading_refusal="unavailable")
    new_test_state(h, "unavailable-import")
    result = h.run("prep", adopted, "1", "--import", str(old), code=2)
    assert "import counted evaluation refused" in result.stderr


@pytest.mark.parametrize("fault", ["write", "hash-format"])
def test_r3_task_hash_checked_before_rename(harness, fault):
    h = harness
    through(h, "build")
    injection = (
        dict(kind="files", match=["mv", "TASKS-A.sha256"], fail=True)
        if fault == "write"
        else dict(kind="sha", match=["TASKS-A.json.part"], stdout="invalid")
    )
    h.set(inject=injection)
    h.run("tasks", code=2)
    assert not (h.state / "private/TASKS-A.json").exists()
    assert (h.state / "private/TASKS-A.json.part").exists()
    h.run("tasks")
    assert (
        len(
            [
                call
                for call in h.calls("tasks")
                if "A" in call["argv"]
                and not any("/rehearsal/" in arg for arg in call["argv"])
            ]
        )
        == 1
    )


@pytest.mark.parametrize("fault", ["header", "exit"])
def test_r3_task_hash_recovery_rechecks(harness, fault):
    # Positive controls: the new recovery must retain the old refusal for bad data.
    h = harness
    through(h, "tasks")
    (h.state / "private/TASKS-A.sha256").unlink()
    if fault == "exit":
        (h.state / "private/tools/tasks-A.exit").write_text("3")
    else:
        path = h.state / "private/TASKS-A.json"
        payload = json.loads(path.read_text())
        payload["header"]["commit"] = "c" * 40
        path.write_text(json.dumps(payload))
    h.run("tasks", code=2)
    assert not (h.state / "private/TASKS-A.sha256").exists()


def test_r3_kill_between_guard_moves(harness):
    h = harness
    h.ready()
    h.set(
        guard_refusal=True,
        inject=dict(
            kind="files", match=["mv", "A.F1.inv-1.guard-out"], phase="after", kill=True
        ),
    )
    h.run("run", "A.F1", code=-9)
    assert (h.state / "logs/A.F1.inv-1.guard-out").exists()
    h.run("abandon", "A.R1")
    h.set(guard_refusal=False)
    h.run("run", "A.F1")
    assert (h.state / "logs/A.F1.inv-1.guard-diag/manifest.json").exists()
    assert len(h.calls("arm")) == 2


def test_r3_newest_invocation_is_numeric(harness):
    """Positive control: completing invocation ten must retain its own records."""
    h = harness
    h.ready()
    for n in range(1, 10):
        prefix = h.state / f"logs/A.F1.inv-{n}"
        prefix.with_suffix(prefix.suffix + ".start").write_text("1")
        prefix.with_suffix(prefix.suffix + ".exit").write_text("exit=3")
        prefix.with_suffix(prefix.suffix + ".seq").write_text(str(n))
        prefix.with_suffix(prefix.suffix + ".guard-out").mkdir()
    (h.state / "counter").write_text("9")
    h.run("run", "A.F1")
    assert (h.state / "logs/A.F1.seq").read_text() == "10\n"
    assert (h.state / "logs/A.F1.exit").read_text() == "exit=0\n"


# Round 4: the counted round owns its state; faults remain inside D3.
@pytest.mark.parametrize(
    "line", ["Follow-up draw: second post", "Follow-up draw: task lists"]
)
def test_r4_two_step_import_after_draw(harness, line):
    h = harness
    through(h, "post-draw")
    old = h.state
    other = fixture_commit(h)
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(old))
    old.rename(old.with_name("retained-official"))
    h.set(
        markers=[
            dict(after_merge=True, first_line=line, created_at="2026-01-02T00:00:01Z")
        ]
    )
    lost = new_test_state(h, "release-only-r4")
    h.run("prep", other, "1", "--import", "none")
    assert (lost / "private/state-lost-after-draw").is_file()
    before = record.read_bytes()
    new_test_state(h, "restarted-r4")
    result = h.run("prep", h.commit, "1", "--import", str(lost), code=None)
    if result.returncode == 0:
        # Base receipt: matching existing posts let the reset pipeline reach an arm.
        for step in (
            "rehearse",
            "post-commit",
            "beacon",
            "draw",
            "post-draw",
            "place",
            "build",
            "tasks",
            "post-tasks",
            "check3",
        ):
            h.run(step)
        h.run("run", "A.F1")
        assert len(h.calls("arm")) == 1
        print("base bypass: two-step import reached first arm with fresh budgets")
    assert result.returncode == 2, (
        "import accepted after the counted round's draw began"
    )
    assert "import refused: counted round draw already began" in result.stderr
    assert record.read_bytes() == before
    assert not (h.state / "private/settings").exists()


@pytest.mark.parametrize("after_void", [False, True])
def test_r4_d4_import_positive_controls(harness, after_void):
    h = harness
    through(h, "post-draw" if after_void else "rehearse")
    old = h.state
    if after_void:
        h.set(place_exit=1)
        h.run("place", code=1)
        number = json.loads(h.scenario.read_text())["round"]
    adopted = fixture_commit(h)
    config = json.loads(h.scenario.read_text())
    h.set(
        commit=adopted,
        place_exit=0,
        round=config["round"] + int(after_void),
        due=config["due"] + 3 * int(after_void),
        counted=True,
        counted_commit=adopted,
        counted_created_at="2026-01-03T00:00:00Z",
        markers=[
            dict(
                after_merge=True,
                first_line="Follow-up draw: second post",
                created_at="2026-01-02T00:00:01Z",
            )
        ]
        if after_void
        else [],
    )
    new_test_state(h, "d4-r4")
    h.run("prep", adopted, "1", "--import", str(old))
    assert not (h.state / "private/state-lost-after-draw").exists()
    if after_void:
        for p in (old / f"private/void-{number}").rglob("*"):
            if p.is_file():
                assert (h.state / p.relative_to(old)).read_bytes() == p.read_bytes()
    h.run("rehearse")


@pytest.mark.parametrize(
    "after_merge,line",
    [
        (True, "Follow-up draw: stop"),
        (False, "Follow-up draw: second post"),
    ],
)
def test_r4_lost_state_marker_filters(harness, after_merge, line):
    """Positive controls for tests F3: unrelated/pre-merge markers do not close prep."""
    h = harness
    record = Path(h.env["HOME"]) / ".bicentennial-followup-official"
    record.write_text(str(h.state.with_name("lost-official")))
    h.set(
        markers=[
            dict(
                after_merge=after_merge,
                first_line=line,
                created_at="2026-01-01T00:00:00Z",
            )
        ]
    )
    h.run("prep", h.commit, "1", "--import", "none")
    assert not (h.state / "private/state-lost-after-draw").exists()
    h.run("rehearse")


def test_r4_empty_lock_start_refuses(harness):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(process_start="")
    result = h.run("rehearse", code=2)
    assert result.stderr == "refused: cannot record lock owner start\n"
    assert not (h.state / "lock").exists()
    assert not h.calls("draw")


@pytest.mark.parametrize("age", [59, 60])
def test_r4_script_written_empty_tool_start_age(harness, age):
    h = harness
    through(h, "beacon")
    h.set(
        empty_tool_start=True,
        inject=dict(
            kind="clock", requires="private/tools/draw.process-start", kill=True
        ),
    )
    h.run("draw", code=-9)
    folder = h.state / "private/tools"
    assert (folder / "draw.process-start").read_bytes() == b""
    assert not (folder / "draw.exit").exists()
    now = json.loads(h.scenario.read_text())["clock"]
    os.utime(folder / "draw.pid", (now - age, now - age))
    h.set(empty_tool_start=False, process_live=True)
    h.run("abandon", "A.F1")
    result = h.run("draw", code=2 if age < 60 else 0)
    if age < 60:
        assert "recorded tool may be starting" in result.stderr
        assert not (folder / "draw.cuts").exists()
    else:
        assert (folder / "draw.cuts").read_text() == "1\n"
        assert (folder / "draw.cut-1/process-start").read_bytes() == b""
    assert len([c for c in h.calls("draw") if "--rehearsal" not in c["argv"]]) == (
        1 if age < 60 else 2
    )


@pytest.mark.parametrize("fault", ["kill", "fail"])
def test_r4_lock_partial_cleared(harness, fault):
    h = harness
    h.run("prep", h.commit, "1")
    h.set(inject=dict(kind="files", match=["mv", "/start.part"], **{fault: True}))
    result = h.run("rehearse", code=-9 if fault == "kill" else 2)
    if fault == "kill":
        owner = next((h.state / "lock").iterdir())
        assert (owner / "start.part").is_file()
        now = json.loads(h.scenario.read_text())["clock"]
        os.utime(owner, (now - 60, now - 60))
    else:
        assert "lock-owner-start record write failed" in result.stderr
        assert not (h.state / "lock").exists()
    h.run("abandon", "A.F1")
    assert not (h.state / "lock").exists()
    h.run("rehearse")


@pytest.mark.parametrize("record_name", ["pid", "process-start", "start"])
def test_r4_failed_fork_record_waits_and_resumes(harness, record_name):
    h = harness
    through(h, "beacon")
    h.set(
        hold_draw=True,
        inject=dict(
            kind="files", match=["mv", f"/tools/draw.{record_name}.part"], fail=True
        ),
    )
    result = h.run("draw", code=2)
    folder = h.state / "private/tools"
    assert (folder / "draw.exit").is_file(), (
        "child exit was not recorded before refusing"
    )
    assert (folder / "draw.exit").read_text() == "0\n"
    assert "tool fork record write failed" in result.stderr
    assert (h.state / "private/DRAW.json").is_file()
    h.run("draw")
    assert len([c for c in h.calls("draw") if "--rehearsal" not in c["argv"]]) == 1
    assert not (folder / "draw.cuts").exists()


def test_r4_kill_with_only_pid_partial(harness):
    h = harness
    through(h, "beacon")
    h.set(
        hold_draw=True,
        inject=dict(kind="files", match=["mv", "/tools/draw.pid.part"], kill=True),
    )
    h.run("draw", code=-9)
    folder = h.state / "private/tools"
    assert (folder / "draw.pid.part").read_text().strip().isdigit()
    assert not (folder / "draw.pid").exists()
    assert not (folder / "draw.start").exists()
    now = json.loads(h.scenario.read_text())["clock"]
    os.utime(folder / "draw.pid.part", (now, now))
    h.run("abandon", "A.F1")
    for _ in range(2):
        result = h.run("draw", code=None)
        count = len([c for c in h.calls("draw") if "--rehearsal" not in c["argv"]])
        assert count == 1, "PID partial ignored: tool forked twice"
        assert result.returncode == 2
        assert "recorded tool may be starting" in result.stderr


def test_r4_portable_full_write_fault(harness):
    """ENOSPC stand-in fails the targeted write on BSD as well as other hosts."""
    h = harness
    through(h, "post-draw")
    number = json.loads(h.scenario.read_text())["round"]
    h.set(
        place_exit=1,
        inject=dict(
            kind="sha",
            match=["placed-1/void.json"],
            full=f"private/void-confirm-{number}",
        ),
    )
    result = h.run("place", code=2)
    assert "No space left on device" in result.stderr
    assert "void confirmation record write failed" in result.stderr
    assert (h.state / f"private/void-confirm-{number}.part").read_bytes() == b""
    assert not any("record-void" in c["argv"] for c in h.calls("dr"))
    h.run("place", code=1)
