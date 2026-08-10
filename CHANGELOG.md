# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Fixed

- Preserve core's three-way Evidence Quality `extraction_tier`
  (`manual`, `llm_grounded`, or `automated`) when parsing
  `ke evidence-intelligence --format json`. This prevents an
  LLM-grounded record from being reduced to the legacy
  `manually_reviewed: false` view. Synthesis remains core's own
  pre-rendered text and is not reimplemented here.
