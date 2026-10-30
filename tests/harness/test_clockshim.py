"""Ported S2 Python self-tests and logical-clock acceptance; no Hermes execution.

S2_CHILD_PYTHON selects the child interpreter without requiring pytest there.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.runtime import clock as clock_module
from bicentennial.runtime.clock import SimClock

SHIM_DIR = (Path(__file__).resolve().parents[2]
            / "src/bicentennial/harness/hermes/clockshim")
SIM = 1740992400.0  # 2025-03-03T09:00:00Z
CHILD_PYTHON = os.environ.get("S2_CHILD_PYTHON") or sys.executable


def _clock(tmp_path, sim=SIM):
    p = tmp_path / "clock.json"
    p.write_text(json.dumps({"sim_start": sim, "wall_anchor": time.time(), "rate": 1.0}))
    return p


def _py(code, clock, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "BICENTENNIAL_CLOCK_FILE")}
    env.update({"PYTHONPATH": str(SHIM_DIR), "BICENTENNIAL_CLOCK_FILE": str(clock)}, **(extra_env or {}))
    return subprocess.run([CHILD_PYTHON, "-c", code], env=env, capture_output=True, text=True, check=False, timeout=60)


def test_wall_readers_are_simulated(tmp_path):
    r = _py("import time, datetime as d\n"
            "print(time.time(), time.time_ns() // 10**9, time.strftime('%Y-%m-%d'), time.gmtime().tm_year,"
            " d.datetime.now(d.timezone.utc).date(), d.datetime.utcnow().year, d.date.today().year)", _clock(tmp_path))
    assert r.returncode == 0, r.stderr
    t, t_ns, day, gm_year, utc_day, utcnow_year, today_year = r.stdout.split()
    assert abs(float(t) - SIM) < 30 and abs(int(t_ns) - SIM) < 30
    assert gm_year == utcnow_year == "2025" and utc_day == "2025-03-03" and today_year == "2025"
    assert day.startswith("2025-03")


def test_duration_clocks_are_untouched(tmp_path):
    r = _py("import time, asyncio\nl = asyncio.new_event_loop()\n"
            "print(time.monotonic() < 1e9, abs(l.time() - time.monotonic()) < 5, time.perf_counter() < 1e9)\nl.close()",
            _clock(tmp_path))
    assert r.stdout.split() == ["True", "True", "True"], r.stderr


def test_datetime_identity_pickle_and_logging(tmp_path):
    code = ("import datetime as d, pickle, logging, io, time\n"
            "n = d.datetime.now()\n"
            "checks = [isinstance(n, d.datetime), isinstance(d.datetime.fromtimestamp(0), d.datetime),\n"
            "          isinstance(n, d.date), issubclass(d.datetime, d.date),\n"
            "          pickle.loads(pickle.dumps(n)) == n, repr(n).startswith('datetime.datetime(')]\n"
            "class K: clock = time.time\n"
            "checks.append(abs(K().clock() - time.time()) < 5)\n"
            "s = io.StringIO(); h = logging.StreamHandler(s); h.setFormatter(logging.Formatter('%(asctime)s'))\n"
            "lg = logging.getLogger('x'); lg.addHandler(h); lg.warning('m')\n"
            "checks.append(s.getvalue().startswith('2025-03'))\n"
            "print(all(checks), checks)")
    r = _py(code, _clock(tmp_path))
    assert r.stdout.startswith("True"), r.stdout + r.stderr


def test_pickle_limit_and_subclass_isinstance(tmp_path):
    # Documented limit (REPORT.md): instances made by the original C classes keep isinstance
    # but no longer pickle; shim-made instances do. A user subclass keeps ordinary isinstance.
    code = ("import datetime as d, pickle\n"
            "RD, RDate = d.datetime.__bases__[0], d.date.__bases__[0]\n"
            "def pk(o):\n"
            "    try:\n"
            "        return pickle.loads(pickle.dumps(o)) == o\n"
            "    except pickle.PicklingError:\n"
            "        return False\n"
            "class MyDT(d.datetime): pass\n"
            "c_dt, c_date = RD.now(), RDate.today()\n"
            "print([isinstance(c_dt, d.datetime), isinstance(c_date, d.date), pk(c_dt), pk(c_date),\n"
            "       pk(d.datetime.now()), pk(d.date.today()),\n"
            "       isinstance(d.datetime.now(), MyDT), isinstance(MyDT.now(), MyDT), issubclass(RD, MyDT)])")
    r = _py(code, _clock(tmp_path))
    assert r.stdout.strip() == "[True, True, False, False, True, True, False, True, False]", r.stdout + r.stderr


def test_bad_rewrite_keeps_last_reading(tmp_path):
    clock = _clock(tmp_path)
    code = ("import time, json, os\n"
            "a = time.time()\n"
            f"p = {str(clock)!r}\n"
            "json.dump({'sim_start': a + 3 * 86400, 'wall_anchor': 1.0, 'rate': None}, open(p + '.t', 'w'))\n"
            "os.replace(p + '.t', p); time.sleep(0.4)\n"
            "print(abs(time.time() - a) < 5)")
    r = _py(code, clock)
    assert r.stdout.strip() == "True", r.stdout + r.stderr


def test_child_python_inherits_shim(tmp_path):
    r = _py("import subprocess, sys\n"
            "print(subprocess.run([sys.executable, '-c', 'import time; print(int(time.time()))'],"
            " capture_output=True, text=True, check=False).stdout.strip())", _clock(tmp_path))
    assert abs(int(r.stdout) - SIM) < 30, r.stderr


def test_clock_rewrite_is_picked_up(tmp_path):
    clock = _clock(tmp_path)
    code = ("import time, json, os\n"
            "a = time.time()\n"
            f"p = {str(clock)!r}\n"
            "json.dump({'sim_start': a + 3 * 86400, 'wall_anchor': os.stat(p).st_mtime + 0.0, 'rate': 1.0}, open(p + '.t', 'w'))\n"
            "os.replace(p + '.t', p); time.sleep(0.4)\n"
            "print(round((time.time() - a) / 86400, 1))")
    r = _py(code, clock)
    assert r.stdout.strip() == "3.0", r.stdout + r.stderr


def test_unreadable_clock_refuses_wall_time(tmp_path):
    bad = tmp_path / "missing.json"
    r = _py("print('ran')", bad)
    assert r.returncode == 70 and "ran" not in r.stdout


def test_unset_clock_is_inert():
    env = {k: v for k, v in os.environ.items() if k != "BICENTENNIAL_CLOCK_FILE"}
    env["PYTHONPATH"] = str(SHIM_DIR)
    r = subprocess.run([CHILD_PYTHON, "-c", "import sys, time; assert 'sqlite3' not in sys.modules; "
                       "import sqlite3; assert sqlite3.connect.__module__ == '_sqlite3'; "
                       "print(abs(time.time() - %r) < 30)" % time.time()],
                       env=env, capture_output=True, text=True, check=False, timeout=60)
    assert r.stdout.strip() == "True"


def test_sqlite_builtins_and_now(tmp_path):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    code = '''import sqlite3, json
c = sqlite3.connect(':memory:')
queries = ['SELECT CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME', 'SELECT strftime()']
for name in ('date', 'time', 'datetime', 'julianday', 'strftime', 'unixepoch'):
    if name == 'unixepoch' and sqlite3.sqlite_version_info < (3, 38): continue
    prefix = "'%Y-%m-%d %H:%M:%f'," if name == 'strftime' else ''
    queries.append(f"SELECT {name}({prefix.rstrip(',')})")
    for value in ("'now'", "'NOW'", "'nOw'", "x'6e6f77'", "'2001-02-03'", '2451545', 'NULL', "'invalid'"):
        for modifier in ('', ",'+1 day'", ",'start of month'", ",'localtime'", ",'subsec'"):
            queries.append(f'SELECT {name}({prefix}{value}{modifier})')
    queries.append(f"SELECT {name}({prefix}1234567890,'unixepoch')")
queries += ["SELECT strftime('%s')", "SELECT strftime('%Y-%m-%d %H:%M:%f','now')"]
if sqlite3.sqlite_version_info >= (3, 43):
    queries += ["SELECT timediff('now','2000-01-01')", "SELECT timediff('2000-01-01',x'6e6f77')",
                "SELECT timediff('NOW','now')", "SELECT timediff('2001-01-01','2000-01-01')"]
REPLACE
print(json.dumps([c.execute(q).fetchone() for q in queries]))
'''
    replace = "queries = [q.replace('CURRENT_TIMESTAMP', \"datetime('now')\").replace('CURRENT_DATE', \"date('now')\").replace('CURRENT_TIME', \"time('now')\") for q in queries]\n"
    replace += "queries = [q.replace(\"'now'\", \"'2025-03-03 09:00:00.123'\").replace(\"'NOW'\", \"'2025-03-03 09:00:00.123'\").replace(\"'nOw'\", \"'2025-03-03 09:00:00.123'\").replace(\"x'6e6f77'\", \"'2025-03-03 09:00:00.123'\") for q in queries]\n"
    # Omitted time-values need an explicit instant in the unshimmed reference.
    replace += "queries = [q.replace('()', \"('2025-03-03 09:00:00.123')\") if q != 'SELECT strftime()' else q for q in queries]\n"
    replace += "queries = [q.replace(\"strftime('%s')\", \"strftime('%s','2025-03-03 09:00:00.123')\").replace(\"strftime('%Y-%m-%d %H:%M:%f')\", \"strftime('%Y-%m-%d %H:%M:%f','2025-03-03 09:00:00.123')\") for q in queries]"
    state = json.loads(clock.path.read_bytes()) | {"sim_start": SIM + 0.1239}
    clock.path.write_text(json.dumps(state))
    actual, expected = _py(code.replace('REPLACE', ''), clock.path), _py(code.replace('REPLACE', replace), '')
    assert actual.returncode == expected.returncode == 0, actual.stderr + expected.stderr
    assert json.loads(actual.stdout) == json.loads(expected.stdout)


@pytest.mark.parametrize("tz", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_sqlite_now_keeps_builtin_utc_semantics(tmp_path, tz):
    """'now' and 'subsec' relate to modifiers as SQLite's own 'now' does, in any zone (#270 review)."""
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    clock.path.write_text(json.dumps(json.loads(clock.path.read_bytes()) | {"sim_start": SIM + 0.1239}))
    code = '''import sqlite3, json
c = sqlite3.connect(':memory:')
v = sqlite3.sqlite_version_info
checks = ["datetime('now','utc') = datetime('now')",
          "datetime('now','utc','localtime') = datetime('now','localtime')",
          "datetime('now','+1 day','utc') = datetime('now','+1 day')",
          "datetime('now','start of day','utc') = datetime('now','start of day')",
          "julianday('now','utc') = julianday('now')",
          "strftime('%s','now','utc') = strftime('%s','now')",
          "strftime('%Y-%m-%d %H:%M:%f','now','utc') = strftime('%Y-%m-%d %H:%M:%f','now')"]
absolute = ["datetime('now','utc')"]
if v >= (3, 38):
    checks += ["unixepoch('now','utc') = unixepoch('now')"]
if v >= (3, 42):
    checks += ["datetime('subsec') = datetime('now','subsec')",
               "datetime('SubSecond') = datetime('now','subsec')",
               "datetime(x'737562736563') = datetime('now','subsec')",
               "datetime('subsec','utc') = datetime('now','subsec')",
               "julianday('subsec') = julianday('now')",
               "unixepoch('subsec') = unixepoch('now','subsec')",
               "strftime('%Y-%m-%d %H:%M:%f','subsec') = strftime('%Y-%m-%d %H:%M:%f','now')"]
    absolute += ["datetime('subsec')", "unixepoch('SUBSECOND')"]
if v >= (3, 43):
    checks += ["timediff('subsec','2000-01-01') = timediff('now','2000-01-01')"]
print(json.dumps([[c.execute('SELECT ' + q).fetchone()[0] for q in checks],
                  [c.execute('SELECT ' + q).fetchone()[0] for q in absolute], list(v)]))
'''
    actual, expected = _py(code, clock.path, {"TZ": tz}), _py(code, "", {"TZ": tz})
    assert actual.returncode == expected.returncode == 0, actual.stderr + expected.stderr
    relations, values, version = json.loads(actual.stdout)
    assert relations == json.loads(expected.stdout)[0]
    if tuple(version) >= (3, 46):  # 'utc' and 'localtime' became no-ops on 'now' in 3.46
        assert all(relations), relations
        assert values[0] == "2025-03-03 09:00:00"
    if tuple(version) >= (3, 42):
        assert values[1:] == ["2025-03-03 09:00:00.123", 1740992400.123]


def test_sqlite_connections_binding_and_default(tmp_path):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    result = _py('''import sqlite3, datetime as d
class Custom(sqlite3.Connection): pass
for connect in (sqlite3.connect, sqlite3.dbapi2.connect):
    c = connect('file:clock?mode=memory&cache=shared', uri=True, factory=Custom, detect_types=sqlite3.PARSE_COLNAMES)
    assert isinstance(c, Custom)
    assert isinstance(c.execute('select ? as "d [date]"', (d.date.today(),)).fetchone()[0], d.date)
    assert c.execute('select ?', (d.datetime.now(),)).fetchone()[0] == '2025-03-03 09:00:00'
    c.execute('create table t (created_at DEFAULT CURRENT_TIMESTAMP)')
    c.execute('insert into t default values')
    assert c.execute('select * from t').fetchone()[0] == '2025-03-03 09:00:00', sqlite3.sqlite_version
    c.close()
''', clock.path, {"TZ": "UTC"})
    assert result.returncode == 0, result.stderr


def test_sqlite_statement_ticks_triggers_and_trace_replacement(tmp_path):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    result = _py('''import sqlite3, json, os
c = sqlite3.connect(':memory:')
def tick():
    p = os.environ['BICENTENNIAL_CLOCK_FILE']
    with open(p) as f: state = json.load(f)
    state['sim_start'] += 60
    with open(p + '.new', 'w') as f: json.dump(state, f)
    os.replace(p + '.new', p)
    return 0
c.create_function('tick', 0, tick)
c.executescript('create table t (created_at DEFAULT CURRENT_TIMESTAMP); create table log (stamp);')
c.execute('insert into t default values')
sql = "select strftime('%s','now'), tick(), strftime('%s','now') from (select 1 union all select 2)"
rows = c.execute(sql).fetchall()
assert rows[0][0] == rows[0][2] == rows[1][0] == rows[1][2]
assert c.execute("select round((julianday('now') - julianday(created_at))*86400) from t").fetchone()[0] == 120
assert int(c.execute(sql).fetchone()[0]) == int(rows[0][0]) + 120  # cached statement re-executed
c.execute('delete from t')
c.executemany("insert into t values (strftime('%s','now') + tick())", [(), ()])
stamps = [int(r[0]) for r in c.execute('select * from t')]
assert stamps[1] - stamps[0] == 60
c.executescript("insert into log values(strftime('%s','now')); select tick(); insert into log values(strftime('%s','now'));")
stamps = [int(r[0]) for r in c.execute('select * from log')]
assert stamps[1] - stamps[0] == 60
c.executescript("delete from t; delete from log; create trigger tr after insert on t begin insert into log values(CURRENT_TIMESTAMP); end;")
c.execute('insert into t values (CURRENT_TIMESTAMP)')
assert c.execute('select * from t').fetchone() == c.execute('select * from log').fetchone()
c.executescript("drop trigger tr; create trigger tr after insert on t begin select tick(); insert into log values(CURRENT_TIMESTAMP); end;")
c.execute('insert into t values (CURRENT_TIMESTAMP)')
outer = c.execute('select * from t order by rowid desc').fetchone()[0]
inner = c.execute('select * from log order by rowid desc').fetchone()[0]
assert inner > outer, (outer, inner)  # trigger trace reset: the disclosed later instant
c.set_trace_callback(lambda sql: None)
row = c.execute(sql).fetchone()
assert int(row[2]) - int(row[0]) == 60  # replacing trace makes reads per call
''', clock.path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("available", [(), ("unixepoch", "timediff")])
def test_sqlite_optional_registration(tmp_path, available):
    result = _py(f'''import sqlite3, sitecustomize as shim
records = []
class Connection(sqlite3.Connection):
    def create_function(self, name, arity, function, **kw): records.append((name, arity, kw))
sqlite3.connect = lambda *a, **kw: Connection(*a, **kw)
shim._sqlite_probe = lambda connection: {available!r}
shim._install_sqlite(shim._Clock({str(SimClock(tmp_path / 'clock.json', int(SIM), 60).path)!r}))
c = sqlite3.connect(':memory:')
assert {{n for n, _, _ in records}} & {{'unixepoch', 'timediff'}} == set({available!r})
assert all(not kw for _, _, kw in records)
assert ('timediff', 2, {{}}) in records if 'timediff' in {available!r} else True
''', tmp_path / "clock.json")
    assert result.returncode == 0, result.stderr


def test_two_scheduled_sessions(tmp_path):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    code = "from datetime import datetime; print(datetime.now().date())"
    first = _py(code, clock.path, {"TZ": "UTC"})
    clock.set_session(int(SIM) + 3 * 86400)
    second = _py(code, clock.path, {"TZ": "UTC"})
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert first.stdout == "2025-03-03\n"
    assert second.stdout == "2025-03-06\n"


def test_logical_ticks_are_byte_identical_across_wall_times(tmp_path):
    outputs = []
    for anchor in (1, 2_000_000_000):
        clock = SimClock(tmp_path / "clock.json", int(SIM), 17)
        output = b""
        for instant in (int(SIM), int(SIM) + 17):
            state = json.loads(clock.path.read_bytes())
            state["wall_anchor"] = anchor
            clock.path.write_bytes(canon(state))
            result = _py(
                "import time; from datetime import datetime, timezone\n"
                "for _ in range(2):\n"
                " print(time.time(), time.time_ns(), datetime.now(timezone.utc).isoformat())\n"
                " time.sleep(1)\n", clock.path,
            )
            assert result.returncode == 0, result.stderr
            lines = result.stdout.splitlines()
            assert lines[0] == lines[1]
            assert lines[0].split()[:2] == [str(float(instant)), str(instant * 10**9)]
            output += result.stdout.encode()
            if instant == int(SIM):
                clock.tick()
        outputs.append(output)
    assert outputs[0] == outputs[1]


def test_logical_reload_in_one_child(tmp_path):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    result = _py(
        "import json, os, time\n"
        "before = time.time()\n"
        f"path = {str(clock.path)!r}\n"
        "with open(path) as stream: state = json.load(stream)\n"
        "state['sim_start'] += 60\n"
        "with open(path + '.new', 'w') as stream: json.dump(state, stream)\n"
        "os.replace(path + '.new', path)\n"
        "time.sleep(0.4)\n"
        "print(time.time() - before)\n", clock.path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "60.0\n"


def test_long_lived_child_sees_each_tick_without_waiting(tmp_path):
    # The director ticks, then answers at once; the child's next read must see the tick.
    clock = SimClock(tmp_path / "clock.json", int(SIM), 60)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "BICENTENNIAL_CLOCK_FILE")}
    env.update({"PYTHONPATH": str(SHIM_DIR), "BICENTENNIAL_CLOCK_FILE": str(clock.path)})
    child = subprocess.Popen(
        [CHILD_PYTHON, "-c", "import sys, time\nfor _ in sys.stdin:\n    print(int(time.time()), flush=True)\n"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    seen = []
    try:
        for _ in range(4):
            for tick in (False, True):
                if tick:
                    clock.tick()
                child.stdin.write("read\n")
                child.stdin.flush()
                seen.append(int(child.stdout.readline()) - int(SIM))
    finally:
        child.stdin.close()
        child.wait(timeout=10)
    assert seen == [0, 60, 60, 120, 120, 180, 180, 240]


def test_writer_is_canonical_and_ticks(tmp_path, monkeypatch):
    monkeypatch.setattr(clock_module.time, "time", lambda: 2_000_000_000.75)
    clock = SimClock(tmp_path / "clock.json", int(SIM), 17)
    assert clock.path.read_bytes() == canon({
        "sim_start": int(SIM), "wall_anchor": 2_000_000_000, "rate": 0, "step_s": 17,
    })
    clock.tick()
    assert json.loads(clock.path.read_bytes())["sim_start"] == int(SIM) + 17
    assert clock.sim_t_s == int(SIM) + 17


@pytest.mark.parametrize("operation", ["construct", "tick", "session", "resume"])
@pytest.mark.parametrize("offset", [0, 1, 3601])
def test_wall_margin_refuses_and_preserves_file(tmp_path, monkeypatch, operation, offset):
    wall = 2_000_000_000
    monkeypatch.setattr(clock_module.time, "time", lambda: wall)
    clock = SimClock(tmp_path / "clock.json", wall - 3601, 1 + offset)
    before = clock.path.read_bytes()
    target = wall - 3600 + offset
    with pytest.raises(ValueError, match="margin"):
        if operation == "construct":
            SimClock(clock.path, target, 1)
        elif operation == "tick":
            clock.tick()
        elif operation == "session":
            clock.set_session(target)
        else:
            SimClock.resume(clock.path, target)
    assert clock.path.read_bytes() == before
    assert clock.sim_t_s == wall - 3601
    assert list(tmp_path.iterdir()) == [clock.path]


def test_resume_uses_schedule_and_preserves_cadence(tmp_path, monkeypatch):
    monkeypatch.setattr(clock_module.time, "time", lambda: 2_000_000_000)
    clock = SimClock(tmp_path / "clock.json", int(SIM), 17)
    state = json.loads(clock.path.read_bytes())
    state.update(sim_start=9_000_000_000, wall_anchor=-9_000_000_000)
    clock.path.write_bytes(canon(state))
    monkeypatch.setattr(clock_module.time, "time", lambda: 2_000_086_400)
    scheduled = int(SIM) + 3 * 86400
    resumed = SimClock.resume(clock.path, scheduled)
    assert resumed.sim_t_s == scheduled
    assert json.loads(clock.path.read_bytes())["sim_start"] == scheduled
    resumed.tick()
    assert json.loads(clock.path.read_bytes())["sim_start"] == scheduled + 17


@pytest.mark.parametrize("value", [1.0, "1", True, None])
def test_non_integer_values_are_refused(tmp_path, value):
    path = tmp_path / "clock.json"
    with pytest.raises(TypeError):
        SimClock(path, value, 1)
    assert not path.exists()
    with pytest.raises(TypeError):
        SimClock(path, int(SIM), value)
    clock = SimClock(path, int(SIM), 1)
    before = path.read_bytes()
    with pytest.raises(TypeError):
        clock.set_session(value)
    with pytest.raises(TypeError):
        SimClock.resume(path, value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("step", [0, -1])
def test_step_must_be_positive(tmp_path, step):
    with pytest.raises(ValueError, match="positive"):
        SimClock(tmp_path / "clock.json", int(SIM), step)
    assert not list(tmp_path.iterdir())


def test_publication_fsyncs_before_atomic_replace(tmp_path, monkeypatch):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 17)
    before = clock.path.read_bytes()
    events = []
    real_fsync, real_replace = clock_module.os.fsync, clock_module.os.replace

    def fsync(fd):
        assert clock.path.read_bytes() == before
        events.append("fsync")
        real_fsync(fd)

    def replace(source, destination):
        assert source.parent == clock.path.parent
        assert destination == clock.path
        assert json.loads(source.read_bytes())["sim_start"] == int(SIM) + 17
        assert events == ["fsync"]
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(clock_module.os, "fsync", fsync)
    monkeypatch.setattr(clock_module.os, "replace", replace)
    clock.tick()
    assert events == ["fsync", "replace"]
    assert list(tmp_path.iterdir()) == [clock.path]


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_publication_failure_preserves_clock(tmp_path, monkeypatch, failure):
    clock = SimClock(tmp_path / "clock.json", int(SIM), 17)
    before = clock.path.read_bytes()

    def fail(*args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(clock_module.os, failure, fail)
    with pytest.raises(OSError, match="injected"):
        clock.tick()
    assert clock.path.read_bytes() == before
    assert clock.sim_t_s == int(SIM)
    assert list(tmp_path.iterdir()) == [clock.path]
