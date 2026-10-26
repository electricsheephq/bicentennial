# Generator spec G1: software partner world (Phase 1 core) — DRAFT

Purpose: a seeded world in which an agent works with a small team on one evolving repository for a simulated 3-26 weeks. Everything the agent can observe is rendered from the world database. Feeds families F1-F13.

## 1. World database (SQLite, one file per world; schema versioned with the generator)
- `entity(id, kind, canonical_name, aliases_json, created_t, retired_t)` — kinds: person, team, repo_module, file, function, flag, endpoint, dependency, service, environment, ticket, incident, test, ci_job, decision, constraint, preference, commitment, credential_placeholder (never a real secret).
- `attr(entity_id, key, value, valid_from_t, valid_to_t, recorded_t, source_event_id)` — bitemporal value history: valid time, plus record time (when the agent was told or could observe it). Revisions are immutable rows, so supersession is a new row and nothing is deleted. Each template declares as-valid or as-known semantics (DESIGN §4.1).
- `event(id, t, kind, channel, actor_id, audience_json, visibility, salience, payload_json)` — channels: chat (user↔agent), tool_result, file_content, commit, ci_log, issue_thread, review_comment, email_digest, standup_note. Visibility: shared, private_to(person), agent_only.
- `fact(id, event_id, subject_id, predicate, object, polarity, modality, strength, speech_act)` — modality: stated, observed (tool output), inferred_allowed (a fact the template may ask as inference), retracted, planted. Strength and speech act (assert, hedge, propose, quote) are compared exactly for gold-critical events (DESIGN §4.4).
- `link(event_id, fact_id, role)` — which facts each event asserts, retracts or mentions.
- `exposure(run_id, event_id, delivered_t, delivery_id)` — written by the director at run time, not by the generator.

Invariant: every rendered claim maps to a `fact` row; a render is rejected if the verifier finds a claim with no row.

## 2. Processes (stochastic, seeded, composable)
1. **Team dynamics:** 3-8 people with roles, time zones, working hours, communication styles; joins and departures; ownership changes per module.
2. **Project arc:** milestones, scope changes, deadline moves (supersession chains of length 1-6).
3. **Decision process:** a question is raised; options are discussed (each option a fact with polarity); a decision is made, sometimes reversed later with a reason; some decisions are stated once in chat and never written into the repo (memory-in-action material).
4. **Constraint process:** user-stated rules ("never log emails", "all new endpoints use the v2 auth decorator", "no dependency with licence L") with scope and start time; some are relaxed or scoped later.
5. **Code evolution:** a templated codebase (a Python service: modules, functions, config constants, flags, endpoints, tests). Commits are generated programmatically as structured diffs (rename, add endpoint, change constant, add test, revert); the repo is a real git history the sandbox can check out at any time.
6. **Incidents and flakiness:** CI failures with deterministic logs, flaky tests with patterns (fails on Mondays, on one runner), incident timelines with root causes revealed later (a delayed-revelation update).
7. **Personal and incidental:** people mention preferences, holidays, side facts (low salience, high later-value for a fixed fraction: the incidental-salience lever).
8. **Commitments:** "remind me on Friday to…", "when the migration lands, ping Sam" (prospective-memory triggers keyed to later events).
9. **Forget requests:** a person asks the agent to forget a private fact; derivative facts (a later summary mentioning it) are linked.
10. **Filler:** routine work sessions rendered from low-salience events of the same processes (keeps the stream consistent and long).

Scale: 1 simulated week ≈ 150-400K tokens of rendered stream depending on activity density; 26 weeks reaches 4-10M tokens.

## 3. Rendering
- Chat turns: an LLM renders each event spec under a persona style sheet; tool results are rendered deterministically from the sandbox (real `git log`, file reads, test output) wherever possible, so most tokens need no LLM.
- Verifier: a different model extracts claims and checks each against the render's own manifest plus the background set B(t, speaker, audience) (DESIGN §4.4). Mismatches re-render (max 3, then fall back to a template). Gold-critical events use the phrase bank and locked tokens. Absence for F7 targets is non-entailment: the top exact, fuzzy and embedding hits are checked by two verifier families.
- Session structure: the stream is cut into harness sessions (work sessions of 10-200 turns); session boundaries, restarts and idle gaps follow the team's calendar.

## 4. Question templates (examples; each compiles to a DB query)
| Family | Template | Gold source |
|---|---|---|
| F1 | "What exact value did we set for <flag described by purpose> after the <incident described>?" | attr at t |
| F2 | "Who first proposed <option described>, and in which conversation?" | fact → event (actor, t, channel) |
| F3 | "How many days passed between the first report of <flaky test described> and its fix?" | event times |
| F4 | "What was the release date before the second slip?" / "What is it now?" | attr history |
| F5 | "How many times did CI fail on <job> in March, and on which days?" | count over events |
| F6 | "Which module had the most ownership changes, and who owns it now?" | aggregate + attr |
| F7 | "When did we decide to drop <dependency that was discussed but never dropped>?" | absence (non-entailment) → false premise |
| F8 | "Did Sam ever tell you why she was away in week 7?" (private to another person → refuse or abstain correctly by visibility) | visibility |
| F9 | Task: "add an endpoint for <feature>" with hidden checks for every active constraint in scope | tests and AST checks, validated against an accept pool and memory-error mutants (DESIGN §7.1b) |
| F10 | At trigger event: did the agent send the ping or reminder? | environment action log |
| F11 | Recurring task type (release checklist) across episodes: steps missed per episode | environment log |
| F12 | After "forget X": X and its derivatives not surfaced; neighbours still answerable | retained twin first; then suppression and neighbour accuracy, scored jointly |
| F13 | Same item set after a fault schedule vs the fault-free twin | paired |

## 5. Determinism and versioning
`(generator_version, genre, seed, scale)` → world DB bytes identical. Rendered stream cached with content hashes. Question set = f(world DB, template set version, sampling seed). Held-out: test seeds, a private template subset and a private persona/style subset.

## 6. Open questions
- Codebase realism: templated Python service vs mutating a real permissively licensed repo snapshot (more realistic code; harder to keep closed-world). Lean: templated first, real-repo variant in v2.
- How much chat should be LLM-rendered at 10M tokens (cost) vs templated paraphrase (artefact risk). Measure render cost per 100K tokens in the pilot.
