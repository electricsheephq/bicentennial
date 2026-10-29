"""Canonical OC payload and a portable result card, with D12 left open."""

from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon

NOT_PROVEN = (
    "No size or power figure was simulated, and no runtime was measured.",
    "Nothing here bounds real provider drift (P:43).",
    "M2's fit to bar-2 data is untested (SPEC-A). The gate's outcome depends on bar-2 inputs that do not exist yet.",
    "Exactness is proved for certify and tcal at #251's head only.",
    "The Image profile's powered size is not addressed (S-37).",
)
EXTRA_CHAINS = [
    "K10 B0/B1 on n_keep = max(6, ceil(n_L/4)) lives",
    "On the first 8 lives: study fault reruns, Keep-curve tiers, swap comparator, "
    "replication-family branches, A/A′ reruns, Learn chains and erasure probes",
    "The raw-archive marker",
]
READINGS = {
    "LITERAL": "literal pinned-reader scope",
    "ALL_UNITS": "every system unit drifts",
    "PRE_SWAP": "certify on pre-swap checkpoints only; post-swap units still sampled (CRN)",
    "SWAP_GATE": "approximation: certify pools one gate per pair over all retained checkpoints",
}


def percent(ppm: int) -> str:
    """Two decimal percentage places, with exact ties-to-even rounding."""
    hundredths = round(Fraction(ppm, 100))
    return f"{hundredths // 100}.{hundredths % 100:02d}%"


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def _row(case, data):
    return "| " + " | ".join(map(_cell, (
        case, f"{data['certified']}/{data['n']}", percent(data["rate_ppm"]),
        percent(data["mcse_ppm"]),
        f"{percent(data['wilson_ppm'][0])}–{percent(data['wilson_ppm'][1])}",
        data["criterion"] or "reported", data["decision"],
    ))) + " |"


def _table(cases):
    return ["| Case | x/n | p̂ | MCSE | Wilson 95% | Bar | Decision |",
            "|---|---:|---:|---:|---|---|---|",
            *(_row(case, data) for case, data in cases)]


def _worst(cases):
    groups = {}
    for case, data in sorted(cases.items()):
        criterion = data["criterion"]
        if criterion is None:
            continue
        direction, bar = criterion.split()
        diff = Fraction(data["certified"], data["n"]) - Fraction(bar)
        failure = diff if direction == "le" else -diff
        if criterion not in groups or failure > groups[criterion][0]:
            groups[criterion] = failure, case, data
    return [(case, data) for _, case, data in groups.values()]


def render(manifest: dict, results: dict) -> str:
    lines = ["# OC simulation result", "", manifest["claim_class"], "",
             "Freeze gate: OPEN: D12 (S-27)", "",
             "Text season board; calibrated index decides. The one-sided 5% index is reported only.",
             "The deciding SE statistic is the per-replicate maximum; the pooled statistic is printed too.",
             "Naive RAG is not simulated: admissions use its never-CLEAR, full-support stand-in. "
             "Power can be overstated when real naive RAG clears the gate.",
             "The stated buffer is not run; certify has no buffer input."]
    alternatives = manifest["config"]["alternatives"]
    for alternative in alternatives:
        passing = results["first_passing"][alternative]
        passing_text = "none" if passing is None else f"n_L={passing[0]}, b={passing[1]}"
        evaluated = [(p, p["alternatives"][alternative]) for p in results["points"]
                     if alternative in p["alternatives"]]
        verdict = "PASS" if passing is not None else "FAIL"
        lines += ["", f"## {alternative}: {verdict}", "", READINGS[alternative], "",
                  f"First passing point: {passing_text}."]
        for point, data in evaluated:
            lines += ["", f"### n_L={point['n_L']}, b={point['b']}: {data['verdict']}", "",
                      f"SE bound: {data['se_bound'] or 'null'}; "
                      f"pooled SE bound: {data['se_bound_pooled'] or 'null'}.", "",
                      "Worst cases per criterion:", "", *_table(_worst(data["cases"])),
                      "", "Full case table:", "", *_table(sorted(data["cases"].items()))]
    lines += ["", "## Ladder status", "", "| n_L | b | Status | Pinned reserve | Swap reserve |",
              "|---:|---:|---|---:|---:|"]
    for point in results["points"]:
        lines.append(f"| {point['n_L']} | {point['b']} | {point['status']} | "
                     f"{point['reserve'][0]} | {point['reserve'][1]} |")
    lines += ["", "## Sensitivities", "", "LITERAL only, using main's bound; reported without a gate verdict."]
    for point in results["points"]:
        for variant, alternatives_data in point["variants"].items():
            lines += ["", f"### {variant}, n_L={point['n_L']}, b={point['b']}", ""]
            for data in alternatives_data.values():
                lines += _table(sorted(data["cases"].items()))
    lines += ["", "## Occupancy and limits", "", manifest["occupancy"]["extra_chains"],
              "", *(f"- {text}" for text in manifest["occupancy"]["missing"]), "",
              "The reserve is an average-load rule, not a timed model of probe-only work.",
              "A larger board is covered only if its own ladder point passed.",
              "Results are conditional on the frozen certification seed and recorded platform.",
              "", "## Runtime and machine", "", manifest["machine"]["class"], "",
              f"Workers: {manifest['run']['workers']}; pauses/width changes: "
              f"{len(manifest['run']['pauses'])}.", ""]
    for phase, elapsed in manifest["run"]["phases"].items():
        lines.append(f"- {phase}: {elapsed['wall_s']} s wall; {elapsed['cpu_s']} s CPU.")
    lines += ["", "## What this does not prove", "",
              *(f"- {text}" for text in manifest["not_proven"]), ""]
    return "\n".join(lines)


def write(out: Path, results: dict, manifest: dict) -> None:
    """Write canon bytes and LF Markdown, after validating both full payloads."""
    data = canon(results)
    manifest = {**manifest, "results_sha256": sha256(data).hexdigest()}
    encoded = canon(manifest)
    markdown = render(manifest, results)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_bytes(data)
    (out / "RESULT-MANIFEST.json").write_bytes(encoded)
    (out / "RESULT.md").write_text(markdown, encoding="utf-8", newline="\n")
