"""AI-O1: the `ResearchPlan`/`ResearchTask` contracts and execution policy.

`docs/roadmap/future_ai_orchestration_plan.md`'s "Recommended Immediate
Decision" section calls for formalizing these contracts first, before any
orchestration framework or LLM-driven planner exists -- "the stable
Knowledge Engine domain model that any future agent framework can
execute." Nothing in this module calls an LLM, retrieves evidence, or
executes a tool; it only defines the typed shape a plan must have and
the consequence-level policy that will gate what a future orchestrator
is allowed to run autonomously.

`TaskType` mirrors the seven `required_capabilities` flags from the
design doc's `ResearchPlan` example (`corpus_retrieval`,
`external_discovery`, `pico_comparison`, `contradiction_search`,
`statistics`, `lifecycle_check`, `reference_context`) rather than an
independently invented vocabulary, so a plan's `tasks` and
`required_capabilities` stay two views of the same underlying set
instead of two structures that can silently drift apart --
`validate_research_plan` in `validation.py` checks that they agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION = 1


class TaskType(StrEnum):
    """A `ResearchTask`'s functional category, one per design-doc worker.

    Matches the design doc's `required_capabilities` flags exactly:
    `CORPUS_RETRIEVAL` (Retrieval Intelligence Worker), `EXTERNAL_DISCOVERY`
    (External Discovery Worker), `PICO_COMPARISON` (Evidence Analyst),
    `CONTRADICTION_SEARCH` (Skeptic / Adversarial Evidence Worker),
    `STATISTICS` (Statistics Auditor), `LIFECYCLE_CHECK` (stability/
    supersedes graph state), and `REFERENCE_CONTEXT` (Reference Knowledge
    Worker).
    """

    CORPUS_RETRIEVAL = "corpus_retrieval"
    EXTERNAL_DISCOVERY = "external_discovery"
    PICO_COMPARISON = "pico_comparison"
    CONTRADICTION_SEARCH = "contradiction_search"
    STATISTICS = "statistics"
    LIFECYCLE_CHECK = "lifecycle_check"
    REFERENCE_CONTEXT = "reference_context"


class ConsequenceLevel(IntEnum):
    """How reversible and consequential a task's execution is.

    Verbatim from the design doc's "Tool Permission Model" section:
    Level 0 pure computation, Level 1 read-only, Level 2 reversible
    bounded write, Level 3 canonical mutation, Level 4 external
    consequential action.
    """

    PURE_COMPUTATION = 0
    READ_ONLY = 1
    REVERSIBLE_BOUNDED_WRITE = 2
    CANONICAL_MUTATION = 3
    EXTERNAL_CONSEQUENTIAL_ACTION = 4


class ExecutionDecision(StrEnum):
    """What a future orchestrator must do before running a task at a given level."""

    AUTONOMOUS = "autonomous"
    AUTONOMOUS_IN_BOUNDED_WORKSPACE = "autonomous_in_bounded_workspace"
    SCHEMA_RULE_GATED = "schema_rule_gated"
    HUMAN_AUTHORIZATION_REQUIRED = "human_authorization_required"


_DEFAULT_EXECUTION_POLICY: dict[ConsequenceLevel, ExecutionDecision] = {
    ConsequenceLevel.PURE_COMPUTATION: ExecutionDecision.AUTONOMOUS,
    ConsequenceLevel.READ_ONLY: ExecutionDecision.AUTONOMOUS,
    ConsequenceLevel.REVERSIBLE_BOUNDED_WRITE: ExecutionDecision.AUTONOMOUS_IN_BOUNDED_WORKSPACE,
    ConsequenceLevel.CANONICAL_MUTATION: ExecutionDecision.SCHEMA_RULE_GATED,
    ConsequenceLevel.EXTERNAL_CONSEQUENTIAL_ACTION: ExecutionDecision.HUMAN_AUTHORIZATION_REQUIRED,
}
"""The design doc's "Default policy" sentence, expressed as data: "Level
0/1 autonomous; Level 2 autonomous only in bounded workspace; Level 3
schema/rule gated and provenance-preserving; Level 4 explicit human
authorization." A future orchestrator consults this, never invents its
own threshold inline."""


def execution_decision_for(level: ConsequenceLevel) -> ExecutionDecision:
    """The default execution policy's decision for a given consequence level."""

    return _DEFAULT_EXECUTION_POLICY[level]


TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL: dict[TaskType, ConsequenceLevel] = {
    TaskType.CORPUS_RETRIEVAL: ConsequenceLevel.READ_ONLY,
    TaskType.EXTERNAL_DISCOVERY: ConsequenceLevel.REVERSIBLE_BOUNDED_WRITE,
    TaskType.PICO_COMPARISON: ConsequenceLevel.READ_ONLY,
    TaskType.CONTRADICTION_SEARCH: ConsequenceLevel.READ_ONLY,
    TaskType.STATISTICS: ConsequenceLevel.REVERSIBLE_BOUNDED_WRITE,
    TaskType.LIFECYCLE_CHECK: ConsequenceLevel.READ_ONLY,
    TaskType.REFERENCE_CONTEXT: ConsequenceLevel.READ_ONLY,
}
"""Each `TaskType`'s minimum real-world consequence level, read directly
off the design doc's own description of that worker: Retrieval/Evidence
Analyst/Skeptic/lifecycle-check/Reference workers are read-only;
External Discovery "WRITEs temporary candidate objects" and Statistics
"WRITEs verification records" -- both reversible, bounded writes, never
a canonical evidence mutation. A `ResearchTask` may not claim a lower
level than this floor for its `task_type` -- see
`validate_research_plan`."""


@dataclass(frozen=True)
class ResearchTask:
    """One bounded, typed unit of work within a `ResearchPlan`.

    Never executed by this module -- AI-O1 stops at the contract and its
    validator. `depends_on` lists other tasks' `task_id`s that must
    complete first; `validate_research_plan` checks these references
    resolve and contain no cycle.
    """

    task_id: str
    task_type: TaskType
    description: str
    consequence_level: ConsequenceLevel
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResearchPlan:
    """A question decomposed into an inspectable, bounded set of `ResearchTask`s.

    Mirrors the design doc's `ResearchPlan` JSON example
    (`question`/`intent`/`domain`/`subquestions`/`required_capabilities`)
    plus the `tasks` list AI-O1 additionally requires. Nothing here
    decides scientific truth, mutates canonical Evidence Records, or
    executes a tool -- it is proposed structure for a future
    orchestrator to enforce, not an executed workflow.
    """

    schema_version: int
    plan_id: str
    question: str
    intent: str
    domain: str
    subquestions: tuple[str, ...]
    required_capabilities: dict[TaskType, bool]
    tasks: tuple[ResearchTask, ...]
    created_at: str
