"""Golden research-case query plans built through the generic GQR-2 compiler."""

from __future__ import annotations

from knowledge_engine_ai.general_query_plan import (
    ConceptGroup,
    EvidenceScope,
    GeneralQueryPlan,
    SearchTrack,
    compile_general_query_plan,
)
from knowledge_engine_ai.research_case_benchmark import (
    GoldenResearchCase,
    default_golden_research_cases,
)

_MONSTER_CASE_ID = "monster-energy-bp-one-year"


def monster_energy_bp_query_plan(
    case: GoldenResearchCase | None = None,
    *,
    max_total_variants: int = 32,
) -> GeneralQueryPlan:
    """Compile the issue #79 provider-neutral search plan.

    This is a golden fixture, not a special-case production answer path.  It
    exercises the same generic GQR-2 compiler intended for arbitrary questions,
    while preserving issue #79's reviewed search objectives so future changes
    can be regression-tested.
    """

    resolved_case = case or _monster_case()
    if resolved_case.case_id != _MONSTER_CASE_ID:
        raise ValueError(
            f"Monster query-plan fixture requires case {_MONSTER_CASE_ID!r}; "
            f"received {resolved_case.case_id!r}."
        )

    concepts = (
        ConceptGroup(
            concept_id="monster_brand",
            canonical_term="Monster Energy",
            synonyms=("Monster Zero Ultra", "Monster Original"),
        ),
        ConceptGroup(
            concept_id="monster_zero_ultra",
            canonical_term="Monster Zero Ultra",
            synonyms=("White Monster",),
        ),
        ConceptGroup(
            concept_id="monster_original",
            canonical_term="Monster Energy Original",
            synonyms=("Monster Original", "Original Green Monster"),
        ),
        ConceptGroup(
            concept_id="energy_drink_class",
            canonical_term="energy drink",
            synonyms=("energy drinks", "commercial energy drink"),
        ),
        ConceptGroup(
            concept_id="monster_or_energy_drink",
            canonical_term="Monster Energy",
            synonyms=("energy drink", "Monster Zero Ultra", "Monster Original"),
        ),
        ConceptGroup(
            concept_id="blood_pressure",
            canonical_term="blood pressure",
            synonyms=(
                "hypertension",
                "systolic blood pressure",
                "diastolic blood pressure",
                "ambulatory blood pressure",
            ),
        ),
        ConceptGroup(
            concept_id="acute_timecourse",
            canonical_term="acute",
            synonyms=("post-consumption", "60 minutes", "120 minutes"),
        ),
        ConceptGroup(
            concept_id="repeated_exposure",
            canonical_term="habitual",
            synonyms=("repeated use", "chronic", "daily"),
        ),
        ConceptGroup(
            concept_id="long_term",
            canonical_term="12 months",
            synonyms=("one year", "1 year", "6 months", "longitudinal"),
        ),
        ConceptGroup(
            concept_id="caffeine",
            canonical_term="caffeine",
            synonyms=("caffeine supplementation", "chronic caffeine"),
        ),
        ConceptGroup(
            concept_id="sugar_sweetened_beverage",
            canonical_term="sugar-sweetened beverage",
            synonyms=("sugar sweetened beverages", "SSB"),
        ),
        ConceptGroup(
            concept_id="artificially_sweetened_beverage",
            canonical_term="artificially sweetened beverage",
            synonyms=("diet beverage", "non-nutritively sweetened beverage"),
        ),
        ConceptGroup(
            concept_id="bp_measurement",
            canonical_term="blood pressure measurement",
            synonyms=("blood pressure reading", "BP measurement"),
        ),
        ConceptGroup(
            concept_id="null_or_tolerance",
            canonical_term="no significant change",
            synonyms=("null finding", "tolerance", "not significant"),
        ),
    )

    tracks = (
        SearchTrack(
            track_id="direct_monster_or_commercial_energy_drink_trials",
            purpose="Find direct Monster or closely matched commercial energy-drink BP trials.",
            scope=EvidenceScope.DIRECT,
            concept_ids=("monster_brand", "blood_pressure", "acute_timecourse"),
            fixed_terms=("trial",),
            max_variants=5,
        ),
        SearchTrack(
            track_id="direct_zero_ultra_blood_pressure",
            purpose="Explicitly search Zero Ultra / White Monster blood-pressure evidence.",
            scope=EvidenceScope.DIRECT,
            concept_ids=("monster_zero_ultra", "blood_pressure", "acute_timecourse"),
            max_variants=4,
        ),
        SearchTrack(
            track_id="direct_original_monster_blood_pressure",
            purpose="Explicitly search Original Green Monster blood-pressure evidence.",
            scope=EvidenceScope.DIRECT,
            concept_ids=("monster_original", "blood_pressure", "acute_timecourse"),
            max_variants=4,
        ),
        SearchTrack(
            track_id="energy_drink_randomized_or_meta_analysis",
            purpose="Find randomized and meta-analytic energy-drink blood-pressure evidence.",
            scope=EvidenceScope.CLASS_LEVEL,
            concept_ids=("energy_drink_class", "blood_pressure", "acute_timecourse"),
            fixed_terms=("randomized meta-analysis",),
            max_variants=5,
        ),
        SearchTrack(
            track_id="repeated_or_chronic_energy_drink_exposure",
            purpose=(
                "Find repeated-use energy-drink studies that can separate tolerance "
                "from persistence."
            ),
            scope=EvidenceScope.CLASS_LEVEL,
            concept_ids=("energy_drink_class", "blood_pressure", "repeated_exposure"),
            max_variants=5,
        ),
        SearchTrack(
            track_id="chronic_caffeine_randomized_or_meta_analysis",
            purpose="Find chronic caffeine BP evidence as bounded indirect context.",
            scope=EvidenceScope.INDIRECT_CONTEXT,
            concept_ids=("caffeine", "blood_pressure", "repeated_exposure"),
            fixed_terms=("randomized meta-analysis",),
            max_variants=4,
        ),
        SearchTrack(
            track_id="sugar_sweetened_beverage_incident_hypertension",
            purpose=(
                "Find prospective incident-hypertension evidence relevant to "
                "Original Monster sugar."
            ),
            scope=EvidenceScope.INDIRECT_CONTEXT,
            concept_ids=("sugar_sweetened_beverage", "blood_pressure"),
            fixed_terms=("prospective cohort incident hypertension",),
            max_variants=4,
        ),
        SearchTrack(
            track_id="artificially_sweetened_beverage_context",
            purpose=(
                "Find observational context for artificially sweetened beverages "
                "without inferring causality."
            ),
            scope=EvidenceScope.INDIRECT_CONTEXT,
            concept_ids=("artificially_sweetened_beverage", "blood_pressure"),
            fixed_terms=("prospective cohort",),
            max_variants=4,
        ),
        SearchTrack(
            track_id="clinical_bp_measurement_guidance",
            purpose="Find clinical guidance on caffeine before blood-pressure measurement.",
            scope=EvidenceScope.GUIDANCE,
            concept_ids=("bp_measurement", "caffeine"),
            fixed_terms=("guideline avoid before measurement",),
            max_variants=4,
        ),
        SearchTrack(
            track_id="direct_6_12_month_or_one_year_energy_drink_longitudinal",
            purpose=(
                "Explicitly test whether direct 6-12 month or one-year energy-drink "
                "BP evidence exists."
            ),
            scope=EvidenceScope.DIRECT,
            concept_ids=("monster_or_energy_drink", "blood_pressure", "long_term"),
            fixed_terms=("longitudinal daily",),
            max_variants=6,
        ),
        SearchTrack(
            track_id="counterevidence_or_null_findings",
            purpose="Deliberately search null, nonsignificant, and tolerance findings.",
            scope=EvidenceScope.COUNTEREVIDENCE,
            concept_ids=("monster_or_energy_drink", "blood_pressure", "null_or_tolerance"),
            max_variants=6,
        ),
    )

    required_tracks = set(resolved_case.required_search_tracks)
    fixture_tracks = {track.track_id for track in tracks}
    missing_required_tracks = required_tracks - fixture_tracks
    if missing_required_tracks:
        raise ValueError(
            "Monster query-plan fixture is missing benchmark-required track(s): "
            + ", ".join(sorted(missing_required_tracks))
        )

    return compile_general_query_plan(
        resolved_case.question,
        concepts=concepts,
        tracks=tracks,
        domain_hint=resolved_case.domain,
        answer_dimensions=resolved_case.required_dimensions,
        seed_source_ids=resolved_case.required_seed_source_ids,
        max_total_variants=max_total_variants,
    )


def _monster_case() -> GoldenResearchCase:
    for case in default_golden_research_cases():
        if case.case_id == _MONSTER_CASE_ID:
            return case
    raise RuntimeError(f"Golden research case {_MONSTER_CASE_ID!r} is not registered.")


__all__ = ["monster_energy_bp_query_plan"]
