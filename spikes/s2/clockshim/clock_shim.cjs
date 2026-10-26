// Simulated-clock shim for a Node harness (spike S2). Load with
//   NODE_OPTIONS="--require <this file>"   and   BICENTENNIAL_CLOCK_FILE=<clock.json>
// clock.json is the same file the Python shim reads:
//   {"sim_start": <epoch seconds>, "wall_anchor": <epoch seconds>, "rate": 1.0}
// Simulated ms = (sim_start + (wall_now - wall_anchor) * rate) * 1000, re-read when the file changes.
//
// Patched: Date.now(), new Date() with no arguments, and Date() called as a function.
// Not patched: performance.now / process.hrtime (durations), and engine-internal clock reads
// such as Intl.DateTimeFormat#format() with no date, which use the original Date.now.
// With BICENTENNIAL_CLOCK_FILE unset the shim does nothing; set but unreadable, it exits 70.
'use strict';
const fs = require('fs');

const path = (process.env.BICENTENNIAL_CLOCK_FILE || '').trim();
if (path) {
  const RealDate = Date;
  const realNow = RealDate.now;
  const RECHECK_MS = 250;
  let clock = null;
  let mtimeMs = -1;
  let nextCheck = 0;

  const load = () => {
    const st = fs.statSync(path);
    const data = JSON.parse(fs.readFileSync(path, 'utf8'));
    const c = { simStart: Number(data.sim_start), wallAnchor: Number(data.wall_anchor), rate: Number(data.rate ?? 1) };
    if (!Number.isFinite(c.simStart) || !Number.isFinite(c.wallAnchor) || !Number.isFinite(c.rate)) {
      throw new Error('clock fields are not numbers');
    }
    clock = c;
    mtimeMs = st.mtimeMs;
  };

  try {
    load();
  } catch (err) {
    process.stderr.write(`bicentennial clock shim: unreadable clock file (${err.name}); refusing wall time\n`);
    process.exit(70);
  }

  const simMs = () => {
    const mono = performance.now();
    if (mono >= nextCheck) {
      nextCheck = mono + RECHECK_MS;
      try {
        if (fs.statSync(path).mtimeMs !== mtimeMs) load();
      } catch (_) { /* keep the last good reading */ }
    }
    const wall = realNow() / 1000;
    return (clock.simStart + (wall - clock.wallAnchor) * clock.rate) * 1000;
  };

  // A plain function sharing Date.prototype, so instanceof holds for engine-made Dates too
  // (fs.Stats times, structuredClone) and subclasses keep working through new.target.
  function SimDate(...args) {
    if (!new.target) return new RealDate(simMs()).toString();
    return Reflect.construct(RealDate, args.length === 0 ? [simMs()] : args, new.target);
  }
  Object.defineProperty(SimDate, 'name', { value: 'Date' });
  Object.defineProperty(SimDate, 'length', { value: 7 });
  SimDate.prototype = RealDate.prototype;
  SimDate.now = function now() { return Math.floor(simMs()); };
  SimDate.parse = RealDate.parse;
  SimDate.UTC = RealDate.UTC;
  Object.defineProperty(RealDate.prototype, 'constructor', { value: SimDate, writable: true, configurable: true });
  globalThis.Date = SimDate;
}
