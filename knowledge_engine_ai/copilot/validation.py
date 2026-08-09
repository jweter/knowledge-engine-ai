"""AI-O1's schema validator: is a `ResearchPlan` well-formed and internally consistent?

Never judges whether a plan is a *good* plan, scientifically sound, or
worth running -- that stays a human/orchestrator decision. This module
only checks the structural and cross-reference invariants a plan must
satisfy before any future orchestrator (AI-O3+) is allowed to touch it:
unique task IDs, resolvable dependencies, no dependency cycle, no task
claiming a lower consequence level than its `task_type`'s known floor,
and `required_capabilities` staying in agreement with which task types
actually appear in `tasks` -- so a plan cannot silently declare a
capability it does not schedule a task for, or schedule a task for a
capability it declares `False`.
"""

from __future__ import annotations

from typing import Any

from knowledge_engine_ai.copilot.contracts import (
    SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION,
    TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL,
    ConsequenceLevel,
    ResearchPlan,
    ResearchTask,
    TaskType,
)


class ResearchPlanValidationError(RuntimeError):
    """A `ResearchPlan` failed a structural or cross-reference invariant."""


class ResearchPlanParseError(RuntimeError):
    """A `ResearchPlan` JSON payload did not match the expected shape."""


def validate_research_plan(plan: ResearchPlan) -> None:
    """Raise `ResearchPlanValidationError` on the first invariant violation found.

    Checks, in order: schema version, a non-empty question, unique task
    IDs, every `depends_on` reference resolves to a task in this same
    plan, no dependency cycle, every task's `consequence_level` meets
    its `task_type`'s minimum floor, and `required_capabilities` exactly
    matches the set of `task_type`s actually present in `tasks`.
    """

    if plan.schema_version != SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION:
        raise ResearchPlanValidationError(
            f"Unsupported ResearchPlan schema_version: {plan.schema_version!r} "
            f"(this project understands {SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION!r})."
        )

    if not plan.question.strip():
        raise ResearchPlanValidationError("ResearchPlan.question must not be empty.")

    _validate_unique_task_ids(plan.tasks)
    _validate_dependencies_resolve(plan.tasks)
    _validate_no_dependency_cycle(plan.tasks)
    for task in plan.tasks:
        _validate_consequence_level_floor(task)
    _validate_capabilities_match_tasks(plan)


def _validate_unique_task_ids(tasks: tuple[ResearchTask, ...]) -> None:
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            raise ResearchPlanValidationError(f"Duplicate task_id: {task.task_id!r}.")
        seen.add(task.task_id)


def _validate_dependencies_resolve(tasks: tuple[ResearchTask, ...]) -> None:
    known_ids = {task.task_id for task in tasks}
    for task in tasks:
        for dependency_id in task.depends_on:
            if dependency_id not in known_ids:
                raise ResearchPlanValidationError(
                    f"Task {task.task_id!r} depends on unknown task_id {dependency_id!r}."
                )


def _validate_no_dependency_cycle(tasks: tuple[ResearchTask, ...]) -> None:
    depends_on_by_id = {task.task_id: task.depends_on for task in tasks}
    visiting: set[str] = set()
    resolved: set[str] = set()

    def visit(task_id: str, path: tuple[str, ...]) -> None:
        if task_id in resolved:
            return
        if task_id in visiting:
            cycle = " -> ".join((*path, task_id))
            raise ResearchPlanValidationError(f"Dependency cycle detected: {cycle}.")
        visiting.add(task_id)
        for dependency_id in depends_on_by_id.get(task_id, ()):
            visit(dependency_id, (*path, task_id))
        visiting.discard(task_id)
        resolved.add(task_id)

    for task in tasks:
        visit(task.task_id, ())


def _validate_consequence_level_floor(task: ResearchTask) -> None:
    floor = TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL[task.task_type]
    if task.consequence_level < floor:
        raise ResearchPlanValidationError(
            f"Task {task.task_id!r} ({task.task_type.value}) declares consequence_level "
            f"{task.consequence_level.name} below its type's minimum {floor.name}."
        )


def _validate_capabilities_match_tasks(plan: ResearchPlan) -> None:
    task_types_present = {task.task_type for task in plan.tasks}
    for task_type in TaskType:
        declared = plan.required_capabilities.get(task_type, False)
        present = task_type in task_types_present
        if declared and not present:
            raise ResearchPlanValidationError(
                f"required_capabilities declares {task_type.value!r} True, "
                "but no task of that type is scheduled."
            )
        if present and not declared:
            raise ResearchPlanValidationError(
                f"A task of type {task_type.value!r} is scheduled, "
                "but required_capabilities does not declare it True."
            )


def parse_research_plan(payload: dict[str, Any]) -> ResearchPlan:
    """Parse a `ResearchPlan` JSON payload (e.g. a planner's structured output).

    Raises `ResearchPlanParseError` on an unsupported `schema_version`,
    a missing required field, or an unrecognized `task_type` -- never
    guesses a default for data the payload did not actually provide.
    Does not call `validate_research_plan`; callers run that separately
    once parsing succeeds, matching this repository's existing
    parse-then-validate convention.
    """

    schema_version = payload.get("schema_version")
    if schema_version != SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION:
        raise ResearchPlanParseError(
            f"Unsupported ResearchPlan schema_version: {schema_version!r} "
            f"(this project understands {SUPPORTED_RESEARCH_PLAN_SCHEMA_VERSION!r})."
        )

    try:
        required_capabilities = {
            TaskType(key): bool(value) for key, value in payload["required_capabilities"].items()
        }
        tasks = tuple(_parse_task(task_payload) for task_payload in payload["tasks"])
        return ResearchPlan(
            schema_version=schema_version,
            plan_id=payload["plan_id"],
            question=payload["question"],
            intent=payload["intent"],
            domain=payload["domain"],
            subquestions=tuple(payload["subquestions"]),
            required_capabilities=required_capabilities,
            tasks=tasks,
            created_at=payload["created_at"],
        )
    except KeyError as exc:
        raise ResearchPlanParseError(f"ResearchPlan JSON is missing field: {exc}") from exc
    except ValueError as exc:
        raise ResearchPlanParseError(f"ResearchPlan JSON has an invalid value: {exc}") from exc


def _parse_task(payload: dict[str, Any]) -> ResearchTask:
    try:
        return ResearchTask(
            task_id=payload["task_id"],
            task_type=TaskType(payload["task_type"]),
            description=payload["description"],
            consequence_level=ConsequenceLevel(payload["consequence_level"]),
            depends_on=tuple(payload.get("depends_on", ())),
        )
    except KeyError as exc:
        raise ResearchPlanParseError(f"ResearchTask JSON is missing field: {exc}") from exc
    except ValueError as exc:
        raise ResearchPlanParseError(f"ResearchTask JSON has an invalid value: {exc}") from exc
