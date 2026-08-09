from __future__ import annotations

from knowledge_engine_ai.copilot.contracts import (
    ConsequenceLevel,
    ExecutionDecision,
    TaskType,
    execution_decision_for,
)


def test_execution_decision_matches_the_design_docs_default_policy() -> None:
    assert execution_decision_for(ConsequenceLevel.PURE_COMPUTATION) == ExecutionDecision.AUTONOMOUS
    assert execution_decision_for(ConsequenceLevel.READ_ONLY) == ExecutionDecision.AUTONOMOUS
    assert (
        execution_decision_for(ConsequenceLevel.REVERSIBLE_BOUNDED_WRITE)
        == ExecutionDecision.AUTONOMOUS_IN_BOUNDED_WORKSPACE
    )
    assert (
        execution_decision_for(ConsequenceLevel.CANONICAL_MUTATION)
        == ExecutionDecision.SCHEMA_RULE_GATED
    )
    assert (
        execution_decision_for(ConsequenceLevel.EXTERNAL_CONSEQUENTIAL_ACTION)
        == ExecutionDecision.HUMAN_AUTHORIZATION_REQUIRED
    )


def test_task_type_has_exactly_the_seven_design_doc_capabilities() -> None:
    assert {member.value for member in TaskType} == {
        "corpus_retrieval",
        "external_discovery",
        "pico_comparison",
        "contradiction_search",
        "statistics",
        "lifecycle_check",
        "reference_context",
    }


def test_consequence_levels_are_ordered_zero_through_four() -> None:
    assert [level.value for level in ConsequenceLevel] == [0, 1, 2, 3, 4]
