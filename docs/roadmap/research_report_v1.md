# Research Report v1 — AI Responsibilities

## Owner-approved architecture (2026-10-25)

The standard Research Report runs computation locally while acquiring online sources on demand from a single user-facing request. A pre-ingested local document corpus and Ollama are not mandatory dependencies. Preserve structured report schema, progressive states, citation verification, contradictory evidence, uncertainty, and the Monster Energy benchmark. Use bounded temporary storage and cleanup; see `docs/OWNER_APPROVED_ROADMAP_2026-10-25.md`.


Status: active roadmap contract  
Date: 2026-08-31

Incremental implementation (2026-11-02): `copilot/online_evidence_adapter.py`
provides a content-checked typed boundary for Core's on-demand evidence bundle.
The opt-in `ke_client.online_research_evidence()` bridge invokes Core's
`online-research` and `online-evidence-validate` commands under one bounded
execution budget, checks byte-exact temporary source contents, preserves
unavailable-source rows and the discovery-run identity, and removes temporary
storage on success or failure. It requires neither an indexed corpus nor
Ollama. The bridge does not establish source authenticity, synthesize a
ResearchReport, retain a durable provider ledger, or satisfy the Monster
end-to-end gate. `copilot/online_report.py` deterministically projects that evidence into a
Research Report v1 (claim rows, cited excerpt IDs, certainty capped below HIGH,
unavailable sources as missing evidence, bounded claim count, no LLM). Next:
guarded Web one-request integration, provider-coverage
projection, and actual Research Report Product Reality.
Parent product contract: `knowledge-engine-core/docs/roadmap/research_report_v1.md`

Cross-repo compatibility check (2026-11-14): `tests/fixtures/online_evidence/`
vendors a byte-identical copy of `knowledge-engine-core`'s own committed
`ke-online-evidence/v1` golden fixture (`bundle.json` and `contents/`), copied
from Core commit `02da1f2666e643e6e6f2a42bc93f53ae57c1b977` (see the fixture
directory's `README.md`). `tests/test_online_evidence_core_fixture.py` loads
it from disk, with no network access and no pre-ingested corpus, and asserts
`parse_content_checked_online_evidence()` and `build_online_research_report()`
accept Core's real bundle unmodified — including its failed and unavailable
sources landing in `missing_evidence` — catching drift that hand-authored test
payloads cannot.

Orchestrator integration (2026-11-14): `copilot/run_research_question.py` now
also exposes `run_online_research_question()`, a thin, independent opt-in
wrapper beside `run_research_question()` that composes the same two calls
`ke-ai online-report` already makes (`ke_client.online_research_evidence()`
then `online_report.build_online_research_report()`) as a plain function other
orchestrators can call directly, instead of only reaching this path by
shelling out to the standalone CLI command. It returns an additive
`OnlineResearchQuestionResult` (`report`, `search_run_id`, stable
`error_code`) rather than raising, following the same convention
`research_report_integration.ResearchReportBuildResult` already uses. The
default local-corpus/GQR path in `run_research_question()` is untouched: this
wrapper is not called from it and has no effect unless a caller invokes it
explicitly. `tests/copilot/test_run_online_research_question.py` exercises a
successful bundle, a bundle with a failed/unavailable source, and two bridge-
failure shapes (a hard CLI failure and a rejected-at-validation failure)
against a stubbed Core CLI, asserting both the produced `ResearchReport` (or
stable error code) and that Core's temporary retrieved content and discovery
ledger are actually removed in every case.

Web-contract verification performed for this integration (2026-11-14):
read `knowledge-engine-web`'s actual current structured-report consumption at
commit `1927bca933fa1485b73aca53f06cd8154e0b811e` —
`knowledge_engine_web/ai_orchestration.py`'s `run_ai_orchestration()` /
`run_guarded_ai_orchestration()` and `knowledge_engine_web/research_jobs.py`'s
`_presentation_payload()`. Web's `/ask` research-job path is built entirely
around the local-corpus `ResearchQuestionResult` this new wrapper does not
return: `_presentation_payload()` reads `research.progress_report`,
`research.conversion_funnel_report`, `result.research_state`,
`result.narrative_releaseable`, `result.verification`, and
`result.close_result` directly off that object, and
`_build_research_report_projection()` builds its `ResearchReport` via
`research_report_integration.build_research_report_for_result()`, which itself
requires `narrative_releaseable`, `effective_evidence_report`, and
`progress_report` — an LLM-synthesized report over the local-corpus
evidence, not this deterministic online-evidence projection. The
`ResearchReport` *data contract* this wrapper returns is the identical typed
`research_report.ResearchReport` class Web already renders (same
`schema_version`, same `to_dict()`/`to_json()` shape), so there is no schema
drift to close. What is not yet wired is the call path: Web would need a new
branch — in `research_jobs._execute_research_job()`/`_presentation_payload()`
and `ai_orchestration.run_guarded_ai_orchestration()` — that, for an
online-evidence-mode request, calls `run_online_research_question()` directly
and persists a trimmed presentation payload (no `progress`, no
`conversion_funnel`, no `verification`, no `close_gate`, since this path
produces none of those) instead of today's single
`run_ai_orchestration()` → `_presentation_payload()` shape. That Web-side
routing change is out of scope for this AI-repository slice and belongs to a
`knowledge-engine-web` PR that opts into it explicitly.

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
