"""Intent-engineering contracts for the Research Copilot.

These contracts adapt the most useful LifeOS TELOS/Ideal State Artifact
ideas to Knowledge Engine without introducing a LifeOS runtime dependency.
They deliberately contain no model calls, tool execution, or evidence
mutation. They define inspectable intent and falsifiable completion criteria
that the orchestrator and deterministic verification layer can consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

SUPPORTED_RESEARCH_ISA_SCHEMA_VERSION = 1


class PrivacyClass(StrEnum):
    """Maximum sensitivity class for research context and routing policy."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class CriterionStatus(StrEnum):
    """Observed state of one falsifiable Ideal State criterion."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class GlobalResearchIntent:
    """Stable epistemic doctrine that applies across Knowledge Engine projects."""

    mission: str = "Produce defensible, traceable scientific conclusions."
    epistemic_principles: tuple[str, ...] = (
        "Separate evidence from inference.",
        "Prefer primary literature for factual scientific claims.",
        "Preserve contradictory and qualifying evidence.",
        "Never fabricate citations.",
        "Distinguish absence of evidence from evidence of absence.",
        "Preserve raw source provenance.",
        "Record uncertainty explicitly.",
        "Prefer deterministic computation when it can answer reliably.",
    )


@dataclass(frozen=True)
class ProjectResearchIntent:
    """Longer-lived objective and policy for one research project."""

    project_id: str
    objective: str
    constraints: tuple[str, ...] = field(default_factory=tuple)
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    cloud_allowed: bool = False
    source_preferences: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IdealStateCriterion:
    """One falsifiable statement that must be probed before a run may close."""

    criterion_id: str
    claim: str
    probe: str
    required: bool = True


@dataclass(frozen=True)
class ResearchISA:
    """Task-specific Ideal State Artifact for one bounded research run."""

    schema_version: int
    run_id: str
    question: str
    ideal_state: str
    criteria: tuple[IdealStateCriterion, ...]
    known: tuple[str, ...] = field(default_factory=tuple)
    unknown: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CriterionResult:
    """Evidence-bearing result of running one ISA probe."""

    criterion_id: str
    status: CriterionStatus
    evidence: str


@dataclass(frozen=True)
class ISAValidationResult:
    """Aggregate close-gate result for a Research ISA."""

    complete: bool
    unresolved_required_criteria: tuple[str, ...]


def validate_research_isa(isa: ResearchISA) -> tuple[str, ...]:
    """Return structural validation errors for a Research ISA.

    This validates the contract itself, not whether its probes have passed.
    Returning all errors instead of raising on the first one makes the object
    easier to inspect in CLI/API surfaces and deterministic tests.
    """

    errors: list[str] = []

    if isa.schema_version != SUPPORTED_RESEARCH_ISA_SCHEMA_VERSION:
        errors.append(
            "unsupported schema_version: "
            f"{isa.schema_version}; expected {SUPPORTED_RESEARCH_ISA_SCHEMA_VERSION}"
        )
    if not isa.run_id.strip():
        errors.append("run_id must not be empty")
    if not isa.question.strip():
        errors.append("question must not be empty")
    if not isa.ideal_state.strip():
        errors.append("ideal_state must not be empty")
    if not isa.criteria:
        errors.append("at least one ideal-state criterion is required")

    seen_ids: set[str] = set()
    for criterion in isa.criteria:
        if not criterion.criterion_id.strip():
            errors.append("criterion_id must not be empty")
        elif criterion.criterion_id in seen_ids:
            errors.append(f"duplicate criterion_id: {criterion.criterion_id}")
        else:
            seen_ids.add(criterion.criterion_id)

        if not criterion.claim.strip():
            errors.append(f"criterion {criterion.criterion_id!r} claim must not be empty")
        if not criterion.probe.strip():
            errors.append(f"criterion {criterion.criterion_id!r} probe must not be empty")

    return tuple(errors)


def evaluate_isa_close_gate(
    isa: ResearchISA,
    results: tuple[CriterionResult, ...],
) -> ISAValidationResult:
    """Decide whether all required ISA criteria have passed.

    Missing results, failed probes, and blocked probes remain unresolved.
    Optional criteria do not prevent closure. Unknown result IDs are ignored
    here because structural/result-set validation belongs at the orchestration
    boundary where richer provenance is available.
    """

    result_by_id = {result.criterion_id: result for result in results}
    unresolved: list[str] = []

    for criterion in isa.criteria:
        if not criterion.required:
            continue
        result = result_by_id.get(criterion.criterion_id)
        if result is None or result.status is not CriterionStatus.PASSED:
            unresolved.append(criterion.criterion_id)

    return ISAValidationResult(
        complete=not unresolved,
        unresolved_required_criteria=tuple(unresolved),
    )
