# G1 template screening set (#533)

This public set screens candidate template versions only. It is never a run of
record, a validation draw, a certification set, or evidence for a benchmark bar.
It contains 20 G1 lives, `screen-g1-1` through `screen-g1-20`, under T2's placement
rules ([RING0 §13, E34](../../../specs/ring0/RING0.md)).

The public seed rule is fixed before any candidate report: assign integers
2001 through 2020 in life order. If a seed fails placement, take the next unused
integer starting at 2021 and record the failed seed, replacement seed, rule and
item in `replacements` in [t2-screen.toml](t2-screen.toml). T2's other placement
and stopping rules apply. These seeds do not overlap public T2 or round 1's
validation seeds.

Placement uses template edition 1. [placement.json](placement.json) preserves
the round 1 table format, including checkpoint-5 hosts, per-branch/checkpoint
caps and early-bundle counts. All 20 design seeds passed on the first try; no replacements were needed.

The screening-set commitment is the commit first adding this directory,
not the base commit. Resolve its SHA after committing with
`git log --diff-filter=A --format=%H -- results/validity-2/screening/t2-screen.toml`.
Record that SHA before any candidate report. This change's offline edition-1
build/read check is a compatibility proof, not a candidate screening result.

The regression test builds the first two lives for speed; the lane's separate
offline proof builds all 20 and exercises sealed scripted controls, all simple
policies and the anchor report. No live model is involved.

| Life | Seed | Placement | Early bundles | Checkpoint-5 templates |
|---|---:|---|---:|---|
| screen-g1-1 | 2001 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-2 | 2002 | pass | 3 | drift-config, drift-quote |
| screen-g1-3 | 2003 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-4 | 2004 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-5 | 2005 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-6 | 2006 | pass | 4 | drift-config, drift-quote, recall-value |
| screen-g1-7 | 2007 | pass | 4 | drift-config, drift-quote, recall-value |
| screen-g1-8 | 2008 | pass | 3 | drift-config, drift-quote |
| screen-g1-9 | 2009 | pass | 4 | drift-config, drift-quote, recall-value |
| screen-g1-10 | 2010 | pass | 3 | drift-config, drift-quote |
| screen-g1-11 | 2011 | pass | 3 | drift-config, drift-quote |
| screen-g1-12 | 2012 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-13 | 2013 | pass | 3 | drift-config, drift-quote |
| screen-g1-14 | 2014 | pass | 3 | drift-config, drift-quote |
| screen-g1-15 | 2015 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-16 | 2016 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-17 | 2017 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-18 | 2018 | pass | 3 | drift-config, drift-quote, recall-value |
| screen-g1-19 | 2019 | pass | 3 | drift-config, drift-quote |
| screen-g1-20 | 2020 | pass | 4 | drift-config, drift-quote |
