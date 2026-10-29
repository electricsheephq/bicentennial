# S8: an image profile through a real harness

**Question.** Can Bicentennial put evidence that exists only in an image into a life, route it through a real harness, and later ask an unforeseen question about it? And can it tell a perception failure apart from a memory failure, at a known cost?

S8 is a feasibility spike for the Image profile (design v2.0, DV9 in `docs/DECISIONS-v2.md`). It produces no score for any memory system. Until S8 passes, the Image profile reads "pending" in Ring 0. It joins the season-1 sealed board only if S8 and the pilot's validity checks pass; otherwise it joins in season 2. In season 1 the Image board is planned at 8 lives of 40 image bundles each; at that size it publishes cell verdicts and diagnostics and issues no certificate (DV38).

**Recorded change.** The owner's direction of 2026-10-26, to test capabilities such as images that systems lack, moves rendered images ahead of the original brief's "build capture only after measured use" (#1719). The images here are rendered from world state, never by an image generator. Continuous-stream capture still waits for measured use.

## What it builds (spike-grade code, under `spikes/s8/`)
1. **A renderer.** It draws images deterministically from world-state records, never with an image generator. Kinds:
   - an app screenshot (a settings page with a port value);
   - a document page (a receipt with line items);
   - a simple scene (a desk with labelled objects).

   Each image carries an **exposure manifest**: every value that is legible and unoccluded in the image, with its bounding box. Gold questions may use only manifest values. Presentation (font, theme, layout, colour) is randomised from its own seed, independently of the gold values.
   - **Fidelity checks** (joining the design's render checks): a manifest verifier, which checks each manifest value is drawn as recorded, and a human-key sample covering legibility. The design's thresholds are manifest-verifier recall ≥ 0.99 against a 200-item human-key sample, and human legibility ≥ 95%; the spike reports against them.
2. **Delivery into a life.** Ten seeded 6-session micro-lives in the G1 genre, scripted as in S6a, so each mode gets at least 30 base questions plus their twins. Three images arrive in session 2: one as a user attachment, one as a tool observation (the env server's `screen` tool), one as a workspace file. Session 2 ends with a third replay turn, "Thanks. Please keep both images in mind.", so a live write turn receives the workspace inspection result. Questions come in session 6. Each question asks about a detail that the session-2 conversation never mentions.
   - **Typed answer envelopes:** every question has an exact or structured answer type first (a number, a string from the manifest, a list), so no judge is needed for the spike's items.
3. **Routing through Hermes v0.22.2** (the pinned clone), in both of `agent/image_routing.py`'s modes:
   - **text mode:** the main model stays text-only (GLM), and Hermes' `vision_analyze` describes the image through the auxiliary vision provider. The director pins and records that provider. This is the **memory-layer view**;
   - **native mode:** a vision-capable main model receives the image parts. This is the **system view**. ⟦placeholder, not an open decision: the benchmark maintainers choose the vision-capable main model for native mode in this spike, from the capability census, and pin it in C-1's route table before any Image board (DV41, DV46).⟧

   Native-routing *system* rows are reported separately from *memory-layer* rows, and the two are never averaged.
4. **A vision lane, chosen in this order:**
   1. a vision model available on the GLM Coding Plan, if one exists. Probe the coding endpoint for a vision model such as a GLM-4.xV id with one image request; the text models already rejected image parts;
   2. otherwise, one paid flash-class vision model.

   The spend cap is $10 for the whole spike. Before each paid call, its maximum charge is reserved against the remaining budget. When the next call's reservation would exceed it, the spike makes a recorded, controlled stop. Spend is reported per call and in total. The chosen model is the candidate **pinned vision reader**, the vision slot that the design adds to the route table and completion slot C-1; the spike records it, and does not freeze it. The vision provider is pinned separately from the main model, so a model swap does not move it.
5. **The observation and assistance contract,** which holds for every memory comparison in the spike:
   - every arm gets the same image bytes per item, the same perception service, the same access timing and the same logical budget;
   - **the caption cache:** the director caches a description only by an identical authorised call (the same image bytes, sent to the same pinned provider with the same prompt, by an arm entitled to make that call). A cache hit returns what that call would have returned and never grants an arm evidence it did not receive. Cache hits are recorded per arm;
   - **reinspection:** an arm may look at an original image again at question time only if its stack retained that image, and the look is charged to its logical budget. The ledger records every reinspection.
6. **Baselines and controls:**
   - **the no-memory floor:** questions asked with no history;
   - **the oracle ceiling, which is the direct-evidence control:** the same stack, at question time, handed the original image and the question. A stack that cannot use the evidence even when handed it directly is **N/A_READER** for that item, which separates "cannot perceive" from "did not remember";
   - **naive RAG** over the stack's own descriptions of the session-2 images.
7. **Shortcut checks:**
   - presentation randomised independently of gold (item 1);
   - **stylistically matched twins:** twin items built from the same template with the gold value changed and presentation matched, so that style alone cannot tell the twins apart;
   - **shuffled history:** the session-2 images swapped for presentation-matched images carrying different values. A high score here means the shortcut check has not passed; report whether the result shows a shortcut or is inconclusive before deciding whether to redesign the twins or presentation;
   - **a held-out style:** one presentation family used only at question time.
8. **Gist and detail as descriptive tags.** Any representation that keeps the information earns credit; the design principle is the unforeseen later question. For each question, record whether the text-mode description retained the asked value. This measures how often a description keeps a detail; it is not a pass rule.

## What it measures
- Routing works in each mode and channel: yes or no, with the request ledger. A pair routes only when a session-2 image request has a known role, a matched image-bearing request reaches a live model successfully after normalised retries, and the pair's next main or write-turn request is answered 200.
- Direct-evidence accuracy per mode, which measures perception, and the N/A_READER count.
- Delayed accuracy after 4 sessions per mode, against the no-memory floor, naive RAG, stylistically matched twins and shuffled history.
- Detail retention in text-mode descriptions: the share of asked values present in the description.
- Cost and latency per vision call, cache hit rate, reinspections and their charge, and projected vision spend per season under the design (about $50 a season, approved by the owner on 2026-10-26). These fill the design's cost term for the Image profile's two views.
- Each row's stack identity: memory, harness, model, the vision provider and spend.
- Whether presentation alone predicts any answer: the twin, shuffled-history and held-out-style results.
- The fidelity checks: manifest verifier results and the human-key legibility sample.

## Done when
`spikes/s8/REPORT.md` gives each measurement with its sample size, and every mode × channel pair (user attachment, `screen` tool observation, workspace file) routes its image through the director with the ledger showing every request classified and none unknown. **Admission to Ring 0.** This is a feasibility gate for the developer packs only, never a board rule. A mode is admitted when all of these hold:
1. **Fidelity first.** The manifest verifier's recall is ≥ 0.99 against the 200-item human-key sample, and human legibility is ≥ 95%. Otherwise the renderer is fixed and re-run, and no mode is admitted.
2. **Sample size.** At least 30 base questions in the mode, from at least 10 lives; twins are counted separately.
3. **The reader can perceive.** At most 20% of the mode's items are N/A_READER. N/A_READER items leave the delayed comparison, and their count is reported. A mode above 20% is not admitted, because it would measure perception, not memory.
4. **Direct evidence clears the floor.** The one-sided 95% lower bound of (direct-evidence accuracy − no-memory accuracy) is at least 30 percentage points.
5. **Shuffled history does not clear it.** The one-sided 95% upper bound of (shuffled-history accuracy − no-memory accuracy) is at most 10 points. Otherwise the shortcut check has not passed, and the profile stays pending. Report whether the result shows a shortcut or is inconclusive before deciding whether to redesign the twins or presentation.

Bounds come from a cluster bootstrap over lives (10,000 draws), because items within a life are correlated. The Image profile is admitted to Ring 0 when every mode × channel pair routes and both modes are admitted. A mode that fails is reported with its numbers, and the profile stays "pending".

## Does not prove
- Anything about any memory system's quality.
- That rendered images resemble real users' images. Photos, audio and video come later.
- Claude Code image input. That needs its own adapter step.
- Season cost beyond the projection.

## Machine and rules
- Run under `nice`.
- Gate on the busy marker: pause GLM while `glm` is true.
- Never touch a production agent, and write nothing outside the spike's own isolated Hermes home.
- The key reaches only the director, through the child env.
- Public-check every committed file.
