"""C11's canonical schema, card contents, disclosures and portable bytes."""

import json
from hashlib import sha256

import pytest

from bicentennial.canon import canon
from bicentennial.ocsim import card, run


@pytest.fixture
def payload():
    config = run.RunConfig(tuple(run.ALTERNATIVES), 1)
    cases = run._case_table({"LITERAL|base|none|m0": [457, 458, 457, 100, 9443, 0, 99],
                              "LITERAL|stress_fast|trend-5|m0": [543, 544, 543, 0, 9457, 0, 0],
                              "LITERAL|base|none|m10": [8079, 8080, 8079, 0, 1921, 0, 0]},
                             ("X",), config.budgets())
    alternatives = {a: {"se_bound": "9/2", "se_bound_pooled": "8/2", "verdict": "FAIL",
                         "cases": cases if a == "LITERAL" else {}}
                    for a in config.alternatives}
    results = {"points": [{"n_L": 24, "b": 150, "status": "EVALUATED", "reserve": [1, 0],
                            "alternatives": alternatives,
                            "variants": {"tau0": {"LITERAL": {
                                "se_bound": "9/2", "se_bound_pooled": None, "verdict": "REPORTED",
                                "cases": {c: {**d, "decision": "REPORTED"} for c, d in cases.items()}}}}}],
               "first_passing": {a: None for a in config.alternatives},
               "freeze_gate": "OPEN: D12 (S-27)"}
    manifest = {"schema": "bicentennial.ocsim.result/v1", "claim_class": "planning smoke, not the gate",
                "code": {"commit": "0" * 40, "c8_hash": "1" * 64, "certify_sha256": "2" * 64,
                         "tcal_sha256": "3" * 64, "dirty": True},
                "inputs": {"sha256": "4" * 64, "planning": True, "latent_flags": ["twin_default"]},
                "config": run.constants_manifest(config),
                "audits": {"replicates": 1, "certify_calls": 4, "fields_compared": 32, "mismatches": 0},
                "solver": {"X": {"step_exp": 8, "bound_milli_ppm": 1000,
                                  "midpoint_error_ppm": 500, "audit_error_ppm": 400}},
                "occupancy": {"reserves": [[1, 0]],
                              "extra_chains": "not modelled: under-count disclosed",
                              "missing": card.EXTRA_CHAINS},
                "run": {"phases": {"phase0": {"wall_s": 1, "cpu_s": 1}}, "pauses": [], "workers": 1},
                "machine": {"platform": "synthetic", "machine": "synthetic", "python_version": "3.14.9",
                            "cpu_count": 4, "class": "synthetic test machine"},
                "not_proven": list(card.NOT_PROVEN)}
    return results, manifest


def test_full_manifest_canon_and_writer(payload, tmp_path):
    results, manifest = payload
    assert canon(manifest)
    card.write(tmp_path, results, manifest)
    data = (tmp_path / "results.json").read_bytes()
    assert data == canon(results)
    encoded = (tmp_path / "RESULT-MANIFEST.json").read_bytes()
    written = json.loads(encoded)
    assert canon(written) == encoded
    assert written["results_sha256"] == sha256(data).hexdigest()
    assert "results_sha256" not in manifest
    assert written["config"]["Z2"] == "960364705173531/250000000000000"
    assert written["config"]["BOUND_MILLI"] == 0.05.hex()
    assert written["inputs"]["latent_flags"] == ["twin_default"]
    assert set(written) == {"schema", "claim_class", "code", "inputs", "config", "results_sha256",
                            "audits", "solver", "occupancy", "run", "machine", "not_proven"}


def test_markdown_contents_order_and_portability(payload):
    results, manifest = payload
    text = card.render(manifest, results)
    assert "planning smoke, not the gate" in text
    assert "Freeze gate: OPEN: D12 (S-27)" in text
    assert text.index("## LITERAL") < text.index("## ALL_UNITS") < text.index("## PRE_SWAP") < text.index("## SWAP_GATE")
    for a in run.ALTERNATIVES:
        assert card.READINGS[a] in text
    assert "SE bound: 9/2; pooled SE bound: 8/2" in text
    assert "5.43%" in text and "80.79%" in text
    assert "543/10000" in text
    assert "Worst cases per criterion:" in text and "Full case table:" in text
    assert "tau0, n_L=24, b=150" in text
    assert "not modelled: under-count disclosed" in text
    missing = ["K10 B0/B1 on n_keep = max(6, ceil(n_L/4)) lives",
               "On the first 8 lives: study fault reruns, Keep-curve tiers, swap comparator, "
               "replication-family branches, A/A′ reruns, Learn chains and erasure probes",
               "The raw-archive marker"]
    not_proven = ("Nothing here bounds real provider drift (P:43).",
                  "M2's fit to bar-2 data is untested (SPEC-A). The gate's outcome depends on bar-2 inputs that do not exist yet.",
                  "Exactness is proved for certify and tcal at #251's head only.",
                  "The Image profile's powered size is not addressed (S-37).")
    assert card.EXTRA_CHAINS == missing and card.NOT_PROVEN == not_proven
    assert all(value in text for value in (*missing, *not_proven,
        "The reserve is an average-load rule, not a timed model of probe-only work.",
        "The stated buffer is not run; certify has no buffer input.",
        "Text season board; calibrated index decides. The one-sided 5% index is reported only.",
        "Naive RAG is not simulated: admissions use its never-CLEAR, full-support stand-in. Power can be overstated when real naive RAG clears the gate.",
        "A larger board is covered only if its own ladder point passed.",
        "Results are conditional on the frozen certification seed and recorded platform.",
        "LITERAL only, using main's bound; reported without a gate verdict.",
        "The deciding SE statistic is the per-replicate maximum; the pooled statistic is printed too."))
    assert "No size or power figure was simulated, and no runtime was measured." not in text
    config = run.configure(run.RunConfig(("LITERAL",), 1),
                           constants=run.test_constants(SE_STATISTIC="pooled"))
    manifest["config"] = run.constants_manifest(config)
    assert "The deciding SE statistic is the pooled statistic;" in card.render(manifest, results)
    assert "synthetic test machine" in text
    assert "/Users/" not in text and "/tmp/" not in text
    assert "\r" not in text and text.endswith("\n")
    worst = card._worst(results["points"][0]["alternatives"]["LITERAL"]["cases"])
    assert worst[0][0] == "LITERAL|stress_fast|trend-5|m0"


def test_report_order_deterministic_and_no_float_payload(payload, tmp_path):
    results, manifest = payload
    card.write(tmp_path / "one", results, manifest)
    card.write(tmp_path / "two", results, manifest)
    for name in ("results.json", "RESULT-MANIFEST.json", "RESULT.md"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    with pytest.raises(TypeError, match="unsupported canonical JSON type: float"):
        card.write(tmp_path / "bad", results, {**manifest, "unexpected_float": 1.0})
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("ppm,expected", ((0, "0.00%"), (50_000, "5.00%"),
                                           (807_900, "80.79%"), (1_000_000, "100.00%"),
                                           (50, "0.00%"), (150, "0.02%")))
def test_percentage_exact(ppm, expected):
    assert card.percent(ppm) == expected
