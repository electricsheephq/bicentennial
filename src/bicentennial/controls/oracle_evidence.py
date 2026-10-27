"""Evidence-only ceiling, excluding forbidden context."""

from bicentennial.api.adapters.oracle_evidence import OracleEvidence

from .common import run_arm


def run(inp, *, score):
    arm = run_arm(inp, OracleEvidence, score=score, oracle=True)
    if any(r["forget"] is not None and r["forget"]["in_context"] is True for r in arm["reports"]):
        raise ValueError("oracle context carries a forbidden token")
    return arm
