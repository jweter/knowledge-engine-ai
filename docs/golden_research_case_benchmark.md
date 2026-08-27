# Golden Research-Case Benchmark

## Purpose

`knowledge_engine_ai.research_case_benchmark` adds a second benchmark layer for
General Question Research Loop v1 (issue #69).

The existing `retrieval_benchmark.py` answers a different question: **did ranked
retrieval return already-reviewed Evidence Record IDs?** That contract must stay
anchored to Core's reviewed evidence maps.

A golden **research case** instead asks whether an arbitrary-question research
run behaved correctly when the relevant literature may not be indexed yet. It
scores only structured, inspectable run facts. It never asks an LLM to grade an
LLM answer and never upgrades a discovery candidate into evidence.

## First case: Monster Energy and one-year blood pressure (issue #79)

The first case is `monster-energy-bp-one-year`.

Benchmark exposure assumptions are copied from issue #79 so every implementation
is testing the same question:

- **Monster Zero Ultra / White Monster:** two 16-fl-oz cans/day, approximately
  300 mg caffeine/day, zero sugar.
- **Monster Original Green:** two 16-fl-oz cans/day, approximately 320 mg
  caffeine/day plus approximately 108 g sugar/day.

The case requires separate coverage of:

1. acute pressor effects during the hours after consumption;
2. persistent/chronic baseline BP over repeated use;
3. incident hypertension risk over longer follow-up;
4. BP-measurement artifact from caffeine before a reading;
5. Original-vs-Zero long-term risk context;
6. direct Monster evidence vs class-level/indirect evidence; and
7. certainty plus missing-evidence disclosure.

It also requires distinct search tracks for direct Monster/commercial energy-drink
trials, energy-drink randomized/meta-analytic evidence, repeated/chronic
energy-drink exposure, chronic caffeine evidence, sugar-sweetened beverage
cohorts, artificially sweetened beverage context, clinical BP measurement
guidance, and an explicit search for direct 6-12 month or approximately one-year
energy-drink longitudinal evidence.

## Seed identities are not conclusions

The PMID list from issue #79 is stored as `pmid:<number>` discovery-seed
identities. The benchmark asks whether the run explicitly reviewed those known
relevant leads. It does **not** assert that the paper supports a particular
conclusion and does not treat the PMID as an Evidence Record ID.

Two seeds are additionally marked as counter-evidence targets because issue #79
explicitly requires null/tolerance findings to be represented:

- `pmid:26931509`
- `pmid:26708636`

Any source may affect synthesis only after normal Core acquisition, grounding,
validation, Evidence Record promotion, and re-retrieval.

## Per-source extraction audit

Issue #79 requires source-level extraction, not citation presence alone. Each
required discovery seed therefore must have an auditable record of whether these
fields were captured:

- population;
- exposure;
- dose;
- duration;
- comparator;
- BP measurement method;
- effect size;
- confidence interval; and
- risk of bias or limitations.

`SourceFieldGap` records any missing required field for a reviewed source. A
benchmark run cannot pass by silently omitting a field. This contract still does
not decide what the extracted value should be; grounding and scientific truth
remain Core-owned evidence concerns.

## Deterministic acceptance guards

`evaluate_research_case()` fails visibly when a structured run snapshot shows
any of the following:

- one of the two exposure variants was not covered;
- acute/chronic/incident-hypertension/measurement dimensions were collapsed or
  omitted;
- direct-vs-class evidence or certainty/missing-evidence framing was omitted;
- a required search track was skipped;
- a required PMID seed or counter-evidence seed was not reviewed;
- a required seed was not audited for the required per-source extraction fields;
- a per-source extraction audit found required fields missing;
- PubMed was not attempted or fewer than two scholarly providers were attempted;
- an actually degraded provider was not reported, or a provider was reported as
  degraded when the structured run facts did not mark it degraded;
- an empty indexed corpus did not trigger bounded discovery;
- no direct long-term study was found and the answer failed to disclose that
  evidence gap;
- any factual claim lacks a source link; or
- a named inference guard was violated, including claiming a one-year Monster
  trial without a direct source or treating indirect caffeine/coffee/soda or
  artificial-sweetener evidence as direct Monster causality.

The benchmark therefore tests research discipline and evidence boundaries, not
whether a model produces a preferred scientific conclusion.

## Current limitation / next integration slice

This PR intentionally introduces the **case specification and deterministic
scorer**, not a fake end-to-end pass. The current synchronous GQR path still
lacks automatic grounded extraction/promotion and re-retrieval for newly
acquired sources (GQR-4/GQR-5). A later adapter should construct
`ResearchCaseRunSnapshot` from durable structured research-session artifacts
once those fields exist. It must not infer benchmark facts by scraping narrative
prose.
