# Validity round 2: candidate cards

**Status, 14 November 2026:** published before any candidate report, as the plan requires ([PLAN.md](../PLAN.md) §4).
No candidate has been built or screened yet.

## Why these cards exist

Round 1 cleared the repaired versions (v2) of `drift-chain-fault`, `drift-config` and `drift-quote`: a reader handed the
evidence does them. But naive retrieval also scored 100 on them, so they cannot show that memory beats retrieval.
Round 2 looks for versions on which a reader handed the evidence still succeeds while every naive anchor fails. The
four naive anchors are naive retrieval, BM25, grep and a recent window. Each card proposes one v3 version of one Drift
template. Before any report, it states:
- the exact prompt and three paraphrases;
- each anchor's predicted pair score;
- the predicted risk to the oracle-evidence row.

## How the cards were made

1. **Bars first.** The bars in [BARS.md](BARS.md) were written before any card was drafted.
2. **Three designers, three angles.** Three independent designers drafted eleven cards. Each worked from one angle:
   - beat the anchors (retrieval-adversarial);
   - keep the evidence reader right (oracle-safety-first);
   - make sure the separation is a memory capability (mechanism-validity).

   Each designer was a fresh-context `claude-opus-5-5` agent at high effort, working read-only. Each was given:
   - the plan, the bars, the code and a digest of wording facts;
   - the anchor results already seen on the public lives for `drift-config-v1` and `wake-loop-v1`.

   The designers could call pure functions such as the schedule builder. They could not build lives or run any anchor
   or report. None saw an anchor report on the screening set.
3. **One blind judge.** A fresh-context `claude-opus-5-5` agent at high effort scored every card against every bar. It
   saw the cards and the code, not the designers' angles, and recommended at most eight. Its scores are in
   [JUDGE.md](JUDGE.md).
4. **The owner's selection.** The benchmark owner took the judge's seven recommended cards unchanged
   ([CARDS.md](CARDS.md)) and ruled on the points below. The other four cards are printed in
   [NOT-SCREENED.md](NOT-SCREENED.md), with the judge's reasons.

Card ids are the judge's: K-numbers per template, in designer order. Gaps in the numbering are the cards that are not
screened.

| Template | Screened | Not screened |
|---|---|---|
| `drift-config` | K1 (names "the retry entry"), K3 (names only the file), K4 (names only the file, with the scope spelled out) | K2 and K5 (move the correction earlier in the schedule) |
| `drift-quote` | K1 ("the missing timeout entry"), K3 (every firmly decided settings entry, none named) | K2 ("the one settings entry never committed") |
| `drift-chain-fault` | K1 ("the milestone after the beta"), K3 (every milestone, none named) | K2 ("our non-beta milestone") |

## The owner's rulings

1. **The entry name leaves the prompt. This is a departure, flagged.** The plan's rule for a candidate (§4) keeps
   round 1's repair: the entry name, the decision rule and the quote rule. Every screened card keeps the decision rule
   and the quote rule. But each one drops the exact entry or milestone name, or keeps only one word of it.
   - **Why the designers dropped it:** while the prompt carries the name, grep reaches the evidence. The name's rarest
     word occurs in every evidence event: `interval` for `drift-config`, `lock` and `setting` for `drift-quote`, and
     `general` for `drift-chain-fault`.
   - **Ruling:** accepted for the screen.
     - A reader handed the evidence can still recover the name: `drift-config`'s entry is in the file it is asked to
       edit, and the evidence events name the quote entry and the milestone.
     - The `drift-config` cards edit an entry that is already in the file. The other cards add a line, and their
       prompts say to copy the name exactly as written in the conversation.
     - The binding check is the live oracle smoke ([#535](https://github.com/electricsheephq/bicentennial/issues/535)):
       a finalist that a reader with the evidence still fails is dropped there.
     - Round 2's declaration will carry this departure, and the plan's table of departures lists it (PLAN §11).
2. **One build per card.** All cards of one template claim the same version and table ids, and some share a source
   file. Building them together would collide (the judge's conflicts 1 to 3). So:
   - each card is screened in its own build, as the only v3 of its template, with its class in its own source file;
   - the shared edits land once, with the finalists, after the screen: the edition-3 registry, its C-7 entry, the
     `--edition` choices and their tests.
3. **`drift-config` K4's token audit.** The judge passed K4 on condition that one token of paraphrase 1, `reflects`,
   is classed. It is absent: no G1 text source contains it, and none of the 1,558 visible G1 events on the public lives
   does. The fix is added to the card and marked.
4. **Not screened.**
   - **`drift-config` K2 and K5** move the correction earlier in the schedule, in edition 3 only. The judge would allow
     that only if the existing placement demonstrably fails, that is, if at least 8 of the 20 screening lives have
     their first long sprint in session 2. The committed screening roster has 7 (below). The judge also found that K2's
     account of the window used the wrong event order. Round 2's own risk from the same placement is ruling 10.
   - **`drift-quote` K2:** the judge's fix needs new wording, and K3 already tests the same lever with the exclusions
     spelled out.
   - **`drift-chain-fault` K2:** a reader handed the evidence cannot check "non-beta", so the oracle row is at risk.

5. **A sweep prompt scores one entry, by design.** `drift-quote` K3 asks for every firmly decided settings entry and
   `drift-chain-fault` K3 for every milestone, but each act table scores one entry: `lock timeout` and
   `general release`, the entry whose memory the item tests. The sweep is how the prompt avoids naming the entry; it is
   the cue, not the measure. Scoring the other entries would make one item's score depend on facts that other items
   fork, so a pair would no longer test one memory. Extra entries are neither rewarded nor penalized, and a missing
   unscored entry costs nothing. A pass shows that the scored entry is right, not that the sweep was complete, and
   round 2's results will say so for these cards.
6. **`drift-chain-fault` K1 is screened as a backup only.** Its prompt names the milestone by its relation, "after the
   beta", and the gold evidence never mentions the beta. The judge failed K2 ("our non-beta milestone") for a premise
   of the same kind. K1 passed with the risk rated moderate, but the difference is one of degree. So K1 can be the
   `drift-chain-fault` finalist only if K3 does not pass the screen; if it is, the live oracle smoke is its check.
7. **Ties between finalists of one template,** decided before any report. The plan orders finalists by the primary
   lever, then by the lowest best-anchor score (§4). Remaining ties go to the card with fewer prompt and paraphrase
   tokens that occur in the evidence, then to the card with the lower stated risk to the oracle row, then to the lower
   K-number.
8. **`drift-config` K3 gains "Never add entries."** It now ends the prompt and each paraphrase, marked in
   [CARDS.md](CARDS.md#drift-config-k3). As drafted, K3 asked for a check of the whole file without forbidding
   additions. A system that remembers `lock timeout`'s decision, which was never committed, could then add it, and on
   the hedged twin any change scores FAIL_TASK, 0. That penalty would fall on good memory, and neither the scripted
   screen nor the oracle smoke could see it, because the oracle is never handed `lock timeout`. K4 already carries the
   same sentence. The change comes before any screen; the screen's vocabulary counts check that no evidence token
   enters.
9. **Prompts at the same checkpoint never meet.** The judge's conflict 6 (and its sixth fact to verify) asked whether
   `drift-config` K4's "Never add entries" and `drift-quote` K3's "adding any entry this file lacks" could reach one
   system together at checkpoint 5. They cannot. Each act item is compiled into its own probe session
   (`director/compiler/hermes.py`), and each probe session runs on fresh copies of the workspace and of every memory
   surface, which are put back when it ends (`runner/life.py`). So neither prompt, nor anything a system does in
   answer, reaches the other probe.
10. **Round 2's risk on `drift-config` is accepted.** Every screened `drift-config` card keeps edition 1's placement.
    On the screening set the recent window will score about 35, at the gate. On round 2's ten fresh lives it scores
    about 10 points per life whose first long sprint is in session 2. The ranking rule needs the best anchor at or
    below 35, so four or more such lives would stop `drift-config` from ranking: a chance of about 22% (k ~ Bin(10, 1/4),
    P(k >= 4) = 0.224). The gate is not loosened if that happens (PLAN §10). K2 and K5 stay unscreened: their earlier
    correction changes edition 3's world for every card (the judge's conflict 4), which would make the other screens
    incomparable. The earlier placement is the first `drift-config` item for the next round.
11. **The card cap counts screened cards.** The plan allows at most eight cards (§4); its purpose is to limit how many
    candidates are tried against the screening set. Eleven were drafted and seven are screened. The four others are
    printed, never built or read, so they cannot affect the screen. PLAN §11 records this reading.

## Anchor identities

Every card's predictions were made against these anchors at `5064cf6`, as the plan requires (PLAN §3: every report and
card records each anchor's spec and code hashes, the code hash covering the anchor's import closure). No file in those
closures, and no anchor spec, has changed on `main` since. Each screen report's header records the same fields, so a
report made with a different anchor shows a different hash.

| Anchor | Spec | Spec SHA-256 | Code SHA-256 (import closure) |
|---|---|---|---|
| BM25 | `specs/controls/bm25.md` | `62de7820d62bbda5df3f5c50f2aa8c1dbdca59f6f756fa5ca180874bbae63574` | `5dff62d794c247167ad404236a74679578596c774c84fff53727aa576fe5562c` |
| Grep | `specs/controls/grep.md` | `273740596c007cf226ad649412983e5f9994247e6941d99330a14f82fe088621` | `9c10ef8f09c7ab4d2cc1bd16e3df008159c4696aeb4a74acdde15a786c52a418` |
| Recent window | `specs/controls/recent_window.md` | `e2fb3d12076536a65b4a586c46985ee273638fb7acf51740caee236e867acbfc` | `ff2a157c591050b8f521ce1f2d32cd98027bb75f1f7c9698e35c76492188747c` |
| Naive retrieval (a pinned control) | `specs/controls/naive_rag.md` | `f25e32ec9ee7b97dffdc733b6c6a04dd251807bbdeadcf23651b305c84041759` | `b97757225775942d92506723514038e5b014f2717df5714951d8e985b62df09b` |

## What the owner saw before choosing

**Disclosure.** Before reading the cards, the owner read edition 1's anchor report on the 20-life screening set, built
while the screening set was committed (#533). The designers and the judge did not see it. It covers the v1 templates
and counts pairs out of 20 (right / confidently wrong / no credit):

| v1 template | Naive retrieval | BM25 | Grep | Recent window |
|---|---|---|---|---|
| `drift-config-v1` | 4 / 0 / 16 | 14 / 0 / 6 | 20 / 0 / 0 | 7 / 0 / 13 |
| `drift-quote-v1` | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 | 0 / 7 / 13 |
| `drift-chain-fault-v1` | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 | 0 / 0 / 20 |
| `wake-loop-v1` | 0 / 0 / 20 | 0 / 0 / 20 | 0 / 0 / 20 | 0 / 0 / 20 |

What it implies for these cards:
- The recent window ignores the prompt, and every screened card keeps edition 1's placement.
- So the owner expects the window to score on the screening set about as it did there:
  - about +35 on `drift-config`, from the seven lives whose first long sprint is in session 2;
  - about −35 on `drift-quote`;
  - 0 on `drift-chain-fault`.
- For `drift-config`, +35 sits exactly at the finalist gate (best anchor at most 35).

The cards' window predictions were written without this, and they are printed unchanged. On the screening set, read
them as already known. They remain predictions on round 2's fresh lives.

## Facts checked before publication

- **First long sprint of each screening life**, read from the committed schedules before any candidate report:
  - session 2 on 7 lives;
  - session 3 on 5;
  - session 4 on 4;
  - session 5 on 4.

  On the five public G1 lives, it never falls in session 2.
- **Largest single event:** 667 estimated tokens on the public lives and 666 on the screening set, against the
  anchors' window of 16,384.
- **`reflects`:** absent from every G1 text source and every public G1 event, as above.

## What happens next

1. **Screen** ([#534](https://github.com/electricsheephq/bicentennial/issues/534)): each card gets a screening build
   that is never registered as an edition.
   - Up to three iterations per card on the public lives, then one read on the screening set.
   - Each read runs the four anchors, the scripted oracle and the no-memory battery.
   - The judge's list of facts to verify first ([JUDGE.md](JUDGE.md)) is part of that work.
   - Every iteration and report is published with round 2, finalist or not.
2. **Finalists**, at most one per template (PLAN §4). Each must meet all of these:
   - the scripted oracle scores 100;
   - the best anchor scores at most 35;
   - the same holds under each paraphrase;
   - every no-memory battery policy scores at most 0.
3. **The live oracle smoke** ([#535](https://github.com/electricsheephq/bicentennial/issues/535)), then **round 2**
   ([#536](https://github.com/electricsheephq/bicentennial/issues/536)).

**Claim class:** design documents, published before any report. They predict; they show nothing yet.

**Process note:** one designer wrote a small helper script outside the repository (a static token counter), against
its read-only instruction. It changed no repository file.
