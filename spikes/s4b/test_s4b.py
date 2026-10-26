"""Loopback-only acceptance tests; no provider credentials required."""
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import lane
import run


def contend(path, ready, go, results):
    a = lane.args(['--spend-file', path, '--spend-cap-usd', '0.05'])
    ready.put(True)
    go.wait(10)
    results.put(lane.Spend(a).reserve({'messages': [], 'max_tokens': 32768}) is not None)


class TestS4b(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, BICENTENNIAL_UPSTREAM_KEY='synthetic-test-secret',
                              BICENTENNIAL_UPSTREAM_OPENAI_URL='http://127.0.0.1:1')
        self.env.start()
        self.addCleanup(self.env.stop)

    def make(self, *extra):
        return lane.Director(lane.args(['--spend-file', str(self.root / 'spend.json'),
                                       '--ledger-dir', str(self.root / 'ledger'), '--write-turns', *extra]))

    def live(self, response, status=200):
        seen = []
        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw = json.dumps(response).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        os.environ['BICENTENNIAL_UPSTREAM_OPENAI_URL'] = f'http://127.0.0.1:{srv.server_port}'
        return self.make('--mode', 'live'), seen

    def response(self, **kw):
        return {'provider': 'DeepSeek', 'model': lane.MODEL, 'usage': {'prompt_tokens': 100, 'completion_tokens': 5},
                    'choices': [{'message': {'role': 'assistant', 'content': 'none'}, 'finish_reason': 'stop'}]} | kw

    def test_pin_and_readback_and_undeclared_key(self):
        d, seen = self.live(self.response())
        body = {'messages': [{'role': 'user', 'content': d.expected[0]['user']}], 'reasoning_effort': 'medium',
                    'tools': [{'function': {'name': 'memory'}}]}
        rec = {'upstream': []}
        d.write_turn(body, d.expected[0], rec)
        self.assertTrue(rec['write_turn_readback'])
        for kind in ('aux', 'summariser', 'probe', 'ramp'):
            self.assertTrue(d.upstream(body, kind)['ok'])
        self.assertTrue(all(all(b[k] == v for k, v in lane.ADAPT.items()) for b in seen))
        real = d.upstream
        def adulterate(body, kind):
            u = real(body, kind)
            u['wire']['undeclared'] = True
            return u
        d.upstream = adulterate
        rec = {'upstream': []}
        d.write_turn(body, d.expected[0], rec)
        self.assertFalse(rec['write_turn_readback'])
        self.assertTrue(d.stopped)

    def test_wrong_provider_and_model_stop(self):
        for delta in ({'provider': 'Other'}, {'model': 'deepseek/other'}):
            with self.subTest(delta=delta):
                d, seen = self.live(self.response(**delta))
                u = d.upstream({'messages': []}, 'probe')
                self.assertEqual(u['category'], 'pin_failure')
                self.assertTrue(d.stopped)
                self.assertTrue(d.upstream({'messages': []}, 'aux')['unsent'])
                self.assertEqual(len(seen), 1)

    def test_endpoint_pin_flag(self):
        flags = ('--provider-only', 'deepinfra/fp8', '--served-provider', 'DeepInfra')
        for served, ok in (('DeepInfra', True), ('DeepSeek', False)):
            with self.subTest(served=served):
                d, seen = self.live(self.response(provider=served))
                d = self.make('--mode', 'live', *flags)
                body = {'messages': [{'role': 'user', 'content': d.expected[0]['user']}], 'reasoning_effort': 'medium',
                        'tools': [{'function': {'name': 'memory'}}]}
                rec = {'upstream': []}
                d.write_turn(body, d.expected[0], rec)
                self.assertTrue(rec['write_turn_readback'])  # the forwarded body is right either way
                self.assertEqual(rec['upstream'][0]['category'], '' if ok else 'pin_failure')
                self.assertEqual(d.stopped, not ok)
                self.assertTrue(seen and all(b['provider'] == {'only': ['deepinfra/fp8'], 'allow_fallbacks': False}
                                             for b in seen))

    def test_hold_schedule(self):
        d = self.make('--hold-schedule', '5,15,45')
        replies = iter([{'ok': False, 'category': 'overload'}] * 3 + [{'ok': True, 'category': ''}])
        d.upstream = lambda body, kind: next(replies)
        with patch.object(lane.time, 'sleep') as sleep:
            rec = {'upstream': []}
            self.assertTrue(d.upstream_retry({}, 'write_turn', rec)['ok'])
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 15, 45])
        self.assertEqual((len(rec['upstream']), rec['held_s']), (4, 65))
        d = self.make()  # the default is S6a's own 5, 15; a fourth refusal is returned, never slept on
        d.upstream = lambda body, kind: {'ok': False, 'category': 'rate'}
        with patch.object(lane.time, 'sleep') as sleep:
            rec = {'upstream': []}
            self.assertEqual(d.upstream_retry({}, 'aux', rec)['category'], 'rate')
        self.assertEqual(([c.args[0] for c in sleep.call_args_list], len(rec['upstream']), rec['held_s']), ([5, 15], 3, 20))
        d.upstream = lambda body, kind: {'ok': False, 'category': 'auth'}
        with patch.object(lane.time, 'sleep') as sleep:
            d.upstream_retry({}, 'aux', {'upstream': []})
        sleep.assert_not_called()

    def test_reserve_settle_and_refuse_before_send(self):
        d, seen = self.live(self.response(usage={'cost': 0.002}))
        self.assertEqual(d.upstream({'messages': []}, 'aux')['cost_usd'], 0.002)
        d.a.spend_cap_usd = 0.002  # fresh policy/file for the over-cap test
        d.spend.path = self.root / 'small.json'
        self.assertEqual(d.upstream({'messages': []}, 'aux')['category'], 'spend_cap')
        self.assertEqual(len(seen), 1)

    def test_token_estimate_and_failed_refusal(self):
        d, _ = self.live(self.response())
        u = d.upstream({'messages': []}, 'aux')
        self.assertTrue(u['cost_estimated'])
        self.assertAlmostEqual(u['cost_usd'], 0.000036)
        d, _ = self.live({'error': 'refused'}, 429)
        u = d.upstream({'messages': []}, 'aux')
        self.assertEqual((u['cost_usd'], u['zero_cost_refusal']), (0, True))

    def test_two_processes_share_reservation_cap(self):
        ctx = mp.get_context('spawn')
        ready, results, go = ctx.Queue(), ctx.Queue(), ctx.Event()
        ps = [ctx.Process(target=contend, args=(str(self.root / 'race.json'), ready, go, results)) for _ in range(2)]
        for p in ps:
            p.start()
        for _ in ps:
            ready.get(timeout=10)
        go.set()
        self.assertEqual(sorted(results.get(timeout=10) for _ in ps), [False, True])
        for p in ps:
            p.join(10)
            self.assertEqual(p.exitcode, 0)

    def test_full_life_ramp_no_network_or_secret_persistence(self):
        d = self.make()
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')) as net, \
                patch.object(lane.s6, 'marker_state', return_value={'exit': 10, 'glm': True}):
            run.dryrun(d, self.root / 'dry')
            r = run.ramp(d, self.root / 'ramp')
        self.assertEqual(net.call_count, 0)
        self.assertEqual(r['sustained_concurrency'], 32)
        summ = json.loads((self.root / 'dry/summary.json').read_text())
        self.assertEqual(summ['cursor'], 64)
        for path in self.root.rglob('*'):
            if path.is_file():
                raw = path.read_bytes()
                if path.suffix == '.zst':
                    raw = lane.s6.zstd.decompress(raw)
                self.assertNotIn(b'synthetic-test-secret', raw)
        p = subprocess.run([sys.executable, '-B', '-c',
                            "import lane; lane.s6.Guard().check(b'synthetic-test-secret')"],
                           cwd=Path(lane.__file__).parent, capture_output=True, check=False)
        self.assertEqual(p.returncode, 3)
        self.assertNotIn(b'synthetic-test-secret', p.stderr)

    def test_replay_launch_replaces_director_without_helper(self):
        os.environ['S6A_SCRATCH'] = str(self.root)
        target = str(run.s6replay.HERE / 'director.py')
        with patch.object(run.s6replay, 'subprocess', wraps=subprocess), patch.object(subprocess, 'Popen') as popen:
            with patch.object(run.s6replay, 'main', side_effect=lambda: run.s6replay.subprocess.Popen(
                    ['s4b-direct-launch', 'nice', target, '--ledger-dir', str(self.root / 'link')])), \
                    patch.object(sys, 'argv', ['test']):
                run.replay(self.make().a, ['--spend-file', 'shared'], [])
            cmd = popen.call_args.args[0]
            self.assertNotIn('s4b-direct-launch', cmd)
            self.assertIn(str(Path(lane.__file__)), cmd)
            self.assertEqual(cmd[-2:], ['--spend-file', 'shared'])

    def test_peak_boundaries(self):
        for day, hour, expected in [(26, 1, 'peak'), (26, 4, 'off_peak'), (26, 6, 'peak'),
                                    (26, 10, 'off_peak'), (25, 2, 'off_peak')]:
            self.assertEqual(lane.peak(datetime(2026, 10, day, hour, tzinfo=timezone.utc)), expected)


if __name__ == '__main__':
    unittest.main()
