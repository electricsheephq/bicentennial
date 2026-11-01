# Bicentennial v0.1 Kit: acceptance result

Claim class: unit outputs of the v0.1 kit; not predictive of the full tier.
Ring 0 developer signal; not predictive of the full tier; never certifies.

- Tool version: 0.1.0.dev0
- Code commit: 366903e84ffe61d56e6fae573075a2b8534d72e9
- T0 pack hash (86 packs): 737625ebdbee50df990a7b7929fd57eca8a90cdd148c9c0c46aeaacf0d7c5b9d
- T1 pack hash: b2e233207ac54115a77d9c0280e3cdb0c809df31e27430a59b401beae1aa4c41
- Accepted: yes
- Spend: 0 micro-USD

## Results

| System | Tier | Run | Exit | Unit | Gate | Run status | Card sha256 |
|---|---|---|---|---|---|---|---|
| hermes-native | T0 | run1 | 1 | 86 packs | FAIL 86 | COMPLETE | fb4a742b6ca5f5ccef52f0f997e484bc2f27d467b245f4b9d2892efc65eb30b6 |
| hermes-native | T0 | run2 | 1 | 86 packs | FAIL 86 | COMPLETE | fb4a742b6ca5f5ccef52f0f997e484bc2f27d467b245f4b9d2892efc65eb30b6 |
| hermes-native | T1 | base | 0 | system | CONFORMANCE_PASS | COMPLETE | a23984d7ab148d2ab95bf4bce40cb4d055ccf079d4467ea1a86b2ddb951411d7 |
| hermes-native | T1 | base | 0 | wiped | FAIL | COMPLETE | 5c622ef81bacb381d4d301e30e4d3e08b21f00302e44c72fc085c9e968eea640 |
| hermes-native | T1 | run1 | 0 | system | PASS | COMPLETE | 9877ca6bab0a5c2a91ae84eaa6fe486c5bc8cfd13b2dacf9e4d38ebe20dec058 |
| hermes-native | T1 | run1 | 0 | wiped | FAIL | COMPLETE | 5c622ef81bacb381d4d301e30e4d3e08b21f00302e44c72fc085c9e968eea640 |
| hermes-native | T1 | run2 | 0 | system | PASS | COMPLETE | 9877ca6bab0a5c2a91ae84eaa6fe486c5bc8cfd13b2dacf9e4d38ebe20dec058 |
| hermes-native | T1 | run2 | 0 | wiped | FAIL | COMPLETE | 5c622ef81bacb381d4d301e30e4d3e08b21f00302e44c72fc085c9e968eea640 |
| holographic | T0 | run1 | 0 | 86 packs | PASS 86 | COMPLETE | 5e421ceae2f822d13903bc268821377724a12bb7c4426e7875e804cf5294a695 |
| holographic | T0 | run2 | 0 | 86 packs | PASS 86 | COMPLETE | 5e421ceae2f822d13903bc268821377724a12bb7c4426e7875e804cf5294a695 |
| holographic | T1 | base | 0 | system | CONFORMANCE_PASS | COMPLETE | 755e5f5ef19c63daa7ad99e0c54ae5505ab98a10dbf076c61f51a925eb6251fe |
| holographic | T1 | base | 0 | wiped | FAIL | COMPLETE | c2257258e36b7d3aa55b0cc08732df51a50e0871092ff447401ce2a24314afbd |
| holographic | T1 | run1 | 0 | system | PASS | COMPLETE | 79d0d55d4ccbc0c39cc7f81ad9d0fa87627800a4945e55c61fdee6780d219691 |
| holographic | T1 | run1 | 0 | wiped | FAIL | COMPLETE | c2257258e36b7d3aa55b0cc08732df51a50e0871092ff447401ce2a24314afbd |
| holographic | T1 | run2 | 0 | system | PASS | COMPLETE | 79d0d55d4ccbc0c39cc7f81ad9d0fa87627800a4945e55c61fdee6780d219691 |
| holographic | T1 | run2 | 0 | wiped | FAIL | COMPLETE | c2257258e36b7d3aa55b0cc08732df51a50e0871092ff447401ce2a24314afbd |
| mem0-oss | T0 | run1 | 1 | 86 packs | FAIL 86 | COMPLETE | b454e75ef2806edef2983a96dea7ef1cd06deaadf07f2a13714aa5d5a2836012 |
| mem0-oss | T0 | run2 | 1 | 86 packs | FAIL 86 | COMPLETE | b454e75ef2806edef2983a96dea7ef1cd06deaadf07f2a13714aa5d5a2836012 |
| mem0-oss | T1 | base | 0 | system | CONFORMANCE_PASS | COMPLETE | e334159cd211235d08be0424781e9e1146e066052ac556ef7cc532949713ec35 |
| mem0-oss | T1 | base | 0 | wiped | FAIL | COMPLETE | ab624819f1df451cefc463221da996b8cdf0c7accc36a4438c840f42c76a9adf |
| mem0-oss | T1 | run1 | 0 | system | PASS | COMPLETE | 94174317e76b135c5115cc80f81ead18a1f3e51d8c4987482943dff09752a460 |
| mem0-oss | T1 | run1 | 0 | wiped | FAIL | COMPLETE | ab624819f1df451cefc463221da996b8cdf0c7accc36a4438c840f42c76a9adf |
| mem0-oss | T1 | run2 | 0 | system | PASS | COMPLETE | 94174317e76b135c5115cc80f81ead18a1f3e51d8c4987482943dff09752a460 |
| mem0-oss | T1 | run2 | 0 | wiped | FAIL | COMPLETE | ab624819f1df451cefc463221da996b8cdf0c7accc36a4438c840f42c76a9adf |
| reference_store | T0 | run1 | 0 | 86 packs | PASS 86 | COMPLETE | d5fbef9850efff4479fc3818b6704f2c87b805e4573de3d10d7ef9f4044f498c |
| reference_store | T0 | run2 | 0 | 86 packs | PASS 86 | COMPLETE | d5fbef9850efff4479fc3818b6704f2c87b805e4573de3d10d7ef9f4044f498c |

## Loop time

| Tier | Unit | Target ms | Idle max ms | Busy max ms | Idle n | Busy n |
|---|---|---|---|---|---|---|
| T0 | pack | 60000 | 97185 | not measured | 688 | 0 |
| T1 | run | 600000 | 5319842 | 8906970 | 8 | 1 |

T0's first pack includes the adapter-invariant time.

## Target misses

- hermes-native T1 base system: 3842809 ms against 600000 ms (idle)
- hermes-native T1 run1 system: 3868521 ms against 600000 ms (idle)
- hermes-native T1 run2 system: 8906970 ms against 600000 ms (busy)
- holographic T1 base system: 3913536 ms against 600000 ms (idle)
- holographic T1 run1 system: 3911498 ms against 600000 ms (idle)
- holographic T1 run2 system: 3918356 ms against 600000 ms (idle)
- mem0-oss T0 run1 pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1: 96958 ms against 60000 ms (idle)
- mem0-oss T0 run1 pack/G1/Drift/drift-quote@1/s3-d1-kill/1: 80346 ms against 60000 ms (idle)
- mem0-oss T0 run1 pack/G1/Recall/recall-value@1/s3-d1-kill/1: 79516 ms against 60000 ms (idle)
- mem0-oss T0 run1 pack/G2/Drift/drift-asof@1/s3-d1-kill/1: 79514 ms against 60000 ms (idle)
- mem0-oss T0 run1 pack/G2/Keep/keep-incidental@1/s3-d1-kill/1: 80228 ms against 60000 ms (idle)
- mem0-oss T0 run2 pack/G1/Drift/drift-chain-fault@1/s3-d1-kill/1: 97185 ms against 60000 ms (idle)
- mem0-oss T0 run2 pack/G1/Drift/drift-quote@1/s3-d1-kill/1: 79745 ms against 60000 ms (idle)
- mem0-oss T0 run2 pack/G1/Recall/recall-value@1/s3-d1-kill/1: 79249 ms against 60000 ms (idle)
- mem0-oss T0 run2 pack/G2/Drift/drift-asof@1/s3-d1-kill/1: 79901 ms against 60000 ms (idle)
- mem0-oss T0 run2 pack/G2/Keep/keep-incidental@1/s3-d1-kill/1: 79151 ms against 60000 ms (idle)
- mem0-oss T1 base system: 5312984 ms against 600000 ms (idle)
- mem0-oss T1 run1 system: 5319842 ms against 600000 ms (idle)
- mem0-oss T1 run2 system: 5307942 ms against 600000 ms (idle)

## Disclosures

### hermes-native

- t0.baseline: no fault-free twin at v0.1
- t0.crash: API-mode crash equals restart
- t0.entrypoint: in-process memory host: MemoryManager or memory tool + SessionDB (T0)
- t0.event_mapping: every event becomes one user-side turn with an empty assistant side
- t0.injection: The session-start memory snapshot is read; other harness prompt injection is not exercised.
- t0.pair: API-mode INV-PAIR certifies call and result survival; linkage requires Hermes mode
- t0.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["h11","0.16.0"],["hermes-agent","0.0.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["nemo-relay","0.10.0"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["prompt-toolkit","3.0.52"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t0.worker_dists_sha256: sha256:78dec4ab203d2546a025694218754cfe9a967c0aaa3a6da302c71683c7088d50 n=80
- t1.a4_gaps: expected: the wiped arm restores the fresh install at every wake
- t1.assistant_turns: scripted assistant turns: fixed placeholder
- t1.baselines: naive RAG not run in v0.1; the baseline set is incomplete
- t1.corpus: corpus: memory-layer mode
- t1.corpus_crash: API-mode crash equals restart
- t1.estimator: {"name":"utf8-bytes-div4","sha256":null}
- t1.fresh_install: fresh-install hash compared within the run
- t1.isolation: probe isolation is per checkpoint, not per item
- t1.key_matching: G2 action predicates key on the planned key and first_execution_t takes the first call of any step tool; safe at T0/T1 scripted replay only
- t1.not_exercised: ["KEEP-FORGET","KEEP-NEIGH","TUE-EVENT"]
- t1.receipt: receipt tokens_by_role, store_growth_bytes and process_ids are not measured at T1 v0.1
- t1.reclassified: []
- t1.terminal: T1 toolset includes terminal; scripted turns run only compiled workspace commands; a live model could reach the Hermes home
- t1.tool_search: scripted-tier Hermes config: tool search off, so every offered tool is eager and scripted turns call write, recall and environment tools directly; a single API attempt and no auto-recovery waits, since the simulated clock is frozen inside a turn; live tiers keep the pin's defaults
- t1.transforms: []
- t1.tuesday: Tuesday timing is not exercised at T1
- t1.unsettled: unsettled checkpoints still run their probes; every item of such a checkpoint is SYSTEM_FAILURE (unsettled)
- t1.verdicts: INVALID: the wiped control passed or a honeypot was read (exit 1); BLOCKED: infrastructure failed after its reruns with no known failure (exit 2); a known failure wins
- t1.verified_empty: verified empty: before configuration; configuration is benchmark-written
- t1.window: context_length 65536; compression.threshold_tokens 16384 = W
- t1.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["h11","0.16.0"],["hermes-agent","0.0.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["nemo-relay","0.10.0"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["prompt-toolkit","3.0.52"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t1.worker_dists_sha256: sha256:78dec4ab203d2546a025694218754cfe9a967c0aaa3a6da302c71683c7088d50 n=80

### holographic

- t0.baseline: no fault-free twin at v0.1
- t0.crash: API-mode crash equals restart
- t0.entrypoint: in-process memory host: MemoryManager or memory tool + SessionDB (T0)
- t0.event_mapping: every event becomes one user-side turn with an empty assistant side
- t0.pair: API-mode INV-PAIR certifies call and result survival; linkage requires Hermes mode
- t0.plugin_deps: sha256:a0b010079a92f0e70690a0aad8730305308850bc91640769f38331c367c284ac n=2
- t0.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["h11","0.16.0"],["hermes-agent","0.0.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["nemo-relay","0.10.0"],["numpy","2.4.3"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["prompt-toolkit","3.0.52"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t0.worker_dists_sha256: sha256:0eab1b88047e73836da4321102af109762d90695c2b1a2584003d252f56cd0d1 n=81
- t1.a4: A4 not audited for plug-in providers at v0.1
- t1.assistant_turns: scripted assistant turns: fixed placeholder
- t1.baselines: naive RAG not run in v0.1; the baseline set is incomplete
- t1.corpus: corpus: memory-layer mode
- t1.corpus_crash: API-mode crash equals restart
- t1.estimator: {"name":"utf8-bytes-div4","sha256":null}
- t1.fresh_install: fresh-install hash compared within the run
- t1.fresh_install_mask: fresh-install hash: director port masked in config.yaml and mem0.json
- t1.isolation: probe isolation is per checkpoint, not per item
- t1.key_matching: G2 action predicates key on the planned key and first_execution_t takes the first call of any step tool; safe at T0/T1 scripted replay only
- t1.not_exercised: ["KEEP-FORGET","KEEP-NEIGH","TUE-EVENT"]
- t1.plugin_deps: sha256:a0b010079a92f0e70690a0aad8730305308850bc91640769f38331c367c284ac n=2
- t1.plugin_snapshot: a plug-in's verified-empty listing is its install snapshot, taken after the plug-in's own install-time files are written
- t1.receipt: receipt tokens_by_role, store_growth_bytes and process_ids are not measured at T1 v0.1
- t1.reclassified: []
- t1.reclassify: plug-in end_timeout, final_mismatch, resume_failed and turn_timeout stops are INFRA_FAILURE when the no-memory floor stops identically; probe sessions only
- t1.terminal: T1 toolset includes terminal; scripted turns run only compiled workspace commands; a live model could reach the Hermes home
- t1.tool_search: scripted-tier Hermes config: tool search off, so every offered tool is eager and scripted turns call write, recall and environment tools directly; a single API attempt and no auto-recovery waits, since the simulated clock is frozen inside a turn; live tiers keep the pin's defaults
- t1.transforms: []
- t1.tuesday: Tuesday timing is not exercised at T1
- t1.unsettled: unsettled checkpoints still run their probes; every item of such a checkpoint is SYSTEM_FAILURE (unsettled)
- t1.verdicts: INVALID: the wiped control passed or a honeypot was read (exit 1); BLOCKED: infrastructure failed after its reruns with no known failure (exit 2); a known failure wins
- t1.verified_empty: verified empty: before configuration; configuration is benchmark-written
- t1.window: context_length 65536; compression.threshold_tokens 16384 = W
- t1.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["h11","0.16.0"],["hermes-agent","0.0.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["nemo-relay","0.10.0"],["numpy","2.4.3"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["prompt-toolkit","3.0.52"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t1.worker_dists_sha256: sha256:0eab1b88047e73836da4321102af109762d90695c2b1a2584003d252f56cd0d1 n=81

### kit

- kit.busy.T0: T0 loop time not measured busy
- kit.determinism: determinism is claimed per machine and pin set only (RING0 §4)
- kit.t0_mode: T0 ran in memory-layer mode on every system; the T0 Hermes-replay fallback ships in v0.2 (RING0 §13 E5)
- kit.targets: loop-time targets are engineering budgets, not bars (PREREG §8 bar 5); every miss is listed under Target misses

### mem0-oss

- t0.baseline: no fault-free twin at v0.1
- t0.crash: API-mode crash equals restart
- t0.embeddings: Hashed-vector stub (RING0 E10): cosine reported as (1 + c)/2 over D-1 hashed token coordinates; similarity order preserved; hybrid weights and absolute thresholds not validated.
- t0.entrypoint: in-process memory host: MemoryManager or memory tool + SessionDB (T0)
- t0.event_mapping: every event becomes one user-side turn with an empty assistant side
- t0.extraction: Automatic extraction not exercised (RING0 E11, #208): the stub's reply format is not the one the pinned release reads; results cover explicit-write storage and recall.
- t0.pair: API-mode INV-PAIR certifies call and result survival; linkage requires Hermes mode
- t0.plugin_deps: sha256:a8663970dfd0332fee38b503ed17d0f49c9a414bd187b8a27083495052e83a14 n=32
- t0.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["backoff","2.2.1"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["grpcio","1.84.1"],["h11","0.16.0"],["h2","4.4.1"],["hermes-agent","0.0.0"],["hpack","4.2.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["hyperframe","6.1.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["mem0ai","2.2.1"],["nemo-relay","0.10.0"],["numpy","2.5.4"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["portalocker","4.4.1"],["posthog","7.75.11"],["prompt-toolkit","3.0.52"],["protobuf","6.33.6"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["qdrant-client","1.20.0"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sqlalchemy","2.1.6"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t0.worker_dists_sha256: sha256:081413f7fa82366450837fc857652601f3e48950886c532abecf4eebcda7e306 n=92
- t1.a4: A4 not audited for plug-in providers at v0.1
- t1.assistant_turns: scripted assistant turns: fixed placeholder
- t1.baselines: naive RAG not run in v0.1; the baseline set is incomplete
- t1.corpus: corpus: memory-layer mode
- t1.corpus_crash: API-mode crash equals restart
- t1.embeddings: Hashed-vector stub (RING0 E10): cosine reported as (1 + c)/2 over D-1 hashed token coordinates; similarity order preserved; hybrid weights and absolute thresholds not validated.
- t1.estimator: {"name":"utf8-bytes-div4","sha256":null}
- t1.extraction: Automatic extraction not exercised (RING0 E11, #208): the stub's reply format is not the one the pinned release reads; results cover explicit-write storage and recall.
- t1.fresh_install: fresh-install hash compared within the run
- t1.fresh_install_mask: fresh-install hash: director port masked in config.yaml and mem0.json
- t1.isolation: probe isolation is per checkpoint, not per item
- t1.key_matching: G2 action predicates key on the planned key and first_execution_t takes the first call of any step tool; safe at T0/T1 scripted replay only
- t1.not_exercised: ["KEEP-FORGET","KEEP-NEIGH","TUE-EVENT"]
- t1.plugin_deps: sha256:a8663970dfd0332fee38b503ed17d0f49c9a414bd187b8a27083495052e83a14 n=32
- t1.plugin_snapshot: a plug-in's verified-empty listing is its install snapshot, taken after the plug-in's own install-time files are written
- t1.receipt: receipt tokens_by_role, store_growth_bytes and process_ids are not measured at T1 v0.1
- t1.reclassified: []
- t1.reclassify: plug-in end_timeout, final_mismatch, resume_failed and turn_timeout stops are INFRA_FAILURE when the no-memory floor stops identically; probe sessions only
- t1.terminal: T1 toolset includes terminal; scripted turns run only compiled workspace commands; a live model could reach the Hermes home
- t1.tool_search: scripted-tier Hermes config: tool search off, so every offered tool is eager and scripted turns call write, recall and environment tools directly; a single API attempt and no auto-recovery waits, since the simulated clock is frozen inside a turn; live tiers keep the pin's defaults
- t1.transforms: []
- t1.tuesday: Tuesday timing is not exercised at T1
- t1.unsettled: unsettled checkpoints still run their probes; every item of such a checkpoint is SYSTEM_FAILURE (unsettled)
- t1.verdicts: INVALID: the wiped control passed or a honeypot was read (exit 1); BLOCKED: infrastructure failed after its reruns with no known failure (exit 2); a known failure wins
- t1.verified_empty: verified empty: before configuration; configuration is benchmark-written
- t1.window: context_length 65536; compression.threshold_tokens 16384 = W
- t1.worker_dists: [["annotated-doc","0.0.5"],["annotated-types","0.8.0"],["anyio","4.14.2"],["attrs","26.1.0"],["backoff","2.2.1"],["browser-harness","0.1.13"],["cdp-use","1.4.5"],["certifi","2026.5.20"],["cffi","2.1.1"],["charset-normalizer","3.5.1"],["click","8.4.2"],["croniter","6.0.0"],["cryptography","50.0.1"],["distro","1.9.0"],["fastapi","0.133.1"],["fetch-use","0.4.0"],["fire","0.7.1"],["firecrawl-anydoc","0.2.4"],["grpcio","1.84.1"],["h11","0.16.0"],["h2","4.4.1"],["hermes-agent","0.0.0"],["hpack","4.2.0"],["httpcore","1.0.9"],["httpcore2","2.12.0"],["httptools","0.8.0"],["httpx","0.28.1"],["httpx2","2.12.0"],["hyperframe","6.1.0"],["idna","3.19"],["importlib-metadata","8.7.1"],["jinja2","3.1.6"],["jiter","0.16.0"],["jsonschema","4.26.0"],["jsonschema-specifications","2025.9.1"],["markdown","3.10.2"],["markdown-it-py","4.2.0"],["markupsafe","3.0.3"],["mcp","2.0.0"],["mcp-types","2.0.0"],["mdurl","0.1.2"],["mem0ai","2.2.1"],["nemo-relay","0.10.0"],["numpy","2.5.4"],["openai","2.24.0"],["opentelemetry-api","1.39.1"],["packaging","26.0"],["pathspec","1.1.1"],["pillow","12.3.0"],["pillow-heif","1.6.0"],["portalocker","4.4.1"],["posthog","7.75.11"],["prompt-toolkit","3.0.52"],["protobuf","6.33.6"],["psutil","7.2.2"],["ptyprocess","0.7.0"],["pycparser","3.0"],["pydantic","2.13.4"],["pydantic-core","2.46.4"],["pygments","2.21.0"],["pyjwt","2.13.0"],["python-dateutil","2.9.0.post0"],["python-dotenv","1.2.2"],["python-multipart","0.0.32"],["pytz","2026.3.post1"],["qdrant-client","1.20.0"],["referencing","0.37.0"],["requests","2.33.0"],["resvg-py","0.4.0"],["rich","14.3.3"],["rpds-py","2026.6.3"],["ruamel-yaml","0.18.16"],["six","1.17.0"],["sniffio","1.3.1"],["snowballstemmer","3.1.1"],["socksio","1.0.0"],["sqlalchemy","2.1.6"],["sse-starlette","3.4.8"],["starlette","1.3.1"],["tenacity","9.1.4"],["termcolor","3.3.0"],["tomli-w","1.2.0"],["tqdm","4.70.0"],["truststore","0.10.4"],["typing-extensions","4.16.0"],["typing-inspection","0.4.4"],["urllib3","2.7.0"],["uvicorn","0.41.0"],["watchfiles","1.2.0"],["wcwidth","0.8.2"],["websockets","15.0.1"],["zipp","4.1.0"]]
- t1.worker_dists_sha256: sha256:081413f7fa82366450837fc857652601f3e48950886c532abecf4eebcda7e306 n=92

### reference_store

- t0.baseline: no fault-free twin at v0.1
- t0.crash: API-mode crash equals restart
- t0.entrypoint: reference adapter
- t0.event_mapping: every event becomes one user-side turn with an empty assistant side
- t0.pair: API-mode INV-PAIR certifies call and result survival; linkage requires Hermes mode

## Acceptance checks

| Check | Holds | Failures |
|---|---|---|
| runs_complete | yes |  |
| exit_codes | yes |  |
| schema | yes |  |
| t0_packs | yes |  |
| run_status | yes |  |
| t0_identical | yes |  |
| t1_gate | yes |  |
| t1_baseline | yes |  |
| t1_identical | yes |  |
| wiped_fails | yes |  |
| isolation | yes |  |
| controls | yes |  |
| honeypot | yes |  |
| spend | yes |  |
| pins | yes |  |
| disclosures | yes |  |
| loop_time_measured | yes |  |

## What this does not prove

These are unit outputs of the v0.1 kit, run on one machine with one pin set. They are not predictive of the full tier and never certify a system. Determinism is claimed per machine and pin set only. Act results at T0 and T1 are evidence-conditioned scripted actions, not an Act judgement. Loop-time targets are engineering budgets, not bars.
