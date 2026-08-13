# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Cross-repository AI-O13 through AI-O15 status alignment.** Updated the web
  integration design after `knowledge-engine-web` PRs #41, #49, and #50: the AI
  package dependency is wired through real web settings, `/ask` capability-gates
  the composed Research Copilot while preserving deterministic retrieval, and
  hosted Research Sessions require a canonically contained persistent mount.
  The Render alpha remains retrieval-only until an operator provisions and
  verifies that mount and the remaining hosted-runtime controls. Durable SQLite
  reopen behavior is recorded separately from a future user-facing resume
  workflow. No AI runtime behavior changes in this repository.

- **Launch-gate dependency security.** Upgraded Typer to the current release
  line and removed the obsolete direct Click compatibility pin that held the
  environment on a vulnerable Click release. CI now audits the resolved Python
  environment with `pip-audit`, and Dependabot monitors Python and GitHub
  Actions dependencies weekly.

- **Correction to the AI-O12-O17 architecture decision's reasoning.**
  The original decision text (this file's "Web Integration plan"
  entry below) claimed `knowledge-engine-web` "already imports
  `knowledge-engine-core` directly as a Python package," making
  `knowledge-engine-ai` "cost almost nothing" to add alongside it.
  Verified false while starting AI-O13: `web`'s `pyproject.toml` has
  no `core` dependency, and `web`'s own `docs/web_design.md` explains
  why -- it deliberately reads `core`'s SQLite database via reflection
  specifically to avoid that dependency weight. `web` has zero ML
  dependencies today. The real cost of adding `ai`: `ai`'s retrieval
  shells out to the `ke` CLI, so `run_research_question` only actually
  works in `web` (not just imports) once `core`'s full dependency
  stack -- torch included -- is available too, and `web`'s deployed
  data snapshot has no `sources.csv` (`ke evidence-report` needs one).
  The decision (library integration over a standalone service) still
  stands -- it just no longer stands on a "this is nearly free" claim
  that was never true. See `docs/web_integration_design.md`'s
  Architecture decision section for the corrected reasoning, and its
  AI-O13 section for what this changes about that step's own scope.
  The historical entry below is left as written -- this is a new entry
  documenting the correction, not a silent edit of the record.

- **AI-O12: compose the orchestrator into one callable pipeline.** The
  actual missing piece `docs/web_integration_design.md` identified --
  `knowledge_engine_ai/copilot/run_research_question.py`'s
  `run_research_question` is this repo's first caller that composes
  `SessionRepository.create_session` -> `run_fixed_evidence_workflow`
  (AI-O3/AI-O5) -> `synthesize_answer` (opt-in local LLM) ->
  `verify_synthesis` (AI-O6 Skeptic check) -> `build_session_report`
  (AI-O7) -> `attempt_session_close` (AI-O2's ISA close gate) ->
  `build_session_trace` (AI-O9) into one call, end to end. A
  `ResearchISA` with two fixed criteria (citation integrity, no
  qualifying/contradicting evidence silently omitted) is attached to
  every session this creates; both criteria pass vacuously when no
  narrative was produced (no evidence to narrate, or the local LLM call
  itself failed) rather than requiring a dynamic `required` flag the
  write-once ISA contract does not allow. A synthesis-step failure is
  still durable and visible (its own failed `ResearchEvent`, surfaced on
  `ResearchQuestionResult.synthesis_error`) without blocking session
  close -- the close gate is scoped to narrative correctness, not
  synthesis availability. New `ke-ai research` CLI command exercises the
  composed pipeline (`--session-db` for the durable SQLite session
  store, `--llm-model`/`--ollama-host` matching `ask --synthesize`'s
  existing flags), so this repo's own CLI dogfoods the orchestrator
  before `knowledge-engine-web` ever calls it (AI-O14). Live-verified
  against the real GLP-1 corpus with real Ollama models, three real runs
  read in full (not just checked for a non-error exit code), each a
  genuinely different outcome: a `qwen2.5:1.5b` run produced a real
  synthesized narrative that the Skeptic check correctly flagged for
  missing bracket citations -- a real catch, not a contrived test
  fixture -- blocking that session's close exactly as designed; a
  `qwen3:4b` run against a narrower slice of the corpus (no evidence
  record with a stated claim in the top matches) completed cleanly with
  no narrative to verify, the vacuous-pass path exercised for real; and
  a first `qwen3:4b` attempt at the wider slice **found a real,
  pre-existing bug this live run is what surfaced**: `llm.py`'s
  `UrllibOllamaTransport.post` only wrapped connect-phase failures into
  `LocalLLMError` via `except URLError` -- a slow generation (Qwen3's
  "thinking" mode) can time out reading the response body itself, which
  `urlopen` raises as a bare `TimeoutError`, not a `URLError`, so it
  escaped unwrapped and crashed the whole command instead of being
  reported as an ordinary synthesis failure. Fixed with a dedicated
  `except TimeoutError` catch and a regression test
  (`test_urllib_transport_wraps_a_slow_response_timeout_as_local_llm_error`);
  this was a pre-existing gap in `ask --synthesize` too, not something
  AI-O12 introduced, just the first live run patient enough (a slower,
  reasoning model over more evidence) to hit it.

- **`docs/web_integration_design.md`: the Web Integration plan (AI-O12-O17),
  doc-only.** Audited the actual current state rather than assuming it from
  milestone names: AI-O1-O9's orchestrator (`run_fixed_evidence_workflow`,
  `verify_synthesis`, `build_session_report`, `attempt_session_close`,
  `build_session_trace`) is fully built and tested, but grepping the whole
  repo for callers outside `tests/` finds none -- not even this repo's own
  `ke-ai ask` CLI command uses it, and `knowledge-engine-web`'s live `/ask`
  page doesn't import `knowledge-engine-ai` at all (it reimplements a
  simpler version directly against `core`). Three layers, none connected.
  Recorded the architecture decision (library integration into
  `knowledge-engine-web`, not a standalone orchestration service, for this
  phase -- the reasoning: `ai` has no web-framework dependency today, `web`
  already imports `core` directly as a package so the "shell out to `ke`,
  never import `core`" weight-avoidance concern `ke_client.py` was built
  around doesn't apply the same way to `ai` itself becoming a `web`
  dependency; a standalone service is deferred to AI-O18+, not rejected, for
  when a second consumer or real multi-tenant load justifies it) and the
  full step-wise breakdown, each step with its own definition of done:
  AI-O12 (compose the orchestrator into one callable pipeline -- the actual
  missing piece everything else depends on), AI-O13 (add `knowledge-engine-ai`
  as a `knowledge-engine-web` dependency), AI-O14 (route `/ask` through it),
  AI-O15 (session-persistence decision for the deployed environment), AI-O16
  (guardrails for a real, publicly-reachable, LLM-cost-bearing endpoint),
  AI-O17 (live end-to-end verification, then close
  `long_term_vision.md`'s "finished product" claim in `knowledge-engine-core`
  for real). Also engages honestly with two things a first pass missed:
  `knowledge-engine-web/docs/web_design.md`'s existing "Decision: local
  LLM" section already rejected a `knowledge-engine-ai` dependency once,
  for a much smaller case (~150 lines of Ollama-client duplication) --
  that reasoning stands for that decision but doesn't apply the same way
  to reusing the entire orchestrator, and AI-O13 should update that
  section rather than leave two contradictory rationales on record; and
  the deployed Render alpha has **no LLM inference in production at all
  today** (`web_design.md`: "deliberately presents retrieval-only Ask
  until it gets a separately hosted, secured, and operationally durable
  inference architecture -- not attempted here") -- AI-O12-O14 are fully
  buildable and live-verifiable in local/dev now, but AI-O17's
  public-alpha half is blocked on that unresolved hosting question,
  named explicitly rather than silently assumed away by AI-O15/AI-O16's
  guardrail work. See `docs/roadmap/future_ai_orchestration_plan.md`'s
  new "Web Integration" section for the pointer. Nothing implemented
  yet -- this is the plan, not the work.

- **AI-O9: Observability + Budgeting.** Closed two real gaps in AI-O2's
  `ResearchEvent` schema and added a read-side reporting layer over it,
  rather than a new persistence mechanism. `ResearchEvent` gains an
  additive `duration_ms: int | None` field (no schema-version bump);
  `orchestrator/workflow.py`'s `_record_step` now times every fixed
  step and populates `duration_ms`, and populates the already-existing
  but previously-never-written `source_ids` field with each retrieval
  step's retrieved evidence-record IDs. New
  `knowledge_engine_ai/orchestrator/observability.py`:
  `build_session_trace(session, events)` projects a session's event log
  into a `SessionTrace` (deduplicated `evidence_record_ids` in
  first-appearance order, `total_duration_ms` summing only events with
  a known duration, `failed_events`); `render_session_trace` renders it
  as plain text with one section per success-criterion question. "Why"
  is answered at the session level (`session.user_question_original`),
  not a per-step field -- this project has no per-step reasoning data
  today, since `run_fixed_evidence_workflow`'s step sequence is fixed by
  its own code (AI-O3), not chosen by a model that could explain a
  choice. Resource/cost budgeting beyond wall-clock duration is
  explicitly out of scope for this slice -- nothing in this project
  tracks a cost unit today (Ollama is local and free per-call, no cloud
  provider is wired in). 12 new tests (`tests/test_observability.py`
  plus new duration/source_ids assertions in
  `tests/test_orchestrator_workflow.py`). Live-verified end to end
  against the real GLP-1 corpus with `core`'s actual `ke` executable,
  all four fixed steps: all six trace sections rendered with real data
  -- 4 real evidence-record IDs surfaced via `source_ids` for the first
  time, `total_duration_ms=120,058` (58,166ms for the combined
  parallel-retrieval call, itself a genuine and worth-keeping
  observation rather than tuned away), `all_succeeded=True`. See
  `docs/ai_o9_design.md`.

- **AI-O8: Model Router.** New `knowledge_engine_ai/model_benchmark.py`:
  `run_model_benchmark` runs a set of role-tagged `BenchmarkTask` probes
  against each candidate model, reusing this project's own existing
  deterministic graders rather than inventing a new scoring method --
  the planning probe wraps AI-O4's `plan_from_question` + AI-O1's
  `validate_research_plan`, the synthesis probe wraps `synthesize_answer`
  + AI-O6's `verify_synthesis` (passing only when neither
  `hallucinated_citations` nor `ungrounded_numbers` fired).
  `recommend_models_by_role` picks the smallest candidate
  (`approx_parameter_count_billions`, caller-supplied) that passed every
  task for a `ModelRole`, meeting the roadmap's literal success
  criterion ("use the smallest model meeting task-quality thresholds");
  a role with zero qualifying candidates is omitted, not an error.
  `provider_specs_from_benchmark` closes the loop into the
  provider-role-routing work merged just ahead of this milestone
  (`routing.py`'s `ProviderSpec`/`select_provider`): a benchmark
  recommendation becomes better-informed input to that one routing
  mechanism instead of a second one, `max_privacy` never exceeding
  `SENSITIVE`. 9 new tests in `tests/test_model_benchmark.py`.
  Live-verified against both models actually pulled in this environment
  (`qwen2.5:1.5b`, `qwen3:4b`) with a real running Ollama server, a real
  planning question, and the same real GLP-1 `EvidenceReport` AI-O6/AI-O7
  live-verified against: `qwen2.5:1.5b` passed both the planning and
  synthesis/citation-compliance probes; `qwen3:4b` failed both (planning
  timed out even at a 300s per-call budget; synthesis returned an empty
  response because its "thinking" tokens consumed the entire response
  budget, reproducing AI-O4's prior anecdotal finding as an automated,
  repeatable benchmark result). A real timeout-tuning artifact was found
  and corrected during verification -- `OllamaLLM`'s 120s default timeout
  made even `qwen2.5:1.5b`'s planning probe appear to fail on a cold
  model load, when an isolated retry with a longer timeout completed in
  36.2 seconds; re-run with `timeout_seconds=300.0` for an honest read.
  See `docs/ai_o8_design.md`.

- **AI-O7: Research Session Synthesis.** New
  `knowledge_engine_ai/orchestrator/session_report.py`:
  `build_session_report(narrative, report, verification)` resolves each
  `[evidence_record_id]` citation a `synthesis.py` narrative actually
  makes into a `SourcedClaim` carrying the containing `RetrievedPaper`'s
  real title, authors, year, DOI, citation string, and source URL -- the
  join from an evidence-record-level citation up to paper-level
  bibliography that no earlier module performed.
  `SessionReport.unresolved_citations` reuses AI-O6's own
  `VerificationResult.hallucinated_citations` (taken as a parameter, not
  recomputed) so a citation is never independently re-checked twice; a
  citation repeated more than once in the narrative resolves to exactly
  one `SourcedClaim`, in order of first appearance.
  `SessionReport.is_fully_sourced` is `True` only when
  `unresolved_citations` is empty. `verification.py`'s citation regex
  moved from a private `_CITATION_RE` to a shared, exported
  `CITATION_PATTERN` constant both modules now import, rather than each
  maintaining its own copy. 5 new tests in `tests/test_session_report.py`.
  Live-verified by re-resolving the real narrative and `EvidenceReport`
  AI-O6's own live check already captured against the real GLP-1 corpus:
  both of the narrative's genuine citations resolved to their correct
  source papers with real DOIs
  (`10.3389/fphar.2022.935823`, `10.1038/s41591-024-02996-7`), zero
  unresolved citations, `is_fully_sourced=True`. See `docs/ai_o7_design.md`.

- **AI-O6: deterministic Skeptic/Verifier.** New
  `knowledge_engine_ai/orchestrator/verification.py`: `verify_synthesis`
  checks a `synthesis.py`-generated narrative against the
  `EvidenceReport` it was built from -- hallucinated citations (a cited
  `[evidence_record_id]` absent from the report), ungrounded numbers (a
  numeric token not present in any cited record's
  `claim_text`/`result_summary`, reusing `core`'s
  `golden_map_grounding.py` numeric-presence technique), and missed
  qualifiers (a `qualifies`/`contradicts`-direction or
  `limitations`-bearing record never cited at all). No LLM verifying
  another LLM, matching AI-O3/AI-O5's deterministic-first precedent. 9
  new tests; one real bug the tests themselves caught (the number
  regex initially matched the "1" inside `[ev-1]` citation brackets as
  a false ungrounded-number finding, fixed by stripping citations
  before extracting numbers). Live-verified end to end against the real
  GLP-1 corpus, `core`'s actual `ke` executable, and a real running
  Ollama model (`qwen2.5:1.5b`): the model's real narrative cited only
  2 of 4 retrieved evidence records, and the checker correctly flagged
  the 2 silently-dropped records as missed qualifiers, with zero
  hallucinated citations or ungrounded numbers -- a genuine first
  real-world signal, not a contrived example. See `docs/ai_o6_design.md`.

- **AI-O5: parallel retrieval + contradiction-oriented retrieval.** New
  `knowledge_engine_ai/orchestrator/parallel_retrieval.py`:
  `run_parallel_retrieval` widens AI-O3's single always-run retrieval
  step into two, run concurrently via a `ThreadPoolExecutor` -- the
  unmodified question (primary) and the same question with `core`'s own
  already-validated same-PICO-contradiction-audit negative-signal
  phrase set appended (contradiction-oriented). No new `core`-side
  capability and no LLM call; each branch's `KeCommandError` is caught
  independently rather than aborting its sibling, matching AI-O3's
  "one step's failure does not stop the rest" discipline.
  `ParallelRetrievalResult.contradiction_only_evidence_record_ids` is
  the concrete recall-gain signal AI-O5's success criterion asks to
  measure. `run_fixed_evidence_workflow` now records both branches as
  separate `ResearchEvent`s (`retrieval_and_evidence_intelligence`,
  `contradiction_oriented_retrieval`); `WorkflowResult.parallel_retrieval`
  carries the full two-branch detail, `evidence_report` still points at
  the primary branch alone for backward compatibility. Optional
  external discovery is an injectable callable, deliberately left
  unwired to any concrete `core` capability (`ke discovery-cycle-run`'s
  persisted pagination-offset semantics do not fit a per-question call
  -- see the design doc). Live-verified against `core`'s real GLP-1 and
  oncology corpora with the actual `ke` executable, at two retrieval
  depths for the oncology check: at a shallow window (`--limit 5`/`8`)
  both corpora showed zero recall gain (the GLP-1 result matches
  `core`'s own contradiction audit finding no contradiction exists
  there -- a correct null result); at a deeper window (`--limit 20`)
  the oncology corpus showed a real, substantial gain -- 63 primary IDs
  vs. 145 contradiction IDs, 121 net-new against only 37 lost, roughly
  3.3x net-new records vs. lost. Retrieval depth, not just query
  wording, materially changes whether the gain is visible at all --
  whether those 121 net-new records are disproportionately genuine
  contradiction candidates was not manually spot-checked and is named
  explicit follow-up work. See `docs/ai_o5_design.md`'s "what this does
  not establish" section for the full honest interpretation. A real,
  narrow concurrency defect was found and
  worked around during verification (two `ke` subprocesses racing to
  apply the same pending schema migration to one on-disk SQLite file on
  first concurrent use), documented rather than silently patched. 6 new
  tests in `tests/test_parallel_retrieval.py`; `tests/test_orchestrator_workflow.py`
  updated for the two-event retrieval step. See `docs/ai_o5_design.md`.

- **AI-O4: local LLM query planner.** New
  `knowledge_engine_ai/copilot/planner.py`: `plan_from_question` prompts
  a local Ollama model to decompose a natural-language question into a
  `ResearchPlan` JSON object, extracts it with a brace-balanced scan
  (survives markdown-fence wrapping), force-overwrites the model's
  `plan_id`/`created_at` with deterministically generated values rather
  than trusting the model to echo them, and validates the result through
  AI-O1's unmodified `parse_research_plan`/`validate_research_plan`.
  Raises `PlannerError` with the raw model output attached on any parse
  or validation failure -- no retry, no repair. Live-verified against a
  real, running `ollama serve` process: 3 of 3 real questions (one per
  this project's three corpus domains) produced a schema-valid,
  correctly domain-matched plan on the first attempt. `qwen3:4b`'s
  hybrid-reasoning "thinking" mode was found unusable at default
  settings in this CPU-only environment (its reasoning tokens consumed
  the entire response budget); verification instead used `qwen2.5:1.5b`.
  16 new tests in `tests/copilot/test_planner.py`. See
  `docs/ai_o4_design.md`.

- **AI-O3: fixed-order deterministic orchestrator.** New
  `knowledge_engine_ai/orchestrator/workflow.py`:
  `run_fixed_evidence_workflow` connects retrieval + Evidence
  Intelligence (always) and the evidence-map / statistical-verification
  steps (only when the caller supplies their required curated inputs)
  to an AI-O2 `ResearchSession`, appending one `ResearchEvent` per step
  whether it succeeds or fails. No LLM call anywhere -- the step
  sequence and each step's run condition are fixed by this module's own
  code, meeting the roadmap's AI-O3 success criterion verbatim ("one
  session can call multiple existing Knowledge Engine capabilities and
  assemble structured results without an LLM dynamically deciding
  execution"). Two new `ke_client.py` wrappers
  (`evidence_map_report`/`statistical_verify`) support this -- neither
  underlying `ke` command has a `--format json` mode, so both return
  their rendered Markdown verbatim. Live-verified end to end against
  the real GLP-1 corpus with `core`'s actual `ke` executable. 12 new
  tests. See `docs/ai_o3_design.md`.

- **AI-O2: durable `ResearchSession`/`ResearchEvent` persistence.**
  New `knowledge_engine_ai/sessions/` subpackage
  (`models.py`/`repository.py`): `SessionStatus` (the design doc's
  nine lifecycle states), frozen `ResearchSession`/`ResearchEvent`
  dataclasses (the session stores only header fields -- everything the
  design doc's `retrieval_runs[]`-style list fields represent is
  derived from the event log, not duplicated), and a SQLite-backed
  `SessionRepository` whose `create_session`/`append_event` raise
  typed `Duplicate*Error`s on a re-used ID rather than silently
  duplicating a row. Success criterion ("a workflow can stop and
  resume without losing or duplicating state") verified end to end by
  a test that closes and reopens a real file-backed database
  connection mid-session. No orchestrator, no LLM call. 12 new tests
  in `tests/sessions/`. See `docs/ai_o2_design.md`.

- **AI-O1: `ResearchPlan`/`ResearchTask` contracts, `TaskType` enum,
  execution-consequence policy, and schema validator.** New
  `knowledge_engine_ai/copilot/` subpackage
  (`contracts.py`/`validation.py`): a seven-value `TaskType` enum
  matching `docs/roadmap/future_ai_orchestration_plan.md`'s
  `required_capabilities` flags, a five-level `ConsequenceLevel` plus
  `execution_decision_for()` implementing that document's default
  execution policy verbatim, frozen `ResearchTask`/`ResearchPlan`
  dataclasses, and `validate_research_plan()`/`parse_research_plan()`
  checking schema version, unique task IDs, resolvable/acyclic
  dependencies, per-task-type consequence-level floors, and
  `required_capabilities`-to-`tasks` agreement. No LLM call, no
  autonomous tool execution, no orchestrator -- the design doc's own
  "Recommended Immediate Decision" section names formalizing these
  contracts as the unconditional next step, ahead of the evidence-base
  thickness gate that applies to later workflow-execution milestones
  (AI-O3 onward). 16 new tests in `tests/copilot/`. See
  `docs/ai_o1_design.md`.

### Changed

- **Reframed AI-O11 (Hypothesis / Experiment Assistance)'s "human
  scientific review" language in `docs/roadmap/future_ai_orchestration_plan.md`.**
  `knowledge-engine-core`'s M72 (jweter/knowledge-engine-core#343)
  established this project's real default for review: an LLM proposes,
  a deterministic grounding check accepts or drops the proposal, and
  human review stays available without being a required gate for every
  record. AI-O11's own text still said a generated hypothesis requires
  human scientific review outright, which no longer matches the pattern
  this project has since built and applied consistently (M52, M69,
  M72). Reframed to name the same grounding-verification pattern as the
  default acceptance mechanism, with human review available and
  expected before acting on a hypothesis outside this system, but not a
  blocking gate this project imposes on every proposal at scale.
  Left `Level 4 -- external consequential action`'s "explicit human
  authorization" language untouched: that gate is about irreversible
  real-world side effects (an action outside this system, not a
  scientific-content classification), a different risk category from
  the review-gate language this pass targets.

### Fixed

- Preserve core's three-way Evidence Quality `extraction_tier`
  (`manual`, `llm_grounded`, or `automated`) when parsing
  `ke evidence-intelligence --format json`. This prevents an
  LLM-grounded record from being reduced to the legacy
  `manually_reviewed: false` view. Synthesis remains core's own
  pre-rendered text and is not reimplemented here.
