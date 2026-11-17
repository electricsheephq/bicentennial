# Bicentennial repository instructions

These instructions are for maintainers, contributor agents and review bots working in
`electricsheephq/bicentennial`, the open benchmark for agent memory. They hold the standing rules, how to run the tests
the way CI runs them, and how public text is checked. The plan is [ROADMAP.md](ROADMAP.md), and the current state is
[docs/project-status.md](docs/project-status.md). The standing rules found so far are in the invariant catalogue,
[docs/invariants.md](docs/invariants.md) (V1 to V51), each with its source, the code that enforces it and the tests
that prove it; [#603](https://github.com/electricsheephq/bicentennial/issues/603) adds the full tier's missing rules.
Cite rules by their id.

## Standing rules

These are the rules an agent meets most often. Each id leads to the rule's source in the catalogue.
- **Freeze before data.** A run's declaration merges to `main` before its draw (V1). Every arm is frozen and runs at
  one run commit fixed before the draw, except that a Ring 1 run's bar arms run from the bar's frozen checkout (V2).
  In a Ring 1 run, seeds are drawn only after every arm is frozen and nominated; each run's declaration says when its
  seeds become public, and full-tier seeds stay sealed (V3, V43).
- **No early scores.** No score is opened before the declaration's checks allow it, and the reading script prints no
  score while any arm is pending (V4). Repair and calibration decisions come from control rows only (V5), and
  difficulty is frozen from controls only (V27).
- **Failures by cause.** A failure is charged to whoever caused it, not to whatever reported it: an infrastructure
  failure is rerun at most twice and then BLOCKED, and a system failure scores zero (V7). Every live arm runs under a
  send bound (V8).
- **Frozen records.** A frozen pre-registration is never edited; a change makes a new version (V12). PREREG governs
  frozen quantities, and a difference elsewhere is recorded as an erratum (V14). An edit to any pinned artifact voids
  the run; after an edit to code under a code pin, such as a top-level file in `src/bicentennial/score/`, packs built
  before it fail `verify` (V15).
  A change that moves a pin updates the pin table and `prereg/CHANGELOG.md` (V16).
- **No humans.** No person grades, annotates, keys, audits, adjudicates or breaks a tie (V20).
- **Independence.** The benchmark never tunes, patches or advises on LCM-X and copies no LCM-X code (V23). The
  operator never runs LCM-X at Ring 0, and the runners refuse it (V24). LCM-X's developers and lanes never see held-out
  material (V25).
- **No real data.** No raw transcripts, corpus text or personal data are used (V28).

## Running the tests the way CI does

CI (`.github/workflows/ci.yml`) uses Python 3.14 on Linux and installs the package with `pip install -e .[dev]`.
- **Lint:** `ruff check`, then `python scripts/public_check.py`.
- **Tests:** `PYTHONHASHSEED=0 pytest -q`, split into the seven shards that `.github/workflows/ci.yml` lists. Each shard
  runs whole test files, placed by the durations measured in `tests/shard_weights.json` (`tests/conftest.py`); a new
  file is placed at the median weight.
- **The check that counts:** the `test` job is green only when lint and every shard passed. A pull request merges only
  when `test` passed at its exact head (V35).
- **Locally:** a Python 3.14 virtual environment with `pip install -e .[dev]`, then `PYTHONHASHSEED=0 pytest -q` from the
  repository root, or name the files you changed. The `bicentennial` command and the pack installer exit 3 `hashseed`
  unless `PYTHONHASHSEED=0` (V38); the scripts in `scripts/` do not check it.
- **Tests outside CI:** CI collects `tests/` only. The tests beside a run's code (`results/followup/run/test_*.py` and
  each round's `test_table.py`) run in that run's rehearsal or by hand, with the command in
  `results/followup/run/README.md` or in the test file's own docstring.
- **Writing tests:** CI runs plain `pytest`, which does not put the repository root on the path, so
  `from tests.x import ...` fails there even though it passes under `python -m pytest`: a head of
  [#434](https://github.com/electricsheephq/bicentennial/pull/434) failed all seven shards this way. In a test folder
  with an `__init__.py`, import a shared helper relatively (`from .test_x import ...`); in a folder without one, such as
  `tests/runner` or `tests/harness`, import it by its bare name (`from test_x import ...`), as those folders do. A new
  folder with its own `conftest.py` needs an empty `__init__.py`, or that `conftest.py` shadows the root one: a head of
  [#538](https://github.com/electricsheephq/bicentennial/pull/538) broke `tests/test_shards.py` this way. Run a new
  folder together with `tests/test_shards.py` in one session before you push. A script outside the package is loaded by
  path with `importlib.util`, as `tests/test_v01_acceptance.py` does. A test must not depend on git history, because
  some checks run on an archive of the commit, or on the network.

## Public text

Everything in this repository and every issue, pull request and comment is public.
- `scripts/public_check.py` checks tracked files: no local home or volume paths; no names from the deny list named by
  `BICENTENNIAL_DENY_LIST` (CI runs without one, so maintainers run it with theirs before a release); and the canary
  from `CANARY` in every file under `packs/`, `corpus/` and `schemas/fixtures/` (V31).
- Issue, pull request and comment text is not checked by CI. Before posting it, check that it has no local paths, no
  person, customer or machine names and no private repository names, and that every reference to another repository
  is a full link. This rule comes from
  [LCM-X's repository instructions](https://github.com/electricsheephq/lcm-x/blob/main/AGENTS.md), adopted in
  [#593](https://github.com/electricsheephq/bicentennial/issues/593).
- Never paste a sealed seed, an answer key or a per-item result on a private life (V43), or an access key or token,
  and never quote corpus text beyond what a published page already shows (V28).

## Issues and pull requests

These practices come from
[LCM-X's repository instructions](https://github.com/electricsheephq/lcm-x/blob/main/AGENTS.md), adopted in
[#593](https://github.com/electricsheephq/bicentennial/issues/593), except where a rule id is given.
- Search open and closed issues first. One accepted issue per change. A pull request says `Refs #N`, and uses a
  closing keyword only when the merge alone meets the issue's acceptance.
- A pull request body states why, what changes, an `## Evidence` block (the exact commands run and their results), its
  claim class and what it does not prove, and a `Risk:` line: Low, Standard or High, where High is anything that
  changes a score, a pack, a pin, a check, a run's procedure or a frozen file.
- Every review thread, bot threads included, gets a reply with its disposition (fixed in a named commit, false with
  evidence, an accepted tradeoff, or a follow-up issue) and is then resolved.
- Merge with a merge commit at the reviewed head: `gh pr merge N --merge --match-head-commit <sha>` (V36). Never
  force-push `main`, and never merge with a failing or pending `test` (V35).
- Agent-written issues, pull requests and comments start with the hidden `agent-origin:v1` marker naming the model
  (the owner's rule, so that readers can tell agent-written text).

## Results

- A result page (`results/<release>/<dated-folder>/RESULT.md`) has a `Claim class:` line and a `RESULT-MANIFEST.json`
  beside it, made by `scripts/result_manifests.py` (V29); run its `check` before you push. By practice it also has a
  "What this does not prove" section, which must be a bullet list where present (V29).
- A run's declaration is merged before its draw (V1), and no score is opened before the declaration's checks allow it
  (V4). Each declaration and each result is published with an adversarial review by a model family other than its
  author's (V19), and valid zeros are published, all-zero rows included (V27).
- A correction to a published result is a new commit that says what changed and why, and refreshes the result's
  manifest (V29).
