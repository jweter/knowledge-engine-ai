from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine_ai.copilot.contracts import (
    ConsequenceLevel,
    ResearchPlan,
    ResearchTask,
    TaskType,
)
from knowledge_engine_ai.copilot.validation import (
    ResearchPlanParseError,
    ResearchPlanValidationError,
    parse_research_plan,
    validate_research_plan,
)


def _valid_plan(**overrides: Any) -> ResearchPlan:
    retrieval_task = ResearchTask(
        task_id="t1",
        task_type=TaskType.CORPUS_RETRIEVAL,
        description="Search the corpus for randomized evidence on long-term weight loss.",
        consequence_level=ConsequenceLevel.READ_ONLY,
    )
    comparison_task = ResearchTask(
        task_id="t2",
        task_type=TaskType.PICO_COMPARISON,
        description="Compare PICO fields across the retrieved records.",
        consequence_level=ConsequenceLevel.READ_ONLY,
        depends_on=("t1",),
    )
    fields: dict[str, Any] = {
        "schema_version": 1,
        "plan_id": "plan-1",
        "question": "Does semaglutide produce clinically meaningful long-term weight loss?",
        "intent": "evidence_synthesis",
        "domain": "clinical_medicine",
        "subquestions": ("What randomized evidence measures long-term body-weight change?",),
        "required_capabilities": {
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: True,
            TaskType.EXTERNAL_DISCOVERY: False,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: False,
            TaskType.REFERENCE_CONTEXT: False,
        },
        "tasks": (retrieval_task, comparison_task),
        "created_at": "2026-08-09T00:00:00Z",
    }
    fields.update(overrides)
    return ResearchPlan(**fields)


def test_valid_plan_passes() -> None:
    validate_research_plan(_valid_plan())


def test_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(ResearchPlanValidationError, match="schema_version"):
        validate_research_plan(_valid_plan(schema_version=2))


def test_empty_question_is_rejected() -> None:
    with pytest.raises(ResearchPlanValidationError, match="question"):
        validate_research_plan(_valid_plan(question="   "))


def test_duplicate_task_id_is_rejected() -> None:
    duplicate = ResearchTask(
        task_id="t1",
        task_type=TaskType.REFERENCE_CONTEXT,
        description="A second task reusing task_id t1.",
        consequence_level=ConsequenceLevel.READ_ONLY,
    )
    plan = _valid_plan(
        tasks=(*_valid_plan().tasks, duplicate),
        required_capabilities={
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: True,
            TaskType.EXTERNAL_DISCOVERY: False,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: True,
            TaskType.REFERENCE_CONTEXT: True,
        },
    )
    with pytest.raises(ResearchPlanValidationError, match="Duplicate task_id"):
        validate_research_plan(plan)


def test_unresolved_dependency_is_rejected() -> None:
    dangling = ResearchTask(
        task_id="t3",
        task_type=TaskType.REFERENCE_CONTEXT,
        description="Depends on a task that does not exist.",
        consequence_level=ConsequenceLevel.READ_ONLY,
        depends_on=("does-not-exist",),
    )
    plan = _valid_plan(
        tasks=(*_valid_plan().tasks, dangling),
        required_capabilities={
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: True,
            TaskType.EXTERNAL_DISCOVERY: False,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: False,
            TaskType.REFERENCE_CONTEXT: True,
        },
    )
    with pytest.raises(ResearchPlanValidationError, match="unknown task_id"):
        validate_research_plan(plan)


def test_dependency_cycle_is_rejected() -> None:
    task_a = ResearchTask(
        task_id="a",
        task_type=TaskType.CORPUS_RETRIEVAL,
        description="Depends on b.",
        consequence_level=ConsequenceLevel.READ_ONLY,
        depends_on=("b",),
    )
    task_b = ResearchTask(
        task_id="b",
        task_type=TaskType.PICO_COMPARISON,
        description="Depends on a, forming a cycle.",
        consequence_level=ConsequenceLevel.READ_ONLY,
        depends_on=("a",),
    )
    plan = _valid_plan(tasks=(task_a, task_b))
    with pytest.raises(ResearchPlanValidationError, match="Dependency cycle"):
        validate_research_plan(plan)


def test_consequence_level_below_type_floor_is_rejected() -> None:
    understated = ResearchTask(
        task_id="t3",
        task_type=TaskType.EXTERNAL_DISCOVERY,
        description="Claims pure computation for a task that writes candidate objects.",
        consequence_level=ConsequenceLevel.PURE_COMPUTATION,
    )
    plan = _valid_plan(
        tasks=(*_valid_plan().tasks, understated),
        required_capabilities={
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: True,
            TaskType.EXTERNAL_DISCOVERY: True,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: False,
            TaskType.REFERENCE_CONTEXT: False,
        },
    )
    with pytest.raises(ResearchPlanValidationError, match="below its type's minimum"):
        validate_research_plan(plan)


def test_declared_capability_without_matching_task_is_rejected() -> None:
    plan = _valid_plan(
        required_capabilities={
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: True,
            TaskType.EXTERNAL_DISCOVERY: True,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: False,
            TaskType.REFERENCE_CONTEXT: False,
        }
    )
    with pytest.raises(ResearchPlanValidationError, match="no task of that type is scheduled"):
        validate_research_plan(plan)


def test_scheduled_task_without_declared_capability_is_rejected() -> None:
    plan = _valid_plan(
        required_capabilities={
            TaskType.CORPUS_RETRIEVAL: True,
            TaskType.PICO_COMPARISON: False,
            TaskType.EXTERNAL_DISCOVERY: False,
            TaskType.CONTRADICTION_SEARCH: False,
            TaskType.STATISTICS: False,
            TaskType.LIFECYCLE_CHECK: False,
            TaskType.REFERENCE_CONTEXT: False,
        }
    )
    with pytest.raises(ResearchPlanValidationError, match="does not declare it True"):
        validate_research_plan(plan)


_VALID_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "plan_id": "plan-1",
    "question": "Does semaglutide produce clinically meaningful long-term weight loss?",
    "intent": "evidence_synthesis",
    "domain": "clinical_medicine",
    "subquestions": ["What randomized evidence measures long-term body-weight change?"],
    "required_capabilities": {
        "corpus_retrieval": True,
        "pico_comparison": True,
        "external_discovery": False,
        "contradiction_search": False,
        "statistics": False,
        "lifecycle_check": False,
        "reference_context": False,
    },
    "tasks": [
        {
            "task_id": "t1",
            "task_type": "corpus_retrieval",
            "description": "Search the corpus.",
            "consequence_level": 1,
            "depends_on": [],
        },
        {
            "task_id": "t2",
            "task_type": "pico_comparison",
            "description": "Compare PICO fields.",
            "consequence_level": 1,
            "depends_on": ["t1"],
        },
    ],
    "created_at": "2026-08-09T00:00:00Z",
}


def test_parse_research_plan_round_trips_and_then_validates() -> None:
    plan = parse_research_plan(_VALID_PAYLOAD)
    assert plan.plan_id == "plan-1"
    assert plan.tasks[1].depends_on == ("t1",)
    validate_research_plan(plan)


def test_parse_research_plan_rejects_unsupported_schema_version() -> None:
    payload = {**_VALID_PAYLOAD, "schema_version": 99}
    with pytest.raises(ResearchPlanParseError, match="schema_version"):
        parse_research_plan(payload)


def test_parse_research_plan_rejects_missing_field() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "question"}
    with pytest.raises(ResearchPlanParseError, match="missing field"):
        parse_research_plan(payload)


def test_parse_research_plan_rejects_unknown_task_type() -> None:
    payload = {
        **_VALID_PAYLOAD,
        "tasks": [{**_VALID_PAYLOAD["tasks"][0], "task_type": "not_a_real_task_type"}],
    }
    with pytest.raises(ResearchPlanParseError, match="invalid value"):
        parse_research_plan(payload)
