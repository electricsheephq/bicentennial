"""Offline, synthetic proof of the follow-up's frozen lists and reading rules."""

import importlib.util
import json
import shutil
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KINDS = ("drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3", "wake-loop-v1")
DESC = ("recall-value-v1", "drift-asof-v1")
G1 = tuple(f"SYNTHETICG1{n}" for n in range(5))
G2 = tuple(f"SYNTHETICG2{n}" for n in range(5))
IDENTITY = "synthetic-served-identity-value"
COMMIT = "a" * 40
HASHES = {"system_hash": "1" * 64, "harness_hash": "2" * 64, "route_table_hash": "3" * 64}
ORDER = tuple(f"{p}.{a}" for p, arms in (
    ("A", "F1 R1 O1 H1 H2 O2 R2 F2 O3 B1 G1 W1"),
    ("B", "F1 R1 O1 H1 H2 O2 R2 F2 O3 G1 W1 B1"),
    ("C", "F1 R1 O1 H1 H2 O2 R2 F2 O3 W1 B1 G1")) for a in arms.split())
RERUN = "rerun once (§3, §4), then run again with --after-reruns"


def module(name):
    spec = importlib.util.spec_from_file_location(f"followup_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return path


def edit(path, change):
    obj = json.loads(path.read_bytes())
    change(obj)
    write(path, obj)


def layout():
    rows = []
    for genre, lives in (("G1", G1), ("G2", G2)):
        for n, life in enumerate(lives):
            refs = KINDS if genre == "G1" else ("drift-booking-v1",)
            for j, ref in enumerate(refs):
                for b in (0, 1):
                    table = ("drift-config-corrected-v3", "drift-config-hedged-v3")[b] if ref == KINDS[1] else ref
                    rows.append((genre, dict(life=life, branch=f"B{b}", item_id=f"SYNITEM{genre}{n}{j}{b}",
                                             template_id=ref.rsplit("-v", 1)[0], template_version=int(ref[-1]),
                                             bundle_id=f"SYNBUNDLE{genre}{n}{j}"),
                                 dict(stage="act", decision_table_ref=table)))
            for ref in ((DESC[0],) if genre == "G1" else (DESC[1], "recall-count-v1")):
                rows.append((genre, dict(life=life, branch="B0", item_id=f"SYNITEM{genre}{n}{ref}",
                                         template_id=ref.rsplit("-v", 1)[0], template_version=1, bundle_id=None),
                             dict(stage="qa", decision_table_ref=None)))
    return [(g, r, dict(i, item_id=r["item_id"])) for g, r, i in rows]


def scripted(life, control, pack):
    mine = [r for _, r, _ in layout() if r["life"] == life]
    present = pack == "B"
    score = {"naive_rag": 1000, "bm25": -1000, "grep": 1000, "recent_window": -1000}[control]
    score *= {"A": 1, "B": 0, "C": -1}[pack]
    return dict(reports=[dict(item_id=r["item_id"], in_context=present) for r in mine],
                items=[dict(item_id=r["item_id"], score_milli=score, failure_class=None) for r in mine])


def make_packs(root, letter, records=None):
    source = layout() if records is None else records
    for genre, lives in (("G1", G1), ("G2", G2)):
        for life in lives:
            mine = [(r, i) for g, r, i in source if g == genre and r["life"] == life]
            sealed = root / "pack" / genre / life / "7" / "sealed"
            write(sealed / "records.json", [r for r, _ in mine])
            write(sealed / "pack.json", dict(genre=genre, items=[i for _, i in mine], text="synthetic task text"))
            write(sealed / "scoring.json", {})
            write(sealed / "naive_rag.json", dict(arm=scripted(life, "naive_rag", letter)))
            # Real life manifests carry no scoring-code pin; the pack index holds it.
            write(sealed.parent / "manifest.json", dict(pins=dict(zip(
                ("controls_sha256", "reader_sha256", "scorer_sha256"), (c * 64 for c in "9ac"), strict=True))))
    write(root / "index.json", dict(label=letter, pins=dict(scoring_code_sha256="b" * 64)))
    return root


@pytest.fixture
def tasks():
    return module("tasks")


@pytest.fixture
def table():
    return module("table")


@pytest.fixture
def run(tmp_path, monkeypatch, capsys, table):
    def reports(packs):
        report = {life: {control: {field: {r["item_id"]: r for r in scripted(life, control, packs.name)[field]}
                  for field in ("reports", "items")} for control in ("naive_rag", "bm25", "grep", "recent_window")}
                  for life in (*G1, *G2)}
        keys = {(rec["life"], rec["branch"], rec["item_id"]) for _, rec, _ in layout()}
        return (report, keys), None
    monkeypatch.setattr(table, "scripted_reports", reports)
    monkeypatch.setattr(table, "recompute_blocks", lambda packs, arm: {"synthetic": "4" * 64})
    monkeypatch.setattr(table, "frame_sha256", lambda: "5" * 64)
    packs, paths, frozen = {}, {}, {}
    for p in "ABC":
        packs[p] = make_packs(tmp_path / p, p)
        records = table.frozen.pack_records(packs[p])
        rows, reason = table.frozen.target_rows(records)
        assert reason is None
        desc, reason = table.frozen.descriptive_rows(records)
        assert reason is None
        frozen[p] = write(tmp_path / f"TASKS-{p}.json", dict(header=dict(commit=COMMIT, edition=3, pack=p,
            spec_sha256=sha256(p.encode()).hexdigest(), draw_sha256="6" * 64,
            pack_hash=table.pack_tree_hash(packs[p])), rows=rows, descriptive=desc))
    check3 = tmp_path / "check3.txt"
    check3.write_text("\n".join([f"commit {COMMIT}", *(f"suite::{t} PASSED" for t in table.CHECK3_TESTS), "exit 0"]))
    tree_hashes = {p: table.pack_tree_hash(packs[p]) for p in "ABC"}
    for slot, label in enumerate(ORDER):
        p, repeat = label.split(".")
        row = repeat[0]
        path = tmp_path / "arms" / label
        paths[label] = path
        units = {f"{life}/{b}": dict(cached=False) for life in (*G1, *G2) for b in ("B0", "B1")}
        outcomes, probes, card_items = {}, {u: [] for u in units}, []
        for _genre, rec, item in layout():
            key = "/".join(rec[k] for k in ("life", "branch", "item_id"))
            ref = f"{rec['template_id']}-v{rec['template_version']}"
            score = 1000 if row in ("O", "H") else 0
            if ref in DESC:
                score = 500 if p == "B" else 1000
            outcomes[key] = dict(score_milli=score, failure_class=None, template_ref=ref, stage=item["stage"])
            unit = f"{rec['life']}/{rec['branch']}"
            probes[unit].append(dict(item_id=rec["item_id"], live=dict(served_by="live"),
                                     shadow=dict(in_context_initial=row == "O" or p == "B")))
            card_items.append(dict(rec, score_milli=score))
        control = table.CONTROL.get(row)
        write(path / "card.json", dict(pins=dict(benchmark_commit=COMMIT, scorer_commit="b" * 40, **HASHES),
            pack_hash=tree_hashes[p], system="hermes-native", served_identity=IDENTITY,
            floor=dict(units=units), items=card_items))
        write(path / "outcomes.json", outcomes)
        write(path / "units.json", dict(start_ms=slot * 10000, end_ms=slot * 10000 + 1000))
        write(path / "disclosures.json", dict(floor=units, live=dict(identity_drift=None, sends=100,
            phase_sends=dict(floor=40, system=60)), unreadable_state=[]))
        receipt = dict(tokens_by_role=[dict(role="summariser", input=0, output=0)])
        write(path / "receipt.json", receipt)
        write(path / "receipts/system.json", receipt)
        write(path / f"{control or 'no_memory'}.json", {u: dict(stops={u.replace('/', ''): None}) for u in units})
        if control:
            meta = dict(arm=control, frame_sha256=None if row == "F" else "5" * 64,
                        block_sha256={} if row == "F" else {"synthetic": "4" * 64})
            if row in "BGW":
                meta["anchor"] = table.rules.card_anchors()[control]
            if row in "GW":
                meta["reader_window"] = 32768
            write(path / "control.json", meta)
        for unit, records in probes.items():
            write(path / (control or "system") / unit / "t2lite_probes.json", records)
    capsys.readouterr()
    def go(flags=(), order=ORDER, attempts=ORDER, extra=(), omit=(), digests=None):
        argv = []
        for p in "ABC":
            argv += ["--pack", p, str(packs[p]), str(frozen[p]), (digests or {}).get(p, sha256(frozen[p].read_bytes()).hexdigest())]
        for key, value in HASHES.items():
            argv += ["--" + key.replace("_", "-"), value]
        argv += ["--order", ",".join(order), "--check3", str(check3), *flags]
        if attempts is not None:
            argv += ["--attempts", ",".join(attempts)]
        argv += [f"{label}={paths[label]}" for label in ORDER if label not in omit]
        code = table.main([*argv, *extra])
        return code, capsys.readouterr().out
    go.paths, go.packs, go.tasks, go.check3 = paths, packs, frozen, check3
    return go


def test_task_list_and_header(tasks, tmp_path, capsys):
    packs = make_packs(tmp_path / "A", "A")
    spec, draw = write(tmp_path / "spec.toml", {}), write(tmp_path / "draw.json", [])
    out = tmp_path / "tasks.json"
    argv = ["--pack", "A", "--packs", str(packs), "--spec", str(spec), "--draw", str(draw),
            "--commit", COMMIT, "--edition", "3", "--out", str(out)]
    assert tasks.main(argv) == 0
    data = json.loads(out.read_bytes())
    assert len(data["rows"]) == 40 and len(data["descriptive"]) == 10
    assert set(data["header"]) == {"commit", "edition", "spec_sha256", "draw_sha256", "pack_hash", "pack"}
    assert data["header"]["pack"] == "A" and out.read_bytes() == tasks.canon(data)
    for section in ("rows", "descriptive"):
        assert all(set(row) == {"life", "branch", "item_id", "template_ref", "bundle_id", "decision_table_ref"}
                   for row in data[section])
        assert data[section] == sorted(data[section], key=lambda r: (r["life"], r["branch"], r["item_id"]))
    assert b"recall-count-v1" not in out.read_bytes()
    assert "synthetic task text" not in capsys.readouterr().out
    for flag, bad in (("--pack", "D"), ("--commit", "short"), ("--edition", "2")):
        changed = argv.copy()
        changed[changed.index(flag) + 1] = bad
        out.unlink(missing_ok=True)
        assert tasks.main(changed) == 3 and not out.exists()


@pytest.mark.parametrize("fault", ("four_g1", "four_g2", "shared_life", "g2_target", "missing_twin", "two_pairs",
    "wrong_table", "corrected_twice", "wrong_version", "nonaction", "no_bundle", "duplicate_key", "descriptive_twice",
    "desc_action", "desc_twin"))
def test_frozen_rows_refuse_each_fault(tasks, fault, tmp_path, capsys):
    records = deepcopy(layout())
    if fault == "four_g1":
        records = [x for x in records if x[1]["life"] != G1[-1]]
    elif fault == "four_g2":
        records = [x for x in records if x[1]["life"] != G2[-1]]
    elif fault == "shared_life":
        # Every record of one G2 life carries a G1 life's name, so each genre still counts five lives.
        for genre, rec, _ in records:
            if genre == "G2" and rec["life"] == G2[0]:
                rec["life"] = G1[0]
    elif fault == "g2_target":
        records.append(("G2", dict(records[0][1], life=G2[0]), records[0][2]))
    elif fault == "missing_twin":
        records.pop(0)
    elif fault == "two_pairs":
        records += [(g, dict(r, item_id=r["item_id"] + "extra", bundle_id="extra"), i)
                    for g, r, i in records[:2]]
    elif fault == "wrong_table":
        records[0][2]["decision_table_ref"] = "wrong"
    elif fault == "corrected_twice":
        records[3][2]["decision_table_ref"] = "drift-config-corrected-v3"
    elif fault == "wrong_version":
        records[0][1]["template_version"] = 2
    elif fault == "nonaction":
        records[0][2]["stage"] = "qa"
    elif fault == "no_bundle":
        for _, rec, _ in records[:2]:
            rec["bundle_id"] = None
    elif fault == "duplicate_key":
        records[2][1]["item_id"] = records[0][1]["item_id"]
    else:
        n = next(n for n, (_, r, _) in enumerate(records) if r["template_id"] == "recall-value")
        if fault == "descriptive_twice":
            records.append(deepcopy(records[n]))
        elif fault == "desc_action":
            records[n][2]["stage"] = "act"
        else:
            records[n][1]["bundle_id"] = "descriptive-bundle"
    func = tasks.descriptive_rows if fault.startswith("desc") else tasks.target_rows
    rows, reason = func(records)
    assert rows is None and reason
    if fault in ("four_g2", "shared_life"):
        assert reason == "pack composition must be five G1 and five G2 lives"
    if fault == "shared_life":
        # The fixture writer files records by their life; relabel the sealed G2 life in place instead.
        packs = make_packs(tmp_path / "invalid", "A")
        edit(packs / "pack/G2" / G2[0] / "7/sealed/records.json", lambda o: [r.update(life=G1[0]) for r in o])
        assert tasks.target_rows(tasks.pack_records(packs))[1] == reason
    else:
        packs = make_packs(tmp_path / "invalid", "A", records=records)
    spec, draw = write(tmp_path / "spec.toml", {}), write(tmp_path / "draw.json", [])
    out = tmp_path / "tasks.json"
    code = tasks.main(["--pack", "A", "--packs", str(packs), "--spec", str(spec), "--draw", str(draw),
                       "--commit", COMMIT, "--edition", "3", "--out", str(out)])
    assert code == 3 and not out.exists() and capsys.readouterr().out.startswith("REFUSED:")


@pytest.fixture(scope="module")
def real_pack(tmp_path_factory):
    from bicentennial.packs import build, install
    root = tmp_path_factory.mktemp("public-edition3")
    build.build_tier("T2", root / "built", harness_artifacts=[dict(name="hermes", version="synthetic", sha256="a" * 64)],
                     spec_path=ROOT / "tiers/life_specs/t2.toml", edition=3)
    install.install(root / "built/T2", root / "installed")
    return root / "installed"


def test_public_edition3_pack(tasks, table, real_pack, tmp_path):
    records = tasks.pack_records(real_pack)
    rows, reason = tasks.target_rows(records)
    assert reason is None and len(rows) == 40
    desc, reason = tasks.descriptive_rows(records)
    assert reason is None and len(desc) == 10
    data = dict(header=dict(pack="A", edition=3, commit=COMMIT, draw_sha256="a" * 64,
                spec_sha256="b" * 64, pack_hash=table.pack_tree_hash(real_pack)), rows=rows, descriptive=desc)
    path = write(tmp_path / "tasks.json", data)
    pack = table.load_pack("A", real_pack, path, sha256(path.read_bytes()).hexdigest())
    assert table.scripted_reports is table.rules.load_pack
    assert len(pack["reports"]) == 10
    assert all(set(reports) == {"naive_rag", "bm25", "grep", "recent_window"}
               for reports in pack["reports"].values())


@pytest.mark.parametrize("fault", ("label_missing", "label_extra", "label_duplicate", "sha", "letter", "edition",
    "pack_hash", "rows", "descriptive", "commit", "draw", "shared_pack", "shared_spec", "no_control",
    "wrong_control", "no_receipt", "h_control", "h_system", "arm_commit", "noncanonical"))
def test_input_refusals(run, fault):
    path = run.paths["A.R1"]
    flags, extra, omit, digests = (), (), (), None
    if fault.startswith("label_"):
        if fault == "label_missing":
            omit = ("A.R1",)
        elif fault == "label_duplicate":
            extra = ("A.F1=unused",)
        else:
            extra = ("D.F1=unused",)
    elif fault == "noncanonical":
        path = run.tasks["A"]
        path.write_text(json.dumps(json.loads(path.read_bytes()), indent=2))
    elif fault in ("sha", "letter", "edition", "pack_hash", "rows", "descriptive", "commit", "draw", "shared_pack", "shared_spec"):
        def change(obj):
            if fault == "sha":
                return
            if fault in ("rows", "descriptive"):
                obj[fault].pop()
            elif fault in ("shared_pack", "shared_spec"):
                key = "pack_hash" if fault == "shared_pack" else "spec_sha256"
                obj["header"][key] = json.loads(run.tasks["B"].read_bytes())["header"][key]
            else:
                key = {"letter": "pack", "sha": "draw_sha256", "draw": "draw_sha256"}.get(fault, fault)
                obj["header"][key] = (2 if fault == "edition" else "d" * 40 if fault == "commit"
                                      else "7" * 64 if fault in ("draw", "pack_hash") else "bad")
        edit(run.tasks["A"], change)
        if fault == "shared_pack":
            run.packs["A"] = run.packs["B"]
        if fault == "commit":
            for arm_path in run.paths.values():
                (arm_path / "card.json").unlink()
        if fault == "sha":
            digests = {"A": "0" * 64}
    elif fault == "no_control":
        (path / "control.json").unlink()
    elif fault == "wrong_control":
        edit(path / "control.json", lambda o: o.update(arm="bm25"))
    elif fault == "no_receipt":
        (path / "receipt.json").unlink()
    elif fault == "h_control":
        write(run.paths["A.H1"] / "control.json", {})
    elif fault == "h_system":
        edit(run.paths["A.H1"] / "card.json", lambda o: o.update(system="wrong"))
    else:
        edit(path / "card.json", lambda o: o["pins"].update(benchmark_commit="c" * 40))
    code, out = run(flags=flags, extra=extra, omit=omit, digests=digests)
    assert code == 3 and "REFUSED:" in out and "== 3. Scores" not in out


@pytest.mark.parametrize("fault", ("block", "anchor", "window", "presence", "cached", "probe_missing",
                                   "probe_duplicate", "stopped", "compacted"))
def test_control_checks_are_pack_local(run, fault):
    path = run.paths["B.G1"]
    probe = path / "grep" / G1[0] / "B0/t2lite_probes.json"
    if fault in ("block", "anchor", "window"):
        edit(path / "control.json", lambda o: o.update(**{
            {"block": "block_sha256", "anchor": "anchor", "window": "reader_window"}[fault]: None}))
    elif fault == "presence":
        edit(probe, lambda o: o[0]["shadow"].update(in_context_initial=False))
    elif fault == "cached":
        edit(path / "card.json", lambda o: next(iter(o["floor"]["units"].values())).update(cached=True))
    elif fault == "probe_missing":
        probe.unlink()
    elif fault == "probe_duplicate":
        edit(probe, lambda o: o.append(o[0]))
    elif fault == "stopped":
        edit(path / "grep.json", lambda o: next(iter(o.values())).update(stops={}))
    else:
        edit(path / "receipt.json", lambda o: o["tokens_by_role"][0].update(input=1))
    code, out = run()
    if fault == "compacted":
        assert code == 4 and "pending before any score: B.G1 - rerun once (§3, §4)" in out
    else:
        assert code == 3 and [s for s in out.splitlines() if s.startswith("INVALID CONTROL ROW")] == ["INVALID CONTROL ROW B.G1"]
    assert "== 3. Scores" not in out
    if fault == "stopped":
        write(path / "grep.json", None)
        code, out = run()
        assert code == 3 and "INVALID CONTROL ROW B.G1" in out


def test_reference_uses_controls_and_tie_order(run, table):
    for label in ORDER:
        if ".H" in label:
            edit(run.paths[label] / "card.json", lambda o: o.update(served_identity="different"))
    code, out = run()
    assert code == 4 and "pending before any score: A.H1 A.H2 B.H1 B.H2 C.H1 C.H2 -" in out
    arms = {k: dict(card=dict(served_identity="first" if n < 15 else "second"))
            for n, k in enumerate(k for k in ORDER if ".H" not in k)}
    assert table.reference_identity(arms, list(arms)) == "first"
    assert table.reference_identity(arms, list(reversed(arms))) == "second"
    arms.update({k: dict(card=dict(served_identity="second")) for k in ORDER if ".H" in k})
    assert table.reference_identity(arms, list(arms)) == "first"
    for k in arms:
        arms[k]["card"]["served_identity"] = "second" if k != "A.F1" else "first"
    assert table.reference_identity(arms, list(arms)) == "second"


@pytest.mark.parametrize("first,second", (("A", "B"), ("B", "A")))
def test_reference_tie_excludes_earliest_minority(run, table, first, second):
    controls = [k for k in ORDER if ".H" not in k]
    identities = dict(zip(controls, ["C", first, second] + [first] * 13 + [second] * 13 + ["C"], strict=True))
    for label in ORDER:
        identity = identities.get(label, "C")
        edit(run.paths[label] / "card.json", lambda o, value=identity: o.update(served_identity=value))
    code, out = run(flags=("--checks-only",))
    assert code == 4
    assert "reference identity " + table.short(first) + "\n" in out
    for label in controls:
        assert f"check 4 {label}: identity pass {identities[label] == first}\n" in out
    for label in ORDER:
        if ".H" in label:
            assert f"check 4 {label}: identity pass False\n" in out


@pytest.mark.parametrize("used_identity", ("A", "B"), ids=("used-position", "used-identity"))
def test_reference_tie_uses_rerun_identity_and_position(run, table, used_identity):
    controls = [k for k in ORDER if ".H" not in k and k != "A.F1"]
    # The used arms tie 14:14; the earliest remaining control carries C, then B.
    remaining_a = 14 - (used_identity == "A")
    remaining_b = 14 - (used_identity == "B")
    values = ["C", "B", "C"] + ["A"] * remaining_a + ["B"] * (remaining_b - 1)
    identities = dict(zip(controls, values, strict=True))
    for label in ORDER:
        identity = identities.get(label, "A" if label == "A.F1" else "C")
        edit(run.paths[label] / "card.json", lambda o, value=identity: o.update(served_identity=value))
    first_attempt = run.paths["A.F1"]
    used_attempt = first_attempt.with_name("A.F1.rerun")
    shutil.copytree(first_attempt, used_attempt)
    edit(used_attempt / "card.json", lambda o: o.update(served_identity=used_identity))
    run.paths["A.F1"] = used_attempt
    set_rerun_time(run, "A.F1")
    code, out = run(flags=("--checks-only", "--reruns", "A.F1"), order=rerun_order("A.F1"),
                    attempts=(*ORDER, "A.F1.rerun"))
    assert code == 4
    assert "reference identity " + table.short("B") + "\n" in out
    assert f"check 4 A.F1: identity pass {used_identity == 'B'}\n" in out
    assert json.loads((first_attempt / "card.json").read_bytes())["served_identity"] == "A"


@pytest.mark.parametrize("value", ("drift", "absent"))
def test_identity_disclosure_required(run, value):
    disclosures = run.paths["A.F1"] / "disclosures.json"
    original = disclosures.read_bytes()
    edit(disclosures, lambda o: o["live"].update(identity_drift="changed")
         if value == "drift" else o["live"].pop("identity_drift"))
    code, out = run()
    assert code == 4 and f"pending before any score: A.F1 - {RERUN}\n" in out
    if value == "absent":
        # Restore the control arm first, so only H's missing disclosure can hold the scores.
        disclosures.write_bytes(original)
        write(run.paths["A.H1"] / "disclosures.json", None)
        code, out = run()
        assert code == 4 and f"pending before any score: A.H1 - {RERUN}\n" in out
        assert "check 4 A.H1: identity pass False\n" in out


@pytest.mark.parametrize("key", tuple(HASHES))
def test_h_commitment_hashes(run, key):
    # All cards still share pins; the posted commitment differs, isolating H's check 4.
    assert run(flags=("--" + key.replace("_", "-"), "7" * 64))[0] == 4


@pytest.mark.parametrize("fault", ("missing", "duplicate", "wrong_unit", "copied_unit", "not_live", "own_failure",
                                   "neighbour_failure"))
def test_h_probe_coverage_and_item_exception(run, fault):
    path = run.paths["A.H1"]
    probe = path / "system" / G1[0] / "B0/t2lite_probes.json"
    if fault == "missing":
        edit(probe, lambda o: o.pop(0))
    elif fault == "duplicate":
        edit(probe, lambda o: o.append(o[0]))
    elif fault == "wrong_unit":
        records = json.loads(probe.read_bytes())
        edit(probe, lambda o: o.pop(0))
        edit(path / "system" / G1[1] / "B0/t2lite_probes.json", lambda o: o.append(records[0]))
    elif fault == "copied_unit":
        # The original stays in place, so coverage holds and only the misplaced copy fails.
        records = json.loads(probe.read_bytes())
        edit(path / "system" / G1[1] / "B0/t2lite_probes.json", lambda o: o.append(records[0]))
    else:
        edit(probe, lambda o: o[0]["live"].update(served_by="scripted"))
        if fault != "not_live":
            outcomes = json.loads((path / "outcomes.json").read_bytes())
            keys = list(outcomes)
            key = next(k for k in keys if k.endswith(json.loads(probe.read_bytes())[0 if fault == "own_failure" else 1]["item_id"]))
            outcomes[key].update(failure_class="SYSTEM_FAILURE", score_milli=0)
            write(path / "outcomes.json", outcomes)
    code, out = run()
    assert code == (0 if fault == "own_failure" else 4)
    assert "check 7 A.H1:" in out
    if fault == "copied_unit":
        assert "check 7 A.H1: targets 40 covered_once 40 duplicated 0 misplaced 1 not_live_unexcused 0" in out
        assert f"pending before any score: A.H1 - {RERUN}\n" in out


@pytest.mark.parametrize("value,ok", ((None, True), ({"attempts": [{"attempt": 0, "stopped": None}]}, True),
    ({"attempts": [{"attempt": 0, "stopped": ["SYSTEM_FAILURE", "synthetic", 1]}]}, True),
    ({"attempts": [{"attempt": 0, "stopped": ["INFRA_FAILURE", "synthetic", 1]}]}, False),
    ({"attempts": [{"attempt": 0, "stopped": ["INFRA_FAILURE", "synthetic", 1]}, {"attempt": 1, "stopped": None}]}, True),
    ({"attempts": []}, False), ({"attempts": [{}]}, False), ("unreadable", False)))
def test_system_stop_fixture_table(table, tmp_path, value, ok):
    path = tmp_path / "unit_diagnostics.json"
    if value == "unreadable":
        path.write_text("{")
    elif value is not None:
        write(path, value)
    assert table.system_stop(path) is ok


def test_system_stop_on_g2_is_checked(run):
    write(run.paths["A.H1"] / "system" / G2[-1] / "B1/unit_diagnostics.json",
          dict(attempts=[dict(attempt=0, stopped=["INFRA_FAILURE", "synthetic", 1])]))
    assert run()[0] == 4


def test_h_coverage_uses_unit_qualified_keys(table, tmp_path):
    rows = [dict(life=life, branch="B0", item_id="invented-shared-id") for life in G1[:2]]
    for row in rows:
        write(tmp_path / "system" / row["life"] / "B0/t2lite_probes.json",
              [dict(item_id=row["item_id"], live=dict(served_by="live"))])
    arm = dict(run=tmp_path, name="A.H1", outcomes={})
    pack = dict(tasks=dict(rows=rows), reports=dict.fromkeys(G1[:2], {}))
    assert table.system_live(arm, pack)


def rerun_order(label):
    return tuple(k for k in ORDER if k != label) + (label,)


def set_rerun_time(run, label):
    edit(run.paths[label] / "units.json", lambda o: o.update(start_ms=400000, end_ms=401000))


def after_reruns(run, labels, flags=()):
    """Read with --after-reruns once each label's one rerun has run, after all 36 first attempts."""
    for n, label in enumerate(labels):
        edit(run.paths[label] / "units.json", lambda o, n=n: o.update(start_ms=400000 + n * 10000,
                                                                      end_ms=401000 + n * 10000))
    return run(flags=("--after-reruns", "--reruns", ",".join(labels), *flags),
               order=tuple(k for k in ORDER if k not in labels) + tuple(labels),
               attempts=(*ORDER, *(k + ".rerun" for k in labels)))


@pytest.mark.parametrize("fault", ("block", "presence", "stop"))
def test_second_control_fault_ends_even_if_first_failed_identity(run, fault):
    path = run.paths["A.R1"]
    edit(path / "card.json", lambda o: o.update(served_identity="first-attempt-mismatch"))
    assert run()[0] == 4
    edit(path / "card.json", lambda o: o.update(served_identity=IDENTITY))
    if fault == "block":
        edit(path / "control.json", lambda o: o.update(block_sha256={}))
    elif fault == "presence":
        edit(path / "naive_rag" / G1[0] / "B0/t2lite_probes.json",
             lambda o: o[0]["shadow"].update(in_context_initial=True))
    else:
        edit(path / "naive_rag.json", lambda o: next(iter(o.values())).update(stops={}))
    set_rerun_time(run, "A.R1")
    code, out = run(flags=("--reruns", "A.R1"), order=rerun_order("A.R1"), attempts=(*ORDER, "A.R1.rerun"))
    assert code == 5 and "RUN ENDS:" in out and "(§4); no score is opened" in out
    assert all(f"reading {t}: unresolved" in out for t in KINDS)
    assert "== 3. Scores" not in out


def test_check3_and_checks_only(run):
    assert run(flags=("--checks-only",))[0] == 0
    assert "== 3. Scores" not in run(flags=("--checks-only",))[1]
    run.check3.write_text("exit 1")
    assert run()[0] == 3
    code, out = run(flags=("--after-reruns",))
    assert code == 5 and "missing observations: " + " ".join(ORDER) in out


@pytest.mark.parametrize("fault", ("pin", "pack", "no_time", "failed_test", "wrong_commit", "no_exit"))
def test_global_check_faults(run, fault):
    path = run.paths["A.F1"]
    if fault == "pin":
        edit(path / "card.json", lambda o: o["pins"].update(scorer_commit="d" * 40))
    elif fault == "pack":
        edit(path / "card.json", lambda o: o.update(pack_hash="0" * 64))
    elif fault == "no_time":
        edit(path / "units.json", lambda o: o.pop("end_ms"))
    else:
        text = run.check3.read_text()
        if fault == "failed_test":
            text += "\nsuite::test_c_floor_bodies_and_memory_off FAILED\nexit 0"
        elif fault == "wrong_commit":
            text = text.replace(COMMIT, "d" * 40)
        else:
            text = text.removesuffix("exit 0")
        run.check3.write_text(text)
    code, out = run()
    assert code == 3 and "== 3. Scores" not in out


def test_also_printed_uses_runner_shapes(run):
    path = run.paths["A.H1"]
    units = json.loads((path / "card.json").read_bytes())["floor"]["units"]
    first, second = list(units)[:2]
    edit(path / "card.json", lambda o: o["floor"]["units"][first].update(cached=True))
    edit(path / "no_memory.json", lambda o: o[second].update(stops={}))
    edit(path / "disclosures.json", lambda o: o.update(unreadable_state=dict(system=7, no_memory=3)))
    edit(path / "receipts/system.json", lambda o: o["tokens_by_role"][0].update(input=23, output=11))
    edit(path / "receipt.json", lambda o: o["tokens_by_role"][0].update(input=99, output=77))
    code, out = run()
    assert code == 0 and "A.H1 floor live 18 cached or unconfirmed 1 stopped or not recorded 1" in out
    assert "A.H1 summariser input 23 output 11" in out
    assert "A.H1 sends 100 start 30000 end 31000 served identity " in out
    assert "A.H1 phase sends floor 40 system 60" in out
    for p in "ABC":
        for key, prefix in zip(("controls_sha256", "reader_sha256", "scoring_code_sha256", "scorer_sha256"), "9abc", strict=False):
            assert f"pack code pin {p} {key} {prefix * 12}\n" in out
    for p, score in (("A", 100), ("B", 0), ("C", -100)):
        assert f"scripted beside live {p} R {KINDS[0]} scripted points {score} ({score:.1f}) live points 0" in out
    assert any(line.startswith("A.H1 sends") and line.endswith("unreadable_state 7") for line in out.splitlines())
    assert "three packs code pins agree True" in out
    write(path / "no_memory.json", None)
    code, out = run()
    assert code == 0 and "A.H1 floor live 0 cached or unconfirmed 1 stopped or not recorded 19" in out


@pytest.mark.parametrize("fault", ("rotated", "early_rerun", "overlap", "no_attempts"))
def test_order_faults(run, fault):
    order, attempts, flags = ORDER, ORDER, ()
    if fault == "rotated":
        order = ORDER[:21] + ("B.B1", "B.G1", "B.W1") + ORDER[24:]
        attempts = order
    elif fault == "early_rerun":
        order, attempts, flags = rerun_order("A.F1"), (*ORDER[:1], "A.F1.rerun", *ORDER[1:]), ("--reruns", "A.F1")
    elif fault == "overlap":
        edit(run.paths["A.R1"] / "units.json", lambda o: o.update(start_ms=0))
    else:
        attempts = None
    code, out = run(flags=flags, order=order, attempts=attempts)
    assert code == 3 and "== 3. Scores" not in out


@pytest.mark.parametrize("lost,readings,room,use", (("C.H2", "ranking candidate", "holds", "unresolved"),
    ("B.O3", "unresolved", "holds", "holds"), ("A.W1", "unresolved", "unresolved", "unresolved")))
def test_missing_data_preserves_independent_readings(run, lost, readings, room, use):
    (run.paths[lost] / "card.json").unlink()
    code, pending = run()
    assert code == 4 and f"pending before any score: {lost} - rerun once (§3, §4), then run again with --after-reruns" in pending
    code, out = after_reruns(run, [lost])
    assert code == 0 and all(f"reading {t}: {readings}" in out for t in KINDS)
    assert f"Room: {room}" in out and f"Use: {use}" in out
    if lost == "A.W1":
        assert "Room against R: holds" in out and "Use against R: holds" in out


def test_h_rerun_failure_does_not_suppress_controls(run):
    edit(run.paths["C.H2"] / "card.json", lambda o: o.update(served_identity="different"))
    assert run()[0] == 4
    set_rerun_time(run, "C.H2")
    code, out = run(flags=("--after-reruns", "--reruns", "C.H2"), order=rerun_order("C.H2"),
                    attempts=(*ORDER, "C.H2.rerun"))
    assert code == 0 and "Use: unresolved" in out and "Room: holds" in out
    assert all(f"reading {t}: ranking candidate" in out for t in KINDS)


def test_unscored_pair_is_kind_local(run):
    edit(run.paths["A.W1"] / "outcomes.json", lambda o: next(iter(o.values())).update(score_milli=None))
    code, out = after_reruns(run, ["A.W1"])
    assert code == 0 and f"reading {KINDS[0]}: unresolved" in out
    assert all(f"reading {t}: ranking candidate" in out for t in KINDS[1:])
    assert "Room against W: unresolved" in out and "Room against R: holds" in out


def test_h_incomplete_target_excludes_the_whole_arm(run):
    edit(run.paths["A.H1"] / "outcomes.json", lambda o: next(iter(o.values())).update(score_milli=None))
    code, out = after_reruns(run, ["A.H1"])
    assert code == 0 and "Use: unresolved" in out and "Room: holds" in out
    for kind in KINDS:
        assert f"pooled repeat H1 {kind} pairs 15 right 0 wrong 0 without_credit 0 non_result 15 points n/a incomplete" in out


def test_no_arms_contract(run):
    for path in run.paths.values():
        (path / "card.json").unlink()
    code, out = run()
    assert code == 4 and out.count(": missing") == 36
    assert "pending before any score: " + " ".join(ORDER) + " - rerun once (§3, §4), then run again with --after-reruns" in out
    assert run(flags=("--after-reruns",))[0] == 3


def reading_fixture(table, values):
    members = [dict(template=KINDS[0], life=("A", str(n)), keys=(f"{n}a", f"{n}b")) for n in range(15)]
    used = {}
    for row, repeats in table.ROWS.items():
        used[row] = []
        for repeat in repeats:
            scores = values.get(repeat, [1000 if row == "O" else 0] * 15)
            used[row].append(dict(name=repeat, outcomes={key: dict(score_milli=score, failure_class=None)
                for b, score in zip(members, scores, strict=False) for key in b["keys"]}))
    return dict(use={KINDS[0]: used}, members={KINDS[0]: members}, left={KINDS[0]: {}})


def test_readings_precedence_and_combination_counts(table):
    ctx = reading_fixture(table, {})
    lines, result = table.reading(ctx, KINDS[0])
    assert result == "ranking candidate"
    assert [int(line.split("combinations ")[1].split()[0]) for line in lines if "combinations " in line] == [3, 12, 6, 6, 6, 6]
    for values, expected in ((dict(O1=[0] * 15), "unstable"),
        (dict.fromkeys(("O1", "O2", "O3"), [0] * 15), "low"), (dict(F1=[1000] * 15, F2=[1000] * 15), "cleared")):
        ctx = reading_fixture(table, values)
        assert table.reading(ctx, KINDS[0])[1] == expected
        ctx["left"][KINDS[0]]["F1"] = "missing"
        assert table.reading(ctx, KINDS[0])[1] == "unresolved"


@pytest.mark.parametrize("row", ("R", "B", "G", "W"))
def test_each_anchor_above_35_prevents_candidate(table, row):
    ctx = reading_fixture(table, {r: [1000] * 6 + [0] * 9 for r in table.ROWS[row]})
    assert table.reading(ctx, KINDS[0])[1] == "cleared"


def test_single_combination_flip_prevents_candidate(table):
    ctx = reading_fixture(table, dict(F1=[-1000] * 15, F2=[1000] * 9 + [0] * 6,
        R1=[1000] * 4 + [0] * 11, R2=[-1000] * 12 + [0] * 3,
        O2=[1000] * 14 + [0], O3=[1000] * 12 + [0] * 3))
    lines, result = table.reading(ctx, KINDS[0])
    assert result == "cleared" and any("combinations 12 agreeing 11" in line for line in lines)


def test_reading_c_uses_only_two_trials(table):
    lines, result = table.reading(reading_fixture(table, dict(O3=[-1000] * 15)), KINDS[0])
    assert lines[0].endswith("c 100 (100.0)") and result == "unstable"


def test_lower_twin_and_pooled_points(run):
    path = run.paths["A.R1"] / "outcomes.json"
    def change(obj):
        for key, value in obj.items():
            if key.startswith(G1[0] + "/") and value["template_ref"] == KINDS[0]:
                value["score_milli"] = 1000 if "/B0/" in key else -1000
    edit(path, change)
    code, out = run()
    assert code == 0
    assert f"A.R1 {KINDS[0]} pairs 5 right 0 wrong 1 without_credit 4 non_result 0 points -20" in out
    assert f"pooled repeat R1 {KINDS[0]} pairs 15 right 0 wrong 1 without_credit 14 non_result 0 points -20/3" in out


def test_life_scores_average_repeats_and_four_kinds(run):
    for p in "ABC":
        for repeat in ("H1", "R2"):
            edit(run.paths[f"{p}.{repeat}"] / "outcomes.json", lambda o: [v.update(score_milli=0) for v in o.values()])
        edit(run.paths[f"{p}.R1"] / "outcomes.json", lambda o: [v.update(score_milli=1000) for v in o.values()])
        edit(run.paths[f"{p}.W1"] / "outcomes.json", lambda o: [v.update(score_milli=1000)
             for v in o.values() if v["template_ref"] == KINDS[0]])
    code, out = run()
    assert code == 0 and "Room against R: holds nonzero 15 mean 1/2" in out
    assert "Use against B: holds nonzero 15 mean 1/2" in out
    assert "Use against R: inconclusive nonzero 0 mean 0" in out
    assert "Room against W: holds nonzero 15 mean 3/4" in out
    assert "H minus F; no significance claimed: nonzero 15 mean 1/2 (0.5) p 1/16384" in out
    assert all(f"H minus F {kind} points 50 (50.0)" in out for kind in KINDS)


@pytest.mark.parametrize("values,expected,p", (([1] * 5 + [0] * 10, "inconclusive", Fraction(1, 16)),
    ([1] * 6 + [0] * 9, "holds", Fraction(1, 32)), ([1] * 6 + [-1] * 5 + [0] * 4, "does not hold", Fraction(1)),
    ([-1] * 6 + [0] * 9, "does not hold", Fraction(1, 32)), ([0] * 15, "inconclusive", Fraction(1))))
def test_exact_contrast_cases(table, values, expected, p):
    result = table.comparison({("ABC"[n // 5], n % 5): Fraction(v) for n, v in enumerate(values)}, "synthetic")
    assert result["reading"] == expected and result["p"] == p and len(result["differences"]) == 15
    assert table.contrast_verdict(["unresolved", "inconclusive", "does not hold", "holds"]) == "does not hold"
    assert table.contrast_verdict(["unresolved", "inconclusive", "holds", "holds"]) == "unresolved"
    assert table.contrast_verdict(["holds", "inconclusive", "holds", "holds"]) == "inconclusive"
    assert table.contrast_verdict(["holds"] * 4) == "holds"


def test_o3_does_not_enter_contrasts(run):
    before = run()[1].split("== 5.")[1].split("== 6.")[0]
    for p in "ABC":
        edit(run.paths[f"{p}.O3"] / "outcomes.json", lambda o: [v.update(score_milli=-1000) for v in o.values()])
    after = run()[1].split("== 5.")[1].split("== 6.")[0]
    assert before == after


def test_qualified_fifteen_lives_and_zero_kind_difference(run):
    code, out = run()
    assert code == 0 and "Room against R: holds nonzero 15 mean 1 (1.0) p 1/16384" in out
    lines = [line for line in out.splitlines() if line.startswith("Room against R ")
             and line.split()[3] in ("A", "B", "C") and " difference " in line]
    assert len(lines) == 15
    for p in "ABC":
        edit(run.paths[f"{p}.W1"] / "outcomes.json", lambda o: [v.update(score_milli=1000)
             for v in o.values() if v["template_ref"] == KINDS[0]])
    assert f"Room against W zero or negative: {KINDS[0]}" in run()[1]


def test_contrast_failure_precedes_unresolved_and_inconclusive(run):
    for p in "ABC":
        for repeat in ("O1", "O2"):
            edit(run.paths[f"{p}.{repeat}"] / "outcomes.json", lambda o: [v.update(score_milli=0) for v in o.values()])
        for repeat in ("R1", "R2"):
            edit(run.paths[f"{p}.{repeat}"] / "outcomes.json", lambda o: [v.update(score_milli=1000) for v in o.values()])
    (run.paths["A.W1"] / "card.json").unlink()
    code, out = after_reruns(run, ["A.W1"])
    assert code == 0 and "Room: does not hold" in out
    assert "Room against W: unresolved" in out and "Room against B: inconclusive" in out


def test_descriptive_points_and_unread_never_affect_output(run):
    code, before = run()
    assert code == 0 and f"descriptive A.F1 {DESC[0]}: scored 5 not_scored 0 points 100" in before
    assert f"descriptive B.F1 {DESC[0]}: scored 5 not_scored 0 points 50" in before
    assert f"descriptive F {DESC[0]}: scored 30 not_scored 0 points 250/3" in before
    def unread(obj):
        for key, value in obj.items():
            if "recall-count" in key or key.startswith(tuple(life + "/" for life in G2)) and value["stage"] == "act":
                value.update(score_milli=987654321)
    for path in run.paths.values():
        edit(path / "outcomes.json", unread)
    assert run()[1] == before


def test_excluded_descriptive_arm_is_published_separately(run):
    edit(run.paths["A.H1"] / "card.json", lambda o: o.update(served_identity="different"))
    code, out = after_reruns(run, ["A.H1"])
    assert code == 0 and f"descriptive A.H1 {DESC[0]}: scored 5 not_scored 0 points 100" in out
    assert f"descriptive H {DESC[0]}: scored 25 not_scored 5 points 80" in out


def test_filter_rule_and_sections(table, run, tmp_path):
    for values in product((1000, 0, -1000, None), repeat=3):
        trials = [{} if v is None else {"k": dict(score_milli=v)} for v in values]
        good, unknown = values.count(1000), values.count(None)
        expected = "pass" if good >= 2 else "fail" if good + unknown < 2 else "unresolved"
        assert table.twin(trials, "k") == ((good, unknown), expected)
    for values in product(("pass", "fail", "unresolved"), repeat=2):
        assert table.bundle_verdict(values) == ("fail" if "fail" in values else "unresolved" if "unresolved" in values else "pass")
    path = tmp_path / "filter.json"
    assert run(flags=("--filter-out", str(path)))[0] == 0
    data = json.loads(path.read_bytes())
    assert set(data) == set("ABC") and path.read_bytes() == table.canon(data)
    for p in "ABC":
        assert data[p]["tasks_sha256"] == sha256(run.tasks[p].read_bytes()).hexdigest()
        assert sum(len(v["kept"]) for v in data[p]["templates"].values()) == 20
    edit(run.paths["A.O1"] / "card.json", lambda o: o.update(served_identity="excluded"))
    edit(run.paths["A.O3"] / "outcomes.json", lambda o: [v.update(score_milli=0) for v in o.values()])
    assert after_reruns(run, ["A.O1"], flags=("--filter-out", str(path)))[0] == 0
    data = json.loads(path.read_bytes())
    assert data["A"]["o_excluded"] == ["A.O1"]
    assert all(len(v["unresolved"]) == 5 and not v["kept"] for v in data["A"]["templates"].values())


@pytest.mark.parametrize("mode", ("pass", "pending", "ends", "after"))
def test_output_discipline_and_sections(run, table, mode):
    flags = ()
    if mode in ("pending", "after"):
        (run.paths["A.H1"] / "card.json").unlink()
    elif mode == "ends":
        run.check3.write_text("exit 1")
        flags = ("--after-reruns",)
    code, out = after_reruns(run, ["A.H1"]) if mode == "after" else run(flags=flags)
    assert code == {"pass": 0, "pending": 4, "ends": 5, "after": 0}[mode]
    codes = [line for line in out.splitlines() if line.startswith("code ")]
    assert len(codes) == 4 and all(len(line.rsplit(" ", 1)[1]) == 12 for line in codes)
    assert table.DECLARED_ORDER == ORDER
    for forbidden in (*G1, *G2, "SYNITEM", "SYNBUNDLE", IDENTITY, "synthetic task text", "4" * 64, str(run.packs["A"].parent)):
        assert forbidden not in out
    sections = [line.split(".", 1)[0] for line in out.splitlines() if line.startswith("== ")]
    assert sections == [f"== {n}" for n in range(1, 9 if code == 0 else 3)]
    if code == 0:
        assert "system units have no cache path" in out
        line = next(line for line in out.splitlines() if line.startswith("H minus F; no significance claimed:"))
        assert "holds" not in line and "inconclusive" not in line


def first_kind_item(life):
    return lambda o: next(v for k, v in o.items() if k.startswith(life + "/") and v["template_ref"] == KINDS[0])


@pytest.mark.parametrize("fault", ("missing", "mismatch", "incomplete", "compacted", "h_checks"))
def test_after_reruns_waits_for_each_owed_rerun(run, fault):
    label = "A.H1" if fault == "h_checks" else "A.R1"
    path = run.paths[label]
    if fault == "missing":
        (path / "card.json").unlink()
    elif fault == "mismatch":
        edit(path / "card.json", lambda o: o.update(served_identity="different"))
    elif fault == "incomplete":
        edit(path / "outcomes.json", lambda o: first_kind_item(G1[0])(o).update(score_milli=None))
    elif fault == "compacted":
        edit(path / "receipt.json", lambda o: o["tokens_by_role"][0].update(input=1))
    else:
        edit(path / "system" / G1[0] / "B0/t2lite_probes.json", lambda o: o[0]["live"].update(served_by="scripted"))
    edit(run.paths["B.O1"] / "card.json", lambda o: o.update(served_identity="different"))
    for owed, (code, out) in ((f"{label} B.O1", run(flags=("--after-reruns",))), (label, after_reruns(run, ["B.O1"]))):
        # Every arm that has not had its rerun holds the scores; once B.O1's rerun is spent, only the other one.
        assert code == 4 and f"pending before any score: {owed} - {RERUN}\n" in out
        assert "== 3. Scores" not in out
    code, out = after_reruns(run, [label, "B.O1"])
    assert code == 0 and "== 3. Scores" in out


def test_scripted_beside_live_uses_usable_repeats(run):
    edit(run.paths["A.R2"] / "outcomes.json", lambda o: [v.update(score_milli=1000) for v in o.values()
                                                         if v["template_ref"] == KINDS[0]])
    code, out = run()
    assert code == 0 and f"row R A {KINDS[0]} pairs 10 right 5 wrong 0 without_credit 5 non_result 0 points 50 (50.0) complete" in out
    assert f"scripted beside live A R {KINDS[0]} scripted points 100 (100.0) live points 50 (50.0)\n" in out
    # An excluded repeat is not the anchor's live score, whatever it scored.
    edit(run.paths["A.R1"] / "outcomes.json", lambda o: [v.update(score_milli=-1000) for v in o.values()])
    edit(run.paths["A.R1"] / "card.json", lambda o: o.update(served_identity="different"))
    code, out = after_reruns(run, ["A.R1"])
    assert code == 0 and f"row R A {KINDS[0]} pairs 5 right 5 wrong 0 without_credit 0 non_result 0 points 100 (100.0) incomplete" in out
    assert f"scripted beside live A R {KINDS[0]} scripted points 100 (100.0) live points 100 (100.0)\n" in out
    assert f"scripted beside live A R {KINDS[1]} scripted points 100 (100.0) live points 0 (0.0)\n" in out


@pytest.mark.parametrize("fault", ("incomplete", "missing", "compacted", "mismatch"))
def test_filter_keeps_an_incomplete_trials_scored_items(run, tmp_path, fault):
    path = run.paths["A.O1"]
    edit(run.paths["A.O3"] / "outcomes.json", lambda o: [v.update(score_milli=0) for v in o.values()])
    if fault == "incomplete":
        edit(path / "outcomes.json", lambda o: first_kind_item(G1[0])(o).update(score_milli=None))
    elif fault == "missing":
        (path / "card.json").unlink()
    elif fault == "compacted":
        edit(path / "receipt.json", lambda o: o["tokens_by_role"][0].update(input=1))
    else:
        edit(path / "card.json", lambda o: o.update(served_identity="different"))
    receipt = tmp_path / "filter.json"
    code, out = after_reruns(run, ["A.O1"], flags=("--filter-out", str(receipt)))
    assert code == 0
    data = json.loads(receipt.read_bytes())["A"]
    for t in KINDS:
        # O2 alone is at 1000 and O3 at 0: a pair is kept only where O1 is scored at 1000 on both twins.
        kept = (4 if t == KINDS[0] else 5) if fault == "incomplete" else 0
        assert f"filter A {t} kept {kept} dropped 0 unresolved {5 - kept}\n" in out
        assert len(data["templates"][t]["kept"]) == kept and len(data["templates"][t]["unresolved"]) == 5 - kept
    assert data["o_excluded"] == ([] if fault == "incomplete" else ["A.O1"])
    left = {t: ["A.O1"] if fault != "incomplete" or t == KINDS[0] else [] for t in KINDS}
    assert data["o_excluded_by_kind"] == left
