"""S4b paid OpenAI lane; S6a owns classification, write life and ledger format."""
import argparse
import contextlib
import fcntl
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 's6a'))
import director as s6

MODEL = 'deepseek/deepseek-v4.1-flash-1017'
ADAPT = {'provider': {'only': ['deepseek'], 'allow_fallbacks': False}, 'usage': {'include': True}}


def adapt(a):
    """The declared wire additions for this run's pinned provider (an endpoint slug, e.g. deepinfra/fp8)."""
    return ADAPT | {'provider': {'only': [a.provider_only], 'allow_fallbacks': False}}
LIFE = Path(s6.__file__).with_name('micro_life.json')


class Spend:
    def __init__(self, a):
        self.a = a
        self.path = Path(a.spend_file)

    @contextlib.contextmanager
    def locked(self):
        with os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            raw = f.read()
            policy = [self.a.spend_cap_usd, self.a.input_usd, self.a.output_usd, self.a.chars_per_token]
            b = json.loads(raw) if raw else {'policy': policy, 'settled': 0, 'estimated': 0, 'open': {},
                                                'reserved_calls': 0, 'settled_calls': 0, 'refused_calls': 0, 'max_single_call': 0}
            if b['policy'] != policy:
                raise ValueError('shared spend policy mismatch')
            yield b
            f.seek(0)
            f.write(json.dumps(b, allow_nan=False))
            f.truncate()
            f.flush()
            os.fsync(f.fileno())

    def reserve(self, wire):
        if not isinstance(wire.get('max_tokens', 32768), int) or wire.get('max_tokens', 32768) <= 0:
            raise ValueError('positive integer max_tokens required')
        prompt = math.ceil(len(s6.canon(wire)) / self.a.chars_per_token)
        cost = (prompt * self.a.input_usd + wire.get('max_tokens', 32768) * self.a.output_usd) / 1e6
        with self.locked() as b:
            if b['settled'] + sum(b['open'].values()) + cost > self.a.spend_cap_usd:
                b['refused_calls'] += 1
                return None
            rid = uuid.uuid4().hex
            b['open'][rid] = cost
            b['reserved_calls'] += 1
            return rid

    def settle(self, rid, usage, refused=False):
        with self.locked() as b:
            reserved = b['open'].pop(rid)
            estimated = usage.get('cost') is None
            if refused:
                cost, estimated = 0, False
            elif not estimated:
                cost = float(usage['cost'])
            elif all(k in usage for k in ('prompt_tokens', 'completion_tokens')):
                cost = (usage['prompt_tokens'] * self.a.input_usd
                        + usage['completion_tokens'] * self.a.output_usd) / 1e6
            else:  # ambiguous response: retain its whole reservation as charged, never free it
                cost = reserved
            if not math.isfinite(cost) or cost < 0:
                raise ValueError('invalid usage cost')
            b['settled'] += cost
            b['estimated'] += cost if estimated else 0
            b['settled_calls'] += 1
            b['max_single_call'] = max(b['max_single_call'], cost)
            return cost, estimated, cost > reserved


def peak(now=None):
    now = now or datetime.now(timezone.utc)
    return 'peak' if now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10) else 'off_peak'


class Director(s6.Director):
    def __init__(self, a):
        super().__init__(a)
        self.spend = Spend(a)
        self.adapt = adapt(a)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def upstream(self, body, kind):
        sub = {'kind': kind, 'model': self.a.model, 'marker': s6.marker_state(), 'glm_wait_s': 0,
                   'load': os.getloadavg(), 'window': peak(), 'declared_keys': sorted(self.adapt),
                   'served_provider': None, 'served_model': None, 't_ms': 0, 'ok': False, 'status': 0}
        if self.stopped:
            return dict(sub, category='budget_or_stop', unsent=True)
        wire = {k: v for k, v in body.items() if k not in s6.TRANSPORT_KEYS}
        wire.update(model=self.a.model, stream=False, **self.adapt)
        sub.update(req=self.ledger.blob(wire), wire=wire)
        rid = self.spend.reserve(wire)
        if rid is None:
            self.stopped = True
            return dict(sub, category='spend_cap', unsent=True)
        sub['reservation'] = rid
        t0, resp, status, category, refused = time.monotonic(), {}, -1, None, False
        response_started = False
        try:
            if self.a.mode == 'stub':
                resp = self._stub(wire, kind)['body'] | {'provider': 'DeepSeek', 'model': self.a.model}
                status = 200
            else:
                req = urllib.request.Request(self.url, data=s6.canon(wire), headers={
                    'Content-Type': 'application/json', 'Authorization': f'Bearer {self.key}'})
                try:
                    with self.opener.open(req, timeout=self.a.timeout) as r:
                        response_started, status = True, r.status
                        raw = r.read()
                except urllib.error.HTTPError as e:
                    response_started, status = True, e.code
                    raw = e.read()
                    e.close()
                self.guard.check(raw)
                try:
                    resp = json.loads(raw)
                except ValueError:
                    resp = {}
                if status >= 400:
                    category = s6.refusal_category(status, raw.decode('utf-8', 'replace'))
                    refused = not resp.get('usage')
                elif not resp.get('choices'):
                    category = 'invalid_response'
        except (urllib.error.URLError, ConnectionError) as e:
            category, refused = f'error:{type(e).__name__}', not response_started
        except Exception as e:  # noqa: BLE001 - retain full charge for an ambiguous billed response
            category = f'error:{type(e).__name__}'
        usage = resp.get('usage') or {}
        cost, estimated, over = self.spend.settle(rid, usage, refused)
        provider, model = resp.get('provider'), resp.get('model')
        if 200 <= status < 300 and (str(provider).lower() != self.a.served_provider.lower()
                                     or not str(model).startswith('deepseek/deepseek-v4.1-flash')):
            category = 'pin_failure'
        if over and category != 'pin_failure':
            category = 'reservation_exceeded'
        if category in ('pin_failure', 'reservation_exceeded', 'invalid_response'):
            self.stopped = True
        self._streak(category)
        return dict(sub, status=status, ok=category is None, category=category or '', body=resp,
                    resp=self.ledger.blob(resp), usage=usage, served_provider=provider, served_model=model,
                    cost_usd=cost, cost_estimated=estimated, zero_cost_refusal=refused,
                    t_ms=round((time.monotonic() - t0) * 1000))

    def upstream_retry(self, body, kind, rec):
        """S6a's retry with a configurable hold schedule (--hold-schedule, seconds); each try is counted and the
        held seconds are recorded. The default, 5,15, is S6a's own."""
        held = 0
        for wait in [*self.a.hold_schedule, None]:
            up = self.upstream(body, kind)
            rec["upstream"].append(self._strip(up))
            if up["ok"] or up["category"] not in ("overload", "concurrency", "rate") or wait is None or self.stopped:
                rec["held_s"] = rec.get("held_s", 0) + held
                return up
            time.sleep(wait)
            held += wait

    def write_turn(self, body, turn, rec):
        # S6a readback receives the exact declared additions in its expected harness body.
        out = super().write_turn(body | self.adapt, turn, rec)
        if rec.get('write_turn_readback') is False:
            self.stopped = True
            self.write_failures += 1
            rec['write_turn_failed'] = 'readback_failure'
        return out

    def handle(self, path, body):
        if self.stopped:
            return 503, {'error': 'director stopped'}, {'role': 'aux', 'upstream': []}
        return super().handle(path, body)


def hold_schedule(v):
    """Comma-separated non-negative whole seconds; an empty string means no retries."""
    holds = [int(x) for x in v.split(',')] if v else []
    if any(h < 0 for h in holds):
        raise argparse.ArgumentTypeError('hold durations must be non-negative')
    return holds


def parser():
    p = argparse.ArgumentParser()
    p.add_argument('--spend-file', required=True)
    p.add_argument('--spend-cap-usd', type=float, default=4.0)
    p.add_argument('--input-usd', type=float, default=0.30)
    p.add_argument('--output-usd', type=float, default=1.20)
    p.add_argument('--chars-per-token', type=float, default=4.0)
    p.add_argument('--model', default=MODEL)
    p.add_argument('--provider-only', default='deepseek', help='the router endpoint slug every request is pinned to')
    p.add_argument('--hold-schedule', type=hold_schedule, default=[5, 15],
                   help='seconds to hold before each retry of a refused director-originated call (S6a: 5,15)')
    p.add_argument('--served-provider', default='DeepSeek', help='the provider name every response must report')
    p.add_argument('--mode', choices=['stub', 'live'], default='stub')
    return p


def args(extra=()):
    p = parser()
    for name, default, typ in [('port', 8764, int), ('life', str(LIFE), str), ('ledger-dir', '', str),
                              ('budget-file', '', str), ('budget-cap', 10000, int), ('run', 'write', str),
                              ('context-length', 64000, int), ('timeout', 300, float),
                              ('aliases', 'bicentennial-main,bicentennial-summariser,bicentennial-aux', str)]:
        p.add_argument('--' + name, default=default, type=typ)
    p.add_argument('--write-turns', action='store_true')
    p.add_argument('--measure-overhead', action='store_true')
    a = p.parse_args(extra)
    a.lane_rewrite = ''
    if not all(math.isfinite(x) and x > 0 for x in
               (a.spend_cap_usd, a.input_usd, a.output_usd, a.chars_per_token)) or a.spend_cap_usd > 5:
        p.error('positive finite prices/token ratio and 0 < cap <= 5 required')
    return a


def main():
    a = args(sys.argv[1:])
    if a.mode == 'live' and not all(os.environ.get(k) for k in
                                   ('BICENTENNIAL_UPSTREAM_KEY', 'BICENTENNIAL_UPSTREAM_OPENAI_URL')):
        sys.exit('live mode needs upstream URL and key in environment')
    srv = s6.ThreadingHTTPServer(('127.0.0.1', a.port), s6.make_handler(Director(a)))
    print('S4b director ready', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
