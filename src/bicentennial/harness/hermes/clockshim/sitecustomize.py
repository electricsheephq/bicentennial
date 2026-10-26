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

Unreachable from Python (see REPORT.md): SQLite 'now', kernel file times, and any C
code or child process that reads the OS clock directly.

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
        self.mtime_ns = None
        self.state = (0.0, 0.0, 1.0)  # (sim_start, wall_anchor, rate)
        self.next_check = 0.0
        self.load()

    def load(self):
        st = _os.stat(self.path)
        with open(self.path, encoding="utf-8") as fh:
            data = _json.load(fh)
        state = (float(data["sim_start"]), float(data["wall_anchor"]), float(data.get("rate", 1.0)))
        # One attribute store: a concurrent now() sees the old or the new reading, never a mix,
        # and a bad file leaves the old reading intact.
        self.state = state
        self.mtime_ns = st.st_mtime_ns

    def refresh(self):
        # Re-read when the director rewrites the file (a long-lived process may span a jump).
        mono = _real_monotonic()
        if mono < self.next_check:
            return
        self.next_check = mono + _RECHECK_SECONDS
        try:
            if _os.stat(self.path).st_mtime_ns != self.mtime_ns:
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
