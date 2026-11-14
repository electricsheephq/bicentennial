# Transcript grep scripted anchor v1

This system-agnostic anchor sits outside the controls pin. Every report carries
its spec and code sha256 hashes, including its import closure. Any spec or code
change is a new anchor version. It is offline, scripted, API mode only.

Use only events with `t_sim <= now`. Terms are distinct prompt words from the
pinned naive retrieval's `words` (`\w+` over `str.lower()`), present as words
in at least one visible event. Sort terms by visible-event frequency ascending,
then alphabetically. For each term, visit matching events newest first by
`(t_sim, event_id)` descending, skipping events already visited. Stop at the
first event whose addition, including joining newlines, would exceed W = 16384
estimated tokens (`world.tokens.estimate_tokens`). Never truncate an event.
Output selected whole events in `(t_sim, event_id)` ascending order, joined by
newlines; cite their ids with confidence 1000. Empty selection returns UNKNOWN.

Recall requires all required tokens occurring in an evidence event together in
one retrieved whole event; empty token sets use separately counted id recall.
Reports say `recall_basis: "event_quote"`; k is the retrieved-event count.
The pinned runner and reader are unchanged; pair points are a scripted proxy.
