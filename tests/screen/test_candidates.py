"""Screening construction proof; never assert or expose candidate scores."""

import importlib
import json
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial import cue_words
from bicentennial.anchors import report as anchors
from bicentennial.canon import canon
from bicentennial.items import c7
from bicentennial.items.editions import BY_REF, C7_FILES, EDITIONS
from bicentennial.items.templates import g1
from bicentennial.packs import build
from bicentennial.packs.install import install
from bicentennial.runner import t1
from bicentennial.runner.guard import Marker
from bicentennial.runner.units import T2_SPEC
from bicentennial.score.check_selftest import mutant_roles
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.world import targeted
from bicentennial.world.db import open_world

ROOT = Path(__file__).resolve().parents[2]
TEXTS = json.loads(Path(__file__).with_name('texts.json').read_bytes())
def registry_snapshot():
    return ({e: {g: tuple((id(t), asdict(t)) for t in ts) for g, ts in gs.items()}
             for e, gs in EDITIONS.items()}, {r: (id(t), asdict(t)) for r, t in BY_REF.items()}, dict(C7_FILES))


REGISTRIES = registry_snapshot()
from bicentennial.screen import __main__ as command  # noqa: E402
from bicentennial.screen.candidates import CANDIDATES  # noqa: E402


def registries_unchanged():
    assert registry_snapshot() == REGISTRIES


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    out = tmp_path_factory.mktemp('screen-fixture')
    source = (ROOT / 'tiers/life_specs/t2.toml').read_text()
    source = (source[:source.index('[[lives]]')] + '[[lives]]\nlife = "screen-fixture"\ngenre = "G1"\nseed = 4\nreads_session = 1\n'
              + source[source.index('[selection]'):])
    spec = out / 'fixture.toml'
    spec.write_text(source)
    artifact = load(REGISTRY / 'hermes-native.toml')['artifact']
    start = time.monotonic()
    result = build.build_tier('T2', out / 'v2', spec_path=spec, edition=2, harness_artifacts=[artifact])
    elapsed = time.monotonic() - start
    # Timings only: these are not benchmark-quality or candidate scores.
    print(f'fixture one-life full build seconds={elapsed:.3f}')
    (out / 'timing.json').write_text(json.dumps(dict(full_build_ms=round(elapsed * 1000))))
    rel, = result['index']['packs']
    baseline = out / 'v2/T2' / rel
    candidate = build.build_tier('T2', out / 'candidate', spec_path=spec,
                                screening=('drift-config-K1', 0), harness_artifacts=[artifact])
    return SimpleNamespace(out=out, spec=spec, baseline=baseline, rel=rel, result=candidate,
                           candidate=out / 'candidate/T2' / rel, artifact=artifact)


def test_all_card_texts_and_fields_on_same_fixture(fixture):
    pack = t1._pack(fixture.out / 'v2/T2', fixture.rel)
    spec = targeted.load_tier(fixture.spec)
    for card, variants in CANDIDATES.items():
        assert len(variants) == 4
        v2 = BY_REF[variants[0].template_id + '-v2']
        records = [r for r in pack.records.values() if r['template_id'] == v2.template_id]
        assert len(records) == 2
        for record in records:
            item = next(i for i in pack.pack['items'] if i['item_id'] == record['item_id'])
            checkpoint = item['probe_point']
            with closing(open_world(pack.life_dir / f"world.{record['branch']}.db", readonly=True)) as db:
                original, = replace(v2, checkpoint=checkpoint).instances(db, pack.schedule)
                for v, template in enumerate(variants):
                    a, = targeted.repoint_templates(spec, (replace(template, checkpoint=checkpoint),))
                    built, = a.instances(db, pack.schedule)
                    assert built.prompt.encode() == TEXTS[card][v].encode()
                    assert asdict(replace(built, prompt=original.prompt,
                                          decision_table_ref=original.decision_table_ref)) == asdict(original)
                    assert built.decision_table_ref == original.decision_table_ref.removesuffix('-v2') + '-v3'
                    assert a.BINDING_FIELDS == v2.BINDING_FIELDS
                    entry = c7.entry(template, 'g1', c7.cells(ROOT))
                    assert {p for p in entry['source_sha256'] if p.startswith('screen/candidates/')} == {
                        f'screen/candidates/{card.lower().replace("-", "_")}.py'}
    registries_unchanged()


def test_prompt_lint_and_fault_constraint(capsys):
    requests = cue_words.template_requests(ROOT / 'src/bicentennial/screen/candidates')
    assert len(requests) == 28 and not cue_words.check_requests(requests)
    assert cue_words.main([]) == 0
    assert not capsys.readouterr().out
    for variants in CANDIDATES.values():
        for template in variants:
            if template.template_id == 'drift-chain-fault':
                with pytest.raises(ValueError):
                    replace(template, fault=False)
    for tid, roles in mutant_roles().items():
        if tid.endswith('-v3'):
            assert roles == g1.G1_MUTANT_ROLES[tid.removesuffix('-v3') + '-v2']


def test_isolation(fixture):
    registries_unchanged()
    marking = dict(card='drift-config-K1', variant=0)
    assert fixture.result['index']['screening_only'] == marking
    assert anchors.load(fixture.candidate / 'manifest.json')['screening_only'] == marking
    a, b = fixture.baseline, fixture.candidate
    files = {p.relative_to(a).as_posix() for p in a.rglob('*') if p.is_file()}
    assert files == {p.relative_to(b).as_posix() for p in b.rglob('*') if p.is_file()}
    changed = {p for p in files if (a / p).read_bytes() != (b / p).read_bytes()}
    assert changed == {'manifest.json', 'sealed/pack.json', 'sealed/scoring.json', 'sealed/records.json',
                       'sealed/reader_keys.jsonl', 'sealed/controls.json', 'sealed/naive_rag.json',
                       'sealed/build_log.json', 'build_receipt.json', 'sealed/meta.json',
                       'sealed/life/items.B0.json', 'sealed/life/items.B1.json'}
    for name in ('sealed/records.json', 'sealed/life/items.B0.json', 'sealed/life/items.B1.json'):
        def other(path, name=name):
            rows = anchors.load(path)
            if name.endswith('records.json'):
                return [{k: v for k, v in r.items() if k != 'unfiltered_sample'}
                        for r in rows if r['template_id'] != 'drift-config']
            ids = {r['item_id'] for r in anchors.load(path.parents[1] / 'records.json')
                   if r['template_id'] != 'drift-config'}
            return [r for r in rows if r['item_id'] in ids]
        assert other(a / name) == other(b / name)
    assert all('screening_only' not in anchors.load(a / p) for p in ('manifest.json', 'sealed/pack.json'))


@pytest.mark.parametrize('control', [False, True])
def test_prepare_refuses_screening_as_c7_changed(fixture, tmp_path, monkeypatch, control):
    digest = install(fixture.out / 'candidate/T2', tmp_path / 'installed')
    entry = load(REGISTRY / 'hermes-native.toml')
    entry['artifact']['sha256'] = '1' * 64
    entry['fresh_install_hash'] = '1' * 64
    monkeypatch.setattr(t1, 'read_marker', lambda: Marker(0, False, 'fixture'))
    monkeypatch.setattr(t1, 'worker_properties', lambda *a: ())
    try:
        # The v3 ref now exists, but screening entries are not the registered entry.
        with pytest.raises(t1.T1Refused, match='^c7_changed$'):
            t1.prepare(system='hermes-native', entry=entry, worker_argv=['fixture'],
                       packs=tmp_path / 'installed', pack_hash=digest, control=control,
                       spec=replace(T2_SPEC, composition=('G1',)))
    finally:
        for path in (tmp_path / 'installed').rglob('*'):
            path.chmod(path.stat().st_mode | 0o200)
        (tmp_path / 'installed').chmod(0o755)


def test_command_shapes_and_safe_stdout(fixture, tmp_path, capsys):
    out = tmp_path / 'command'
    assert command.main(['--spec', str(fixture.spec), '--out', str(out),
                         '--cards', 'drift-config-K1', '--variants', '0']) == 0
    captured = capsys.readouterr().out
    # Do not put captured stdout or the report in an assertion's diagnostic output.
    data = anchors.load(out / 'report.json')
    card = data['cards']['drift-config-K1']
    variant = card['variants']['0']
    assert isinstance(variant['placement_succeeded'], bool)
    assert set(variant['rows']) == {'naive_rag', *anchors.ANCHORS, 'oracle_evidence',
                                   *command.POLICIES, *command.HEURISTICS}
    assert len(variant['items']) == 2 and len(variant['pairs']) == 1
    assert all(i['item_id'] not in captured for i in variant['items'])
    assert all(set(i) >= {'item_id', 'anchors', 'vocabulary', 'oracle_evidence', 'battery'}
               for i in variant['items'])
    assert all(set(row) == {'pairs', 'right', 'confidently_wrong', 'no_credit',
                            'net_pair_points_milli', 'net_pair_score'} for row in variant['rows'].values())
    assert all(set(v) == {'visible_events', 'oracle_span'} for i in variant['items']
               for v in i['vocabulary'].values())
    assert all(text not in captured for text in TEXTS['drift-config-K1'])
    assert (out / 'report.json').read_bytes() == canon(data) + b'\n'
    assert card['header']['variant_texts'] == TEXTS['drift-config-K1']
    assert all(len(data['header'][k]) == n for k, n in (('spec_sha256', 64), ('base_commit', 40)))
    assert len(card['header']['module_sha256']) == 64
    split = canon(dict(rows=[dict(item_id=variant['items'][0]['item_id'])]))
    # A supplied selection is read as given, including one at the path a run without a
    # selection writes to: it is refused, never overwritten.
    for tasks in (tmp_path / 'split.json', out / 'drift-config-K1/0/tasks.json'):
        tasks.write_bytes(split)
        with pytest.raises(ValueError, match='splits a pair'):
            command.evaluate(out / 'drift-config-K1/0/T2', CANDIDATES['drift-config-K1'][0], tasks)
        assert tasks.read_bytes() == split
    registries_unchanged()


def test_screening_output_and_selection_refusals(tmp_path):
    for selection in [('missing', 0), ('drift-config-K1', 4)]:
        with pytest.raises(ValueError, match='screening candidate'):
            build.build_tier('T2', tmp_path, screening=selection, harness_artifacts=[])
    with pytest.raises(ValueError, match='screening output'):
        build.build_tier('T2', ROOT / 'packs/forbidden', screening=('drift-config-K1', 0), harness_artifacts=[])
    with pytest.raises(SystemExit):
        command.main(['--spec', 'unused', '--out', str(tmp_path / 'command'), '--variants', '4'])


def test_anchor_header_uses_shared_constants(monkeypatch):
    monkeypatch.setattr(anchors, 'WINDOW', 123)
    monkeypatch.setattr(anchors, 'SENSITIVITY_WINDOWS', (45, 67))
    assert anchors.header()['window'] == 123
    assert anchors.header()['sensitivity_windows'] == [45, 67]


def test_registry_import_stays_isolated():
    registries_unchanged()
    importlib.reload(sys.modules['bicentennial.screen.candidates'])
    registries_unchanged()


# The public T2 packs as `main` builds them from a clean tree with no screening code (99fdadc and 0928685), per
# SQLite build. The packs hold SQLite world databases, and a library that turns secure_delete on by default (Ubuntu's,
# which CI's Python links) zeroes freed space inside their pages, so their bytes and hash differ (#327,
# docs/developers/ring0.md section 4). The values for "on" were built on `main` with secure_delete turned on for every
# connection, which reproduces the hash CI's Python builds. Edition 1's hash with it off is also the pack hash of the
# published 2026-11-04 live-arm result. A build with another default fails until its hashes are captured on `main`.
PUBLIC_T2_HASHES = {
    0: {1: '15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04',  # off (macOS and uv's Python)
        2: '3e58b80124568d1fd275e608a17b2c145531b2619d1d2155ee32aed71c23658d'},
    1: {1: 'dd1ed4aaecd6890ea6da14ed841acab47c53ffe2404da3304d4210b866439a22',  # on (Ubuntu's SQLite)
        2: 'f4ec2417b6634823f2522dd9dd463d0d3c7e929f03b5d5e46d272dc95a49ee76'},
}


def test_public_t2_hashes_equal_base(tmp_path):
    with closing(sqlite3.connect(':memory:')) as db:
        secure_delete = db.execute('PRAGMA secure_delete').fetchone()[0]
    assert secure_delete in PUBLIC_T2_HASHES, f'no hashes captured on main for secure_delete={secure_delete}'
    artifact = load(REGISTRY / 'hermes-native.toml')['artifact']
    for edition, expected in PUBLIC_T2_HASHES[secure_delete].items():
        built = build.build_tier('T2', tmp_path / f'edition-{edition}', edition=edition,
                                 harness_artifacts=[artifact])
        assert built['pack_hash'] == expected, f'edition {edition}'


def test_gate_on_synthetic_rows_only():
    rows = {n: command.counts([0]) for n in ('naive_rag', *anchors.ANCHORS,
                                            'oracle_evidence', *command.POLICIES)}
    rows['oracle_evidence'] = command.counts([1000])
    variants = {str(v): dict(placement_succeeded=True, rows=rows.copy()) for v in range(4)}
    assert command.verdict(variants) == dict(passes_gate=True, reasons=[])
    assert not command.verdict({'0': variants['0']})['passes_gate']
    for name, value in [('oracle_evidence', 999), ('bm25', 351), (command.POLICIES[0], 1)]:
        modified = {**variants, '3': dict(placement_succeeded=True,
                                        rows={**rows, name: command.counts([value])})}
        assert not command.verdict(modified)['passes_gate']
    variants['3']['rows']['bm25'] = command.counts([350])
    assert command.verdict(variants)['passes_gate']
    variants['3'] = dict(placement_succeeded=False)
    assert not command.verdict(variants)['passes_gate']


def test_refusals_stay_per_variant_and_finished_cards_are_kept(tmp_path, monkeypatch):
    rows = {n: command.counts([0]) for n in ('naive_rag', *anchors.ANCHORS, *command.POLICIES, *command.HEURISTICS)}
    rows['oracle_evidence'] = command.counts([1000])

    def fake_build(tier, dest, *, harness_artifacts, spec_path, screening):
        if screening == ('drift-config-K1', 0):
            raise build.PackRefused('controls')
        dest.mkdir(parents=True)

    def fake_evaluate(root, template, tasks=None):
        if template is CANDIDATES['drift-config-K1'][2]:
            raise ValueError('no scored candidate pairs')
        if template is CANDIDATES['drift-quote-K1'][0]:
            raise KeyError('a defect, not a refusal')
        return dict(items=[], pairs=[], rows=rows)

    monkeypatch.setattr(command, 'build_tier', fake_build)
    monkeypatch.setattr(command, 'evaluate', fake_evaluate)
    out = tmp_path / 'out'
    with pytest.raises(KeyError):
        command.main(['--spec', str(ROOT / 'tiers/life_specs/t2.toml'), '--out', str(out),
                      '--cards', 'drift-config-K1,drift-quote-K1'])
    data = json.loads((out / 'report.json').read_bytes())
    assert list(data['cards']) == ['drift-config-K1']
    card = data['cards']['drift-config-K1']
    assert card['variants']['0'] == dict(stage='build', refusal='PackRefused: controls')
    assert card['variants']['2'] == dict(placement_succeeded=True, stage='evaluate',
                                         refusal='ValueError: no scored candidate pairs')
    assert all(card['variants'][v]['rows'] == rows for v in ('1', '3'))
    assert card['verdict'] == dict(passes_gate=False, reasons=['variant 0: refused', 'variant 2: refused'])
    assert not (out / 'report.json.part').exists()
