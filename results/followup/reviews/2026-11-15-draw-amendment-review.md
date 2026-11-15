# Review of the follow-up's seed-draw amendment, 15 November 2026

Reviewers: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only and offline on each draft with the repository and a saved beacon round; and three fresh-context Claude reviewers (`claude-opus-5-5` at high effort), each from one lens: an **adversary** who controls the machine, the run script, the repository's commits, the merging GitHub account and the timing of every post, but cannot forge GitHub's timestamps, comment ids or merge records or drand's rounds; **operations**, with agents running the draw end to end and no human step; and **consistency**, against every other section and RING0 §14.7. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. The text under each pass is Astra's own, unedited except that one reference to a draft's file name is given as its section and line, and its line breaks are written with a backslash; the Claude reviewers' findings are summarised in the dispositions. Line numbers refer to the draft each pass read. P1 and P3 in Astra's text are the build packets for the seed tool's three-pack mode and for the run script; their changes land as code with those pull requests.

## Why the draw changed

The declaration as first reviewed ([its review](2026-11-14-declaration-review.md)) drew the seeds with `secrets.randbits(63)` and posted the drawn list's sha256 before any pack was built. A bot reviewer on the pull request (Grok, P3) found that nothing checkable ruled out a quiet redraw: the operator could draw lists in private, run the cheap scripted anchors on each, and post the one it liked. It also found that the commitment lacked RING0 §14.7's draw-time receipt, and it proposed a committed secret combined with a public beacon round. This amendment closes that. It went through two mechanisms.

- **r5 to r9, commit and reveal.** The seeds came from a secret, committed by its hash on #394, combined with a drand quicknet round named before its value existed; the secret was to be revealed with the results.
- **r10 to r13, the beacon alone.** The seeds come from the public round only. There is no secret, and the lives are public from the round on (§9's departure row).

## How each finding was used

The review budget for a mechanism is one initial pass and three passes on fixes, then a decision checkpoint.

- **r5, the first draft (Astra SOUND-WITH-FIXES; all three lenses SOUND-WITH-FIXES):**
  - **The relay and hash checks do not authenticate the round (Astra 1):** fixed in r6. drand's public record is the authority anyone can compare the round against, and the relay and hash checks are named as checks on the script's own read. Astra's r6 pass judged its demand for local signature checking stronger than this declaration needs.
  - **The one-hour "round not published" exit allowed a redraw no one could check (Astra 2; operations):** fixed. A late round is waited for, and after 24 hours the run stops with no new draw.
  - **Nothing made the first post binding, unedited or unique (adversary); restarts, retried posts and a lost secret had no rule (operations):** fixed. A restart reuses the saved secret and round, and the rules say which post counts.
  - **Smaller points:** which clock times the post; what "the draw time" is; tying the committed seeds that are skipped to the run commit; publishing abandoned commitments; a rehearsal that checks a known answer, not only that the derivation repeats. All taken.
- **r6 (Astra SOUND; all three lenses SOUND-WITH-FIXES):**
  - **Two holes (adversary):** naming a new run commit dropped a counted draw, and a secret "lost" after the second post let the operator run a list of its choosing.
  - **A contradiction (operations):** the rule for which post counts contradicted the restart rule.
  - **Fixed in r7:** the earliest eligible post counts whatever commit it names, and the run is bound to that commit. A secret lost after the second post stops the run with every reading unresolved, and a late post never counts. Astra's r7 pass withdrew its r6 SOUND.
- **r7 (Astra SOUND-WITH-FIXES; all three lenses SOUND-WITH-FIXES):**
  - **Astra:** a stop had to publish at once a round that might not be readable.
  - **Adversary:** a repeated post could name a new run commit.
  - **Smaller points:** who may post; definitions for the posts; the stop list; what §6 does after a stop.
  - **Fixed in r8:** a stop publishes what it has, and the round when it can be read. Repeats are one post carrying the earliest post's values. The account, the issue, the first line, the content as created and the timing are defined. A stop before the round keeps round 2's ranking set, and a later stop leaves every reading unresolved.
- **r8 (Astra SOUND; all three lenses SOUND-WITH-FIXES):**
  - **Two vetoes:** two posts created in the same second let the operator pick the counted draw after the round (adversary). The author found the second: a secret claimed lost after the scores were seen turned every reading unresolved, a veto that could follow the scores.
  - **Checkpoint 1:** fix now, with one targeted review of the fix. The stop rule, written before that review: one more merge-blocking hole in this mechanism and it would be replaced.
  - **Fixed in r9:** same-second posts are ordered by comment id, and the secret is published and checked before the first reading.
- **r9 (Astra SOUND; adversary and consistency lenses SOUND-WITH-FIXES):**
  - **Two more vetoes that could follow the scores:** the secret could still be withheld until every arm's card existed, and the stop for an edited or deleted post had no end.
  - **Checkpoint 2:** stop patching, as the stop rule said. Every late veto found from r7 to r9 came from holding a secret after the draw. Hiding the seeds buys nothing in this run: one frozen system, whose identity is fixed in the first post before the round's value exists; scripted controls; a pinned reader; and placement and reading fixed at the run commit. So r10 replaced the mechanism, with a budget of its own.
  - **Kept from r8 and r9:** the definition of a commitment post, same-second order, repeats as one post, the counted-and-void chain, and §10's note on deletion.
- **r10, the beacon alone, first pass (Astra SOUND-WITH-FIXES; all three lenses SOUND-WITH-FIXES):**
  - **The stop for an unusable commit had no end, so it could follow the scores (Astra 1; adversary):** fixed in r11. Both of the draw's stops come before the first arm.
  - **Smaller points:** full 40-character commit ids; a void counts only when the seed tool reproduces it; the restart and late-post steps restored; a stop dated by its post; leftover sealing wording. All taken.
- **r11 (Astra SOUND-WITH-FIXES; all three lenses SOUND-WITH-FIXES, none blocking):**
  - **"Before any post ... posts nothing" forbade the required second post and the stop post (Astra):** fixed in r12. The guard covers further first posts only.
  - **Lens points taken:** the pack stop covers all three packs, counts only when the build fails again from a fresh checkout, and is posted on #394 by the merging account. All three packs and their task lists are frozen and posted before the first arm, and after that only §4's rules end the run.
- **r12 (Astra SOUND; all three lenses SOUND-WITH-FIXES, each with the same merge-blocking hole):**
  - **The hole:** "a main commit that existed when the post was created" did not say the commit had to be on main at that time. The account could name an unmerged commit, read the public round, then merge that commit (the post counts) or not (a later post counts).
  - **Fixed in r13:** the commit must already be on main, holding this declaration, when the post is created. GitHub's record of the pull request that brought it to main must show that merge in an earlier second; a commit's own dates count for nothing.
  - **Also taken:** a failed build is retried exactly once. The sentence on a stop before the round is due is gone, since both stops need the round. §10 discloses the stop the operator still has.
- **r13 (Astra SOUND; all three lenses SOUND-WITH-FIXES, none blocking):**
  - **Each lens and Astra checked the r12 hole:** whether a post is a commitment post is fixed when it is made, including through the rule that posts giving the same round are one post and through the guard.
  - **Wording and disclosure, taken in the final text:** "holding this declaration unchanged"; every comment with the first-post line is published with the commit it names, the pull request that brought that commit to main, its merge time, and whether it counted and why; §10 names GitHub's pull-request records and says how the operator can still cause a stop; a void must follow the stated rule as well as reproduce in the seed tool (adversary, optional, on text r13 did not change).
  - **The pull-request record is a necessary condition, not the whole test (all three lenses):** accepted. main's ruleset refuses non-fast-forward pushes and deletion, with no bypass, so a commit reaches main once: "on main when the post was created" means an ancestor of main whose pull request merged in an earlier second. A squash- or rebase-merged branch commit that never reached main fails the text's first condition. The run script checks both.
  - **Checkpoint 3:** the review is complete for the draw, so the run moves on. One bounded check of the final wording follows, with a rule set before it: an edit it finds unsound goes back to r13's text.
- **r14, the final check of the wording (Astra SOUND; consistency lens SOUND):** r14 takes the r13 points above and the pull request's two P4 bot comments: the status line says how each review is published, and §3 and §9 name the anchors. Neither reviewer found an edit that changes a rule, contradicts another section or cannot be followed. Applied after it: the status line gives the amendment's date.

**Build items,** which the three-pack seed tool and the run script must do and which land with those pull requests:
- check before each post that the posting account is the one that merged this declaration;
- read each comment as it was created, from its edit history, and keep each post's JSON;
- the guard against a further first post reads the saved posts as well as #394;
- name a commit that a merged pull request had already brought to main;
- rebuild a failed build once, and run again, without counting it, a build cut off by a sleep or a crash;
- test the derivation against a known answer for a published round.

## Pass on r5, the first draft

1. **Merge-blocking — The stated beacon checks do not authenticate the draw.**\
   **Evidence:** r5 §2, line 14 requires two agreeing relays and `randomness = sha256(signature)`; §3, line 40 calls these “signature checks.” That hash relation does not verify a signature or bind it to quicknet’s committed round. Operator-supplied matching JSON can satisfy it with arbitrary signature bytes, permitting screened randomness.\
   **Smallest fix:** require verification of the quicknet BLS signature against the pinned chain’s public key and the committed round, retaining the randomness hash check.

2. **Merge-blocking — The timeout permits replacement without checkable justification.**\
   **Evidence:** r5 §2, line 14: “If the round is not published within an hour … a new secret and round are posted.” Neither the required receipts nor the saved round JSON establish publication time. An operator can see an unfavourable draw, claim nonpublication, reveal the discarded secret and replace it; revealing that secret does not prove the timeout was legitimate.\
   **Smallest fix:** retrieval failure must retain the same commitment and round. Retry automatically; if the run must end, publish an incomplete outcome without authorizing a replacement draw. Keep the deterministic placement-void exception.

3. **Not merge-blocking — The build packets need coordinated updates, as anticipated.**\
   **Evidence:** P1 S1, lines 80–90, and D2, lines 156–159, prescribe direct random drawing and the old DRAW shape; P3 D8, lines 249–265, prescribes one draw post.\
   **Required changes:**\
   - **P1:** replace real random drawing with the specified deterministic derivation and collision skipping; define private secret/beacon provenance alongside DRAW, preserving existing placement inputs and public-integer rehearsal behavior. Update the derivation fixture and output checks.\
   - **P3:** automatically create and verify the first post before the future round; authenticate that round, derive once, and post the draw receipt before placement/build. Preserve the same attempt across interruptions, archive the secret and both posts on placement void, and disclose them with results. Extend D9’s rehearsal and D18’s private-file rules.

The saved diff matches the two declarations; the saved relay responses agree, their digest relation holds, and the five-candidate known-answer derivation matches. These checks do not authenticate the beacon. No tests, builds, network access or writes were performed.

**Verdict: SOUND-WITH-FIXES.**

## Pass on r6

**Finding 1 — Closed for the stated goal.** §2 now explicitly makes drand’s public record the authority and requires disclosure sufficient to recompute the list against that record. Fabricated relay JSON cannot pass that comparison. The relay/hash checks still do **not** authenticate a BLS signature; §3 now labels them correctly. My earlier insistence on local BLS verification was stronger than necessary for this checkable, exploratory declaration.

**Finding 2 — Closed.** §2 requires waiting for the committed round, preserving the secret and round across retries, and stopping after 24 hours without a replacement draw. The deterministic, disclosed placement-void exception remains. Claimed nonpublication no longer permits selection through redraws.

**New holes or contradictions — No new merge-blocking defect found.** A late first post is objectively disqualified by GitHub creation time; that exception cannot replace an already counted draw. Publishing all commitment posts and earlier draw secrets makes the sequence inspectable. The due-time receipt and known-answer rehearsal are consistent with the amendment. Disclosed secret loss or leakage remains a failed proof of recomputability or secrecy, not evidence that those properties held.

Both saved diffs match their declarations. This is a declaration review; implementation and live execution were not verified. No network, tests, builds, or writes were used.

**Verdict: SOUND.**

## Pass on r7

SOUND-WITH-FIXES

The three reported holes are closed:
- **Commit switching:** §2 selects the earliest eligible commitment regardless of commit and binds execution to that commit; changing commits cannot discard it.
- **Secret loss after the second post:** the run stops and every reading becomes unresolved.
- **Late/repeated posts:** late posts are excluded explicitly; duplicate hash-and-round posts inherit the earliest timestamp, so repeating an on-time post does not trigger disclosure.

**Merge-blocking — Immediate stop disclosure requires a potentially unavailable round.**\
At r7 §2, line 19, “published at once with the round as drand serves it” also applies when the committed round cannot be retrieved, or when the commit cannot be used before that future round exists. The script cannot fulfill that combined publication requirement immediately.

**Smallest fix:** publish the surviving secret and stop reason immediately; include the round if available, otherwise record its unavailability and append it when retrievable. Preserve the prohibition on replacement draws.

The whole-number wording matches the scanner’s numeric-boundary rule. P1 must still implement scanning the committed snapshot; P3 must implement the revised commitment, duplicate, late-post and stop rules.

**My unqualified SOUND on r6 does not stand.** I missed the commit-switch loophole and treated disclosed secret loss as invalidating proof without requiring the declaration to invalidate the readings explicitly. R7 repairs both.

Both supplied diffs match their declarations. This was read-only declaration/source inspection; no network, credentials, tests, builds or writes.

**Recommended next steps:** amend the single stop-publication sentence before implementation. No broader hardening is needed for this finding.

## Pass on r8

SOUND

R8 closes the reported defects without a new merge-blocking hole or contradiction:

- **Stop disclosure:** the surviving secret and reason publish immediately; the round follows when readable.
- **Repeat posts:** the earliest post fixes the round and commit for that secret hash; repeats cannot change the skip set.
- **Eligibility:** the account, issue, first-line marker, creation-time content and timing threshold are explicit.
- **Draw order:** the earliest eligible draw counts; only a placement void advances to the next.
- **Stops:** an unusable commit and edits or deletions of either counted post explicitly stop the run.
- **Ranking consequences:** stops before the round preserve round 2’s set; later stops make every reading unresolved and invoke §6.

The creation-time rule prevents editing an innocuous comment into an eligible commitment. §10 correctly preserves the evidence limit: deletion detection depends on retained records or independent copies; it is not guaranteed by the current issue view.

Both supplied diffs match their declarations. P1/P3 must implement these revised rules together.

This is declaration-level review only; implementation and execution remain unverified. No network, credentials, tests, builds or writes were used.

## Pass on r9

SOUND

R9 closes both holes without a new merge-blocking defect in the reviewed amendment.

- **Same-second commitments:** §2’s lower-comment-id tie-break fixes the order independently of the operator. Repeats retain every value of the earliest post.
- **Secret-loss veto:** publication and verification precede the first reading of the actual run. Once published, losing the private copy cannot make the secret unavailable or justify invalidating scores.
- **§3 reruns:** the sequence is consistent: 36 first attempts → publish and verify → reading script → eligible rerun → reading script again. Passing arms remain ineligible; commit, identities and bound stay frozen.
- **§4 checks:** publishing the secret opens no score and waives no check. Pending arms still suppress scores, and the existing failure rules remain applicable.
- **§5 readings:** pooling, missing-data rules and contrasts are unchanged. Disclosure creates no new choice of observations.
- The second-post binding, counted-round stop timing and §9→§10 reference are consistent with those rules.

Both supplied diffs match their declarations. This is declaration-level review only; implementation and execution are unverified.

## Pass on r10, the beacon alone

1. **Merge-blocking — Commit unavailability still permits a late veto.**\
   **Evidence:** §2 stops the run “if the run cannot use the commit that the counted post names”; any stop after the round “leaves every reading unresolved.” This has no cutoff. After all required cards exist, but before publication, making the checkout unusable still authorizes replacing their readings with unresolved. Removing the secret and edit-triggered stops does not close this remaining route.\
   **Smallest fix:** make commit unavailability pause further execution without retroactively invalidating completed, valid observations. Missing or invalid observations retain §§4–5’s consequences; unavailable execution machinery alone cannot erase a supported reading.

2. **Not merge-blocking — The implementation packets still specify the old draw.**\
   **Evidence:** P1 D2 specifies `secrets.randbits(63)`; P3 D8 draws before posting, and D18 says “Hidden until the results.” Their planned revision remains necessary.\
   **Smallest fix:** implement r10’s future-round commitment, deterministic derivation against the committed snapshot, counted-post ordering, two-post receipt, and public-lives rule together.

The public derivation otherwise removes secret-loss and withholding vetoes. Creation-time contents, duplicate handling, same-second ordering, commit binding, and deterministic placement voids preserve the earlier repairs. Later comment edits no longer change the draw or invalidate it.

Making the lives public introduces no demonstrated defect in this frozen exploratory run: identities and rules precede the round, and the inspected Hermes setup checks a fresh installation. This supports the declared departure from sealed Ring 1 seeds; it does not prove live execution compliance.

Both diffs match their declarations. The known-answer derivation matches, and the saved relay responses agree with its signature-hash relation. No network, credentials, tests, builds, or writes were used. Implementation and live beacon authenticity remain unverified.

**Verdict: SOUND-WITH-FIXES.**

## Pass on r11

**SOUND-WITH-FIXES**

r11 closes r10’s hole: §2 confines both draw stops to before the first arm, so commit unavailability cannot later erase completed readings. Dating a stop by its reason post also prevents backdating it before the round.

**Merge-blocking — The posting guard forbids the required receipt.**\
§2, “The round,” says “Before any post” and “posts nothing” while an on-time, non-void draw exists. Once the first post succeeds, this forbids §2’s mandatory second post; packs cannot then be built while obeying both rules. It also covers required stop-reason posts.

**Smallest fix:** narrow the guard to first commitment posts: “Before posting a `Follow-up draw: first post`, it reads #394 and posts no further first post while an on-time commitment post of a draw that is not void exists.”

Otherwise, I found no new qualifying defect in the delta. Both supplied diffs match their declarations. This is a read-only declaration review; implementation and live execution remain unverified.

## Pass on r12

SOUND

r12 closes the r11 blocker: §2’s guard now forbids only further **first posts**, leaving the required second receipt and stop-reason posts permitted.

The accompanying changes introduce no qualifying defect:
- The commitment names an existing main commit; §3 still requires that commit to contain the declaration and run machinery.
- A pack/task-list stop requires failure again from a fresh checkout at the fixed commit; a successful retry cannot justify stopping.
- All three packs and task lists are frozen and their hashes posted before any arm starts, consistent across §§2–3.
- After that point, §4 governs termination and §5 handles missing readings, without reopening the draw.

Both supplied diffs match their declaration files. This is an offline, read-only declaration review; implementation and execution remain unverified.

## Pass on r13

SOUND

r13 closes the reported defect without a new merge-blocking hole or contradiction.

- **Eligibility is fixed at creation.** §2 requires the named commit already to hold the declaration on main, evidenced by a PR merge in an earlier second. Later merging cannot qualify an earlier comment; commit dates cannot substitute.
- **Same-round grouping preserves that boundary.** Only commitment posts are grouped. An ineligible earlier comment cannot supply its timestamp or values to a later eligible post. Among eligible posts, the earliest supplies every value; later duplicates cannot replace its commit or identity.
- **The first-post guard remains consistent.** An on-time, nonvoid commitment blocks further first posts. Later merging cannot activate an earlier ineligible comment. Advancing requires the reproducible placement void; a stop permits no replacement draw.
- **Retry and stop rules agree.** Exactly one fresh-checkout rebuild resolves the retry ambiguity. Both stops occur after the round is due, and §§5–6 make every reading unresolved and remove all four kinds. §10 accurately discloses that consequence without granting another stop condition.

Offline declaration review only; implementation and live GitHub records were not verified.

## Final check, on the wording (r14)

SOUND

No r14 edit introduces a way to choose or bias the lives or readings, a contradiction, or an impossible requirement.
- “Unchanged” tightens eligibility; the placement addition requires both rule compliance and reproducibility.
- Publishing every matching first-post comment broadens disclosure without changing which post counts.
- Naming R, B, G and W agrees with §5; B, G and W remain the once-per-pack rows.
- The review-publication wording changes disclosure only.
- §10 describes the existing ability to cause a stop; it grants no replacement draw or new stop rule.

No reversion needed. Offline wording review only; implementation and live records were not verified.
