"""Simulated-clock shim for a Python harness (spike S2).

Put this directory on PYTHONPATH and point BICENTENNIAL_CLOCK_FILE at a clock.json
the director writes:

    {"sim_start": <epoch seconds>, "wall_anchor": <epoch seconds>, "rate": 1.0}

The simulated instant is ``sim_start + (wall_now - wall_anchor) * rate``: it starts at
``sim_start`` when the director writes the file and then ticks with the wall clock, so
durations inside a session stay real and ordering is preserved.

Patched (wall-clock readers only):
  time.time, time.time_ns, and the no-argument forms of time.localtime, time.gmtime,
  time.ctime, time.asctime and time.strftime; datetime.datetime.now, utcnow and today;
  datetime.date.today.

Deliberately NOT patched: time.monotonic, time.perf_counter, time.process_time and
asyncio loop time. They measure durations, never dates, and timeouts depend on them.

SQLite 'now' and the 'subsec'/'subsecond' time-values through sqlite3.connect and
sqlite3.dbapi2.connect follow the clock, floored to UTC milliseconds and marked as
UTC like SQLite's own 'now', with one instant per traced statement.
Unreachable: SQLite opened outside Python's sqlite3 (C/Rust, apsw), direct
sqlite3.Connection construction, kernel file times (disclosed per system), and C
code or children reading the OS clock directly. Trigger trace events reset the
instant; a trigger can read later than its statement if the clock moves. Another
statement run on the same connection while one is open also resets it. Replacing
the trace callback makes reads per call. Non-deterministic overrides are refused
in generated columns, expression indexes and partial-index WHERE clauses, even
without 'now'; trusted_schema=OFF also refuses them in triggers, views and DEFAULTs.

With BICENTENNIAL_CLOCK_FILE unset the shim does nothing. With it set but unreadable the
process exits with code 70 rather than silently running on wall time.
"""

import datetime as _dt_mod
import json as _json
import os as _os
import sys as _sys
import time as _time

_CLOCK_ENV = "BICENTENNIAL_CLOCK_FILE"
_EXIT_BAD_CLOCK = 70
_RECHECK_SECONDS = 0.25

_real_time = _time.time
_real_time_ns = _time.time_ns
_real_localtime = _time.localtime
_real_gmtime = _time.gmtime
_real_ctime = _time.ctime
_real_asctime = _time.asctime
_real_strftime = _time.strftime
_real_monotonic = _time.monotonic
_RealDatetime = _dt_mod.datetime
_RealDate = _dt_mod.date


class _Clock:
    def __init__(self, path):
        self.path = path
        self.ident = None
        self.state = (0.0, 0.0, 1.0)  # (sim_start, wall_anchor, rate)
        self.next_check = 0.0
        self.load()

    def load(self):
        with open(self.path, encoding="utf-8") as fh:
            st = _os.fstat(fh.fileno())
            data = _json.load(fh)
        state = (float(data["sim_start"]), float(data["wall_anchor"]), float(data.get("rate", 1.0)))
        # One attribute store: a concurrent now() sees the old or the new reading, never a mix,
        # and a bad file leaves the old reading intact.
        self.state = state
        self.ident = (st.st_ino, st.st_mtime_ns)

    def refresh(self):
        # Re-read when the director rewrites the file (a long-lived process may span a jump).
        # Logical mode (rate 0) checks on every read, so a tick is seen by the first read after
        # the writer's os.replace (a new inode); a throttle would tie it to wall timing.
        mono = _real_monotonic()
        if self.state[2] != 0 and mono < self.next_check:
            return
        self.next_check = mono + _RECHECK_SECONDS
        try:
            st = _os.stat(self.path)
            if (st.st_ino, st.st_mtime_ns) != self.ident:
                self.load()
        except (OSError, ValueError, KeyError, TypeError):
            pass  # keep the last good reading; startup already proved the file valid

    def now(self):
        self.refresh()
        sim_start, wall_anchor, rate = self.state
        if rate == 0:
            return sim_start
        return sim_start + (_real_time() - wall_anchor) * rate


class _Unbound:
    """A callable that, like the builtins it replaces and unlike a plain function, does not bind
    when stored as a class attribute (logging.Formatter.converter = time.localtime)."""

    __slots__ = ("__name__", "__qualname__", "_fn")

    def __init__(self, fn, name):
        self._fn = fn
        self.__name__ = self.__qualname__ = name

    def __call__(self, *args, **kwargs):
        return self._fn(*args, **kwargs)

    def __repr__(self):
        return f"<simulated time.{self.__name__}>"


def _sqlite_probe(connection):
    names = []
    for name, args in (("unixepoch", "0"), ("timediff", "0,0")):
        try:
            connection.execute(f"SELECT {name}({args})").fetchone()
        except Exception:  # sqlite3 is imported only after the datetime patch
            continue
        names.append(name)
    return names


def _install_sqlite(clock):
    import math
    import sqlite3
    import threading
    import weakref

    real_connect = sqlite3.connect
    delegate = real_connect(":memory:", check_same_thread=False)
    lock = threading.Lock()
    optional = _sqlite_probe(delegate)

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        cached = [None]

        def trace(_statement):
            cached[0] = None

        connection.set_trace_callback(trace)
        # Only SQLite owns trace: replacement releases it, disabling the cache.
        traced = weakref.ref(trace)

        def instant():
            if cached[0] is None or traced() is None:
                ms = math.floor(clock.now() * 1000)
                cached[0] = (_RealDatetime.fromtimestamp(ms // 1000, _dt_mod.timezone.utc)
                             .strftime("%Y-%m-%d %H:%M:%S") + f".{ms % 1000:03d}Z")
            return cached[0]

        def function(name):
            def call(*values):
                values = list(values)
                target = name.removeprefix("current_")
                if name.startswith("current_"):
                    target = {"timestamp": "datetime"}.get(target, target)
                    values = [instant()]
                else:
                    indices = range(2) if name == "timediff" else [int(name == "strftime")]
                    for index in indices:
                        if index == len(values) and (name != "strftime" or values):
                            values.append(instant())
                        elif index < len(values) and isinstance(values[index], (str, bytes)):
                            word = values[index].lower()
                            if word in ("now", b"now"):
                                values[index] = instant()
                            elif word in ("subsec", "subsecond", b"subsec", b"subsecond"):
                                # SQLite reads these as 'now' plus the subsec modifier.
                                values[index:index + 1] = ([instant()] if name == "timediff"
                                                           else [instant(), "subsec"])
                with lock:
                    return delegate.execute(f"SELECT {target}({','.join('?' for _ in values)})", values).fetchone()[0]
            return call

        for name in ("date", "time", "datetime", "julianday", "strftime", *optional,
                     "current_timestamp", "current_date", "current_time"):
            arity = 0 if name.startswith("current_") else 2 if name == "timediff" else -1
            connection.create_function(name, arity, function(name))
        return connection

    sqlite3.connect = sqlite3.dbapi2.connect = connect


def _install(clock):
    def sim_time():
        return clock.now()

    def sim_time_ns():
        return int(clock.now() * 1_000_000_000)

    def sim_localtime(secs=None):
        return _real_localtime(clock.now() if secs is None else secs)

    def sim_gmtime(secs=None):
        return _real_gmtime(clock.now() if secs is None else secs)

    def sim_ctime(secs=None):
        return _real_ctime(clock.now() if secs is None else secs)

    def sim_asctime(t=None):
        return _real_asctime(_real_localtime(clock.now()) if t is None else t)

    def sim_strftime(fmt, t=None):
        return _real_strftime(fmt, _real_localtime(clock.now()) if t is None else t)

    _time.time = _Unbound(sim_time, "time")
    _time.time_ns = _Unbound(sim_time_ns, "time_ns")
    _time.localtime = _Unbound(sim_localtime, "localtime")
    _time.gmtime = _Unbound(sim_gmtime, "gmtime")
    _time.ctime = _Unbound(sim_ctime, "ctime")
    _time.asctime = _Unbound(sim_asctime, "asctime")
    _time.strftime = _Unbound(sim_strftime, "strftime")

    class _DateMeta(type(_RealDate)):
        # Objects built by C code (sqlite3, zoneinfo, arithmetic) are real date/datetime
        # instances; keep isinstance(x, datetime.datetime) true for them. Only the two shim
        # classes get this; a user subclass of them keeps ordinary isinstance semantics.
        def __instancecheck__(cls, obj):
            if "__real__" in cls.__dict__:
                return isinstance(obj, cls.__real__)
            return super().__instancecheck__(obj)

        def __subclasscheck__(cls, sub):
            if "__real__" in cls.__dict__:
                return issubclass(sub, cls.__real__)
            return super().__subclasscheck__(sub)

    class SimDate(_RealDate, metaclass=_DateMeta):
        __real__ = _RealDate

        def __repr__(self):
            # The C repr prints the bare type name for a subclass; keep the stdlib spelling.
            return "datetime." + _RealDate.__repr__(self)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now())

    class SimDatetime(_RealDatetime, metaclass=_DateMeta):
        __real__ = _RealDatetime

        def __repr__(self):
            return "datetime." + _RealDatetime.__repr__(self)

        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock.now(), tz)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now())

        @classmethod
        def utcnow(cls):
            # Same value as the deprecated stdlib utcnow(), without its DeprecationWarning.
            aware = cls.fromtimestamp(clock.now(), _dt_mod.timezone.utc)
            return aware.replace(tzinfo=None)

    # Pickle and repr resolve these by name, so instances round-trip as datetime.datetime /
    # datetime.date and load as the real classes in an unshimmed process. Known limit: an
    # instance made by the original C classes (sqlite3, zoneinfo, an import taken before the
    # shim) no longer pickles, because datetime.datetime is now a different object.
    for cls, name in ((SimDate, "date"), (SimDatetime, "datetime")):
        cls.__name__ = cls.__qualname__ = name
        cls.__module__ = "datetime"
    _dt_mod.date = SimDate
    _dt_mod.datetime = SimDatetime
    _install_sqlite(clock)


def _main():
    path = _os.environ.get(_CLOCK_ENV, "").strip()
    if not path:
        return
    try:
        clock = _Clock(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _sys.stderr.write(f"bicentennial clock shim: unreadable clock file ({type(exc).__name__}); refusing wall time\n")
        _sys.stderr.flush()
        _os._exit(_EXIT_BAD_CLOCK)
    _install(clock)


_main()
