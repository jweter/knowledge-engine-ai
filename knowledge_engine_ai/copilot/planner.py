"""AI-O4: local LLM plan generation behind AI-O1's schema validator.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O4 milestone: "Add
LLM plan generation behind schema validation." Success criterion:
"natural-language questions reliably map to bounded workflow plans."

This is the first place in the AI-O1-through-O11 build order a model
decides *which* capabilities a question needs -- AI-O3's fixed workflow
never inspected the question's content, only what curated data existed.
The seam AI-O1 built holds here: the model never executes a tool,
mutates canonical data, or decides scientific truth. It proposes a
`ResearchPlan`; `validate_research_plan` (already built, already tested)
is the only authority on whether that plan is well-formed.

`plan_from_question` deliberately does not retry, coerce, or repair a
malformed response -- it raises `PlannerError` with the model's raw
output attached and stops. A caller that wants a bounded retry loop
(e.g. feeding the validation error back to the model) builds that
explicitly; guessing a fix for a small model's malformed JSON here
would be exactly the kind of autonomous repair the design doc's
"no autonomous tool execution" principle warns against at this stage.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from knowledge_engine_ai.copilot.contracts import (
    TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL,
    ResearchPlan,
    TaskType,
)
from knowledge_engine_ai.copilot.validation import (
    ResearchPlanParseError,
    ResearchPlanValidationError,
    parse_research_plan,
    validate_research_plan,
)
from knowledge_engine_ai.llm import LocalLLM

DEFAULT_MAX_TOKENS = 1200


class PlannerError(RuntimeError):
    """The model's response could not be turned into a valid `ResearchPlan`."""


def _task_type_table() -> str:
    lines = []
    for task_type in TaskType:
        floor = TASK_TYPE_MINIMUM_CONSEQUENCE_LEVEL[task_type]
        lines.append(f'  - "{task_type.value}" (minimum consequence_level: {floor.value})')
    return "\n".join(lines)


_EXAMPLE_PLAN = {
    "schema_version": 1,
    "plan_id": "plan-example0001",
    "question": "Does semaglutide reduce body weight more than placebo in adults with obesity?",
    "intent": "Compare semaglutide's weight-loss effect against placebo across the reviewed "
    "corpus.",
    "domain": "obesity_metabolic_disease",
    "subquestions": [
        "What randomized evidence directly compares semaglutide to placebo on body weight?",
        "Are there statistically verified effect sizes for this comparison?",
    ],
    "required_capabilities": {
        "corpus_retrieval": True,
        "external_discovery": False,
        "pico_comparison": True,
        "contradiction_search": False,
        "statistics": True,
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
        },
        {
            "task_id": "t2-compare",
            "task_type": "pico_comparison",
            "description": "Compare PICO fields across the retrieved semaglutide-vs-placebo "
            "records.",
            "consequence_level": 1,
            "depends_on": ["t1-retrieve"],
        },
        {
            "task_id": "t3-verify",
            "task_type": "statistics",
            "description": "Run deterministic statistical verification on any curated effect "
            "sizes found.",
            "consequence_level": 2,
            "depends_on": ["t2-compare"],
        },
    ],
    "created_at": "2026-01-01T00:00:00Z",
}


def build_planning_prompt(question: str, *, plan_id: str, created_at: str) -> str:
    """Assemble the strict, schema-grounded prompt for the local planning model."""

    example_json = json.dumps(_EXAMPLE_PLAN, indent=2)
    return (
        "You are a research-planning assistant. Decompose the user's question into a "
        "ResearchPlan: a bounded list of typed tasks, not an answer to the question itself. "
        "You never execute a tool, retrieve real evidence, or decide the scientific answer here "
        "-- you only propose which bounded steps a future system should run.\n\n"
        "Respond with EXACTLY ONE JSON object matching the schema below. No prose before or "
        "after it, no markdown code fence.\n\n"
        "Required top-level fields:\n"
        '  - "schema_version": always the integer 1\n'
        f'  - "plan_id": always exactly "{plan_id}" (use this exact string)\n'
        '  - "question": the user\'s question, verbatim\n'
        '  - "intent": one sentence describing what the plan is trying to establish\n'
        '  - "domain": a short lowercase-with-underscores label for the subject area\n'
        '  - "subquestions": a list of 1-4 short sub-questions this plan addresses\n'
        '  - "required_capabilities": an object with ALL SEVEN of these keys, each true or '
        "false -- true if and only if at least one task below has that task_type:\n"
        f"{_task_type_table()}\n"
        '  - "tasks": a list of 1-6 task objects, each with:\n'
        '      - "task_id": a short unique string\n'
        '      - "task_type": one of the seven values above\n'
        '      - "description": one sentence, what this task does\n'
        '      - "consequence_level": an integer >= that task_type\'s minimum shown above\n'
        '      - "depends_on": a list of other task_ids in this same plan that must run first '
        "(empty list if none)\n"
        f'  - "created_at": always exactly "{created_at}" (use this exact string)\n\n'
        "Worked example (a different question, for format reference only -- do not reuse its "
        "content):\n\n"
        f"{example_json}\n\n"
        f"Question: {question}\n\n"
        "JSON:"
    )


def plan_from_question(
    question: str,
    llm: LocalLLM,
    *,
    plan_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ResearchPlan:
    """Ask the local model to decompose `question` into a validated `ResearchPlan`.

    `plan_id`/`created_at` are generated here, shown to the model as fixed
    strings for prompt-following, and then force-written back into the
    parsed payload regardless of what the model actually returned -- a
    malformed timestamp or non-unique/empty plan_id has nothing to do
    with the model's planning judgment, so it is never left as a way for
    the model to fail this call.

    Raises `PlannerError`, with the model's raw output attached, on any
    JSON-parsing, schema, or validation failure. Never retries or
    repairs a bad response itself.
    """

    resolved_plan_id = plan_id or f"plan-{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    prompt = build_planning_prompt(question, plan_id=resolved_plan_id, created_at=created_at)
    raw_output = llm.generate(prompt, max_tokens=max_tokens)

    payload_text = _extract_json_object(raw_output)
    if payload_text is None:
        raise PlannerError(f"Model output contained no JSON object.\nRaw output:\n{raw_output}")

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise PlannerError(
            f"Model output was not valid JSON: {exc}\nRaw output:\n{raw_output}"
        ) from exc

    if isinstance(payload, dict):
        # Force these rather than trust the model to echo the prompt's fixed
        # strings back verbatim -- a model that paraphrases or drops them
        # should not silently produce a plan with the wrong plan_id/created_at.
        payload["plan_id"] = resolved_plan_id
        payload["created_at"] = created_at

    try:
        plan = parse_research_plan(payload)
    except ResearchPlanParseError as exc:
        raise PlannerError(
            f"Model output did not match the ResearchPlan schema: {exc}\nRaw output:\n{raw_output}"
        ) from exc

    try:
        validate_research_plan(plan)
    except ResearchPlanValidationError as exc:
        raise PlannerError(
            f"Model produced an invalid ResearchPlan: {exc}\nRaw output:\n{raw_output}"
        ) from exc

    return plan


def _extract_json_object(text: str) -> str | None:
    """Extract the first top-level, brace-balanced {...} object from `text`.

    Local models sometimes wrap JSON in a markdown code fence or add a
    sentence before/after it; this strips that framing rather than
    requiring the model's entire response to be bare JSON. Brace
    balancing (not just find-first-to-find-last) matters because the
    plan's own JSON contains nested objects.
    """

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
