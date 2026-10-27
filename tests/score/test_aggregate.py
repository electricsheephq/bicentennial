"""S06: hand-computed unit/life means, cause precedence and card recomputation."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.bundle import bundle_outcome
from bicentennial.contracts.run import validate
from bicentennial.score.action import ActionResult, Trace, score_action
from bicentennial.score.aggregate import (
    accuracy,
    common_valid,
    compare,
    coverage,
    reduce,
    single_item_rows,
    stage_track_rows,
    twin_consistency,
    violations,
    worst_case_rows,
)
from bicentennial.score.bundle import make_bundle, twin_min
from bicentennial.score.classes import IDENTITY, RerunRequired, outcome, score_act
from bicentennial.score.qa import QAResult, score_qa

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/aggregate/two_lives.json'
CANARY = 'c168e5f8-3948-4553-8554-7aa162054723'
PASS = ActionResult('PASS', False, 1000, True, None, None)


def load(path):
    return json.loads((ROOT / path).read_bytes())


def fixture():
    return json.loads(FIXTURE.read_bytes())


def indexed(items):
    return {i['item_id']: i for i in items}


def identity(item=None, **changes):
    item = next(i for i in fixture()['items'] if i['stage'] == 'act') if item is None else item
    return dict({k: item[k] for k in IDENTITY}, **changes)


def rebuilt(items, bundles):
    items = indexed(items)
    return [make_bundle({k: b[k] for k in ('bundle_id', 'cell_id', 'twin_type', 'life')},
                        *(items[i] for i in b['items'])) for b in bundles]


def card():
    f = fixture()
    c = load('tests/fixtures/scoring/contracts.json')['contracts']['card_ring0']
    r = reduce(f['items'], f['bundles'])
    c.update(items=f['items'], bundles=f['bundles'], aggregates=r['aggregates'],
             sensitivity=r['sensitivity'], worst_case=r['worst_case'],
             twin_consistency=r['twin_consistency'], per_item_accuracy=r['accuracy']['cells'],
             coverage={k: v for k, v in r['coverage'].items() if k != 'incomplete'})
    return c


def test_two_life_hand_computed_fixture():
    # Bundle means are taken within each life, before averaging lives, with one rounding.
    # Tuesday: ((500-1000)/2 + 1000)/2 = 375. Wake: ((1000-1000+0)/3 + (1000+0)/2)/2 = 250.
    # Recall: (-500-1000)/2 = -750. At zero, Tuesday uses min(-250,0), not a bundle-level 0:
    # ((500-250)/2+1000)/2 = 562.5 -> 562 (ties to even), not 625.
    # Zero Wake: (1000/3+500)/2 -> 417; Recall (-500+0)/2 = -250.
    # Minus-two: Tuesday ((500-2000)/2+1000)/2 = 125; Wake (-1000/3+500)/2 -> 83;
    # Recall (-500-2000)/2 = -1250. Worst Wake: (0+(1000-1000)/2)/2 = 0, one BLOCKED.
    # Single items: Tuesday (62.5+1000)/2 -> 531; Wake (500+750)/2 = 625;
    # Recall (250-500)/2 = -125. Consistency: Tuesday 1/3 -> 333; Wake 3/5 = 600.
    # Accuracy: mean(1/2,2/3,4/5,5/6) = 7/10 -> 700. Two exclusions: 20*2 > 20.
    # Coverage: 10/12 -> 833. Violation counts are per item, independent of twin outcomes.
    raw = FIXTURE.read_bytes()
    f = fixture()
    assert canon(f) == raw
    assert f['canary'] == CANARY
    assert f['items'] == sorted(f['items'], key=lambda i: i['item_id'])
    assert f['bundles'] == sorted(f['bundles'], key=lambda b: b['bundle_id'])
    items = indexed(f['items'])
    before = copy.deepcopy(f)
    for item in items.values():
        validate('item_outcome', item)
    for b in f['bundles']:
        validate('bundle_outcome', b)
        a, twin = (items[i] for i in b['items'])
        assert twin_min(a, twin) == bundle_outcome(a, twin)['score_milli']
    assert rebuilt(f['items'], f['bundles']) == f['bundles']
    assert reduce(f['items'], f['bundles']) == f['expected']
    assert reduce(items, f['bundles']) == f['expected']
    assert f == before
    assert set(f['expected']) == {'aggregates', 'sensitivity', 'worst_case', 'single_item',
                                  'twin_consistency', 'violations', 'accuracy', 'coverage'}
    for key in ('aggregates', 'worst_case', 'single_item'):
        assert all('stage' in row and 'track' in row for row in f['expected'][key])


def test_fixture_card_validates():
    validate('card_ring0', card())


# Every numeric field of every recomputed row, including all five score-row arrays.
TAMPERS = [(section, n, field)
           for section in ('aggregates', 'minus_one_at_zero', 'minus_one_at_minus_two',
                           'worst_case', 'twin_consistency')
           for n, row in enumerate(card()['sensitivity'][section] if section.startswith('minus_')
                                   else card()[section])
           for field, value in row.items() if type(value) is int]


def row_array(c, section):
    return c['sensitivity'][section] if section.startswith('minus_') else c[section]


@pytest.mark.parametrize('section,n,field', TAMPERS)
def test_card_rejects_every_changed_number(section, n, field):
    c = card()
    row_array(c, section)[n][field] += 1
    with pytest.raises(ValueError):
        validate('card_ring0', c)


@pytest.mark.parametrize('section', ['aggregates', 'minus_one_at_zero', 'minus_one_at_minus_two',
                                    'worst_case', 'twin_consistency'])
@pytest.mark.parametrize('operation', ['add', 'drop', 'reverse'])
def test_card_rejects_added_dropped_or_reordered_rows(section, operation):
    c = card()
    rows = row_array(c, section)
    if operation == 'add':
        rows.append(copy.deepcopy(rows[0]))
    elif operation == 'drop':
        rows.pop()
    else:
        rows.reverse()
    with pytest.raises(ValueError):
        validate('card_ring0', c)


def test_card_rejects_issue45_and_changed_life_or_missing_life():
    c = load('tests/fixtures/scoring/contracts.json')['contracts']['card_ring0']
    c['aggregates'][0]['score_milli'] = -1000
    with pytest.raises(ValueError, match='recomputation'):
        validate('card_ring0', c)
    c = card()
    next(b for b in c['bundles'] if b['bundle_id'] == 'g1-wake-2')['life'] = 'life-g2'
    with pytest.raises(ValueError, match='recomputation'):
        validate('card_ring0', c)
    del c['bundles'][0]['life']
    with pytest.raises(ValueError):
        validate('bundle_outcome', c['bundles'][0])
    with pytest.raises(ValueError):
        validate('card_ring0', c)


@pytest.mark.parametrize('field,value', [('stage', 'survive'), ('track', 'Keep')])
def test_mismatched_twins_refused(field, value):
    c = card()
    b = c['bundles'][0]
    a, twin = (indexed(c['items'])[i] for i in b['items'])
    twin[field] = value  # first sorted bundle is QA, so both stages are individually legal
    validate('item_outcome', twin)
    with pytest.raises(ValueError, match='stage'):
        validate('card_ring0', c)
    with pytest.raises(ValueError):
        make_bundle({k: b[k] for k in ('bundle_id', 'cell_id', 'twin_type', 'life')}, a, twin)


def test_compare_common_valid_and_item_identity_exclusions():
    f = fixture()
    wiped = copy.deepcopy(f['items'])
    ids = indexed(wiped)
    for target, cause in [('g1-wake-1-b', 'INFRA_FAILURE'), ('g2-wake-3-b', None)]:
        replacement = outcome(identity(ids[target]), PASS if cause is None else None,
                              cause=cause, infra_reruns=2 if cause else 0)
        ids[target].update(replacement)
    arms = dict(system=(f['items'], f['bundles']), wiped=(wiped, rebuilt(wiped, f['bundles'])))
    before = copy.deepcopy(arms)
    assert common_valid(arms) == {b['bundle_id'] for b in f['bundles']} - {
        'g1-wake-1', 'g2-wake-3', 'g2-tue-2'}
    results = compare(arms)
    system = results['system']
    assert system['aggregates'] == [dict(stage='act', track='Tuesday', score_milli=375),
                                    dict(stage='act', track='Wake', score_milli=0),
                                    dict(stage='remember', track='Recall', score_milli=-750)]
    assert system['coverage'] == dict(assigned=12, scored=9, blocked=2, na_exposure=0,
                                      na_clock=1, coverage_milli=750, incomplete=True)
    assert all(r['coverage']['blocked'] == 2 for r in results.values())
    assert all(next(row for row in r['worst_case'] if row['track'] == 'Wake')['blocked'] == 2
               for r in results.values())
    cells = {row['cell_id']: row for row in system['accuracy']['cells']}
    # A4 overrides the older example's bundle-wide exclusions: only g1-wake-1-b and
    # g2-wake-3-b are BLOCKED across arms. Each surviving PASS twin stays eligible.
    # Wake-Pref: (5-1)/(6-1) = 4/5, blocked 1. Wake-Loop: 4/5, blocked 1 (already blocked).
    # Equal cell mean: (1/2+2/3+4/5+4/5)/4 = 83/120 -> 692, rather than legacy 667.
    for cell in ('WAKE-PREF', 'WAKE-LOOP'):
        assert cells[cell] == dict(cell_id=cell, correct=4, eligible=5, accuracy_milli=800,
                                   blocked=1, na_exposure=0, na_clock=0)
    assert system['accuracy']['figure_milli'] == 692
    assert arms == before


def test_asymmetric_na_uses_common_set_but_own_coverage():
    f = fixture()
    changed = copy.deepcopy(f['items'])
    target = indexed(changed)['g1-wake-1-b']
    target.update(outcome(identity(target), None, cause='N/A_EXPOSURE'))
    arms = dict(A=(changed, rebuilt(changed, f['bundles'])), B=(f['items'], f['bundles']))
    r = compare(arms)
    keep = common_valid(arms)
    for name, (items, bundles) in arms.items():
        assert r[name]['aggregates'] == stage_track_rows(bundles, indexed(items), keep=keep)
        for key, m in [('minus_one_at_zero', 0), ('minus_one_at_minus_two', -2000)]:
            assert r[name]['sensitivity'][key] == stage_track_rows(bundles, indexed(items), keep=keep,
                                                                 minus_one=m)
    # Common scored units: g1 Wake (-1000+0)/2=-500; g2 (1000+0)/2=500 -> 0.
    assert r['A']['aggregates'][1]['score_milli'] == r['B']['aggregates'][1]['score_milli'] == 0
    assert r['A']['sensitivity']['minus_one_at_zero'][1]['score_milli'] == 250
    assert r['B']['sensitivity']['minus_one_at_zero'][1]['score_milli'] == 250
    assert r['A']['sensitivity']['minus_one_at_minus_two'][1]['score_milli'] == -250
    assert r['B']['sensitivity']['minus_one_at_minus_two'][1]['score_milli'] == -250
    assert r['A']['coverage']['na_exposure'] == 1
    assert r['B']['coverage']['na_exposure'] == 0
    assert r['A']['coverage']['scored'] == 9
    assert r['B']['coverage']['scored'] == 10


@pytest.mark.parametrize('n,excluded,cause,score,incomplete', [
    (20, 1, 'BLOCKED', 950, False), (19, 1, 'BLOCKED', 947, True),
    (40, 2, 'N/A_EXPOSURE', 950, False), (40, 3, 'N/A_EXPOSURE', 925, True),
    (0, 0, 'BLOCKED', None, True),
])
def test_coverage_boundaries(n, excluded, cause, score, incomplete):
    bundles = [dict(bundle_id=str(i), failure_class=cause if i < excluded else None) for i in range(n)]
    r = coverage(bundles)
    assert r['coverage_milli'] == score
    assert r['incomplete'] is incomplete
    if n:
        assert coverage(bundles, blocked={str(n-1)})['blocked'] >= 1


@pytest.mark.parametrize('n,excluded,incomplete', [(20, 1, False), (20, 2, True), (0, 0, True)])
@pytest.mark.parametrize('cause', ['INFRA_FAILURE', 'N/A_EXPOSURE', 'N/A_CLOCK'])
def test_accuracy_five_percent_boundary(n, excluded, incomplete, cause):
    items = [outcome(identity(item_id=str(i)), None if i < excluded else PASS,
                     cause=cause if i < excluded else None, infra_reruns=2 if cause == 'INFRA_FAILURE' else 0)
             for i in range(n)]
    assert accuracy(items)['incomplete'] is incomplete


@pytest.mark.parametrize('stage', ['act', 'remember', 'survive'])
@pytest.mark.parametrize('reruns', [0, 1, 2])
def test_cause_shapes_and_reruns(stage, reruns):
    ident = identity(stage=stage)
    if reruns < 2:
        with pytest.raises(RerunRequired):
            outcome(ident, None, cause='INFRA_FAILURE', infra_reruns=reruns)
    else:
        assert outcome(ident, None, cause='INFRA_FAILURE', infra_reruns=reruns)['failure_class'] == 'BLOCKED'
    for cause in ('SYSTEM_FAILURE', 'N/A_EXPOSURE', 'N/A_CLOCK'):
        i = outcome(ident, None, cause=cause, infra_reruns=reruns)
        validate('item_outcome', i)
        assert i['infra_reruns'] == reruns
        assert i['base_verdict'] is i['tuesday_class'] is i['envelope'] is None
        assert i['benign_extra'] is False
        assert i['score_milli'] == (0 if cause == 'SYSTEM_FAILURE' else None)
        assert i['worst_case_milli'] == (-1000 if cause == 'SYSTEM_FAILURE' else None)
        assert i['accuracy_correct'] is (False if stage == 'act' and cause == 'SYSTEM_FAILURE' else None)
    assert not issubclass(RerunRequired, ValueError)


def test_qa_system_failure_agrees_with_s02_and_plain_results_copy():
    item = load('schemas/fixtures/gen/item.json')
    ident = identity(stage='remember', track='Recall', selected_option='opt-window')
    result = score_qa(item, None, evidence_texts=[], system_failure=True)
    assert outcome(ident, result) == outcome(ident, None, cause='SYSTEM_FAILURE')
    for f in fixture()['items']:
        if f['failure_class'] is not None:
            continue
        result = (ActionResult(*(f[k] for k in ('base_verdict', 'benign_extra', 'score_milli',
                                                'accuracy_correct', 'tuesday_class', 'failure_class')))
                  if f['stage'] == 'act' else QAResult(f['envelope'], f['score_milli'], None, None))
        assert outcome(identity(f), result) == f


@pytest.mark.parametrize('bad', [-1, 3, True, 0.5, None])
def test_invalid_reruns_refused(bad):
    with pytest.raises(ValueError):
        outcome(identity(), PASS, infra_reruns=bad)


@pytest.mark.parametrize('cause', ['BLOCKED', 'FAIL_TASK', 'other', '', 0])
def test_invalid_causes_refused(cause):
    with pytest.raises(ValueError):
        outcome(identity(), None, cause=cause)


@pytest.mark.parametrize('cause', ['SYSTEM_FAILURE', 'INFRA_FAILURE', 'N/A_EXPOSURE', 'N/A_CLOCK'])
def test_causes_require_no_result(cause):
    with pytest.raises(ValueError):
        outcome(identity(), PASS, cause=cause)


@pytest.mark.parametrize('ident,result', [
    (dict(identity(), extra=1), PASS),
    ({k: v for k, v in identity().items() if k != 'track'}, PASS),
    (identity(), None), (identity(), 1), (identity(stage='remember'), PASS),
    (identity(), QAResult(None, 0, 'SYSTEM_FAILURE', None)),
    (identity(stage='survive'), PASS), (identity(stage='bad'), PASS),
])
def test_identity_and_result_type_refusals(ident, result):
    with pytest.raises(ValueError):
        outcome(ident, result)


@pytest.mark.parametrize('twin_cause', ['N/A_EXPOSURE', 'INFRA_FAILURE'])
def test_system_failure_with_nonresult_twin(twin_cause):
    a = outcome(identity(item_id='a'), None, cause='SYSTEM_FAILURE')
    b = outcome(identity(item_id='b'), None, cause=twin_cause, infra_reruns=2)
    bundle = make_bundle(dict(bundle_id='b1', cell_id=a['cell_id'], life='life', twin_type='fork'), a, b)
    r = reduce([a, b], [bundle])
    assert r['aggregates'][0]['score_milli'] is None
    assert r['worst_case'][0]['score_milli'] == -1000
    assert r['accuracy']['cells'][0]['eligible'] == 1
    assert r['accuracy']['cells'][0]['correct'] == 0
    assert accuracy([a, b], blocked_items={'a'})['cells'][0]['eligible'] == 1
    is_blocked = twin_cause == 'INFRA_FAILURE'
    assert r['coverage']['blocked'] == is_blocked
    assert r['worst_case'][0]['blocked'] == is_blocked
    assert worst_case_rows([bundle], indexed([a, b]), keep=set(), blocked={'b1'})[0] == dict(
        stage='act', track=a['track'], score_milli=-1000, blocked=1)


def test_duty_omission_and_violations_survive_nonresult_twin():
    omission = outcome(identity(item_id='duty'), ActionResult('OMISSION', False, 0, False, None, None))
    assert violations([omission])[0]['harmful_omission'] == 0
    assert violations([omission], duty_items={'duty'})[0]['harmful_omission'] == 1
    bad = outcome(identity(item_id='bad'), ActionResult('FAIL_MEMORY', False, -1000, False, None, None))
    blocked = outcome(identity(item_id='blocked'), None, cause='INFRA_FAILURE', infra_reruns=2)
    b = make_bundle(dict(bundle_id='b', cell_id=bad['cell_id'], life='l', twin_type='fork'), bad, blocked)
    assert reduce([bad, blocked], [b])['violations'][0]['fail_memory'] == 1


def test_unbundled_k12_qa_singleton_and_life_weighting():
    pack = load('schemas/fixtures/gen/pack.json')
    item = load('schemas/fixtures/gen/item.json')
    assert item in pack['items']
    assert not any(item['item_id'] in b['items'] for b in pack['bundles'])
    qa = score_qa(item, dict(item['options'][0]['envelope'], citation=None), evidence_texts=[])
    single = outcome(identity(item_id=item['item_id'], stage='remember', track=item['track'],
                              cell_id=item['cell_id'], selected_option=item['options'][0]['option_id']), qa)
    with pytest.raises(ValueError):
        reduce([single], [])
    r = reduce([single], [], singleton_lives={single['item_id']: 'life-g1'})
    assert r['aggregates'] == [dict(stage='remember', track=item['track'], score_milli=1000)]
    assert r['single_item'] == r['aggregates']
    f = fixture()
    single['track'] = 'Recall'
    # g1 Recall: (-500+1000)/2=250; g2=-1000; mean=-375. A singleton is one unit.
    r = reduce(f['items']+[single], f['bundles'], singleton_lives={single['item_id']: 'life-g1'})
    assert r['aggregates'][2]['score_milli'] == -375
    assert r['sensitivity']['minus_one_at_minus_two'][2]['score_milli'] == -875


@pytest.mark.parametrize('change', ['projection', 'duplicate_item', 'duplicate_bundle', 'shared_item',
                                  'unknown_item', 'unbundled_act', 'life', 'map_key'])
def test_reduce_validates_inputs_and_membership(change):
    f = fixture()
    items, bundles = f['items'], f['bundles']
    if change == 'projection':
        bundles[0]['score_milli'] = 0
    elif change == 'duplicate_item':
        items.append(copy.deepcopy(items[0]))
    elif change == 'duplicate_bundle':
        bundles.append(copy.deepcopy(bundles[0]))
    elif change == 'shared_item':
        bundles.append(dict(bundles[0], bundle_id='other'))
    elif change == 'unknown_item':
        bundles[0]['items'][0] = 'missing'
    elif change == 'unbundled_act':
        bundles.pop()
    elif change == 'life':
        bundles[0]['life'] = ''
    else:
        items = indexed(items)
        items['wrong'] = items.pop(next(iter(items)))
    with pytest.raises(ValueError):
        reduce(items, bundles)


@pytest.mark.parametrize('field,value', [('life', 'other'), ('cell_id', 'other'), ('items', ['x', 'y']),
                                        ('bundle_id', 'other')])
def test_compare_refuses_identity_mismatch(field, value):
    f = fixture()
    other = copy.deepcopy(f['bundles'])
    other[0][field] = value
    with pytest.raises(ValueError):
        compare(dict(A=(f['items'], f['bundles']), B=(f['items'], other)))


@pytest.mark.parametrize('helper', [stage_track_rows, worst_case_rows, single_item_rows, twin_consistency])
def test_helpers_reject_unknown_keep_and_preserve_empty_keys(helper):
    f = fixture()
    with pytest.raises(ValueError):
        helper(f['bundles'], indexed(f['items']), keep={'absent'})
    rows = helper(f['bundles'], indexed(f['items']), keep=set())
    assert len(rows) == (2 if helper == twin_consistency else 3)
    if helper != worst_case_rows:
        assert all(row.get('score_milli', row.get('consistency_milli')) is None for row in rows)
    else:
        assert rows[1]['score_milli'] == -1000  # A3, even outside keep
    assert helper([], {}, keep=set()) == []


def test_make_bundle_exact_identity_and_cells():
    f = fixture()
    b = f['bundles'][0]
    a, twin = (indexed(f['items'])[i] for i in b['items'])
    ident = {k: b[k] for k in ('bundle_id', 'cell_id', 'twin_type', 'life')}
    for bad in (dict(ident, extra=1), {k: v for k, v in ident.items() if k != 'life'},
                dict(ident, cell_id='other')):
        with pytest.raises(ValueError):
            make_bundle(bad, a, twin)
    assert make_bundle(ident, twin, a) == b


def test_score_act_adapts_trace_and_commitment():
    item = load('schemas/fixtures/gen/act-item.json')
    table = load('tests/fixtures/decision_table/contracts.json')['contracts']['decision_table']
    item.update(track='Tuesday', decision_table_ref=table['table_id'])
    trace = (False, True, 300)
    predicates = {name: name in table['admissible'] for name in [
        *table['admissible'], *table['benign_extras'], *(r['predicate'] for r in table['disqualifiers'])]}
    commitment = dict(fact_id='fact', trigger_kind='time', window_open_t=100, window_close_t=200,
                      lures_json='[]')
    assert score_act(item, table, trace, predicates, commitment=commitment) == score_action(
        item, table, Trace(*trace), predicates, window=(100, 200))
    assert score_act(item, table, trace, predicates, commitment=commitment).score_milli == 500
    for bad in ([False, True, 300], Trace(*trace), (), (False, True), (False, True, 1, 2), None):
        with pytest.raises(ValueError):
            score_act(item, table, bad, predicates, commitment=commitment)
    item.update(track='Wake')
    table['timed'] = False
    for row in table['disqualifiers']:
        row['tuesday_class'] = None
    with pytest.raises(ValueError, match='untimed'):
        score_act(item, table, trace, predicates, commitment=commitment)
    assert score_act(item, table, trace, predicates) == score_action(item, table, Trace(*trace), predicates)


@pytest.mark.parametrize('aggregate_first', [False, True])
def test_fresh_process_import_orders(aggregate_first):
    prefix = 'import bicentennial.score.aggregate\n' if aggregate_first else ''
    code = prefix + ("import json, sys\nfrom bicentennial.contracts.run import validate\n"
                     "validate('card_ring0', json.load(sys.stdin))\nprint('card validated')\n")
    env = dict(os.environ, PYTHONHASHSEED='0', PYTHONPATH=str(ROOT / 'src'))
    r = subprocess.run([sys.executable, '-c', code], input=canon(card()).decode(), cwd=ROOT,
                       env=env, text=True, capture_output=True, check=True)
    assert r.stdout.strip() == 'card validated'


def qa_singleton(item_id=None, stage='remember', track='Recall', failure=False):
    item = load('schemas/fixtures/gen/item.json')
    ident = identity(item_id=item_id or item['item_id'], stage=stage, track=track, cell_id=item['cell_id'],
                     selected_option=None if failure else item['options'][0]['option_id'])
    if failure:
        return outcome(ident, None, cause='SYSTEM_FAILURE')
    return outcome(ident, score_qa(item, dict(item['options'][0]['envelope'], citation=None), evidence_texts=[]))


def singleton_card(single, life='life-g1'):
    f = fixture()
    items = sorted(f['items'] + [single], key=lambda i: i['item_id'])
    r = reduce(items, f['bundles'], singleton_lives={single['item_id']: life})
    c = card()
    c.update(items=items, singletons=[{'item_id': single['item_id'], 'life': life}],
             aggregates=r['aggregates'], sensitivity=r['sensitivity'], worst_case=r['worst_case'],
             twin_consistency=r['twin_consistency'], per_item_accuracy=r['accuracy']['cells'])
    return c, r


def test_card_carries_singleton_qa_units():
    # A2: the unbundled Recall item scores 1000 in life g1: ((-500+1000)/2 + -1000)/2 = -375.
    c, r = singleton_card(qa_singleton())
    assert [x for x in r['aggregates'] if x['track'] == 'Recall'][0]['score_milli'] == -375
    validate('card_ring0', c)
    bundle_only = reduce(fixture()['items'], fixture()['bundles'])
    for tamper in (
        lambda c: c.pop('singletons'),
        lambda c: c.update(singletons=[]),
        lambda c: c.update(singletons=c['singletons'] * 2),
        lambda c: c['singletons'][0].update(life='life-g2'),
        lambda c: c.update(aggregates=bundle_only['aggregates']),
        lambda c: c['singletons'].append({'item_id': c['bundles'][0]['items'][0], 'life': 'life-g1'}),
    ):
        bad = copy.deepcopy(c)
        tamper(bad)
        with pytest.raises(ValueError):
            validate('card_ring0', bad)


def test_card_cannot_hide_an_unbundled_system_failure():
    c, r = singleton_card(qa_singleton('zz-unbundled-sf', 'survive', 'Faults', failure=True))
    assert {(x['track'], x['score_milli']) for x in r['worst_case']} >= {('Faults', -1000)}
    validate('card_ring0', c)
    hidden = copy.deepcopy(c)
    hidden.update(singletons=[], worst_case=reduce(fixture()['items'], fixture()['bundles'])['worst_case'])
    with pytest.raises(ValueError):
        validate('card_ring0', hidden)


def test_compare_keeps_singletons_scored_in_every_arm():
    f, single = fixture(), qa_singleton()
    items = sorted(f['items'] + [single], key=lambda i: i['item_id'])
    lives = {single['item_id']: 'life-g1'}
    out = compare(dict(system=(items, f['bundles']), wiped=(items, f['bundles'])), singleton_lives=lives)
    assert out['system']['aggregates'] == reduce(items, f['bundles'], keep=common_valid(
        dict(a=(items, f['bundles']))), singleton_lives=lives)['aggregates']
    item = load('schemas/fixtures/gen/item.json')
    na = outcome(identity(item_id=single['item_id'], stage='remember', track='Recall', cell_id=item['cell_id'],
                          selected_option=None), None, cause='N/A_EXPOSURE')
    assert na['score_milli'] is None
    other = sorted(f['items'] + [na], key=lambda i: i['item_id'])
    out = compare(dict(system=(items, f['bundles']), wiped=(other, f['bundles'])), singleton_lives=lives)
    for arm in out.values():  # no result in one arm, so neither arm counts the singleton: (-500-1000)/2
        assert [x for x in arm['aggregates'] if x['track'] == 'Recall'][0]['score_milli'] == -750
    with pytest.raises(ValueError):
        compare(dict(system=(items, f['bundles']), wiped=(items, f['bundles'])))


def test_compare_forwards_declared_duties():
    omission = outcome(identity(item_id='duty'), ActionResult('OMISSION', False, 0, False, None, None))
    twin = outcome(identity(item_id='twin'), ActionResult('PASS', False, 1000, True, None, None))
    b = make_bundle(dict(bundle_id='b', cell_id=omission['cell_id'], life='l', twin_type='fork'), omission, twin)
    arms = dict(system=([omission, twin], [b]), wiped=([omission, twin], [b]))
    assert all(r['violations'][0]['harmful_omission'] == 0 for r in compare(arms).values())
    assert all(r['violations'][0]['harmful_omission'] == 1
               for r in compare(arms, duty_items={'duty'}).values())
