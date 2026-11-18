# References

This page lists the prior work that the design ([DESIGN.md](DESIGN.md) §2) and the roadmap's comparison section ([ROADMAP.md](../ROADMAP.md), "How Bicentennial differs from other memory benchmarks") name, so each one can be looked up.

How it was built (19 November 2026):
- Every link comes from the Phase 0 survey's source lists, except Compact-Bench's, which came from the arXiv page of that work, opened on 19 November 2026.
- These links were also opened on 19 November 2026, and each page's title matched the work: Ground Truth First, ConPACT, ContinuityBench, The Compaction Cliff, Compact-Bench, LIMBO, MemOps, HOMER, DolphinBench (its site and its arXiv page) and the Agent Memory Leaderboard's repository.
- Each entry gives the name, the year, authors and venue where the source gives them, the link, and one line on what the work measures. The one-line summaries are ours.
- A work named in several places has one entry; other sections point to it.
- A work with no real source found would be listed under "Named in the design, source not located". No link, author or year is filled in by guesswork.

The sections follow the order of DESIGN §2.

## What the popular boards show

- **LoCoMo** (2024; ACL 2024). [arXiv 2402.17753](https://arxiv.org/abs/2402.17753); project page [snap-research.github.io/locomo](https://snap-research.github.io/locomo). Question answering and event summaries over long synthetic conversations of many sessions each.
- **LongMemEval**, including its S variant (2024; ICLR 2025). [arXiv 2410.10813](https://arxiv.org/abs/2410.10813); [repository](https://github.com/xiaowu0162/LongMemEval). Five memory abilities of chat assistants (extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention); the S variant gives each question a history of about 115,000 tokens.
- **Ground Truth First** (2026; a single-author preprint). [arXiv 2607.21962](https://arxiv.org/abs/2607.21962). Long-term agent memory over chat and email at 3 and 9 weeks of tenure, with gold facts sampled from a life script before any text is written and scored by a fixed answerer under two judges from different model families. It reports that architecture rankings change between 3 and 9 weeks, and that at 9 weeks its layered system leads full history under its primary judge but trails it under the cross-family judge.

## Generator-first ground truth

- **Ground Truth First**: see above.
- **MemSim** (2024). [arXiv 2409.20163](https://arxiv.org/abs/2409.20163). Simulated personal-assistant data whose question gold comes from a sampled structured world rather than from a language model's reading of the text (the MemDaily set).
- **GoodAI LTM Benchmark** (2024; NeurIPS 2024 Datasets and Benchmarks, "Beyond Prompts: Dynamic Conversational Benchmarking of LLMs"). [arXiv 2409.20222](https://arxiv.org/abs/2409.20222); [repository](https://github.com/GoodAI/goodai-ltm-benchmark). One long conversation with interleaved tasks, at memory spans from about 2,000 to 500,000 tokens.

## Prospective memory

- **PM-Bench** (2026). [arXiv 2607.12385](https://arxiv.org/abs/2607.12385). Carrying out intentions at future cues over a simulated week, with lures and rescheduled tasks, scored against the set of tasks due at each step.

## History-dependent task validation

- **DolphinBench**: see "Other benchmarks compared in the roadmap".
- **MemoryArena** (2026; ICML 2026). [arXiv 2602.16313](https://arxiv.org/abs/2602.16313); project page [memoryarena.github.io](https://memoryarena.github.io). Whether memory from earlier sessions improves later actions in multi-session tasks that depend on each other.
- **DreamBench-SWE** (2026; a single-author preprint). [arXiv 2608.20664](https://arxiv.org/abs/2608.20664). Memory across sessions for software agents, where later tasks need evidence from earlier sessions and are checked by hidden executable tests.

## Write-step scoring

- **HaluMem** (2025). [arXiv 2511.03506](https://arxiv.org/abs/2511.03506). Errors at each memory operation, with extraction, updating and question answering scored separately.

## Shared-memory governance

- **GateMem** (2026; Ren et al.). [arXiv 2606.18829](https://arxiv.org/abs/2606.18829). Memory shared between several parties, scoring usefulness, access control and forgetting together.

## Forgetting through derived artifacts

- **Bemula** (2026; Xie et al.). [arXiv 2610.18052](https://arxiv.org/abs/2610.18052); [repository](https://github.com/Nboxff/bemula-benchmark). Whether a memory system forgets on request, across several kinds of forget request.
- **AfterDeleteBench** (2026; Saleh et al.). [arXiv 2610.31366](https://arxiv.org/abs/2610.31366). Whether deleted information persists and can still be recovered after deletion.

## Constraint loss through compaction

Compaction here means replacing part of an agent's context with a shorter summary.

- **ConstraintRot** (2026; a single-author preprint). [arXiv 2606.22528](https://arxiv.org/abs/2606.22528). Policy and safety constraint violations after compaction in long-horizon agents.
- **ConPACT** (2026; Wang et al., "Lost in Context Compaction: When LLM Systems Drop Side Constraints"). [arXiv 2608.11242](https://arxiv.org/abs/2608.11242). How often side constraints a user stated survive different compaction methods.
- **ContinuityBench** (2026; an ICML 2026 workshop poster, single author). [ICML 2026 page](https://icml.cc/virtual/2026/68364). How well agents recover from interrupted state, with existing agent benchmarks run at several levels of carried-over state.
- **ContextEcho** (2026). [arXiv 2605.24279](https://arxiv.org/abs/2605.24279). Drift of an assistant's persona and register over very long tool-using sessions, and whether compaction resets it.
- **The Compaction Cliff** (2026; Zerhoudi et al., "The Compaction Cliff in Long-Running AI Agent Memory"). [arXiv 2608.22752](https://arxiv.org/abs/2608.22752). How many rules survive one to five rounds of a production compactor.
- **Compact-Bench** (2026; Sun et al., "Compact-Bench: Measuring What Context Compaction Costs Long-Horizon Coding Agents"). [arXiv 2610.31710](https://arxiv.org/abs/2610.31710). Coding agents continuing a task from the full history against continuing from a compacted summary only, from the same repository state.

## No-literal-match and aggregation items

- **NoLiMa** (2025; Modarressi et al.; ICML 2025). [arXiv 2502.05167](https://arxiv.org/abs/2502.05167); [repository](https://github.com/adobe-research/NoLiMa). Long-context retrieval where the question and the needed passage share no literal words.
- **Oolong** (2025; Bertsch et al.; COLM 2026). [arXiv 2511.02817](https://arxiv.org/abs/2511.02817). Aggregation over long contexts, such as counting and building timelines.

## Item filters

- **LoCoMo-Plus** (2026; ACL 2026). [arXiv 2602.10715](https://arxiv.org/abs/2602.10715); [repository](https://github.com/xjtuleeyf/Locomo-Plus). Applying a constraint stated earlier when the later question shares little wording with it.
- **ConvoMem** (2025). [arXiv 2511.10523](https://arxiv.org/abs/2511.10523). A large conversational memory set covering user facts, changing facts, abstention, preferences and implicit connections.
- **LongMemEval-V2** (2026). [arXiv 2605.12493](https://arxiv.org/abs/2605.12493); [repository](https://github.com/xiaowu0162/LongMemEval-V2). Memory for web agents over very long recorded trajectories, with questions filtered against frontier models.

## Historical belief, over-update and propagation

- **AToKe** (2024; Yin et al.; AAAI 2024). [arXiv 2312.05497](https://arxiv.org/abs/2312.05497). Knowledge editing that must keep earlier facts answerable as of their own dates.
- **Belief-R** (2024; Wilie et al.). [arXiv 2406.19764](https://arxiv.org/abs/2406.19764). Belief revision when a new premise arrives.
- **RippleEdits** (2024; Cohen et al.; TACL 2024). [arXiv 2307.12976](https://arxiv.org/abs/2307.12976); [repository](https://github.com/edenbiran/RippleEdits). Whether an edited fact's consequences reach related facts.
- **MQuAKE** (2023; Zhong et al.; EMNLP 2023). [arXiv 2305.14795](https://arxiv.org/abs/2305.14795); [repository](https://github.com/princeton-nlp/MQuAKE). Multi-hop questions after knowledge edits.

## Learning gain against a no-memory twin

- **CL-Bench** (2026; Asawa et al.). [arXiv 2606.05661](https://arxiv.org/abs/2606.05661); [site](https://www.continual-learning-bench.com). Whether agents learn structure that is never stated, checked by hidden regression tests.
- **PAST-Bench** (2026; Xue et al.). [arXiv 2608.04003](https://arxiv.org/abs/2608.04003); [repository](https://github.com/Gen-Verse/PAST-Bench). Self-improvement across sessions in agent frameworks, with persistence switched on and off.
- **MERIT** (2026; Mishra and Mishra). [arXiv 2609.05441](https://arxiv.org/abs/2609.05441). The value of memory per dollar, under updates and corruption.

## Streaming timing and memory budgets

- **TeleEgo** (2025). [arXiv 2510.23981](https://arxiv.org/abs/2510.23981); [repository](https://github.com/TeleAI-UAGI/TeleEgo). Streaming memory over long egocentric recordings across modalities.
- **OVO-Bench** (2025; CVPR 2025). [arXiv 2501.05510](https://arxiv.org/abs/2501.05510). Online video understanding: questions about the past, the present, and questions that must wait for future evidence.
- **OEM-VQA** (2025; Lando et al.). [arXiv 2506.16450](https://arxiv.org/abs/2506.16450). Online episodic-memory question answering on egocentric video, reported with the memory each method keeps.

## Governance practice

- **ARC-AGI-3** (2026; ARC Prize Foundation). [arXiv 2603.24621](https://arxiv.org/abs/2603.24621); [arcprize.org](https://arcprize.org). Interactive novel games that must be learned while playing, with public and private evaluation splits.
- **Agentic Benchmark Checklist** (2025; Zhu et al.). [arXiv 2507.02825](https://arxiv.org/abs/2507.02825). A checklist of practices for building rigorous agentic benchmarks.
- **BenchJack** (2026; Wang et al.). [arXiv 2605.12673](https://arxiv.org/abs/2605.12673). Shows that agents can reach high scores on many benchmarks without solving their tasks.

## Real-harness and fault precedents

- **MemSecBench** (2026). [arXiv 2607.27080](https://arxiv.org/abs/2607.27080). Memory poisoning in real agent harnesses: whether it persists, is acted on, and can be repaired.
- **LIMBO** (2026; a single-author preprint, "Where Does Exactly-Once Live?"). [arXiv 2609.29095](https://arxiv.org/abs/2609.29095). Duplicate side effects in production agent harnesses under injected service faults.
- **ContextEcho**: see "Constraint loss through compaction".
- **VibeMemBench** (2026). [arXiv 2609.23570](https://arxiv.org/abs/2609.23570). Whether experience drawn from a repository's history changes coding outcomes, scored by executable tests.
- **WorldMemArena** (2026). [arXiv 2605.29341](https://arxiv.org/abs/2605.29341); [repository](https://github.com/UCSB-AI/WorldMemArena). The write, maintain, retrieve and use stages of multimodal agent memory, scored separately.
- **PAST-Bench**: see "Learning gain against a no-memory twin".

## Causal-use probes

- **IMEP** (2026; with ChainBench). [arXiv 2610.23372](https://arxiv.org/abs/2610.23372). An interventional test of memory in vision-language-action systems: edit what is remembered and check whether decisions change.

## On-policy simulated users

- **AMemGym** (2026; ICLR 2026). [arXiv 2603.01966](https://arxiv.org/abs/2603.01966); [project page](https://agi-eval-official.github.io/amemgym). Personalisation against a hidden user state, with simulated users who respond to the assistant, a normalised score and failures split into writing, reading and use.
- **WorldMemArena**: see "Real-harness and fault precedents".

## Budgeted writing

- **MEMAUDIT** (2026). [arXiv 2605.02199](https://arxiv.org/abs/2605.02199). Choosing what to write to memory under a storage budget, scored against an exact optimum.

## Remember, verify or ask

- **Memory Clarification Boundary** (2026; "Remember, Verify, or Ask? Evaluating Memory Decisions at Reuse Time"). [arXiv 2608.19564](https://arxiv.org/abs/2608.19564). Whether a system reuses a memory, checks it, or asks the user, at the moment of reuse.

## Citation scoring

- **L-CiteEval** (2024). [arXiv 2410.02115](https://arxiv.org/abs/2410.02115); [repository](https://github.com/ZetangForward/L-CITEEVAL). Whether answers over long contexts cite the passages that support them.
- **MemOps** (2026; Hao et al., "MemOps: Benchmarking Lifecycle Memory Operations in Long-Horizon Conversations"). [arXiv 2607.12893](https://arxiv.org/abs/2607.12893). Conversational memory as a sequence of lifecycle operations, with the source turns of each answer given as gold.

## Simulated household timelines and month-scale recordings

- **WorldLines** (2026; EMNLP 2026). [arXiv 2606.18847](https://arxiv.org/abs/2606.18847). Memory of a changing world state, and planning, from multi-day household traces.
- **HOMER** (2022; Patel and Chernova, "Proactive Robot Assistance via Spatio-Temporal Object Modeling"; CoRL 2022). [arXiv 2211.15501](https://arxiv.org/abs/2211.15501). A dataset of household object movements from simulated daily routines over many days.
- **FindingDory** (2025). [arXiv 2506.15635](https://arxiv.org/abs/2506.15635); [site](https://findingdory-benchmark.github.io). Memory for embodied agents' navigation and control over long episodes.
- **EgoMonth** (2026). [arXiv 2608.13113](https://arxiv.org/abs/2608.13113). Spatial and temporal memory questions over month-scale egocentric recordings of 20 people.

## Other benchmarks compared in the roadmap

- **Agent Memory Leaderboard (AML)** (2026). [agentmemoryleaderboard.ai](https://agentmemoryleaderboard.ai/); [repository](https://github.com/AML-memory/agent-memory-leaderboard). A public leaderboard of long-term memory systems with textual, coding and multimodal tracks; each system exposes Add and Search endpoints and a fixed pipeline answers the questions.
- **DolphinBench** (2026; Rathi et al., built by Mem0). [dolphinbench.ai](https://dolphinbench.ai/); [arXiv 2609.24971](https://arxiv.org/abs/2609.24971). Tool-using tasks that depend on a long earlier history, run on setups of memory system, model and harness, with cost and latency.

## Named in the design, source not located

None at the time of writing: every work named in DESIGN §2 and in the roadmap's comparison section has a source above.
