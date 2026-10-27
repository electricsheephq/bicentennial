"""Offline S13 gate and stable-field acceptance; run as a script for hash-seed proof."""

import ast
import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import uniform_int
from bicentennial.report import determinism as det
from bicentennial.report import t1_gate as gate
from bicentennial.report.card import assemble, finalize
from bicentennial.score import invariants as source_inv
from bicentennial.score.bundle import make_bundle
from bicentennial.systems.registry import load

ROOT = Path(__file__).resolve().parents[2]
X = ("g1-recall-1", "g1-wake-1", "g1-wake-2", "g1-wake-3", "g2-recall-1", "g2-wake-1",
     "g2-wake-4")


def inputs():
    fixture = json.loads((ROOT / "tests/fixtures/aggregate/two_lives.json").read_bytes())
    example = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())
    example = example["contracts"]["card_ring0"]
    pins = {k: "a" * len(v) for k, v in example["pins"].items() if k != "masks_hash"}
    return dict(tier="T1", mode="hermes", system_entry=load(ROOT / "systems/registry/hermes-native.toml"),
                run_status="COMPLETE", pins=pins, ledger_records=[],
                run_values=dict(sandbox_root="/sandbox/root", director_port="43210"),
                items=fixture["items"], bundles=fixture["bundles"], controls=example["controls"])


def rebuild(card, replacements=None, **changes):
    args = inputs()
    args.update(items=copy.deepcopy(card["items"]), controls=copy.deepcopy(card["controls"]),
                run_status=card["run_status"], tier=card["tier"],
                pins={k: v for k, v in card["pins"].items() if k != "masks_hash"})
    items = {i["item_id"]: i for i in args["items"]}
    original = copy.deepcopy(items)
    for target, source in (replacements or {}).items():
        identity = {k: items[target][k] for k in ("item_id", "cell_id")}
        items[target].update(original[source], **identity)
    args["bundles"] = [make_bundle({k: b[k] for k in ("bundle_id", "cell_id", "twin_type", "life")},
                                    *(items[i] for i in b["items"])) for b in card["bundles"]]
    return assemble(**dict(args, **changes))


def invs(**changes):
    return [source_inv.Verdict(name, changes.get(name, "NOT_EXERCISED" if name == "INV-FORGET"
                                               else "PASS"), 1, 0, (), (), (), ())
            for name in gate.INVARIANTS]


def corpus(status="PASS", reason="", case_id="r1.wipe_on_restart"):
    return [dict(case_id=case_id, status=status, reason=reason, first_diff=None)]


def scenarios():
    c = assemble(**inputs())
    b = finalize(c, "CONFORMANCE_PASS")
    ok = corpus() + corpus(case_id="r2.stale_wins")
    rows = []

    def add(name, *, card=c, baseline=b, cases=ok, invariants=None, crossing=X, arm="system",
            verdict="PASS", reasons=(), regressions=(), excluded=(), failed=(), blocked=()):
        rows.append((name, (card, baseline, cases),
                     dict(invariants=invs() if invariants is None else invariants,
                          crossing=crossing, arm=arm),
                     dict(verdict=verdict, reasons=reasons, regressions=regressions,
                          excluded=excluded, corpus_failed=failed, blocked=blocked)))

    add("equal")
    add("first", baseline=None, verdict="CONFORMANCE_PASS", reasons=("baseline_absent",))
    c1 = rebuild(c, {"g1-wake-1-b": "g1-wake-2-b"})
    add("regression", card=c1, verdict="FAIL", reasons=("regression",), regressions=("g1-wake-1",))
    add("outside-crossing", card=c1, crossing=tuple(i for i in X if i != "g1-wake-1"))
    add("improvement", card=rebuild(c, {"g1-wake-2-b": "g1-wake-2-a"}))
    cw = rebuild(c, {i: "g1-wake-2-b" for i in ("g1-wake-1-a", "g1-wake-1-b", "g2-wake-1-a",
                                              "g2-wake-1-b")})
    iw = invs(**dict.fromkeys(gate.GATED_T1, "FAIL"))
    bad = corpus("FAIL", "mismatch")
    add("wiped-first", card=cw, baseline=None, cases=bad, invariants=iw, arm="wiped", verdict="FAIL",
        reasons=("baseline_absent", "corpus_fail", "invariant_fail"), failed=(bad[0]["case_id"],))
    add("wiped-baseline", card=cw, cases=bad, invariants=iw, arm="wiped", verdict="FAIL",
        reasons=("corpus_fail", "invariant_fail", "regression"),
        regressions=("g1-wake-1", "g2-wake-1"), failed=(bad[0]["case_id"],))
    pass_control = copy.deepcopy(cw)
    pass_control["controls"]["wiped_store"] = "PASS"
    add("wiped-ignores-control", card=pass_control, baseline=None, cases=bad, invariants=iw,
        arm="wiped", verdict="FAIL", reasons=("baseline_absent", "corpus_fail", "invariant_fail"),
        failed=(bad[0]["case_id"],))
    add("wiped-unexpected-pass", card=cw, baseline=None, arm="wiped", verdict="CONFORMANCE_PASS",
        reasons=("baseline_absent",))
    for control, verdict, reason in (("PASS", "INVALID", "wiped_pass"),
                                     ("uninformative", "FAIL", "wiped_uninformative")):
        cc = copy.deepcopy(c)
        cc["controls"]["wiped_store"] = control
        add(control, card=cc, verdict=verdict, reasons=(reason,))
    for name in gate.GATED_T1:
        for status in ("FAIL", "INCONCLUSIVE", "NOT_EXERCISED", "INFRA_FAILURE"):
            infra = status == "INFRA_FAILURE"
            add(name + status, invariants=invs(**{name: status}), verdict="BLOCKED" if infra else "FAIL",
                reasons=("invariant_infra" if infra else "invariant_fail",),
                blocked=(f"invariant:{name}",) if infra else ())
    add("mixed", invariants=invs(**{"INV-VERB": "FAIL", "INV-NEW": "INFRA_FAILURE"}),
        verdict="FAIL", reasons=("invariant_fail", "invariant_infra"), blocked=("invariant:INV-NEW",))
    add("corpus-infra", cases=corpus("INFRA_FAILURE", "infra"), verdict="BLOCKED",
        reasons=("corpus_infra",), blocked=("corpus:r1.wipe_on_restart",))
    add("corpus-fail", cases=bad, verdict="FAIL", reasons=("corpus_fail",), failed=(bad[0]["case_id"],))
    add("excluded", crossing=(*X, "g2-tue-2", "g2-wake-3"), excluded=("g2-tue-2", "g2-wake-3"))
    for status in ("BLOCKED", "INFRA_FAILURE"):
        add(status, card=dict(c, run_status=status), verdict="BLOCKED", reasons=("run_status",),
            blocked=(f"run_status:{status}",))
    all_faults = copy.deepcopy(c)
    all_faults.update(run_status="INFRA_FAILURE")
    all_faults["controls"]["wiped_store"] = "PASS"
    add("invalid-wins", card=all_faults, cases=bad + corpus("INFRA_FAILURE", "infra", "c-infra"),
        invariants=invs(**{"INV-VERB": "FAIL", "INV-NEW": "INFRA_FAILURE"}), verdict="INVALID",
        reasons=("corpus_fail", "corpus_infra", "invariant_fail", "invariant_infra", "run_status",
                 "wiped_pass"), blocked=("corpus:c-infra", "invariant:INV-NEW", "run_status:INFRA_FAILURE"),
        failed=(bad[0]["case_id"],))
    return rows


@pytest.mark.parametrize("name,args,kwargs,expected", scenarios(), ids=lambda v: v if isinstance(v, str) else None)
def test_gate_acceptance(name, args, kwargs, expected):
    before = copy.deepcopy((args, kwargs))
    result = gate.t1_gate(*args, **kwargs)
    for field, value in expected.items():
        assert getattr(result, field) == value
    assert result.exit_code == gate.EXIT[result.verdict]
    assert result.run_status == ("BLOCKED" if result.blocked else args[0]["run_status"])
    assert result.arm == kwargs["arm"]
    assert result.baseline_sha256 == (sha256(args[1]).hexdigest() if args[1] else None)
    assert result.invariants == tuple((i.invariant, i.status) for i in kwargs["invariants"][:3])
    assert set(result.reasons) <= set(gate.REASONS)
    assert canon(result.to_obj()) == canon(json.loads(canon(result.to_obj())))
    with pytest.raises(FrozenInstanceError):
        result.verdict = "FAIL"
    if name != "wiped-ignores-control":
        validate("card_ring0", json.loads(finalize(dict(args[0], run_status=result.run_status), result.verdict)))
    assert (args, kwargs) == before


class LocalResult:
    def __init__(self, obj):
        self.obj = obj

    def to_obj(self):
        return copy.deepcopy(self.obj)


def test_object_and_dict_paths_and_order_are_equivalent_200_cases():
    c = assemble(**inputs())
    b = finalize(c, "PASS")
    for case in range(200):
        order = sorted(gate.INVARIANTS, key=lambda k: uniform_int("s13", ("s13", str(case)),
                                                                0, k, 0, 2**63))
        rows = {r.invariant: r.to_obj() for r in invs()}
        verdicts = [LocalResult(rows[k]) if case % 2 else rows[k] for k in order]
        crossing = sorted(X, key=lambda k: uniform_int("s13", ("s13", str(case)), 1, k, 0, 2**63))
        cases = [LocalResult(corpus()[0]), corpus(case_id="r2.stale_wins")[0]]
        assert gate.t1_gate(c, b, cases, invariants=verdicts, crossing=crossing) == gate.t1_gate(
            c, b, cases, invariants=invs(), crossing=frozenset(X))


def invalid_inputs():
    c = assemble(**inputs())
    cases = []
    cases += [("card-verdict", dict(card=dict(c, gate_verdict="PASS"))),
              ("tier", dict(card=rebuild(c, tier="T0"))),
              ("empty-crossing", dict(crossing=[])), ("numeric-crossing", dict(crossing=[1])),
              ("unknown-crossing", dict(crossing=["absent"])), ("arm", dict(arm="unknown"))]
    good = [r.to_obj() for r in invs()]
    cases += [("three", dict(invariants=good[:3])), ("five", dict(invariants=good + [good[0]])),
              ("duplicate", dict(invariants=good[:3] + [good[0]]))]
    for label, change in (("extra-key", dict(extra=0)), ("unknown-status", dict(status="WHAT"))):
        rows = copy.deepcopy(good)
        rows[0].update(change)
        cases.append((label, dict(invariants=rows)))
    cases.append(("forget", dict(invariants=invs(**{"INV-FORGET": "PASS"}))))
    cases += [("empty-corpus", dict(corpus=[])), ("duplicate-case", dict(corpus=corpus() * 2)),
              ("pass-reason", dict(corpus=corpus(reason="mismatch")))]
    for label, change in (("corpus-keys", dict(extra=1)), ("corpus-status", dict(status="WHAT")),
                          ("corpus-reason", dict(reason="WHAT")), ("pass-diff", dict(first_diff="card.x"))):
        row = dict(corpus()[0], **change)
        cases.append((label, dict(corpus=[row])))
    return cases


@pytest.mark.parametrize("name,changes", invalid_inputs(), ids=lambda v: v if isinstance(v, str) else None)
def test_input_refusals(name, changes):
    c = assemble(**inputs())
    args = dict(card=c, baseline=finalize(c, "PASS"), corpus=corpus(), invariants=invs(), crossing=X)
    args.update(changes)
    before = copy.deepcopy(args)
    with pytest.raises(ValueError):
        gate.t1_gate(**args)
    assert args == before


@pytest.mark.parametrize("field", ["tier", "gate_verdict", "system", "pins.pack_hash", "pins.seed_hash"])
def test_baseline_mismatches(field):
    c = assemble(**inputs())
    args = inputs()
    verdict = "CONFORMANCE_PASS"
    if field == "tier":
        args["tier"] = "T0"
    elif field == "gate_verdict":
        verdict = "FAIL"
    elif field == "system":
        args["system_entry"]["name"] = "other"
    else:
        args["pins"][field.split(".")[1]] = "b" * 64
    baseline = finalize(assemble(**args), verdict)
    with pytest.raises(gate.BaselineMismatch) as error:
        gate.check_baseline(baseline, system=c["system"], pins=c["pins"])
    assert error.value.field == field


def test_baseline_structure_bundle_ids_other_pins_and_precedence():
    c = assemble(**inputs())
    raw = finalize(c, "PASS")
    for bad in (raw + b"\n", b"{", b"[]", canon(dict(json.loads(raw), unknown=0)), b'{"x":1.5}'):
        with pytest.raises(ValueError):
            gate.check_baseline(bad, system=c["system"], pins=c["pins"])
    args = inputs()
    args["pins"]["system_hash"] = "b" * 64
    assert gate.t1_gate(c, finalize(assemble(**args), "PASS"), corpus(), invariants=invs(), crossing=X).verdict == "PASS"
    args = inputs()
    # Remove one QA bundle and retain its two items as singleton units in a valid baseline.
    bundle = args["bundles"].pop(0)
    assert all(i["stage"] != "act" for i in args["items"] if i["item_id"] in bundle["items"])
    args["singleton_lives"] = dict.fromkeys(bundle["items"], bundle["life"])
    baseline = finalize(assemble(**args), "PASS")
    with pytest.raises(gate.BaselineMismatch) as error:
        gate.t1_gate(c, baseline, corpus(), invariants=invs(), crossing=X)
    assert error.value.field == "bundles"
    base = json.loads(raw)
    base.update(tier="T0", system="other", gate_verdict="FAIL")
    with pytest.raises(gate.BaselineMismatch) as error:
        gate.check_baseline(canon(base), system=c["system"], pins=c["pins"])
    assert error.value.field == "tier"


def test_blocked_card_check_and_invalid_wiped_input():
    c = assemble(**inputs())
    with pytest.raises(ValueError, match="BLOCKED gate requires"):
        finalize(c, "BLOCKED")
    c["controls"]["wiped_store"] = "PASS"
    with pytest.raises(ValueError, match="wiped pass invalidates"):
        finalize(c, "FAIL")


def leaf_refs(card):
    """Independent walk returning mutation locations as well as concrete paths."""
    order = {path: n for n, path in enumerate(det.FIELD_ORDER)}

    def walk(p, c, value, parent, key, is_key=False, element=None):
        if p in det.ARRAY_KEYS and isinstance(value, list) and value:
            keys = det.ARRAY_KEYS[p]
            keys = (keys,) if isinstance(keys, str) else keys
            for row in sorted(value, key=lambda r: tuple(r[k] for k in keys)):
                identity = row[keys[0]] if len(keys) == 1 else [row[k] for k in keys]
                concrete = f"{c}[{canon(identity).decode()}]"
                yield from walk(p + "[]", concrete, row, None, None, element=(concrete, keys))
        elif isinstance(value, dict) and value:
            for child in sorted(value, key=lambda k: (order.get(p + "." + k, len(order)), k)):
                keyed = element is not None and child in element[1]
                yield from walk(p + "." + child, c + "." + child, value[child], value, child,
                                keyed, element[0] if keyed else None)
        else:
            yield c, parent, key, is_key, element
    return list(walk("card", "card", card, None, None))


def mutate(parent, key):
    value = parent[key]
    if type(value) is bool:
        parent[key] = not value
    elif type(value) is int:
        parent[key] += 1
    elif isinstance(value, str):
        parent[key] += "x"
    elif value is None:
        parent[key] = 0
    elif isinstance(value, list):
        parent[key] = value + ["zz"]
    else:
        raise AssertionError(type(value))


def determinism_cases():
    c = assemble(**inputs())
    raw = finalize(c, "PASS")
    rows = [(raw, raw, None)]
    c1 = rebuild(c, {"g1-wake-1-b": "g1-wake-2-b"})
    rows.append((raw, finalize(c1, "PASS"), 'card.items["g1-wake-1-b"].base_verdict'))
    for n, (path, _, _, is_key, element) in enumerate(leaf_refs(json.loads(raw))):
        changed = json.loads(raw)
        _, parent, key, _, _ = leaf_refs(changed)[n]
        mutate(parent, key)
        rows.append((raw, canon(changed), element if is_key else path))
    return rows


def test_every_stable_leaf_and_symmetry():
    rows = determinism_cases()
    raw = rows[0][0]
    assert det.stable_fields(json.loads(raw)) == tuple(r[0] for r in leaf_refs(json.loads(raw)))
    for a, b, expected in rows:
        forward, reverse = det.determinism_check(a, b), det.determinism_check(b, a)
        assert forward.first_field == reverse.first_field == expected
        assert forward.identical == (a == b)
        assert (forward.sha256_a, forward.sha256_b) == (sha256(a).hexdigest(), sha256(b).hexdigest())
        assert reverse.sha256_a == forward.sha256_b
        with pytest.raises(FrozenInstanceError):
            forward.identical = False


def property_pairs():
    raw = finalize(assemble(**inputs()), "PASS")
    refs = leaf_refs(json.loads(raw))
    eligible = [n for n, row in enumerate(refs) if not row[3]]
    for case in range(200):
        a = uniform_int("s13", ("s13", str(case)), 0, "first", 0, len(eligible) - 1)
        b = uniform_int("s13", ("s13", str(case)), 0, "second", 0, len(eligible) - 2)
        b += b >= a
        i, j = sorted((eligible[a], eligible[b]))
        changed = json.loads(raw)
        changed_refs = leaf_refs(changed)
        for n in (i, j):
            _, parent, key, _, _ = changed_refs[n]
            mutate(parent, key)
        yield raw, canon(changed), refs[i][0]


def test_two_leaf_property_200_cases():
    for raw, changed, expected in property_pairs():
        assert det.determinism_check(raw, changed).first_field == expected
        assert det.determinism_check(changed, raw).first_field == expected


@pytest.mark.parametrize("a,b,path", [
    ({"tier": "T1", "canary": "a"}, {"tier": "T0", "canary": "b"}, "card.canary"),
    ({"z": 1, "a": 2}, {"z": 2, "a": 3}, "card.a"),
    ({"items": []}, {"items": [{"item_id": "a"}]}, 'card.items["a"]'),
    ({"items": [{"item_id": "a", "envelope": {"value": {"z": 0, "a": False}}}]},
     {"items": [{"item_id": "a", "envelope": {"value": {"z": 1, "a": True}}}]},
     'card.items["a"].envelope.value.a'),
    ({"items": [{"item_id": "a", "competing_present": ["a"]}]},
     {"items": [{"item_id": "a", "competing_present": ["b"]}]}, 'card.items["a"].competing_present'),
    ({"aggregates": [{"stage": "act", "track": "Wake", "score_milli": 1}]},
     {"aggregates": [{"stage": "act", "track": "Wake", "score_milli": 2}]},
     'card.aggregates[["act","Wake"]].score_milli'),
    ({"tier": "T1"}, {}, "card.tier"),
    ({"x": 0}, {"x": []}, "card.x"),
])
def test_diff_walk(a, b, path):
    assert det.determinism_check(canon(a), canon(b)).first_field == path
    assert det.determinism_check(canon(b), canon(a)).first_field == path


def test_duplicate_array_keys_refused():
    a = canon(dict(items=[dict(item_id="a", x=1), dict(item_id="a", x=2)]))
    with pytest.raises(ValueError, match="duplicate"):
        det.determinism_check(a, canon(dict(items=[])))
    with pytest.raises(ValueError, match="duplicate"):
        det.stable_fields(json.loads(a))


@pytest.mark.parametrize("raw", [b'{}\n', b'[]', b'{', b'{"x":1.5}', b'\xff'])
def test_projection_refusals(raw):
    with pytest.raises(ValueError):
        det.stable_projection(raw)
    with pytest.raises(ValueError):
        det.determinism_check(raw, raw)


def test_main(tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    raw = finalize(assemble(**inputs()), "PASS")
    a.write_bytes(raw)
    b.write_bytes(raw)
    assert det.main([str(a), str(b)]) == 0
    assert json.loads(capsys.readouterr().out)["identical"] is True
    b.write_bytes(canon(dict(json.loads(raw), tier="T0")))
    assert det.main([str(a), str(b)]) == 1
    assert json.loads(capsys.readouterr().out)["first_field"] == "card.tier"
    b.write_bytes(raw + b"\n")
    assert det.main([str(a), str(b)]) == 2
    assert capsys.readouterr().err.startswith("refused: ")
    assert det.main([str(a), str(tmp_path / "missing")]) == 2
    assert capsys.readouterr().err.startswith("refused: ")
    result = subprocess.run([sys.executable, "-m", "bicentennial.report.determinism", str(a), str(a)],
                            capture_output=True, check=True)
    assert result.stdout.strip() == canon(det.determinism_check(raw, raw).to_obj())


def test_constant_pins_and_field_order():
    assert gate.INVARIANTS == source_inv.INVARIANTS
    assert gate.GATED_T1 == source_inv.GATED_T1
    assert gate.INV_STATUSES == source_inv.STATUSES
    assert gate.VERDICT_KEYS == tuple(sorted(source_inv.Verdict.__dataclass_fields__))
    assert gate.CORPUS_KEYS == ("case_id", "first_diff", "reason", "status")
    assert gate.GATE_VERDICTS == ("PASS", "CONFORMANCE_PASS", "FAIL", "INVALID", "BLOCKED")
    assert gate.EXIT == dict(PASS=0, CONFORMANCE_PASS=0, FAIL=1, INVALID=1, BLOCKED=2)
    assert gate.ARMS == ("system", "wiped") and gate.ACCEPTED == ("PASS", "CONFORMANCE_PASS")
    rows = re.findall(r"^\| `([^`]+)` \| stable \| ([^\n]+) \|$",
                      (ROOT / "docs/scoring/STABLE-FIELDS.md").read_text(), re.MULTILINE)
    assert det.FIELD_ORDER == tuple(p for p, _ in rows)
    for path, key in det.ARRAY_KEYS.items():
        source = dict(rows)[path].split("order: ")[1]
        assert tuple(re.findall(r"`([^`]+)`", source)) == ((key,) if isinstance(key, str) else key)
    # All object-array order annotations, excluding repeated child annotations.
    arrays = {p for p, s in rows if "order:" in s and "[]" not in p
              and p not in ("card.items[].competing_present", "card.bundles[].items")}
    assert arrays == det.ARRAY_KEYS.keys()
    schema = json.loads((ROOT / "schemas/card_ring0.schema.json").read_bytes())
    assert schema["properties"]["gate_verdict"]["enum"] == list(gate.GATE_VERDICTS)
    assert canon(schema) == (ROOT / "schemas/card_ring0.schema.json").read_bytes()


def test_corpus_constant_pins_when_s12_merges():
    run = pytest.importorskip("bicentennial.corpus.run")
    assert gate.CORPUS_STATUSES == run.STATUSES
    assert gate.CORPUS_REASONS == run.REASONS


def test_import_and_string_hygiene():
    allowed = {"argparse", "copy", "hashlib", "json", "sys", "dataclasses", "collections.abc",
               "bicentennial.canon", "bicentennial.contracts.run"}
    for name in ("t1_gate", "determinism"):
        tree = ast.parse((ROOT / f"src/bicentennial/report/{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed and node.level == 0
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "lcm" not in node.value.lower()


def evidence_bytes():
    gates = [gate.t1_gate(*args, **kwargs).to_obj() for _, args, kwargs, _ in scenarios()]
    diffs = [det.determinism_check(a, b).to_obj() for a, b, _ in determinism_cases()]
    diffs += [det.determinism_check(b, a).to_obj() for a, b, _ in determinism_cases()]
    diffs += [det.determinism_check(a, b).to_obj() for a, b, _ in property_pairs()]
    return canon(dict(gates=gates, determinism=diffs))


def test_hash_seed_identity():
    outputs = []
    for seed in ("0", "random"):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve())], cwd=ROOT,
                                env=dict(os.environ, PYTHONHASHSEED=seed), capture_output=True, check=True)
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == evidence_bytes() + b"\n"


if __name__ == "__main__":
    print(evidence_bytes().decode())
