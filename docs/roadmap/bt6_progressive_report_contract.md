# BT-6 — progressive research report contract for Web

Status: implemented (AI-side contract; Web consumption tracked separately)
Parent: #84
Issue: #90
Refs: #69, jweter/knowledge-engine-web#93

## Purpose

Issue #90's goal: give Web a stable, structured signal for "useful research
in progress" instead of a dead end at the first local corpus miss. Web's own
companion issue (`knowledge-engine-web#93`, "Progressive research UX: never
terminate on the initial corpus miss") names 8 UI states it needs to render:
`searching_indexed_evidence`, `research_required`, `discovering_sources`,
`acquiring_sources`, `validating_extracting_evidence`, `reretrieving`,
`partial_answer`, and `final_answer`/`insufficient_evidence`.

`knowledge_engine_ai.copilot.progress_report` is that AI-side contract. It
does not invent a second research-outcome model: it is a pure read-side
projection over facts `research_state.derive_research_state` and
`bottleneck_report.build_session_bottleneck_report` already compute from
`run_research_question`'s result -- the same "observability only, never a
second source of truth" posture those two modules already established.

## Product invariant

`insufficient_evidence` is a final research outcome, never a synonym for
"the initial indexed retrieval returned zero records." This was already
correctly encoded in `research_state.py`'s v2 schema
(`docs/roadmap/gqr_research_state_v2.md`): a session that triggered bounded
research but has not yet run grounded completion stays `research_required`;
only a session whose bounded research path actually completed (a
`GroundedCompletionResult` exists) can resolve to `insufficient_evidence`.
`ResearchProgressReport.final` makes that gate directly checkable without
re-deriving `ResearchState` branch logic, and
`tests/copilot/test_progress_report.py` asserts it explicitly: zero indexed
evidence with discovery triggered but no grounded-completion attempt yields
`research_required` / `final=False`, while the same zero-evidence session
*after* a completed bounded pass yields `insufficient_evidence` / `final=True`.

## What `ResearchProgressReport` carries

- `progress_stage` (`ResearchProgressStage`): Web's 8 named states, expressed
  in AI-repo terms.
- `research_state` / `research_state_reason`: the existing GQR
  `ResearchState` value this report is derived from, for callers that need
  the finer-grained diagnostic distinction Web's 8-state vocabulary
  collapses (e.g. `blocked` and `insufficient_evidence` both render as
  Web's `insufficient_evidence`).
- `current_stage` (`bottleneck_report.ResearchPipelineStage`) and
  `elapsed_ms`: which fixed pipeline stage this outcome is anchored to, and
  the same overlap-adjusted total duration `bottleneck_report.py` already
  computes (so the known parallel-retrieval double-count is not
  reintroduced here).
- `answer_available` / `wait_reason`: whether a releaseable narrative
  exists yet, and -- only for a non-final `research_required` result --
  what a follow-up call would need to opt into next.
- `indexed_evidence_record_ids` / `newly_acquired_evidence_record_ids`:
  kept separate, per issue #90's explicit requirement, rather than one
  combined evidence-count field.
- `provider_coverage_attempted` / `provider_coverage_completeness` /
  `provider_degraded` / `provider_statuses`: federated-discovery provider
  coverage, reusing the same `completeness`/`provider_statuses` facts
  Core already records -- provider *count* is still never read as a
  quality signal anywhere in this project.
- `citations` / `unresolved_citations` / `limitations`: the narrative's
  resolved sourced claims (`orchestrator.session_report.SourcedClaim`) plus
  the deduplicated `limitations` text of only the EvidenceRecords the
  narrative actually cited.
- `bottleneck_report`: the full `SessionBottleneckReport` embedded
  verbatim, so a caller that wants per-stage timing detail, the slowest
  stage/event, or failed/untimed event IDs does not need a second call.

## Mapping onto Web's 8 states, and what is reserved

`run_research_question` is still a synchronous, single-shot call: it only
returns after the bounded pipeline has already finished one full pass. A
report built from its result can therefore only ever resolve to one of the
states that describe a *completed* call: `research_required`,
`partial_answer`, `final_answer`, or `insufficient_evidence`.
`searching_indexed_evidence`, `discovering_sources`, `acquiring_sources`,
`validating_extracting_evidence`, and `reretrieving` are reserved in this
schema for a later durable/incremental caller that builds a report
mid-flight from partial facts -- the same "reserved but not yet emitted"
precedent `research_state.ResearchState.RESEARCHING` already set for
exactly this reason. Building that incremental/polling caller is explicitly
out of scope for this slice; see "Deferred" below.

`PROVIDER_DEGRADED` (a `ResearchState` with no direct Web analogue) maps to
Web's `final_answer` when the releaseable answer already used grounded
reretrieved evidence, otherwise `partial_answer` -- reusing
`ResearchStateResult.used_reretrieved_evidence` and
`.grounded_completion_completed` rather than re-deriving the distinction
from `reason` text. `BLOCKED` (a required release gate failed) fails closed
to Web's `insufficient_evidence`, since Web's vocabulary has no separate
"blocked" state and a blocked session must never be presented as a final
answer.

## Wiring

`run_research_question` now builds a `ResearchProgressReport` from its own
already-assembled `ResearchQuestionResult` and attaches it as
`ResearchQuestionResult.progress_report` before returning. This is pure,
read-only aggregation -- it appends no new `ResearchEvent`, and does not
change retrieval, discovery, grounded-completion, or release-gate behavior.
`progress_report` defaults to `None` on `ResearchQuestionResult` so a caller
constructing that dataclass directly (a test fixture, for instance) is not
required to supply it; every real `run_research_question` call populates it.

## Cross-repo compatibility

`knowledge-engine-web` pins this package by git revision
(`docs/roadmap/bt7_early_stop_on_adequacy.md`'s precedent) and does not yet
construct or read `progress_report`, so it is unaffected until its pin is
bumped and it opts into rendering the new field. No existing field on
`ResearchQuestionResult` was renamed or removed.

## Deferred (explicitly out of scope for this slice)

- A durable/polling entry point that can build a `ResearchProgressReport`
  *while* discovery/acquisition/extraction/re-retrieval are still running,
  which would let `searching_indexed_evidence`, `discovering_sources`,
  `acquiring_sources`, `validating_extracting_evidence`, and `reretrieving`
  actually be emitted. `run_research_question`'s synchronous architecture
  makes this a larger, separate slice (see `docs/roadmap/
  future_ai_orchestration_plan.md`'s durable-workflow-engine track).
- Any Web-side rendering of this contract -- explicitly tracked as
  `knowledge-engine-web#93` and out of scope for this AI-side PR.
- Wiring `ResearchProgressReport` into `research_pipeline_benchmark.py`'s
  `ResearchBenchmarkRun`/`ResearchConversionFunnel`. Its
  `BenchmarkResearchResult` Protocol does not yet expose
  `session_report`/`effective_evidence_report`, and widening it would touch
  that module's existing test fixtures outside this task's scope; the
  benchmark can adopt `build_research_progress_report` in a follow-up slice
  if useful.
