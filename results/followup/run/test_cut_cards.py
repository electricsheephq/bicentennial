"""Exercise the standalone cutter in isolated Python, with invented card entries."""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.report.t2_card import _row_counts, build_t2_card, validate_t2_card

SCRIPT = Path(__file__).with_name("cut_cards.py")
OUTCOME_COUNTS = ("kept_copies", "null_citation", "infra")


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def keys():
    found = [dict(life=f"invented-life-{n // 5}", branch=f"B{n % 2}", item_id=f"invented-item-{n}") for n in range(50)]
    found[1]["item_id"] = found[0]["item_id"]
    return found


def entry(key, n, *, genre, stage, system):
    """Five outcome shapes in turn: kept failure, blocked, unknown answer, cited answer, no envelope."""
    shape = n % 5
    score, failure = ((0, "SYSTEM_FAILURE"), (None, "BLOCKED"), (1000, None), (1000, None), (1000, None))[shape]
    envelope = ({"type": "answer", "citation": None}, None, {"type": "unknown", "citation": None},
                {"type": "answer", "citation": "invented-citation"}, None)[shape]
    repro = "kept/" + "/".join(key.values()) if system and shape == 0 else None
    return dict(key, genre=genre, stage=stage, score_milli=score, failure_class=failure, envelope=envelope, repro=repro)


def outcome_counts(items):
    """`_row_counts`'s two outcome counts and the runner's `infra` rule, applied to the given items."""
    rows = _row_counts(dict(items=items, floor=dict(units={}), not_scored_live=[]))
    return dict(kept_copies=rows["kept_copies"], null_citation=rows["null_citation"],
                infra=sum(item["failure_class"] == "BLOCKED" for item in items))


def full_card(found, *, system):
    items = [entry(k, n, genre="G1" if n < 45 else "G2", stage="act" if n < 40 else "qa", system=system)
             for n, k in enumerate(found)]
    # Unread entries: a kept failure, a blocked row and an uncited answer, each with a visible score.
    for n in range(3):
        key = dict(life="unread", branch=f"B{n % 2}", item_id=f"unread-{n}")
        item = entry(key, (0, 1, 0)[n], genre="G2", stage="qa", system=system)
        if n == 1:
            item["repro"] = None
        if n == 2:
            item.update(repro=None, failure_class=None, score_milli=987654321)
        items.append(item)
    units = {f"{i['life']}/{i['branch']}": dict(cached=False) for i in items}
    counts = dict(units=len(units), lives=len({i["life"] for i in items}), floor_cached_units=0,
                  not_scored_live=0, **outcome_counts(items))
    for item in items:
        counts[f"items.{item['genre']}.{item['stage']}"] = counts.get(f"items.{item['genre']}.{item['stage']}", 0) + 1
    card = dict(items=items, counts=counts, floor=dict(units=units), not_scored_live=[],
                groups=[["synthetic-cell", "act"]], controls_broken=[], other=dict(synthetic="preserved", count=73))
    if not system:
        card["control"] = "naive_rag"
    return card


def cut(tmp_path, card, *, label="A.F1", raw=None, out=None):
    found = keys()
    frozen = tmp_path / "tasks.json"
    frozen.write_bytes(canon(dict(header=dict(pack="A"), rows=found[:40], descriptive=found[40:])))
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    (run / "card.json").write_bytes(canon(card) if raw is None else raw)
    out = tmp_path / "cut" if out is None else out
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(frozen), str(out), f"{label}={run}"],
                            capture_output=True, text=True)
    return result, out


@pytest.mark.parametrize("fault", (None, "noncanonical", "missing", "duplicate", "substitute", "pack"))
def test_isolated_cutter(tmp_path, fault):
    card = full_card(keys(), system=True)
    if fault == "missing":
        card["items"].pop(0)
    elif fault == "duplicate":
        card["items"].append(card["items"][0])
    elif fault == "substitute":
        card["items"][1] = card["items"][0]
    raw = json.dumps(card).encode() if fault == "noncanonical" else canon(card)
    label = "B.F1" if fault == "pack" else "A.F1"
    result, out = cut(tmp_path, card, label=label, raw=raw)
    if fault:
        assert result.returncode != 0 and (result.stdout + result.stderr).strip() == label
        assert not out.exists() or not list(out.iterdir())
    else:
        assert result.returncode == 0
        assert json.loads(result.stdout) == {label: sha256(raw).hexdigest()}
        written = (out / f"{label}.json").read_bytes()
        assert len(json.loads(written)["items"]) == 50 and b"987654321" not in written
        assert canon(json.loads(written)["other"]) == canon(card["other"])
        assert written == canon(json.loads(written))


@pytest.mark.parametrize("system", (True, False), ids=("system", "control"))
def test_cut_outcome_counts_describe_kept_items(tmp_path, system):
    card = full_card(keys(), system=system)
    result, out = cut(tmp_path, card)
    assert result.returncode == 0
    written = json.loads((out / "A.F1.json").read_bytes())
    kept = [item for item in card["items"] if item["life"] != "unread"]
    assert written["items"] == kept
    want = outcome_counts(kept)
    assert {k: written["counts"][k] for k in OUTCOME_COUNTS} == want
    assert want["null_citation"] > 0 and want["infra"] > 0 and (want["kept_copies"] > 0) is system
    # The unread entries' outcomes are not published as a difference from the full card's counts.
    assert all(card["counts"][k] > want[k] for k in OUTCOME_COUNTS if system or k != "kept_copies")
    # Structure stays as the full card has it.
    for obj in (written, card):
        obj.pop("items")
        for k in OUTCOME_COUNTS:
            obj["counts"].pop(k)
    assert canon(written) == canon(card)


def test_cut_refuses_existing_output_folder(tmp_path):
    out = tmp_path / "cut"
    out.mkdir()
    (out / "earlier.json").write_bytes(b"{}")
    result, _ = cut(tmp_path, full_card(keys(), system=True), out=out)
    # Refused before any card is read, so no label is at fault.
    assert result.returncode != 0 and (result.stdout + result.stderr).strip() == "card"
    assert sorted(p.name for p in out.iterdir()) == ["earlier.json"]
    result, _ = cut(tmp_path, full_card(keys(), system=True), out=tmp_path / "new" / "cut")
    assert result.returncode == 0 and (tmp_path / "new/cut/A.F1.json").is_file()


def test_cut_output_folder_fault_names_no_card(tmp_path):
    # The folder cannot be made (its parent is a file) only after every card is read and found sound.
    (tmp_path / "parent").write_bytes(b"")
    result, _ = cut(tmp_path, full_card(keys(), system=True), out=tmp_path / "parent" / "cut")
    assert result.returncode != 0 and (result.stdout + result.stderr).strip() == "card"
    assert (tmp_path / "parent").read_bytes() == b""


def test_cut_card_is_not_a_t2_card(tmp_path):
    fixture = SCRIPT.parents[3] / "tests/fixtures/scoring/contracts.json"
    original = json.loads(fixture.read_bytes())["contracts"]["card_ring0"]
    row = dict(original["items"][0], life="invented-g1", genre="G1", stage="act", repro=None,
               base_verdict="PASS", accuracy_correct=True, envelope=None)
    items = [dict(row, branch="B0", probe_point=5)]
    items.append(dict(items[0], life="invented-g2", genre="G2", envelope=None, base_verdict=None,
                      score_milli=None, worst_case_milli=None, accuracy_correct=None, tuesday_class=None,
                      failure_class=None, stage_attribution=None, benign_extra=False, carry_over=False))
    unscored = [[items[-1][k] for k in ("life", "branch", "item_id")]]
    floor = dict(served_identity="invented-floor", units={
        f"{i['life']}/{i['branch']}": dict(cache_key="d" * 64, cached=True) for i in items})
    pin_names = ("benchmark_commit", "generator_commit", "director_commit", "scorer_commit",
                 "harness_hash", "system_hash", "route_table_hash", "write_turn_package_hash")
    pins = {k: original["pins"][k] for k in pin_names}
    counts = dict(_row_counts(dict(items=items, floor=floor, not_scored_live=unscored)), infra=0)
    card = build_t2_card(system="invented-system", pack_hash="a" * 64, seed_hash="b" * 64,
                        pins=pins, model="invented-model", effort="medium", served_identity="invented-reader",
                        aa_prime=False, items=items, counts=counts, answer_contract_sha256="c" * 64,
                        not_scored_live=unscored, seed_source=dict(kind="public"),
                        groups=[[row["cell_id"], "act"]], floor=floor, controls_broken=[])
    assert validate_t2_card(card) is None
    run = tmp_path / "run"
    run.mkdir()
    raw = canon(card)
    (run / "card.json").write_bytes(raw)
    tasks = tmp_path / "tasks.json"
    tasks.write_bytes(canon(dict(header=dict(pack="A"), rows=[
        {k: i[k] for k in ("life", "branch", "item_id")} for i in items[:1]], descriptive=[])))
    out = tmp_path / "cut"
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(tasks), str(out), f"A.H1={run}"],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"A.H1": sha256(raw).hexdigest()}
    written = json.loads((out / "A.H1.json").read_bytes())
    assert written["items"] == card["items"][:1] and written["not_scored_live"] == unscored
    with pytest.raises(ValueError, match="^t2_card:not_scored_live$"):
        validate_t2_card(written)


def test_cutter_paragraph_explains_t2_validation():
    paragraph = SCRIPT.with_name("README.md").read_text().split("The cutter uses", 1)[1].split("\n\n", 1)[0]
    assert "validate_t2_card" in paragraph
