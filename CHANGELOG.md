# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
