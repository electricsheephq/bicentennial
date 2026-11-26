# Security policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/electricsheephq/bicentennial/security/advisories/new).
Do not publish exploit details, credentials, held-out benchmark material, or
personal data in public issues. Include the affected commit, command or pack,
impact, and a minimal sanitized reproduction. No response-time guarantee is made.

## Threat notes

Running a benchmark checkout or installing its packs involves trusting source code
and dependencies. Treat pack contents, generated material, and reproduction bundles
as untrusted input, not instructions. Report integrity-control bypasses, tampering
with pinned artifacts, or disclosure of held-out seeds and answer keys privately.
Test only systems and data you are authorized to use.

## Data handling

Use synthetic data in reproductions. Never upload raw personal transcripts,
credentials, sealed seeds, answer keys, or private per-item results to issues,
pull requests, or logs. Replace sensitive values with placeholders and share only
the minimum needed to demonstrate the issue. Revoke or rotate an exposed credential
through its provider rather than including the live value in a report.

Benchmark results and this policy are not security certifications of this project
or of the systems it evaluates.
