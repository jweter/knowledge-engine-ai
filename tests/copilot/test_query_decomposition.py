from __future__ import annotations

import json

import pytest

from knowledge_engine_ai.copilot.query_decomposition import (
    QueryDecompositionError,
    _extract_json_object,
    build_query_decomposition_prompt,
    parse_query_decomposition,
    query_plan_from_question,
)
from knowledge_engine_ai.general_query_plan import EvidenceScope, QueryFrameType


class _FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.max_tokens_seen: list[int] = []

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del timeout_seconds
        self.prompts.append(prompt)
        self.max_tokens_seen.append(max_tokens)
        return self.response


def _generic_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "domain_hint": "cardiovascular_nutrition",
        "frame_type": "generic",
        "pico": None,
        "answer_dimensions": ["acute_effect", "chronic_effect"],
        "concepts": [
            {
                "concept_id": "exposure",
                "canonical_term": "energy drink",
                "synonyms": ["caffeinated energy beverage"],
            },
            {
                "concept_id": "outcome",
                "canonical_term": "blood pressure",
                "synonyms": ["hypertension"],
            },
        ],
        "tracks": [
            {
                "track_id": "direct",
                "purpose": "Find direct exposure and blood-pressure evidence.",
                "scope": "direct",
                "concept_ids": ["exposure", "outcome"],
                "fixed_terms": [],
                "max_variants": 3,
            },
            {
                "track_id": "counter",
                "purpose": "Find null or contradictory blood-pressure findings.",
                "scope": "counterevidence",
                "concept_ids": ["exposure", "outcome"],
                "fixed_terms": ["no significant change"],
                "max_variants": 2,
            },
        ],
    }


def test_query_plan_from_question_compiles_valid_model_structure() -> None:
    question = "Do energy drinks affect blood pressure?"
    llm = _FakeLLM(json.dumps(_generic_payload()))

    plan = query_plan_from_question(question, llm)

    assert plan.question == question
    assert plan.domain_hint == "cardiovascular_nutrition"
    assert plan.frame_type is QueryFrameType.GENERIC
    assert plan.answer_dimensions == ("acute_effect", "chronic_effect")
    assert {track.scope for track in plan.tracks} == {
        EvidenceScope.DIRECT,
        EvidenceScope.COUNTEREVIDENCE,
    }
    assert {variant.track_id for variant in plan.query_variants} == {"direct", "counter"}
    assert len(llm.prompts) == 1


def test_original_question_is_caller_owned_not_model_owned() -> None:
    question = "What constrains atmospheric escape from small exoplanets?"
    payload = _generic_payload()
    payload["domain_hint"] = "physics_astronomy"
    llm = _FakeLLM(json.dumps(payload))

    plan = query_plan_from_question(question, llm)

    assert plan.question == question
    assert "question" not in payload


def test_caller_owned_seed_source_ids_are_added_after_model_validation() -> None:
    llm = _FakeLLM(json.dumps(_generic_payload()))

    plan = query_plan_from_question(
        "Do energy drinks affect blood pressure?",
        llm,
        seed_source_ids=("pmid:37695306", "doi:10.1000/example"),
    )

    assert plan.seed_source_ids == ("pmid:37695306", "doi:10.1000/example")


def test_model_cannot_smuggle_source_identifiers_into_decomposition_schema() -> None:
    payload = _generic_payload()
    payload["seed_source_ids"] = ["pmid:made-up"]
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(QueryDecompositionError, match="unsupported field.*seed_source_ids"):
        query_plan_from_question("Question?", llm)


def test_clinical_question_can_explicitly_propose_pico() -> None:
    payload = _generic_payload()
    payload["domain_hint"] = "clinical_medicine"
    payload["frame_type"] = "pico"
    payload["pico"] = {
        "population": "adults with hypertension",
        "intervention": "home blood pressure monitoring",
        "comparator": "usual office monitoring",
        "outcomes": ["systolic blood pressure"],
    }
    llm = _FakeLLM(json.dumps(payload))

    plan = query_plan_from_question(
        "Does home blood pressure monitoring improve blood pressure in adults with hypertension?",
        llm,
    )

    assert plan.frame_type is QueryFrameType.PICO
    assert plan.pico is not None
    assert plan.pico.population == "adults with hypertension"


@pytest.mark.parametrize(
    "domain_hint",
    ["chemistry_materials", "physics_astronomy", "machine_learning", "general_biology"],
)
def test_nonclinical_model_proposals_remain_generic(domain_hint: str) -> None:
    payload = _generic_payload()
    payload["domain_hint"] = domain_hint
    payload["frame_type"] = "generic"
    payload["pico"] = None
    llm = _FakeLLM(json.dumps(payload))

    plan = query_plan_from_question("A nonclinical research question.", llm)

    assert plan.frame_type is QueryFrameType.GENERIC
    assert plan.pico is None


def test_pico_object_is_rejected_when_frame_is_generic() -> None:
    payload = _generic_payload()
    payload["pico"] = {
        "population": "adults",
        "intervention": "intervention",
        "comparator": None,
        "outcomes": ["outcome"],
    }

    with pytest.raises(QueryDecompositionError, match="Generic framing"):
        parse_query_decomposition(payload)


def test_invalid_evidence_scope_fails_closed() -> None:
    payload = _generic_payload()
    tracks = payload["tracks"]
    assert isinstance(tracks, list)
    assert isinstance(tracks[0], dict)
    tracks[0]["scope"] = "definitely_true"

    with pytest.raises(QueryDecompositionError, match="unsupported value"):
        parse_query_decomposition(payload)


def test_unknown_concept_reference_fails_during_deterministic_compilation() -> None:
    payload = _generic_payload()
    tracks = payload["tracks"]
    assert isinstance(tracks, list)
    assert isinstance(tracks[0], dict)
    tracks[0]["concept_ids"] = ["does_not_exist"]
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(QueryDecompositionError, match="unknown concept"):
        query_plan_from_question("Question?", llm)


def test_compiler_bounds_reject_model_synonym_explosion() -> None:
    payload = _generic_payload()
    concepts = payload["concepts"]
    assert isinstance(concepts, list)
    assert isinstance(concepts[0], dict)
    concepts[0]["synonyms"] = [f"alias-{index}" for index in range(9)]
    llm = _FakeLLM(json.dumps(payload))

    with pytest.raises(QueryDecompositionError, match="more than 8 synonyms"):
        query_plan_from_question("Question?", llm)


def test_global_query_budget_still_applies_after_model_decomposition() -> None:
    llm = _FakeLLM(json.dumps(_generic_payload()))

    with pytest.raises(QueryDecompositionError, match="at least the number of search tracks"):
        query_plan_from_question("Question?", llm, max_total_variants=1)


def test_model_output_with_markdown_framing_is_still_parsed() -> None:
    payload = json.dumps(_generic_payload())
    llm = _FakeLLM(f"Here is the requested JSON:\n```json\n{payload}\n```")

    plan = query_plan_from_question("Question?", llm)

    assert plan.tracks[0].track_id == "direct"


def test_braces_inside_json_strings_do_not_break_object_extraction() -> None:
    text = 'prefix {"purpose": "find {null} results", "nested": {"x": 1}} suffix'

    assert _extract_json_object(text) == '{"purpose": "find {null} results", "nested": {"x": 1}}'


def test_no_json_output_fails_without_a_retry() -> None:
    llm = _FakeLLM("I cannot produce the requested object.")

    with pytest.raises(QueryDecompositionError, match="no complete JSON object"):
        query_plan_from_question("Question?", llm)

    assert len(llm.prompts) == 1


def test_malformed_json_error_keeps_raw_output_for_debugging() -> None:
    raw = '{"schema_version": 1, bad json}'
    llm = _FakeLLM(raw)

    with pytest.raises(QueryDecompositionError, match="Raw output") as exc_info:
        query_plan_from_question("Question?", llm)

    assert raw in str(exc_info.value)


def test_max_tokens_is_forwarded_to_local_model() -> None:
    llm = _FakeLLM(json.dumps(_generic_payload()))

    query_plan_from_question("Question?", llm, max_tokens=777)

    assert llm.max_tokens_seen == [777]


def test_prompt_names_the_non_authority_and_generic_frame_boundaries() -> None:
    prompt = build_query_decomposition_prompt("Does material X change property Y?")

    assert "Do NOT answer the research question" in prompt
    assert "Do NOT invent citations, PMIDs, DOIs" in prompt
    assert 'Default to frame_type="generic"' in prompt
    assert "Never force PICO onto chemistry" in prompt
    assert "Provider selection and known seed sources are caller-owned" in prompt
