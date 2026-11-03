"""The fixed v0.2 identity rules and the schema-owned D6 startup inputs."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts import run
from bicentennial.contracts.bundle import NONRESULTS
from bicentennial.controls.cache import (
    CONTROL_FILES,
    PACKAGE_ROOT,
    READER_FILES,
    code_sha256,
)
from bicentennial.packs.scoring import SCORING_FILES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/repro"


def example(name):
    return json.loads((FIXTURES / f"{name}_v02.json").read_bytes())


@pytest.fixture(params=["snapshot_probe", "live"])
def tier_bundle(request):
    return example(request.param)


def test_valid_snapshot_probe_has_nonempty_d6_context():
    bundle = example("snapshot_probe")
    assert bundle["replay_context"]
    run.validate("repro_bundle", bundle)


def test_valid_live_has_artifact_identity():
    bundle = example("live")
    assert bundle["system"]["name"] != bundle["system"]["artifact"]["name"]
    run.validate("repro_bundle", bundle)


def test_v02_identity_uses_card_item_names_and_checkpoint(tier_bundle):
    card_item = json.loads((run.SCHEMAS / "card_t2.schema.json").read_bytes())["properties"]["items"]["items"]
    fields = ("life", "branch", "item_id", "probe_point", "failure_class", "score_milli")
    # Project the card schema, keeping the card's broader score range and null class.
    schema = dict(type="object", properties={k: card_item["properties"][k] for k in fields},
                  required=list(fields), additionalProperties=False)
    run._check(schema, {k: tier_bundle["identity"][k] for k in fields})
    run.validate("repro_bundle", tier_bundle)


def test_v02_class_refuses_v01(tier_bundle):
    tier_bundle["repro_version"] = "v0.1"
    with pytest.raises(ValueError, match="class/version|enum"):
        run.validate("repro_bundle", tier_bundle)


def test_replay_from_schedule_refuses_v02():
    bundle = json.loads((FIXTURES / "contracts.json").read_bytes())["contracts"]["repro_bundle"]
    bundle["repro_version"] = "v0.2"
    with pytest.raises(ValueError, match="class/version|enum"):
        run.validate("repro_bundle", bundle)


@pytest.mark.parametrize("field,value", [("item_id", "another-item"), ("branch", "B0"),
                                         ("life", "another-life")])
def test_kept_refuses_another_item_branch_or_life(field, value):
    bundle = example("snapshot_probe")
    bundle["identity"][field] = value
    with pytest.raises(ValueError, match="kept identity"):
        run.validate("repro_bundle", bundle)


def test_live_optional_kept_must_match_identity():
    bundle = example("live")
    bundle["kept"] = "kept/g1-example-1/B1/item.example-1"
    run.validate("repro_bundle", bundle)
    bundle["kept"] = "kept/g1-example-1/B1/another-item"
    with pytest.raises(ValueError, match="kept identity"):
        run.validate("repro_bundle", bundle)


def test_v02_refuses_passing_outcome(tier_bundle):
    tier_bundle["identity"]["score_milli"] = 1000
    with pytest.raises(ValueError, match="outcome must be a failure"):
        run.validate("repro_bundle", tier_bundle)


@pytest.mark.parametrize("failure_class", ["FAIL_TASK", "SYSTEM_FAILURE"])
def test_v02_failure_class_must_score_zero(tier_bundle, failure_class):
    # The card scores a system or task failure 0 (contracts/bundle.py), so no card item pairs one with another score.
    tier_bundle["identity"].update(failure_class=failure_class, score_milli=500)
    with pytest.raises(ValueError, match="system/task failure must score 0"):
        run.validate("repro_bundle", tier_bundle)
    tier_bundle["identity"]["score_milli"] = 0
    run.validate("repro_bundle", tier_bundle)


def test_v02_scored_answer_keeps_its_partial_score(tier_bundle):
    tier_bundle["identity"].update(failure_class=None, score_milli=500)
    run.validate("repro_bundle", tier_bundle)


@pytest.mark.parametrize("failure_class", NONRESULTS)
def test_v02_refuses_nonresult_class(tier_bundle, failure_class):
    # The card gives a non-result a null score, so no failed scored item carries one.
    tier_bundle["identity"]["failure_class"] = failure_class
    with pytest.raises(ValueError, match=r'\["identity"\]\["failure_class"\]: invalid enum value'):
        run.validate("repro_bundle", tier_bundle)


HASH_PATHS = [("identity", "pack_hash"),
              *(("identity", "pins", f"{n}_sha256") for n in ("controls", "reader", "scoring", "scorer")),
              ("surface_hashes", "home"), ("workspace_hash",), ("environment_hash",),
              ("route_table_sha256",), ("probe_config_sha256",),
              ("replay_context", "canonical_paths")]


@pytest.mark.parametrize("path", HASH_PATHS, ids=lambda p: ".".join(p))
@pytest.mark.parametrize("bad_hash", ["g" * 64, "a" * 63], ids=["nonhex", "short"])
def test_snapshot_refuses_nonhex_or_short_hash(path, bad_hash):
    bundle = example("snapshot_probe")
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_hash
    with pytest.raises(ValueError, match="pattern mismatch"):
        run.validate("repro_bundle", bundle)


@pytest.mark.parametrize("bad_hash", ["g" * 64, "a" * 63], ids=["nonhex", "short"])
def test_live_refuses_nonhex_or_short_artifact_hash(bad_hash):
    bundle = example("live")
    bundle["system"]["artifact"]["sha256"] = bad_hash
    with pytest.raises(ValueError, match="pattern mismatch"):
        run.validate("repro_bundle", bundle)


def test_live_refuses_missing_artifact_sha256():
    bundle = example("live")
    del bundle["system"]["artifact"]["sha256"]
    with pytest.raises(ValueError, match="sha256"):
        run.validate("repro_bundle", bundle)


def test_snapshot_refuses_unknown_replay_context_member():
    bundle = example("snapshot_probe")
    bundle["replay_context"]["unknown"] = "a" * 64
    with pytest.raises(ValueError, match="unknown"):
        run.validate("repro_bundle", bundle)


@pytest.mark.parametrize("member", list(example("snapshot_probe")["replay_context"]))
def test_snapshot_requires_each_d6_startup_input(member):
    bundle = example("snapshot_probe")
    del bundle["replay_context"][member]
    with pytest.raises(ValueError, match=member):
        run.validate("repro_bundle", bundle)


@pytest.mark.parametrize("reference", ["pack:/absolute", "pack:../outside", "pack:visible/../outside",
                                       "pack:visible//input", "pack:visible/input\n"])
def test_replay_context_refuses_nonrelative_pack_reference(reference):
    bundle = example("snapshot_probe")
    bundle["replay_context"]["compiled_probe"] = reference
    with pytest.raises(ValueError, match="pattern mismatch"):
        run.validate("repro_bundle", bundle)


def test_replay_context_can_grow_in_schema_alone(monkeypatch, tmp_path):
    bundle = example("snapshot_probe")
    bundle["replay_context"]["future_input"] = "a" * 64
    with pytest.raises(ValueError, match="future_input"):
        run.validate("repro_bundle", bundle)
    schema = json.loads((run.SCHEMAS / "repro_bundle.schema.json").read_bytes())
    branch = next(s for s in schema["oneOf"] if "snapshot-probe" in s["properties"]["repro_class"]["enum"])
    context = branch["properties"]["replay_context"]
    context["properties"]["future_input"] = deepcopy(context["properties"]["canonical_paths"])
    context["required"].append("future_input")
    before = code_sha256(CONTROL_FILES)
    (tmp_path / "repro_bundle.schema.json").write_bytes(canon(schema))
    monkeypatch.setattr(run, "SCHEMAS", tmp_path)
    run.validate("repro_bundle", bundle)
    assert code_sha256(CONTROL_FILES) == before


def test_repro_schema_is_outside_every_code_pin():
    schema_path = (run.SCHEMAS / "repro_bundle.schema.json").resolve()
    sets = {"controls": CONTROL_FILES, "reader": READER_FILES, "scoring": SCORING_FILES,
            "scorer": tuple(p.relative_to(PACKAGE_ROOT).as_posix()
                            for p in sorted((PACKAGE_ROOT / "score").glob("*.py")))}
    assert "contracts/repro_bundle.py" in CONTROL_FILES
    for name, files in sets.items():
        assert schema_path not in {(PACKAGE_ROOT / p).resolve() for p in files}, name


def test_new_repro_fixtures_are_canonical_and_validate():
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "contracts.json":
            continue
        raw = path.read_bytes()
        bundle = json.loads(raw)
        assert raw == canon(bundle), path.name
        run.validate("repro_bundle", bundle)
