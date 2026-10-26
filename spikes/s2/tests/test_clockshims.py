"""Self-checks for the S2 clock shims (no harness needed). Run: python3 -m pytest spikes/s2/tests -q

Each case runs a fresh interpreter with the shim, so nothing leaks into the test process.
S2_CHILD_PYTHON picks that interpreter (default: the one running pytest), so the shim can be
checked on another Python without installing pytest there.
The Node cases are skipped when ``node`` is not on PATH.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SHIM_DIR = Path(__file__).resolve().parent.parent / "clockshim"
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
    r = subprocess.run([CHILD_PYTHON, "-c", "import time; print(abs(time.time() - %r) < 30)" % time.time()],
                       env=env, capture_output=True, text=True, check=False, timeout=60)
    assert r.stdout.strip() == "True"


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_node_date_shim(tmp_path):
    env = {**os.environ, "NODE_OPTIONS": f"--require {SHIM_DIR / 'clock_shim.cjs'}",
           "BICENTENNIAL_CLOCK_FILE": str(_clock(tmp_path))}
    js = ("const fs = require('fs'); class X extends Date {};"
          "console.log(JSON.stringify([new Date().toISOString().slice(0, 10), new Date(Date.now()).getUTCFullYear(),"
          " Date().includes('2025'), new Date(0).getTime(), fs.statSync('.').mtime instanceof Date,"
          " new X() instanceof X, new X().getUTCFullYear(),"
          " require('child_process').execSync(process.execPath + ' -e \"console.log(new Date().getUTCFullYear())\"').toString().trim()]))")
    r = subprocess.run([NODE, "-e", js], env=env, capture_output=True, text=True, check=False, timeout=60)
    assert json.loads(r.stdout) == ["2025-03-03", 2025, True, 0, True, True, 2025, "2025"], r.stderr


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_node_unreadable_clock_exits_70(tmp_path):
    env = {**os.environ, "NODE_OPTIONS": f"--require {SHIM_DIR / 'clock_shim.cjs'}",
           "BICENTENNIAL_CLOCK_FILE": str(tmp_path / "missing.json")}
    r = subprocess.run([NODE, "-e", "console.log('ran')"], env=env, capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 70 and "ran" not in r.stdout
