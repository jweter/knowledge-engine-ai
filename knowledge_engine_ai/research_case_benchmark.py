"""Deterministic golden research-case benchmark contracts for GQR v1.

Unlike :mod:`knowledge_engine_ai.retrieval_benchmark`, which scores ranked
retrieval against already-reviewed Evidence Record IDs, this module describes
*research-loop behavior* for questions whose relevant evidence may not be in the
local corpus yet.  The benchmark never asks an LLM whether a run is good.  It
scores only inspectable facts supplied by a structured run snapshot: which
research facets/search tracks were covered, which known discovery seeds were
reviewed, whether bounded scholarly discovery ran when the index was empty,
whether counter-evidence was represented, and whether claim/citation guards
were respected.

Discovery-seed identifiers are search targets, not pre-approved scientific
conclusions and not Evidence Record IDs.  A seed may influence synthesis only
after Core has acquired/validated it and promoted grounded evidence through the
normal trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFieldGap:
    """One reviewed source missing benchmark-required extraction fields."""

    source_id: str
    missing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank("source_id", self.source_id)
        _require_unique_nonblank("missing_fields", self.missing_fields)
        if not self.missing_fields:
            raise ValueError("Source field gap requires at least one missing field.")


@dataclass(frozen=True)
class GoldenResearchCase:
    """One deterministic research-loop benchmark specification."""

    case_id: str
    domain: str
    question: str
    required_variants: tuple[str, ...]
    required_dimensions: tuple[str, ...]
    required_search_tracks: tuple[str, ...]
    required_seed_source_ids: tuple[str, ...]
    required_source_fields: tuple[str, ...]
    counterevidence_seed_source_ids: tuple[str, ...] = ()
    required_providers: tuple[str, ...] = ()
    minimum_attempted_providers: int = 1
    inference_guard_ids: tuple[str, ...] = ()
    require_discovery_on_empty_index: bool = True
    require_long_term_gap_disclosure_when_absent: bool = False
    require_all_factual_claims_source_linked: bool = True

    def __post_init__(self) -> None:
        _require_nonblank("case_id", self.case_id)
        _require_nonblank("domain", self.domain)
        _require_nonblank("question", self.question)
        _require_unique_nonblank("required_variants", self.required_variants)
        _require_unique_nonblank("required_dimensions", self.required_dimensions)
        _require_unique_nonblank("required_search_tracks", self.required_search_tracks)
        _require_unique_nonblank("required_seed_source_ids", self.required_seed_source_ids)
        _require_unique_nonblank("required_source_fields", self.required_source_fields)
        _require_unique_nonblank(
            "counterevidence_seed_source_ids", self.counterevidence_seed_source_ids
        )
        _require_unique_nonblank("required_providers", self.required_providers)
        _require_unique_nonblank("inference_guard_ids", self.inference_guard_ids)

        if not self.required_variants:
            raise ValueError("Golden research case requires at least one exposure/variant.")
        if not self.required_dimensions:
            raise ValueError("Golden research case requires at least one answer dimension.")
        if not self.required_search_tracks:
            raise ValueError("Golden research case requires at least one search track.")
        if not self.required_seed_source_ids:
            raise ValueError("Golden research case requires at least one discovery seed source ID.")
        if not self.required_source_fields:
            raise ValueError(
                "Golden research case requires at least one per-source extraction field."
            )

        unknown_counterevidence = set(self.counterevidence_seed_source_ids) - set(
            self.required_seed_source_ids
        )
        if unknown_counterevidence:
            raise ValueError("Counter-evidence seed IDs must also be required seed source IDs.")

        if self.minimum_attempted_providers < 1:
            raise ValueError("minimum_attempted_providers must be at least 1.")
        if self.minimum_attempted_providers < len(self.required_providers):
            raise ValueError(
                "minimum_attempted_providers cannot be smaller than required_providers count."
            )


@dataclass(frozen=True)
class ResearchCaseRunSnapshot:
    """Structured, non-LLM-graded facts observed from one research-case run.

    ``reviewed_source_ids`` means the run explicitly inspected/validated that
    discovery seed as a source candidate.  It does *not* mean the source is a
    citable Evidence Record.  Claim release remains governed by the normal Core
    evidence and citation-integrity path, represented here only by aggregate
    claim-link counts and inference-guard violations.
    """

    case_id: str
    initial_indexed_evidence_record_count: int
    discovery_triggered: bool
    attempted_providers: tuple[str, ...]
    degraded_providers: tuple[str, ...]
    reported_degraded_providers: tuple[str, ...]
    covered_variants: tuple[str, ...]
    covered_dimensions: tuple[str, ...]
    completed_search_tracks: tuple[str, ...]
    reviewed_source_ids: tuple[str, ...]
    represented_counterevidence_source_ids: tuple[str, ...]
    source_fields_audited_source_ids: tuple[str, ...]
    direct_long_term_study_found: bool
    direct_long_term_gap_reported: bool
    factual_claim_count: int
    source_linked_factual_claim_count: int
    source_field_gaps: tuple[SourceFieldGap, ...] = ()
    violated_inference_guard_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonblank("case_id", self.case_id)
        for name in (
            "attempted_providers",
            "degraded_providers",
            "reported_degraded_providers",
            "covered_variants",
            "covered_dimensions",
            "completed_search_tracks",
            "reviewed_source_ids",
            "represented_counterevidence_source_ids",
            "source_fields_audited_source_ids",
            "violated_inference_guard_ids",
        ):
            _require_unique_nonblank(name, getattr(self, name))

        if self.initial_indexed_evidence_record_count < 0:
            raise ValueError("initial_indexed_evidence_record_count must not be negative.")
        if self.factual_claim_count < 0:
            raise ValueError("factual_claim_count must not be negative.")
        if self.source_linked_factual_claim_count < 0:
            raise ValueError("source_linked_factual_claim_count must not be negative.")
        if self.source_linked_factual_claim_count > self.factual_claim_count:
            raise ValueError("source_linked_factual_claim_count cannot exceed factual_claim_count.")

        unknown_degraded = set(self.degraded_providers) - set(self.attempted_providers)
        if unknown_degraded:
            raise ValueError("degraded_providers must be a subset of attempted_providers.")
        unknown_reported_degraded = set(self.reported_degraded_providers) - set(
            self.attempted_providers
        )
        if unknown_reported_degraded:
            raise ValueError("reported_degraded_providers must be a subset of attempted_providers.")

        gap_source_ids = tuple(gap.source_id for gap in self.source_field_gaps)
        if len(gap_source_ids) != len(set(gap_source_ids)):
            raise ValueError("source_field_gaps must contain at most one gap per source_id.")
        unknown_gap_sources = set(gap_source_ids) - set(self.source_fields_audited_source_ids)
        if unknown_gap_sources:
            raise ValueError("source_field_gaps sources must also be source-field audited.")

        unknown_counterevidence = set(self.represented_counterevidence_source_ids) - set(
            self.reviewed_source_ids
        )
        if unknown_counterevidence:
            raise ValueError(
                "represented_counterevidence_source_ids must be a subset of reviewed_source_ids."
            )


@dataclass(frozen=True)
class ResearchCaseBenchmarkResult:
    """Deterministic pass/fail details for one golden research case."""

    case_id: str
    missing_variants: tuple[str, ...]
    missing_dimensions: tuple[str, ...]
    missing_search_tracks: tuple[str, ...]
    missing_seed_source_ids: tuple[str, ...]
    missing_counterevidence_seed_source_ids: tuple[str, ...]
    missing_required_providers: tuple[str, ...]
    provider_count_shortfall: int
    unreported_degraded_providers: tuple[str, ...]
    incorrectly_reported_degraded_providers: tuple[str, ...]
    missing_source_field_audits: tuple[str, ...]
    source_field_gaps: tuple[SourceFieldGap, ...]
    discovery_required_but_not_triggered: bool
    long_term_gap_disclosure_missing: bool
    unlinked_factual_claim_count: int
    violated_inference_guard_ids: tuple[str, ...]

    @property
    def passes(self) -> bool:
        """Return true only when every deterministic acceptance guard passed."""

        return not any(
            (
                self.missing_variants,
                self.missing_dimensions,
                self.missing_search_tracks,
                self.missing_seed_source_ids,
                self.missing_counterevidence_seed_source_ids,
                self.missing_required_providers,
                self.provider_count_shortfall,
                self.unreported_degraded_providers,
                self.incorrectly_reported_degraded_providers,
                self.missing_source_field_audits,
                self.source_field_gaps,
                self.discovery_required_but_not_triggered,
                self.long_term_gap_disclosure_missing,
                self.unlinked_factual_claim_count,
                self.violated_inference_guard_ids,
            )
        )


def evaluate_research_case(
    case: GoldenResearchCase,
    snapshot: ResearchCaseRunSnapshot,
) -> ResearchCaseBenchmarkResult:
    """Evaluate a structured run snapshot against one golden research case."""

    if snapshot.case_id != case.case_id:
        raise ValueError(
            f"Snapshot case_id {snapshot.case_id!r} does not match case {case.case_id!r}."
        )

    missing_variants = _missing(case.required_variants, snapshot.covered_variants)
    missing_dimensions = _missing(case.required_dimensions, snapshot.covered_dimensions)
    missing_search_tracks = _missing(case.required_search_tracks, snapshot.completed_search_tracks)
    missing_seed_source_ids = _missing(case.required_seed_source_ids, snapshot.reviewed_source_ids)
    missing_counterevidence = _missing(
        case.counterevidence_seed_source_ids,
        snapshot.represented_counterevidence_source_ids,
    )
    missing_required_providers = _missing(case.required_providers, snapshot.attempted_providers)
    provider_count_shortfall = max(
        0,
        case.minimum_attempted_providers - len(snapshot.attempted_providers),
    )
    unreported_degraded_providers = _missing(
        snapshot.degraded_providers, snapshot.reported_degraded_providers
    )
    incorrectly_reported_degraded_providers = _missing(
        snapshot.reported_degraded_providers, snapshot.degraded_providers
    )
    missing_source_field_audits = _missing(
        case.required_seed_source_ids, snapshot.source_fields_audited_source_ids
    )
    required_source_fields = set(case.required_source_fields)
    for gap in snapshot.source_field_gaps:
        unknown_fields = set(gap.missing_fields) - required_source_fields
        if unknown_fields:
            raise ValueError(
                f"Source field gap for {gap.source_id!r} named non-required field(s): "
                + ", ".join(sorted(unknown_fields))
            )

    discovery_required_but_not_triggered = (
        case.require_discovery_on_empty_index
        and snapshot.initial_indexed_evidence_record_count == 0
        and not snapshot.discovery_triggered
    )
    long_term_gap_disclosure_missing = (
        case.require_long_term_gap_disclosure_when_absent
        and not snapshot.direct_long_term_study_found
        and not snapshot.direct_long_term_gap_reported
    )
    unlinked_factual_claim_count = (
        snapshot.factual_claim_count - snapshot.source_linked_factual_claim_count
        if case.require_all_factual_claims_source_linked
        else 0
    )

    known_guards = set(case.inference_guard_ids)
    violated_guards = tuple(
        guard_id for guard_id in snapshot.violated_inference_guard_ids if guard_id in known_guards
    )
    unknown_violations = set(snapshot.violated_inference_guard_ids) - known_guards
    if unknown_violations:
        raise ValueError(
            "Snapshot reported unknown inference-guard violation(s): "
            + ", ".join(sorted(unknown_violations))
        )

    return ResearchCaseBenchmarkResult(
        case_id=case.case_id,
        missing_variants=missing_variants,
        missing_dimensions=missing_dimensions,
        missing_search_tracks=missing_search_tracks,
        missing_seed_source_ids=missing_seed_source_ids,
        missing_counterevidence_seed_source_ids=missing_counterevidence,
        missing_required_providers=missing_required_providers,
        provider_count_shortfall=provider_count_shortfall,
        unreported_degraded_providers=unreported_degraded_providers,
        incorrectly_reported_degraded_providers=incorrectly_reported_degraded_providers,
        missing_source_field_audits=missing_source_field_audits,
        source_field_gaps=snapshot.source_field_gaps,
        discovery_required_but_not_triggered=discovery_required_but_not_triggered,
        long_term_gap_disclosure_missing=long_term_gap_disclosure_missing,
        unlinked_factual_claim_count=unlinked_factual_claim_count,
        violated_inference_guard_ids=violated_guards,
    )


def default_golden_research_cases() -> tuple[GoldenResearchCase, ...]:
    """Return the reviewed GQR research-behavior case bank built so far."""

    return (
        GoldenResearchCase(
            case_id="monster-energy-bp-one-year",
            domain="cardiovascular_nutrition",
            question=(
                "For adults, does drinking two 16-fl-oz Monster Energy drinks every day for "
                "approximately one year increase blood-pressure readings, average resting or "
                "ambulatory blood pressure, or the risk of developing or worsening hypertension?"
            ),
            required_variants=(
                "monster_zero_ultra_two_16oz_per_day",
                "monster_original_two_16oz_per_day",
            ),
            required_dimensions=(
                "acute_pressor_effect",
                "persistent_chronic_bp_effect",
                "incident_hypertension_risk",
                "measurement_artifact",
                "original_vs_zero_long_term_risk",
                "direct_vs_class_level_evidence",
                "certainty_and_missing_evidence",
            ),
            required_search_tracks=(
                "direct_monster_or_commercial_energy_drink_trials",
                "energy_drink_randomized_or_meta_analysis",
                "repeated_or_chronic_energy_drink_exposure",
                "chronic_caffeine_randomized_or_meta_analysis",
                "sugar_sweetened_beverage_incident_hypertension",
                "artificially_sweetened_beverage_context",
                "clinical_bp_measurement_guidance",
                "direct_6_12_month_or_one_year_energy_drink_longitudinal",
            ),
            required_seed_source_ids=(
                "pmid:37695306",
                "pmid:27340146",
                "pmid:41236610",
                "pmid:33341807",
                "pmid:26931509",
                "pmid:28446495",
                "pmid:22298600",
                "pmid:26708636",
                "pmid:38057002",
                "pmid:15834273",
                "pmid:26269365",
                "pmid:26869455",
                "pmid:31826724",
                "pmid:32529512",
            ),
            required_source_fields=(
                "population",
                "exposure",
                "dose",
                "duration",
                "comparator",
                "bp_measurement_method",
                "effect_size",
                "confidence_interval",
                "risk_of_bias_or_limitations",
            ),
            counterevidence_seed_source_ids=(
                "pmid:26931509",
                "pmid:26708636",
            ),
            required_providers=("pubmed",),
            minimum_attempted_providers=2,
            inference_guard_ids=(
                "do_not_treat_discovery_candidate_as_evidence",
                "do_not_collapse_acute_and_chronic_bp",
                "do_not_treat_caffeine_coffee_soda_as_direct_energy_drink_evidence",
                "do_not_infer_zero_ultra_causality_from_artificial_sweetener_observation",
                "do_not_claim_one_year_monster_trial_without_direct_source",
            ),
            require_discovery_on_empty_index=True,
            require_long_term_gap_disclosure_when_absent=True,
            require_all_factual_claims_source_linked=True,
        ),
    )


def _missing(required: tuple[str, ...], observed: tuple[str, ...]) -> tuple[str, ...]:
    observed_set = set(observed)
    return tuple(item for item in required if item not in observed_set)


def _require_nonblank(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank.")


def _require_unique_nonblank(name: str, values: tuple[str, ...]) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{name} entries must not be blank.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} entries must be unique.")


__all__ = [
    "GoldenResearchCase",
    "ResearchCaseBenchmarkResult",
    "ResearchCaseRunSnapshot",
    "SourceFieldGap",
    "default_golden_research_cases",
    "evaluate_research_case",
]
