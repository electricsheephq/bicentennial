# Recent window scripted anchor v1

This system-agnostic anchor sits outside the controls pin. Every report carries
its spec and code sha256 hashes, including its import closure. Any spec or code
change is a new anchor version. It is offline, scripted, API mode only.

Use only events with `t_sim <= now`. Visit events newest first by
`(t_sim, event_id)` descending. Take whole events until the first addition
would exceed W = 16384 estimated tokens (`world.tokens.estimate_tokens`),
including all joining newlines. Stop there, without skipping or truncating.
Output selected events in `(t_sim, event_id)` ascending order, joined by
newlines; cite their ids with confidence 1000. Empty selection returns UNKNOWN.

Recall requires all required tokens occurring in an evidence event together in
one retrieved whole event; empty token sets use separately counted id recall.
Reports say `recall_basis: "event_quote"`; k is the retrieved-event count.
The report separately prints presence at 4096 and 65536 tokens as sensitivity
fields; these never change the default anchor or become CLI flags.
The pinned runner and reader are unchanged. Pair points are a scripted proxy,
not a bound on a live reader's score; pairs use the sealed bundle minimum.
