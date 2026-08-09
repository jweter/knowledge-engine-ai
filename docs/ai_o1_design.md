# AI-O1 Design: Research Plan Contract

Status: implementation-ready design for this repository's first
Research Copilot milestone, the same role `docs/ai_design.md` played
for Retrieval Intelligence's own first slice. The full multi-agent
architecture this milestone is one piece of -- one Research Copilot
orchestrating typed workers behind `ResearchPlan`/`ResearchSession`/
`ResearchTask`/`ResearchEvent` contracts -- is designed in this
repository's own `docs/roadmap/future_ai_orchestration_plan.md`
(canonical) and mirrored in `knowledge-engine-core`'s
`docs/ai_layer_architecture.md`. This document does not repeat that; it
scopes down to what AI-O1 actually builds and why.

## Mission

Build `ResearchPlan` and `ResearchTask` as typed, inspectable contracts
-- not free-form instructions passed between agents -- plus a
`TaskType` enum, a five-level consequence policy, and a schema
validator. `future_ai_orchestration_plan.md`'s own "Recommended
Immediate Decision" section names this as the unconditional next step,
ahead of any orchestration framework:

> Formalize `ResearchPlan`, `ResearchSession`, `ResearchTask`, and
> `ResearchEvent` contracts first. Those four types establish the
> stable Knowledge Engine domain model that any future agent framework
> can execute.

AI-O1 builds the first two of those four (`ResearchPlan`,
`ResearchTask`); `ResearchSession` and `ResearchEvent` are AI-O2's
scope, per the roadmap's own milestone split.

**Success criterion** (verbatim from the roadmap): *a question is
reliably converted into an inspectable bounded plan.* This milestone
builds the inspectable-plan *shape* and its validator. It does not yet
build anything that converts a question into one -- see "Out of scope"
below.

## Why this milestone is not gated on evidence-base thickness

`knowledge-engine-core`'s `docs/roadmap.md` describes the full
`AI-O1`-`AI-O11` sequence as "gated by evidence-base thickness, not
started beyond what Stage 1-3 already ship." That gate is real and
still holds for the milestones that actually touch evidence --
AI-O3 (deterministic orchestrator connecting real retrieval/Evidence
Intelligence/statistics), AI-O10 (Discovery Intelligence), and AI-O11
(hypothesis generation) all require a corpus and relationship graph
mature enough to exercise them meaningfully. AI-O1 is different: it is
a pure type-system and validation-logic contract with no dependency on
corpus size, evidence maturity, or relationship-graph depth --
`future_ai_orchestration_plan.md`'s own "Recommended Immediate
Decision" section calls out these four contracts as the thing to build
*first*, before any workflow implementation, precisely because they
do not need real evidence to be correct. Building AI-O1 now does not
imply AI-O3 or later milestones are unblocked; each remains its own,
separately gated decision.

## The seam (restated, inherited without exception)

Same boundary every `core`, `knowledge-engine-web`, and this
repository's own M1-M3 milestones have held: nothing in this milestone
computes a confidence number, mutates a canonical Evidence Record,
decides scientific truth, or executes a tool. `ResearchPlan`/
`ResearchTask` are proposed structure a future orchestrator will
enforce -- not workflow execution. No LLM call exists anywhere in this
milestone's code, matching the roadmap's explicit AI-O1 boundary: "No
autonomous tools yet."

## What this milestone builds

Four things, all in `knowledge_engine_ai/copilot/`:

1. **`TaskType`** (`contracts.py`) -- a seven-value enum matching
   `future_ai_orchestration_plan.md`'s `ResearchPlan` JSON example's
   `required_capabilities` flags exactly (`corpus_retrieval`,
   `external_discovery`, `pico_comparison`, `contradiction_search`,
   `statistics`, `lifecycle_check`, `reference_context`), one per
   named worker in that document's internal architecture diagram. Not
   an independently invented vocabulary -- reusing the design doc's own
   named capabilities keeps `ResearchTask.task_type` and
   `ResearchPlan.required_capabilities` two views of the same set
   rather than two structures that can drift apart.
2. **`ConsequenceLevel`** and **`ExecutionDecision`** (`contracts.py`)
   -- the design doc's "Tool Permission Model" section's five levels
   (0 pure computation through 4 external consequential action) and its
   "Default policy" sentence ("Level 0/1 autonomous; Level 2 autonomous
   only in bounded workspace; Level 3 schema/rule gated and
   provenance-preserving; Level 4 explicit human authorization"),
   expressed as an enum plus a pure lookup function
   (`execution_decision_for`) instead of a threshold a future caller
   would have to reimplement inline.
   `TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL` additionally maps each
   `TaskType` to the minimum level its own worker description in the
   design doc implies (e.g. External Discovery "WRITEs temporary
   candidate objects" -> at least Level 2; Corpus Retrieval is
   read-only -> Level 1) -- read directly off that document's own
   words, not invented here.
3. **`ResearchTask`/`ResearchPlan`** (`contracts.py`) -- frozen
   dataclasses. A `ResearchTask` is one bounded unit of work
   (`task_id`, `task_type`, `description`, `consequence_level`,
   `depends_on`); a `ResearchPlan` decomposes one question into
   `subquestions`, `required_capabilities`, and an ordered `tasks`
   tuple, mirroring the design doc's own JSON example plus the `tasks`
   list AI-O1 additionally requires.
4. **`validate_research_plan`/`parse_research_plan`**
   (`validation.py`) -- the schema validator. Checks (in order):
   supported `schema_version`, a non-empty `question`, unique
   `task_id`s, every `depends_on` reference resolves within the same
   plan, no dependency cycle, every task's `consequence_level` meets
   its `task_type`'s floor, and `required_capabilities` exactly agrees
   with which `task_type`s are actually scheduled in `tasks` (neither
   a declared-but-unscheduled capability nor a scheduled-but-undeclared
   one passes). `parse_research_plan` follows this repository's
   existing `models.py` convention exactly: a typed `*ParseError` on an
   unsupported `schema_version` or a missing/invalid field, never a
   guessed default.

## Architecture

```
knowledge_engine_ai/
    copilot/
        contracts.py    -- TaskType, ConsequenceLevel, ExecutionDecision,
                            execution_decision_for(), ResearchTask,
                            ResearchPlan. No I/O, no execution.
        validation.py   -- validate_research_plan(), parse_research_plan(),
                            ResearchPlanValidationError, ResearchPlanParseError.
```

Matches `future_ai_orchestration_plan.md`'s own "Suggested Future
Package Layout" section's `copilot/` subpackage, minus `orchestrator.py`
and `planner.py` -- those belong to AI-O3 (deterministic orchestrator)
and AI-O4 (local LLM planner) respectively, not this milestone. "Do not
scaffold all of this immediately," per that same section; AI-O1 creates
only what its own success criterion needs.

## Out of scope (this milestone)

- **Anything that produces a `ResearchPlan` from a real question.**
  AI-O1 defines the shape a plan must have; AI-O4 ("Local Query
  Planner") is where an LLM generates one behind this same schema
  validator. No LLM call exists in this milestone.
- **`ResearchSession`/`ResearchEvent`.** AI-O2's scope
  ("Durable Research Session": persistence, event log, checkpointing,
  continuation), not built here.
- **Any orchestrator that executes a `ResearchPlan`'s tasks.** AI-O3
  ("Deterministic Orchestrator") connects existing `core` retrieval/
  Evidence Intelligence/statistical-verification capabilities using
  fixed workflow rules; AI-O1 stops at the plan's shape and validator,
  never calls `ke` or any other capability.
- **Enforcing `ExecutionDecision`s at runtime.** `execution_decision_for`
  is a pure lookup a future orchestrator will consult; nothing in this
  milestone actually gates or blocks an execution, because nothing in
  this milestone executes anything.
- **`ResearchTask` retry/status state** (`pending`/`running`/`blocked`/
  etc. from the design doc's "Durable Workflow Engine" section). That
  is workflow *execution* state, which belongs with AI-O2/AI-O3's
  session and orchestrator work, not a static plan contract.

## Open questions (owner decisions, not resolved here)

- **Whether `ResearchTask.consequence_level` should ever exceed its
  `task_type`'s floor** (e.g. a `CORPUS_RETRIEVAL` task explicitly
  marked Level 2 for some corpus-specific reason) -- the validator
  currently only enforces a *minimum*, allowing a higher declared
  level; whether that flexibility is ever actually needed is unclear
  until AI-O3 exercises real tasks against it.
- **How `ResearchTask.description` should be structured** once AI-O4's
  planner generates real plans -- free text today, which is enough for
  a human-authored or test plan, but a planner might benefit from a
  more structured shape (e.g. named parameters) once real usage shows
  what's needed. Not designed against a single hypothetical planner
  output.
- **Package structure once AI-O2 adds `ResearchSession`/
  `ResearchEvent`** -- not designed against one capability, revisit at
  that milestone, the same discipline `ai_design.md` applied to its own
  "package structure once a second capability exists" question.
