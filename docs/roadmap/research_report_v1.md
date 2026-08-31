# Research Report v1 — AI Responsibilities

Status: active roadmap contract  
Date: 2026-08-31  
Parent product contract: `knowledge-engine-core/docs/roadmap/research_report_v1.md`

## Goal

`knowledge-engine-ai` must produce a research result that is not merely grounded, but **clear, structured, decision-useful, and inspectably grounded**.

The product target is:

> Match or exceed the readability of a strong scholarly-assistant answer while materially exceeding it in provenance, evidence-boundary discipline, contradiction handling, and missing-evidence disclosure.

## Required structured report contract

Narrative prose alone is not sufficient. The AI layer should converge on a machine-readable `ResearchReport` projection with at least:

- `question`
- `bottom_line`
- `conclusion_rows[]`
  - `question_dimension`
  - `conclusion`
  - `certainty`
  - `certainty_rationale`
  - `supporting_evidence_ids[]`
  - `contradicting_or_null_evidence_ids[]`
  - `directness`
- `narrative_sections[]`
- `missing_evidence[]`
- `direct_evidence_summary`
- `indirect_evidence_summary`
- `provider_coverage`
- `degraded_providers`
- `indexed_before_run_evidence_ids[]`
- `acquired_during_run_evidence_ids[]`
- `limitations[]`
- `session_id`
- `research_state`

The exact schema may evolve, but these semantics are part of the product requirement.

## Synthesis rules

1. Answer the user's actual question first.
2. Separate scientifically distinct dimensions instead of averaging them into one claim.
3. Preserve direct vs indirect evidence classes.
4. Deliberately include null, contradictory, and qualifying evidence.
5. State when direct long-duration evidence was searched for but not found.
6. Never convert an inference into wording that implies a direct trial established it.
7. Every substantive factual claim must resolve to grounded evidence.
8. Certainty must be justified by evidence quality, directness, consistency, duration, and coverage; never invented because the UI expects a rating.
9. If confidence cannot be responsibly assigned, return `unavailable` or equivalent with the reason.
10. A polished answer cannot bypass citation, contradiction, coverage, grounding, or Research ISA close gates.

## Monster Energy acceptance case

Issue #79 (`monster-energy-bp-one-year`) is the first definitive Research Report v1 benchmark.

The AI report must produce separate conclusions for:

- acute post-consumption blood-pressure effect;
- persistent baseline/resting/ambulatory BP with habitual exposure;
- incident hypertension risk over longer follow-up;
- BP measurement artifact from recent caffeine intake;
- Zero Ultra vs Original Monster long-term context;
- direct approximately one-year evidence availability;
- certainty and missing evidence.

It must visibly distinguish:

- Monster-specific evidence;
- commercial energy-drink class evidence;
- caffeine/coffee/soda indirect evidence;
- positive vs null/contradictory findings.

## Benchmark acceptance criteria

The AI-layer benchmark fails if any of the following occurs:

- a factual claim lacks source linkage;
- an acute result is presented as proof of a chronic one-year effect;
- indirect caffeine/coffee/soda evidence is described as direct Monster causality;
- a null/counter-evidence seed is silently omitted;
- the system claims a one-year Monster trial exists without a direct validated source;
- direct-vs-indirect evidence is collapsed;
- certainty is presented without a traceable rationale;
- the report is technically complete but materially less useful/readable than the high-quality scholarly-assistant baseline used for the case.

## Roadmap priority

Until this benchmark passes end to end, prioritize:

1. structured Research Report contract;
2. claim/evidence linkage at report level;
3. dimension-specific conclusions and certainty rationales;
4. missing-evidence representation;
5. deliberate counter-evidence synthesis;
6. end-to-end Monster acceptance run;
7. cross-domain golden cases;
8. latency optimization that preserves all evidence gates.

New orchestration abstractions should not outrank these unless they unblock the report contract.

## Related work

- #69 — General Question Research Loop v1
- #79 — Monster Energy golden case
- #84 — question-to-report bottlenecks
- #90 — progressive report contract for Web
- #92 — time-to-sufficient-evidence policy
- `docs/golden_research_case_benchmark.md`
- `docs/roadmap/gqr2_general_query_plan.md`
