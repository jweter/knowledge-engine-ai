from __future__ import annotations

import json

import pytest

from knowledge_engine_ai.copilot.planner import (
    PlannerError,
    _extract_json_object,
    build_planning_prompt,
    plan_from_question,
)

_VALID_PAYLOAD = {
    "schema_version": 1,
    "plan_id": "plan-model-made-this-up",
    "question": "Does semaglutide reduce body weight more than placebo?",
    "intent": "Compare semaglutide's weight-loss effect against placebo.",
    "domain": "obesity_metabolic_disease",
    "subquestions": ["What randomized evidence compares semaglutide to placebo?"],
    "required_capabilities": {
        "corpus_retrieval": True,
        "external_discovery": False,
        "pico_comparison": False,
        "contradiction_search": False,
        "statistics": False,
        "lifecycle_check": False,
        "reference_context": False,
    },
    "tasks": [
        {
            "task_id": "t1-retrieve",
            "task_type": "corpus_retrieval",
            "description": "Retrieve evidence records matching semaglutide and body weight.",
            "consequence_level": 1,
            "depends_on": [],
        }
    ],
    "created_at": "2020-01-01T00:00:00Z",
}


class _FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.max_tokens_seen: list[int] = []

    def generate(self, prompt: str, *, max_tokens: int = 400) -> str:
        self.prompts.append(prompt)
        self.max_tokens_seen.append(max_tokens)
        return self.response


def test_plan_from_question_returns_a_valid_plan_on_well_formed_output() -> None:
    llm = _FakeLLM(json.dumps(_VALID_PAYLOAD))

    plan = plan_from_question("Does semaglutide reduce body weight more than placebo?", llm)

    assert plan.domain == "obesity_metabolic_disease"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].task_id == "t1-retrieve"
    assert len(llm.prompts) == 1


def test_plan_from_question_overrides_the_models_plan_id_with_the_resolved_one() -> None:
    """The model's own `plan_id`/`created_at` in the payload are never trusted verbatim."""

    llm = _FakeLLM(json.dumps(_VALID_PAYLOAD))

    plan = plan_from_question("A question.", llm, plan_id="plan-explicit")

    assert plan.plan_id == "plan-explicit"
    assert plan.created_at != _VALID_PAYLOAD["created_at"]


def test_plan_from_question_generates_a_plan_id_when_none_given() -> None:
    llm = _FakeLLM(json.dumps(_VALID_PAYLOAD))

    plan = plan_from_question("A question.", llm)

    assert plan.plan_id.startswith("plan-")
    assert plan.plan_id != _VALID_PAYLOAD["plan_id"]


def test_plan_from_question_passes_max_tokens_through() -> None:
    llm = _FakeLLM(json.dumps(_VALID_PAYLOAD))

    plan_from_question("A question.", llm, max_tokens=99)

    assert llm.max_tokens_seen == [99]


def test_plan_from_question_extracts_json_wrapped_in_a_markdown_fence() -> None:
    fenced_response = f"Here is the plan:\n```json\n{json.dumps(_VALID_PAYLOAD)}\n```\nThanks."
    llm = _FakeLLM(fenced_response)

    plan = plan_from_question("A question.", llm, plan_id="plan-fenced")

    assert plan.plan_id == "plan-fenced"


def test_plan_from_question_raises_planner_error_when_no_json_object_present() -> None:
    llm = _FakeLLM("I cannot help with that.")

    with pytest.raises(PlannerError, match="no JSON object"):
        plan_from_question("A question.", llm)


def test_plan_from_question_raises_planner_error_on_malformed_json() -> None:
    llm = _FakeLLM('{"schema_version": 1, "plan_id": "oops",,,}')

    with pytest.raises(PlannerError, match="not valid JSON"):
        plan_from_question("A question.", llm)


def test_plan_from_question_raises_planner_error_when_a_field_is_missing() -> None:
    payload = json.loads(json.dumps(_VALID_PAYLOAD))
    del payload["intent"]
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(PlannerError, match="did not match the ResearchPlan schema"):
        plan_from_question("A question.", llm)


def test_plan_from_question_raises_planner_error_on_unrecognized_task_type() -> None:
    payload = json.loads(json.dumps(_VALID_PAYLOAD))
    payload["tasks"][0]["task_type"] = "not_a_real_task_type"
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(PlannerError, match="did not match the ResearchPlan schema"):
        plan_from_question("A question.", llm)


def test_plan_from_question_raises_planner_error_when_capabilities_disagree_with_tasks() -> None:
    payload = json.loads(json.dumps(_VALID_PAYLOAD))
    payload["required_capabilities"]["statistics"] = True
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(PlannerError, match="produced an invalid ResearchPlan"):
        plan_from_question("A question.", llm)


def test_plan_from_question_raises_planner_error_when_consequence_level_is_too_low() -> None:
    payload = json.loads(json.dumps(_VALID_PAYLOAD))
    payload["tasks"][0]["task_type"] = "statistics"
    payload["tasks"][0]["consequence_level"] = 1
    payload["required_capabilities"] = {
        "corpus_retrieval": False,
        "external_discovery": False,
        "pico_comparison": False,
        "contradiction_search": False,
        "statistics": True,
        "lifecycle_check": False,
        "reference_context": False,
    }
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(PlannerError, match="produced an invalid ResearchPlan"):
        plan_from_question("A question.", llm)


def test_planner_error_message_includes_raw_output_for_debugging() -> None:
    raw = "not json at all, no braces here"
    llm = _FakeLLM(raw)

    with pytest.raises(PlannerError, match=raw):
        plan_from_question("A question.", llm)


def test_build_planning_prompt_includes_the_question_and_fixed_ids() -> None:
    prompt = build_planning_prompt(
        "Does drug X help?", plan_id="plan-abc", created_at="2026-01-01T00:00:00Z"
    )

    assert "Does drug X help?" in prompt
    assert "plan-abc" in prompt
    assert "2026-01-01T00:00:00Z" in prompt
    assert "corpus_retrieval" in prompt


def test_extract_json_object_finds_brace_balanced_object_with_surrounding_prose() -> None:
    text = 'Sure, here it is:\n{"a": 1, "b": {"c": 2}}\nHope that helps.'

    extracted = _extract_json_object(text)

    assert extracted == '{"a": 1, "b": {"c": 2}}'


def test_extract_json_object_returns_none_when_no_brace_present() -> None:
    assert _extract_json_object("no json here") is None


def test_extract_json_object_returns_none_when_braces_never_balance() -> None:
    assert _extract_json_object("{unbalanced") is None
