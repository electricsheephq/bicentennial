"""S4b entry points. Replay wraps S6a without executing its upstream helper."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "s6a"))
import analyse as s6analyse
import lane
import ramp as s6ramp
import replay as s6replay


def ramp(d, out):
    levels, state = [], {'quota_streak': 0, 'quota_stop': False}
    for n in (1, 2, 4, 8, 16, 32):
        def call(i):
            u = d.upstream({'messages': [{'role': 'user', 'content': f'Reply with {i}.'}], 'max_tokens': 16}, 'ramp')
            d.ledger.append({'type': 'ramp', 'upstream': [d._strip(u)]})
            return d._strip(u)
        calls = s6ramp.run_level(n, call, lambda: not d.stopped, state)
        refused = sum(not c.get('ok') for c in calls)
        levels.append({'level': n, 'calls': calls, 'refused': refused, 'complete': all(c.get('sent') and not c.get('unsent') for c in calls),
                           'clean': refused == 0})
        if refused or state['quota_stop']:
            break
    result = {'levels': levels, 'sustained_concurrency': max([v['level'] for v in levels if v['clean']] or [0])}
    write(out / 'ramp.json', result)
    return result


def write(path, obj):
    raw = lane.s6.canon(obj)
    lane.s6.Guard().check(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + b'\n')


def replay(a, extra, rest):
    # S6a's driver writes its evidence under S6A_EVIDENCE only, so --out must name that root.
    evid = os.environ.setdefault('S6A_EVIDENCE', a.out)
    if Path(evid).resolve() != Path(a.out).resolve():
        sys.exit('replay --out must equal S6A_EVIDENCE')
    # Replace only the child director command. Hermes workers and all r6 session mechanics stay S6a's.
    real = s6replay.subprocess
    class Processes:
        def __getattr__(self, name):
            return getattr(real, name)

        def Popen(self, cmd, **kw):
            target = str(s6replay.HERE / 'director.py')
            if target in cmd:
                cmd = [x for x in cmd if x != 's4b-direct-launch']
                cmd[cmd.index(target)] = str(Path(lane.__file__))
                cmd += extra
                i = cmd.index('--ledger-dir') + 1
                bulk = Path(os.environ['S6A_SCRATCH']) / 'ledgers' / a.run
                bulk.mkdir(parents=True, exist_ok=True)
                Path(cmd[i]).symlink_to(bulk, target_is_directory=True)
                cmd[i] = str(bulk)
            return real.Popen(cmd, **kw)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['S6A_HELPER'] = 's4b-direct-launch'  # intercepted above; never an executable
    s6replay.subprocess = Processes()
    sys.argv = ['s4b replay', *rest, '--mode', a.mode, '--chars-per-token', str(a.chars_per_token)]
    s6replay.main()


def analyse(a, out):
    rows, led, summ = s6analyse.load(Path(a.evidence), a.run)
    m = s6analyse.run_measures(rows, led, summ)
    ups = [u for r in led for u in r.get('upstream', [])]
    r = json.loads(Path(a.ramp).read_text())
    ups += [c for lv in r['levels'] for c in lv['calls'] ]
    spend = json.loads(Path(a.spend_file).read_text())
    m['complete'] &= (summ.get('director', {}).get('cursor') == 64 and not
                      summ.get('director', {}).get('stopped') and m['write_turn']['readback_ok'] == 60)
    m.update(refusals=dict(Counter(u.get('category') or u.get('reason', 'unsent') for u in ups if not u.get('ok'))),
             served_providers=dict(Counter(str(u.get('served_provider')) for u in ups)),
             served_models=dict(Counter(str(u.get('served_model')) for u in ups)),
             windows=dict(Counter(u.get('window') for u in ups if u.get('window'))),
             reasoning_tokens=sum((u.get('usage') or {}).get('completion_tokens_details', {}).get('reasoning_tokens', 0)
                                  or 0 for u in ups),
             spend=spend | {'estimated_share': spend['estimated']/spend['settled'] if spend['settled'] else 0},
             memory_calls_executed=len({msg['tool_call_id'] for rec in led if rec.get('req')
                 for msg in json.loads(lane.s6.zstd.decompress((Path(a.evidence) / a.run / 'ledger/blobs' /
                     rec['req'][:2] / (rec['req'] + '.json.zst')).read_bytes())).get('messages', [])
                 if msg.get('role') == 'tool' and msg.get('tool_call_id', '').startswith('bcw')}))
    write(out / 'measurements.json', {'runs': {'write': m}, 'ramp': r, 'mode': summ['args']['mode']})
    old = json.loads((lane.LIFE.parent / 'results/measurements.json').read_text())
    print('| Measure | S6a r6 GLM | S4b |\n|---|---:|---:|')
    for keys in [('write_turn', 'latency_s', 'mean'), ('write_turn', 'prompt_tokens', 'mean'),
                 ('summariser', 'latency_s', 'mean'), ('aux', 'latency_s', 'mean'),
                 ('probe', 'latency_s', 'mean'), ('session_total_s', 'mean'), ('write_turn', 'readback_ok')]:
        vals = []
        for obj in (old['runs']['write'], m):
            for k in keys:
                obj = obj.get(k, {})
            vals.append(obj if obj != {} else 'unavailable')
        print(f'| {"/".join(keys)} | {vals[0]} | {vals[1]} |')
    print(f'| clean ramp | {old["ramp"]["sustained_concurrency"]} | {r["sustained_concurrency"]} |')


def dryrun(d, out):
    # No Hermes install is assumed: exercise the full director life in process, including tool results.
    life, memory, n = json.loads(lane.LIFE.read_text()), 0, 0
    for sess in life['sessions'] + life['probes']:
        messages = [{'role': 'system', 'content': 'Synthetic plumbing replay.'}]
        for t in sess['turns']:
            messages.append({'role': 'user', 'content': t['user']})
            body = {'model': 'bicentennial-main', 'messages': messages, 'reasoning_effort': 'medium',
                        'tools': [{'type': 'function', 'function': {'name': 'memory', 'parameters': {'type': 'object'}}}]}
            code, resp, rec = d.handle('/main/v1/chat/completions', body)
            d.ledger.append(dict(type='request', t=time.time(), **rec))
            assert code == 200 and not d.stopped
            msg = resp['choices'][0]['message']
            if msg.get('tool_calls'):
                messages.append(msg)
                for tc in msg['tool_calls']:
                    messages.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': 'stub execution acknowledged'})
                    memory += 1
                code, resp, rec = d.handle('/main/v1/chat/completions', body | {'messages': messages})
                d.ledger.append(dict(type='request', t=time.time(), **rec))
                assert code == 200
            messages.append(resp['choices'][0]['message'])
            n += 1
    write(out / 'summary.json', {'mode': 'stub', 'sessions': 10, 'probe_sessions': 2, 'turns': n,
                                    'cursor': d.cursor, 'simulated_memory_results': memory, 'network_calls': 0,
                                    'hermes_executed': False, 'stopped': d.stopped,
                                    'readback_passes': sum(json.loads(x).get('write_turn_readback', False)
                                        for x in d.ledger.path.read_text().splitlines())})


if __name__ == '__main__':
    op, rest = sys.argv[1], sys.argv[2:]
    p = lane.parser()
    p.add_argument('--out', required=True)
    p.add_argument('--evidence')
    p.add_argument('--ledger-dir')
    p.add_argument('--run', default='write')
    p.add_argument('--ramp')
    a, rest = p.parse_known_args(rest)
    out = Path(a.out)
    extra = ['--spend-file', a.spend_file, '--spend-cap-usd', str(a.spend_cap_usd),
             '--input-usd', str(a.input_usd), '--output-usd', str(a.output_usd), '--model', a.model,
             '--max-output-tokens', str(a.max_output_tokens),
             '--provider-only', a.provider_only, '--served-provider', a.served_provider,
             '--hold-schedule', ','.join(map(str, a.hold_schedule))]
    if op == 'replay':
        replay(a, extra, [*rest, '--run', a.run])
    elif op == 'analyse':
        analyse(a, out)
    else:
        cfg = lane.args([*extra, '--mode', a.mode, '--chars-per-token', str(a.chars_per_token),
                         '--ledger-dir', str(a.ledger_dir or out / 'ledger'), '--write-turns'])
        d = lane.Director(cfg)
        if op == 'dryrun' and a.mode == 'stub':
            dryrun(d, out)
        elif op == 'ramp':
            ramp(d, out)
        else:
            p.error('choose replay, analyse, dryrun (stub only), or ramp')
