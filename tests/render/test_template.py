"""G08 acceptance: the phrase-bank grid, the slot trace, locked tokens, dates, stamps and purity."""

import json
import os
import re
import subprocess
import sys
import unicodedata
from itertools import count, product
from pathlib import Path

import pytest

from bicentennial.contracts.run import validate
from bicentennial.render import (
    channel_stamp,
    default_bank,
    load,
    relative_date,
    render_event,
)
from bicentennial.render.phrasebank import (
    BANDS,
    MARKERS,
    MODALITIES,
    POLARITIES,
    SLOT,
    SPEECH_ACTS,
    band,
)
from bicentennial.world import create_world, open_world, world_hash
from bicentennial.world import db as writers

ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = ROOT / 'src/bicentennial/render/phrasebank/en.toml'
META = dict(generator_version='g08', genre='software-partner', seed='g08-render', scale=1)
LIFE = 'b0'
NY, PARIS = 'America/New_York', 'Europe/Paris'
CELLS = list(product(SPEECH_ACTS, MODALITIES, BANDS, POLARITIES))
CANARY = 'c168e5f8-3948-4553-8554-7aa162054723'


def entity(db, id, name):
    writers.insert_entity(db, id=id, kind='person', canonical_name=name, aliases_json=[],
                          created_t=0, retired_t=None)


def event(db, id, t, channel='chat', actor='ent'):
    writers.insert_event(db, id=id, t_sim=t, kind='turn', channel=channel, actor_id=actor,
                         audience_json=['agent'], visibility='shared', salience=500, payload_json={})


def fact(db, id, subject='ent', predicate='seat_choice', obj='x', polarity='affirm',
         modality='stated', strength=1000, speech_act='assert', tokens=()):
    writers.insert_fact(db, id=id, subject_id=subject, predicate=predicate, object=obj,
                        polarity=polarity, modality=modality, strength=strength, speech_act=speech_act)
    for i, value in enumerate(tokens):
        writers.insert_locked_token(db, token_id=f'{id}-tok{i}', fact_id=id, kind='code', value=value)


def link(db, event_id, fact_id, role='assert'):
    writers.insert_link(db, event_id=event_id, fact_id=fact_id, role=role)


def build_cells(path, plant_as_stated=False):
    db = create_world(path, META)
    entity(db, 'ent', 'Rin Okafor')
    for n, (act, modality, band_, polarity) in enumerate(CELLS):
        event(db, f'ev-{n:03d}', 1700000001 + n)
        if plant_as_stated and modality == 'planted':
            modality = 'stated'
        fact(db, f'fa-{n:03d}', polarity=polarity, modality=modality, speech_act=act,
             strength=1000 if band_ == 'hard' else 500, tokens=[f'TOK-{n:03d}'])
        link(db, f'ev-{n:03d}', f'fa-{n:03d}')
    event(db, 'ev-claim', 1700000999)
    fact(db, 'fa-claim', speech_act='claim', tokens=['TOK-CLAIM'])
    link(db, 'ev-claim', 'fa-claim')
    db.commit()
    return db


def build_mixed(path, new_value='PROD-WEST-2', plant_modality='planted'):
    t = 1793503800  # America/New_York, the evening before the 2026 fall-back
    db = create_world(path, META)
    entity(db, 'ent', 'Ana Weber')
    entity(db, 'p2', 'Bo Lindqvist')
    fact(db, 'f-old', predicate='deploy_target', obj='staging-east')
    fact(db, 'f-new', predicate='deploy_target', obj=None, tokens=[new_value])
    fact(db, 'f-commit', subject='p2', predicate='review_meeting', speech_act='propose', strength=700,
         tokens=['RVW-5521'])
    fact(db, 'f-hedge', subject='p2', predicate='seat', obj='aisle seat', speech_act='hedge', strength=400)
    fact(db, 'f-plant', predicate='favorite_editor', modality=plant_modality, tokens=['HELIX-9081'])
    fact(db, 'f-obs', subject='p2', predicate='build_status', modality='observed', tokens=['BUILD-3317'])
    fact(db, 'f-quote', predicate='budget', speech_act='quote', polarity='negate', tokens=['EUR-12500'])
    for i, (id, channel, links) in enumerate([
            ('ev-intro', 'chat', [('f-old', 'assert')]),
            ('ev-correction', 'chat', [('f-new', 'assert'), ('f-old', 'retract')]),
            ('ev-commit', 'chat', [('f-commit', 'assert')]),
            ('ev-factless', 'chat', []),
            ('ev-forget', 'chat', []),
            ('ev-mail', 'mail', [('f-quote', 'mention'), ('f-hedge', 'assert')]),
            ('ev-none', 'commit', [('f-obs', 'assert')]),
            ('ev-log', 'ci_log', [('f-obs', 'mention')]),
            ('ev-plant', 'chat', [('f-plant', 'assert')]),
            ('ev-again', 'review_comment', [('f-new', 'mention'), ('f-commit', 'mention')])]):
        event(db, id, t + 600 * i, channel, 'p2' if i % 2 else 'ent')
        for fact_id, role in links:
            link(db, id, fact_id, role)
    writers.insert_commitment(db, fact_id='f-commit', trigger_kind='time', window_open_t=1793590200,
                              window_close_t=1793593800, lures_json=['early'])
    writers.insert_plant(db, fact_id='f-plant', carrier_event_id='ev-plant', kind='source')
    writers.insert_forget_request(db, event_id='ev-forget', covered_fact_ids_json=['f-hedge'])
    db.commit()
    return db


def events(db):
    return [row['id'] for row in db.execute('SELECT id FROM event ORDER BY id')]


def segments(r, stamp):
    """The literal text: the render with its stamp and slot spans removed."""
    assert r.text.startswith(stamp)
    cuts = [len(stamp)] + [x for s in r.slots for x in (s.start, s.end)] + [len(r.text)]
    return [r.text[a:b].casefold() for a, b in zip(cuts[::2], cuts[1::2], strict=True)]


def marked(parts, kind):
    return any(re.search(r'(?<!\w)' + re.escape(m) + r'(?!\w)', p) for m in MARKERS[kind] for p in parts)


def phrases(bank):
    every = [p for cell in bank.cells.values() for p in cell] + list(bank.factless) + [bank.when]
    return {p.phrase_id: p.text for p in every}


def check_trace(db, r, tz, bank=None):
    bank = bank or default_bank()
    ev = db.execute('SELECT t_sim, channel FROM event WHERE id = ?', (r.event_id,)).fetchone()
    for s in r.slots:
        assert s.fact_id in r.fact_ids
        f = db.execute('SELECT * FROM fact WHERE id = ?', (s.fact_id,)).fetchone()
        value = r.text[s.start:s.end]
        if s.token_id is not None:
            token = db.execute('SELECT * FROM locked_token WHERE token_id = ?', (s.token_id,)).fetchone()
            assert s.name == 'object' and token['fact_id'] == s.fact_id and value == token['value']
        elif s.name == 'object':
            assert value == json.loads(f['object'])
        elif s.name == 'subject':
            assert value == db.execute('SELECT canonical_name FROM entity WHERE id = ?',
                                       (f['subject_id'],)).fetchone()[0]
        elif s.name == 'predicate':
            assert value == f['predicate'].replace('_', ' ')
        else:
            c = db.execute('SELECT * FROM commitment WHERE fact_id = ?', (s.fact_id,)).fetchone()
            assert s.name == 'when' and c['trigger_kind'] == 'time'
            assert value == relative_date(ev['t_sim'], c['window_open_t'], tz)
    # Substituting the slot values into the named phrases reproduces the text byte-for-byte.
    bank_id, ids = r.template_id.split(':', 1)
    assert bank_id == bank.bank_id
    values = iter(r.slots)
    filled = []
    for text in map(phrases(bank).__getitem__, ids.split('+')):
        parts = SLOT.split(text)
        for i in range(1, len(parts), 2):
            s = next(values)
            assert s.name == parts[i]
            parts[i] = r.text[s.start:s.end]
        filled.append(''.join(parts))
    assert next(values, None) is None
    style = bank.channels[ev['channel']]
    stamp = channel_stamp(ev['t_sim'], tz, style)
    body = ' '.join(filled)
    assert r.text == {'none': body, 'mail': f'{stamp}\n\n{body}'}.get(style, f'{stamp} {body}')


def test_band_and_cell_api():
    assert (band(0), band(999), band(1000)) == ('soft', 'soft', 'hard')
    for bad in (-1, 1001, True, 500.0, '1000'):
        with pytest.raises(ValueError):
            band(bad)
    bank = default_bank()
    assert bank.cell('hedge', 'planted', 3, 'negate') is bank.cell('hedge', 'stated', 3, 'negate')
    for args in (('claim', 'stated', 1, 'affirm'), ('assert', 'inferred_allowed', 1, 'affirm'),
                 ('assert', 'stated', 1, 'maybe'), ('assert', 'guessed', 1, 'affirm')):
        with pytest.raises(ValueError):
            bank.cell(*args)


def test_cell_table_all_80(tmp_path):
    db = build_cells(tmp_path / 'a.sqlite')
    twin = build_cells(tmp_path / 'b.sqlite', plant_as_stated=True)
    assert len(CELLS) == 80
    rendered = 0
    for n, (act, modality, band_, polarity) in enumerate(CELLS):
        if modality == 'inferred_allowed':
            with pytest.raises(ValueError):
                render_event(db, f'ev-{n:03d}', life=LIFE, tz=PARIS)
            continue
        r = render_event(db, f'ev-{n:03d}', life=LIFE, tz=PARIS)
        own = 'stated' if modality == 'planted' else modality
        assert r.template_id.startswith(f'en-v1:{act}.{own}.{band_}.{polarity}#')
        assert f'TOK-{n:03d}' in r.text and r.gold_critical and r.fact_ids == (f'fa-{n:03d}',)
        assert (r.lane, r.voice) == ('template', 'template')
        check_trace(db, r, PARIS)
        parts = segments(r, channel_stamp(1700000001 + n, PARIS, 'chat'))
        if act in ('hedge', 'propose'):
            assert marked(parts, act) and not marked(parts, 'assert')
        if act == 'quote':
            assert marked(parts, 'quote')
        if act == 'assert':
            assert not marked(parts, 'hedge') and not marked(parts, 'propose')
        if band_ == 'soft':
            assert not marked(parts, 'assert')
        if modality == 'planted':
            t = render_event(twin, f'ev-{n:03d}', life=LIFE, tz=PARIS)
            assert (t.text, t.template_id) == (r.text, r.template_id)
        rendered += 1
    assert rendered == 64
    with pytest.raises(ValueError, match='no phrase cell'):
        render_event(db, 'ev-claim', life=LIFE, tz=PARIS)


def _lines_without(source, header):
    lines = source.splitlines(keepends=True)
    i = lines.index(header + '\n')
    return ''.join(lines[:i] + lines[i + 3:])


REFUSALS = {
    'hedge from now on': lambda s: s.replace('"Maybe the {predicate} for {subject} is {object}."',
                                             '"Maybe the {predicate} for {subject} is {object} from now on."'),
    'missing cell': lambda s: _lines_without(s, '[cells.quote.retracted.hard]'),
    'extra planted cell': lambda s: s + '[cells.assert.planted.soft]\naffirm = ["{object}."]\nnegate = ["{object}."]\n',
    'two objects': lambda s: s.replace('"{subject} said the {predicate} is {object}."',
                                       '"{subject} said the {predicate} is {object} or {object}."'),
    'non-NFC': lambda s: s.replace('"Thanks, noted."', '"Thanks, note\u0301d."'),
    'stray slot': lambda s: s.replace('"Sounds good."', '"Sounds {x} good."'),
    'altered markers': lambda s: s.replace('"for sure", ', ''),
    'empty list': lambda s: s.replace('factless = [', 'factless = [] #'),
    'bad style': lambda s: s.replace('ci_log = "log"', 'ci_log = "syslog"'),
    'extra key': lambda s: s.replace('calibrated = false', 'calibrated = false\nextra = 1'),
    'no subject': lambda s: s.replace('"{subject} said the {predicate} is {object}."', '"Said the {predicate} is {object}."'),
    'missing channel': lambda s: s.replace('tracker = "none"\n', ''),
    'when in a cell': lambda s: s.replace('"{subject} wrote: the {predicate} is {object}."',
                                          '"{subject} wrote: the {predicate} is {object} {when}."'),
    'soft assert marker': lambda s: s.replace('"The {predicate} for {subject} is {object}."',
                                              '"The {predicate} for {subject} is always {object}."'),
    'marker in when': lambda s: s.replace('"Due {when}."', '"Maybe due {when}."'),
}


@pytest.mark.parametrize('name', sorted(REFUSALS))
def test_loader_refusals(tmp_path, name):
    source = BANK_PATH.read_text(encoding='utf-8')
    variant = REFUSALS[name](source)
    assert variant != source
    path = tmp_path / 'variant.toml'
    path.write_text(variant, encoding='utf-8')
    with pytest.raises(ValueError):
        load(path)


def test_shipped_bank_loads(tmp_path):
    bank = load()
    assert bank.calibrated is False and bank.bank_id == 'en-v1' and len(bank.cells) == 48
    assert all(bank.cells.values()) and bank == default_bank()
    copy = tmp_path / 'copy.toml'
    copy.write_bytes(BANK_PATH.read_bytes())
    assert load(copy).sha256 == bank.sha256
    assert len(BANK_PATH.read_text().splitlines()) <= 260


def test_mixed_world_trace(tmp_path):
    db = build_mixed(tmp_path / 'm.sqlite')
    renders = {e: render_event(db, e, life=LIFE, tz=NY) for e in events(db)}
    for r in renders.values():
        check_trace(db, r, NY)
    correction = renders['ev-correction']
    assert correction.fact_ids == ('f-old', 'f-new')
    assert correction.template_id.split(':')[1].split('+')[0].startswith('assert.retracted.hard.affirm#')
    commit = renders['ev-commit']
    assert [s.name for s in commit.slots][-1] == 'when' and commit.template_id.endswith('+when')
    assert renders['ev-factless'].slots == () and renders['ev-factless'].fact_ids == ()
    assert renders['ev-mail'].text.startswith('Date: ') and '\n\n' in renders['ev-mail'].text
    assert renders['ev-mail'].fact_ids == ('f-hedge', 'f-quote')
    assert not renders['ev-none'].text.startswith(('[', 'Date')) and renders['ev-log'].text.startswith('2026-')
    gold = {e for e, r in renders.items() if r.gold_critical}
    assert gold == set(renders) - {'ev-intro', 'ev-factless'}
    assert renders['ev-again'].stream_render() == {'lane': 'template', 'voice': 'template',
                                                   'template_id': renders['ev-again'].template_id}


WORLDS = count()


def mini(tmp_path, tokens=(), obj='x', name='Rin Okafor', extra=None):
    db = create_world(tmp_path / f'mini-{next(WORLDS)}.sqlite', META)
    entity(db, 'ent', name)
    event(db, 'ev', 1700000001)
    fact(db, 'fa', obj=obj, tokens=tokens)
    link(db, 'ev', 'fa')
    if extra:
        extra(db)
    db.commit()
    return db


def test_locked_tokens(tmp_path):
    nfc = 'Zo\u00eb-4410'
    r = render_event(mini(tmp_path, [nfc]), 'ev', life=LIFE, tz=PARIS)
    obj = [s for s in r.slots if s.name == 'object'][0]
    assert r.text[obj.start:obj.end] == nfc and obj.token_id == 'fa-tok0'
    db = mini(tmp_path, ['ABC-{object}-77'])
    r = render_event(db, 'ev', life=LIFE, tz=PARIS)
    assert 'ABC-{object}-77' in r.text
    check_trace(db, r, PARIS)

    def unlinked(db):
        fact(db, 'other', tokens=['Kai-9090'])
    for match, case in (('not NFC', dict(tokens=['Zoe\u0308-4410'])),
                        ('more than one', dict(tokens=['TWO-0001', 'TWO-0002'])),
                        ('non-string object', dict(obj=42)),
                        ('unlinked', dict(name='Kai-9090', extra=unlinked)),
                        ('canary', dict(obj=f'see {CANARY}'))):
        db = mini(tmp_path, **case)
        with pytest.raises(ValueError, match=match):
            render_event(db, 'ev', life=LIFE, tz=PARIS)
    assert unicodedata.normalize('NFC', 'Zoe\u0308-4410') == nfc


GOLDEN_DATES = [
    (PARIS, 1792877400, 1792963800, 'tomorrow'), (PARIS, 1792794600, 1792967400, 'tomorrow'),
    (PARIS, 1792881000, 1792967400, 'today'), (PARIS, 1774737000, 1774823400, 'on Monday'),
    (NY, 1793503800, 1793590200, 'tomorrow'), (NY, 1793507400, 1793592000, 'today'),
    (PARIS, 1793507400, 1793592000, 'tomorrow'), (NY, 1772944200, 1773030600, 'on Monday'),
    (PARIS, 1772944200, 1773030600, 'tomorrow'), (PARIS, 1793012400, 1793358000, 'on Friday'),
    (PARIS, 1793012400, 1793617200, 'next Monday'), (PARIS, 1793012400, 1793703600, 'next Tuesday'),
    (PARIS, 1793012400, 1794135600, 'next Sunday'), (PARIS, 1793012400, 1794222000, 'in 14 days'),
    (PARIS, 1793012400, 1794740400, 'in 20 days'), (PARIS, 1793012400, 1792926000, 'yesterday'),
    (PARIS, 1793012400, 1792753200, 'last Friday'), (PARIS, 1793012400, 1792494000, 'last Tuesday'),
    (PARIS, 1793012400, 1792407600, '7 days ago'), (PARIS, 1793012400, 1791716400, '15 days ago'),
]
GOLDEN_STAMPS = [
    (NY, 1793511000, '[2026-11-01 01:30 -0400]', 'Date: Sun, 01 Nov 2026 01:30:00 -0400', '2026-11-01T01:30:00-04:00'),
    (NY, 1793514600, '[2026-11-01 01:30 -0500]', 'Date: Sun, 01 Nov 2026 01:30:00 -0500', '2026-11-01T01:30:00-05:00'),
    (PARIS, 1792888200, '[2026-10-25 02:30 +0200]', 'Date: Sun, 25 Oct 2026 02:30:00 +0200', '2026-10-25T02:30:00+02:00'),
    (PARIS, 1792891800, '[2026-10-25 02:30 +0100]', 'Date: Sun, 25 Oct 2026 02:30:00 +0100', '2026-10-25T02:30:00+01:00'),
    (PARIS, 1700000001, '[2023-11-14 23:13 +0100]', 'Date: Tue, 14 Nov 2023 23:13:21 +0100', '2023-11-14T23:13:21+01:00'),
]


@pytest.mark.parametrize('row', range(1, 21))
def test_relative_date_golden(row):
    tz, anchor, target, expected = GOLDEN_DATES[row - 1]
    assert relative_date(anchor, target, tz) == expected


@pytest.mark.parametrize('tz,t,chat,mail,log', GOLDEN_STAMPS)
def test_channel_stamp_golden(tz, t, chat, mail, log):
    assert [channel_stamp(t, tz, s) for s in ('chat', 'mail', 'log', 'none')] == [chat, mail, log, '']


def test_date_refusals():
    for args in ((0, 0, 'europe/paris'), (True, 0, PARIS), (0, 1.0, PARIS), (0, 0, 'Mars/Olympus')):
        with pytest.raises(ValueError):
            relative_date(*args)
    for args in ((0, 'europe/paris', 'chat'), (False, PARIS, 'chat'), (0, PARIS, 'syslog')):
        with pytest.raises(ValueError):
            channel_stamp(*args)


def test_render_refusals(tmp_path):
    db = mini(tmp_path, ['GOOD-0001'])
    with pytest.raises(ValueError):
        render_event(db, 'ev', life=LIFE, tz='europe/paris')
    with pytest.raises(ValueError):
        render_event(db, 'missing', life=LIFE, tz=PARIS)
    odd = mini(tmp_path, ['GOOD-0002'], extra=lambda db: event(db, 'ev-odd', 1, 'pager'))
    with pytest.raises(ValueError, match='unknown channel'):
        render_event(odd, 'ev-odd', life=LIFE, tz=PARIS)


def test_commitment_across_fall_back(tmp_path):
    db = create_world(tmp_path / 'c.sqlite', META)
    entity(db, 'ent', 'Rin Okafor')
    event(db, 'ev', 1793503800)
    fact(db, 'fa', tokens=['MEET-0042'])
    link(db, 'ev', 'fa')
    writers.insert_commitment(db, fact_id='fa', trigger_kind='time', window_open_t=1793590200,
                              window_close_t=1793593800, lures_json=[])
    db.commit()
    r = render_event(db, 'ev', life=LIFE, tz=NY)
    (when,) = [s for s in r.slots if s.name == 'when']
    assert r.text[when.start:when.end] == 'tomorrow' and when.fact_id == 'fa'


def test_k12_agreement(tmp_path):
    fixture = json.loads((ROOT / 'schemas/fixtures/gen/world.json').read_bytes())
    db = create_world(tmp_path / 'k12.sqlite', META)
    for table in ('entity', 'event', 'attr', 'fact', 'link', 'lineage'):
        for row in fixture[table]:
            getattr(writers, f'insert_{table}')(db, **row)
    db.commit()
    (ev,), (f,) = fixture['event'], fixture['fact']
    r = render_event(db, ev['id'], life=LIFE, tz=PARIS)
    assert r.text.startswith('[2023-11-14 23:13 +0100] ')
    (obj,) = [s for s in r.slots if s.name == 'object']
    assert r.text[obj.start:obj.end] == 'WINDOW-7401' and obj.fact_id == f['id'] and obj.token_id is None
    check_trace(db, r, PARIS)
    stream = json.loads((ROOT / 'schemas/fixtures/gen/contracts.json').read_bytes())['contracts']['stream']
    stream.update(text=r.text, render=r.stream_render(), fact_ids=list(r.fact_ids),
                  gold_critical=r.gold_critical, tz=PARIS)
    validate('stream', stream)


def comparable(db):
    return {e: (r.text, r.template_id, r.slots) for e in events(db)
            for r in [render_event(db, e, life=LIFE, tz=NY)]}


def test_value_flip_changes_only_linked_events(tmp_path):
    base = comparable(build_mixed(tmp_path / 'a.sqlite'))
    flipped = comparable(build_mixed(tmp_path / 'b.sqlite', new_value='PROD-WEST-9'))
    assert {e for e in base if base[e] != flipped[e]} == {'ev-correction', 'ev-again'}
    for e in ('ev-correction', 'ev-again'):
        assert base[e][0].replace('PROD-WEST-2', 'PROD-WEST-9') == flipped[e][0]
        assert base[e][1:] == flipped[e][1:]


def test_plant_flip_changes_nothing(tmp_path):
    base = comparable(build_mixed(tmp_path / 'a.sqlite'))
    assert comparable(build_mixed(tmp_path / 'b.sqlite', plant_modality='stated')) == base


SCRIPT = """
import sys
from dataclasses import asdict
from bicentennial.canon import canon
from bicentennial.render import render_event
from bicentennial.world import open_world
db = open_world(sys.argv[1])
ids = [row[0] for row in db.execute('SELECT id FROM event ORDER BY id')]
out = [{**asdict(r), 'slots': [list(s) for s in r.slots]}
       for r in (render_event(db, i, life='b0', tz='America/New_York') for i in ids)]
sys.stdout.buffer.write(canon(out))
"""


def test_determinism_across_hash_seeds(tmp_path):
    build_mixed(tmp_path / 'm.sqlite').close()
    outputs = [subprocess.run([sys.executable, '-c', SCRIPT, str(tmp_path / 'm.sqlite')], check=True,
                              capture_output=True, env={**os.environ, 'PYTHONHASHSEED': seed}).stdout
               for seed in ('0', 'random')]
    assert outputs[0] == outputs[1] and len(outputs[0]) > 1000


def test_read_only_and_hash_stable(tmp_path):
    build_mixed(tmp_path / 'm.sqlite').close()
    db = open_world(tmp_path / 'm.sqlite')
    before = world_hash(db)
    for e in events(db):
        check_trace(db, render_event(db, e, life=LIFE, tz=NY), NY)
    assert world_hash(db) == before and db.total_changes == 0 and not db.in_transaction
