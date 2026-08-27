from __future__ import annotations

import json

import pytest

from knowledge_engine_ai.general_query_plan import (
    ConceptGroup,
    EvidenceScope,
    PicoFrame,
    QueryFrameType,
    SearchTrack,
    compile_general_query_plan,
)


def _basic_concepts() -> tuple[ConceptGroup, ...]:
    return (
        ConceptGroup("exposure", "energy drink", ("Monster Energy", "caffeinated beverage")),
        ConceptGroup("outcome", "blood pressure", ("hypertension",)),
    )


def _basic_tracks() -> tuple[SearchTrack, ...]:
    return (
        SearchTrack(
            track_id="direct",
            purpose="Direct exposure/outcome evidence.",
            scope=EvidenceScope.DIRECT,
            concept_ids=("exposure", "outcome"),
            max_variants=4,
        ),
        SearchTrack(
            track_id="counter",
            purpose="Null and contradictory evidence.",
            scope=EvidenceScope.COUNTEREVIDENCE,
            concept_ids=("exposure", "outcome"),
            fixed_terms=("no significant change",),
            max_variants=3,
        ),
    )


def test_compiler_keeps_one_canonical_query_per_track_before_synonym_expansion() -> None:
    plan = compile_general_query_plan(
        "Do energy drinks affect blood pressure?",
        concepts=_basic_concepts(),
        tracks=_basic_tracks(),
        max_total_variants=5,
    )

    assert len(plan.query_variants) == 5
    assert [(variant.track_id, variant.query) for variant in plan.query_variants[:2]] == [
        ("direct", "energy drink blood pressure"),
        ("counter", "energy drink blood pressure no significant change"),
    ]
    assert {variant.track_id for variant in plan.query_variants} == {"direct", "counter"}


def test_global_variant_budget_cannot_starve_a_search_track() -> None:
    with pytest.raises(ValueError, match="at least the number of search tracks"):
        compile_general_query_plan(
            "Question?",
            concepts=_basic_concepts(),
            tracks=_basic_tracks(),
            max_total_variants=1,
        )


def test_unknown_track_concept_fails_before_any_execution_layer() -> None:
    track = SearchTrack(
        track_id="broken",
        purpose="Broken reference.",
        scope=EvidenceScope.DIRECT,
        concept_ids=("missing",),
    )

    with pytest.raises(ValueError, match="unknown concept"):
        compile_general_query_plan(
            "Question?",
            concepts=_basic_concepts(),
            tracks=(track,),
        )


@pytest.mark.parametrize(
    ("domain_hint", "question", "canonical_term"),
    [
        ("chemistry_materials", "Does salt change polymer glass transition?", "polymer"),
        ("physics_astronomy", "What constrains exoplanet atmospheric escape?", "exoplanet"),
        ("machine_learning", "Does retrieval augmentation reduce hallucination?", "RAG"),
        ("general_biology", "Does drought alter stomatal conductance?", "stomata"),
    ],
)
def test_nonclinical_domains_default_to_generic_not_pico(
    domain_hint: str,
    question: str,
    canonical_term: str,
) -> None:
    concept = ConceptGroup("topic", canonical_term)
    track = SearchTrack(
        track_id="primary",
        purpose="Primary literature search.",
        scope=EvidenceScope.DIRECT,
        concept_ids=("topic",),
    )

    plan = compile_general_query_plan(
        question,
        concepts=(concept,),
        tracks=(track,),
        domain_hint=domain_hint,
    )

    assert plan.frame_type is QueryFrameType.GENERIC
    assert plan.pico is None
    assert plan.domain_hint == domain_hint


def test_clinical_question_can_opt_into_pico_explicitly() -> None:
    pico = PicoFrame(
        population="adults with hypertension",
        intervention="home blood-pressure monitoring",
        comparator="usual office monitoring",
        outcomes=("systolic blood pressure", "treatment intensification"),
    )
    concept = ConceptGroup("monitoring", "home blood pressure monitoring")
    track = SearchTrack(
        track_id="clinical",
        purpose="Clinical comparison.",
        scope=EvidenceScope.DIRECT,
        concept_ids=("monitoring",),
    )

    plan = compile_general_query_plan(
        "Does home BP monitoring improve hypertension management?",
        concepts=(concept,),
        tracks=(track,),
        domain_hint="clinical_medicine",
        frame_type=QueryFrameType.PICO,
        pico=pico,
    )

    payload = plan.to_dict()
    assert plan.frame_type is QueryFrameType.PICO
    assert payload["framing"] == {
        "type": "pico",
        "pico": {
            "population": "adults with hypertension",
            "intervention": "home blood-pressure monitoring",
            "comparator": "usual office monitoring",
            "outcomes": ["systolic blood pressure", "treatment intensification"],
        },
    }


def test_pico_is_never_silently_attached_to_generic_plan() -> None:
    pico = PicoFrame(
        population="adults",
        intervention="intervention",
        comparator=None,
        outcomes=("outcome",),
    )
    track = SearchTrack(
        track_id="primary",
        purpose="Primary search.",
        scope=EvidenceScope.DIRECT,
        concept_ids=("topic",),
    )

    with pytest.raises(ValueError, match="only when frame_type is PICO"):
        compile_general_query_plan(
            "Question?",
            concepts=(ConceptGroup("topic", "topic"),),
            tracks=(track,),
            pico=pico,
        )


def test_pico_frame_is_required_when_pico_mode_is_requested() -> None:
    track = SearchTrack(
        track_id="primary",
        purpose="Primary search.",
        scope=EvidenceScope.DIRECT,
        concept_ids=("topic",),
    )

    with pytest.raises(ValueError, match="without a PicoFrame"):
        compile_general_query_plan(
            "Question?",
            concepts=(ConceptGroup("topic", "topic"),),
            tracks=(track,),
            frame_type=QueryFrameType.PICO,
        )


def test_query_plan_json_is_versioned_and_inspectable() -> None:
    plan = compile_general_query_plan(
        "Do energy drinks affect blood pressure?",
        concepts=_basic_concepts(),
        tracks=_basic_tracks(),
        domain_hint="cardiovascular_nutrition",
        answer_dimensions=("acute", "chronic"),
        seed_source_ids=("pmid:1", "pmid:2"),
        max_total_variants=4,
    )

    payload = json.loads(plan.to_json())
    assert payload["schema_version"] == 1
    assert payload["domain_hint"] == "cardiovascular_nutrition"
    assert payload["answer_dimensions"] == ["acute", "chronic"]
    assert payload["seed_source_ids"] == ["pmid:1", "pmid:2"]
    assert len(payload["query_variants"]) == 4


def test_concept_synonym_bound_rejects_unbounded_expansion() -> None:
    with pytest.raises(ValueError, match="more than"):
        ConceptGroup(
            "topic",
            "canonical",
            tuple(f"synonym-{index}" for index in range(9)),
        )


def test_track_variant_bound_rejects_unbounded_expansion() -> None:
    with pytest.raises(ValueError, match="max_variants"):
        SearchTrack(
            track_id="track",
            purpose="Too broad.",
            scope=EvidenceScope.DIRECT,
            concept_ids=("topic",),
            max_variants=13,
        )
