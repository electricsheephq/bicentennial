# Round 2 candidate cards: the judge's bars (written 2026-11-13 ~23:10Z, before any design or report)

The judge scores each card against these bars only. A card passes a bar or fails it, with a one-line reason and a
citation (file:line) where the bar asks for one.

B1. **Plan form (PLAN.md §4).** The card names one Drift id, its lever(s) from §4's list, the mechanism, the exact
    prompt, three paraphrases, a predicted scripted pair score per anchor (naive retrieval, BM25, grep, recent window),
    and the predicted risk to the oracle row. Its code lives in new G1 template files and `world/targeted.py` (plus
    `items/editions.py`, `items/c7.py`, a C-7 spec and tests). It edits no file in a code pin (`controls/*` and its
    import closure, `world/processes/*`, `render/*`, `score/*`, existing `items/templates/g1/*` class files).

B2. **Round 1's repair is kept for its purpose.** A reader handed only the evidence can still tell where to write
    (file and entry), when to leave a value alone (the decision rule) and what to quote (the quote rule). If the card
    drops a repair element from the prompt (for example the entry name), it shows how a reader handed the evidence
    still determines it from the prompt plus the evidence alone, and it labels this a departure for the owner to rule
    on. A card that drops an element without that argument fails.

B3. **Token audit.** Every `\w+` token (naive retrieval's `words`: `\w+` over `str.lower()`) of the prompt and of each
    paraphrase is classed as: absent from every G1 event; present only outside the evidence events; or present in an
    evidence event. Each class cites its source (phrasebank line, sprint log format, tool reads, decision events). A
    token present in an evidence event comes with an argument, under grep's rule (rarest term first by event count,
    newest events first, stop before exceeding W = 16,384 tokens), for why grep's output cannot reach that evidence
    event; otherwise the grep prediction must say grep reaches it.

B4. **Falsifiable predictions.** Each anchor's prediction is a range on the pair scale (points out of 100) with its
    mechanism, consistent with the scripted reader's rule (the first option whose tokens are all present, else the first
    token-less option, else none) and with the twin structure (a pair scores its lower twin). The ranges must be narrow
    enough that the screen can contradict them.

B5. **Oracle safety.** An argument that a live reader handed only the gold evidence picks the right action on both
    twins (B0 and B1), including the hedge twin for drift-config, the quote rule for drift-quote and the last link for
    drift-chain-fault, and that the card adds no way for that reader to make a harmful extra change. The risk level
    (low, moderate, high) follows from the argument.

B6. **Validity.** The separation the card targets is a memory capability (recalling the decided fact about a named
    or implied subject over time), not an artifact:
    (a) the probe is not ambiguous for a real system in a way the oracle row never faces (for example other pending
        changes to other entries of the same file, which only the oracle's gold-only context hides);
    (b) no no-memory policy of `controls/battery.py` `POLICIES` scores above 0 on its pairs (argued from the options);
    (c) the recent-window prediction accounts for the sprint placement, including lives whose first long sprint falls
        in session 2 (how often, and what happens then).

B7. **Editions 1 and 2 unchanged.** The change keeps edition 1 and edition 2 worlds and packs byte-identical, or names
    the exact mechanism that scopes it to edition 3 (for example edition-aware placement), and notes the edition-3 C-7
    entry it needs.

B8. **Smallest change.** No new placement machinery unless the card shows that the existing placement fails the
    window prediction; prefers prompt-only changes where they suffice.

**Selection.** Recommend at most eight cards to publish, at most one finalist per Drift id later (the screen decides).
A card that fails B1, B2, B5 or B7 is not recommended without a stated fix. Cross-card conflicts and facts that must be
verified before the screen are listed separately.
