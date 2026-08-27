"""Bounded provider-neutral query-plan contracts for General Question Research Loop v1.

This module is the GQR-2 search-planning boundary.  It does not execute provider
calls and it does not decide scientific truth.  A caller supplies a structured
question decomposition (concepts and search tracks); the compiler validates that
structure, expands synonym combinations deterministically, and returns a bounded,
inspectable plan.

The compiler deliberately defaults to a generic frame.  PICO is opt-in and must
be explicitly supplied for a question where that framing is appropriate.  This
keeps clinical structure available without forcing it onto chemistry, physics,
machine-learning, biology, or other domains.

Query variants are search artifacts only.  They are not Evidence Records and
their existence never makes a factual claim citable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import product

GENERAL_QUERY_PLAN_SCHEMA_VERSION = 1
MAX_CONCEPTS = 16
MAX_SYNONYMS_PER_CONCEPT = 8
MAX_SEARCH_TRACKS = 16
MAX_VARIANTS_PER_TRACK = 12
MAX_TOTAL_VARIANTS = 64
MAX_QUERY_CHARACTERS = 500


class QueryFrameType(StrEnum):
    """Supported structured framing modes for a general query plan."""

    GENERIC = "generic"
    PICO = "pico"


class EvidenceScope(StrEnum):
    """How directly one search track bears on the user's primary exposure/question."""

    DIRECT = "direct"
    CLASS_LEVEL = "class_level"
    INDIRECT_CONTEXT = "indirect_context"
    GUIDANCE = "guidance"
    COUNTEREVIDENCE = "counterevidence"


@dataclass(frozen=True)
class PicoFrame:
    """Optional PICO framing for questions where PICO is actually suitable."""

    population: str
    intervention: str
    comparator: str | None
    outcomes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank("population", self.population)
        _require_nonblank("intervention", self.intervention)
        if self.comparator is not None:
            _require_nonblank("comparator", self.comparator)
        _require_unique_nonblank("outcomes", self.outcomes)
        if not self.outcomes:
            raise ValueError("PICO frame requires at least one outcome.")

    def to_dict(self) -> dict[str, object]:
        return {
            "population": self.population,
            "intervention": self.intervention,
            "comparator": self.comparator,
            "outcomes": list(self.outcomes),
        }


@dataclass(frozen=True)
class ConceptGroup:
    """One canonical search concept plus bounded synonym/alias alternatives."""

    concept_id: str
    canonical_term: str
    synonyms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier("concept_id", self.concept_id)
        _require_nonblank("canonical_term", self.canonical_term)
        _require_unique_nonblank("synonyms", self.synonyms)
        if len(self.synonyms) > MAX_SYNONYMS_PER_CONCEPT:
            raise ValueError(
                f"Concept {self.concept_id!r} has more than "
                f"{MAX_SYNONYMS_PER_CONCEPT} synonyms."
            )
        if self.canonical_term in self.synonyms:
            raise ValueError("Concept synonyms must not repeat the canonical term.")

    @property
    def terms(self) -> tuple[str, ...]:
        """Canonical term first, then caller-reviewed synonyms in supplied order."""

        return (self.canonical_term, *self.synonyms)

    def to_dict(self) -> dict[str, object]:
        return {
            "concept_id": self.concept_id,
            "canonical_term": self.canonical_term,
            "synonyms": list(self.synonyms),
        }


@dataclass(frozen=True)
class SearchTrack:
    """One bounded literature-search objective within the larger research question."""

    track_id: str
    purpose: str
    scope: EvidenceScope
    concept_ids: tuple[str, ...] = ()
    fixed_terms: tuple[str, ...] = ()
    max_variants: int = 4

    def __post_init__(self) -> None:
        _require_identifier("track_id", self.track_id)
        _require_nonblank("purpose", self.purpose)
        _require_unique_nonblank("concept_ids", self.concept_ids)
        _require_unique_nonblank("fixed_terms", self.fixed_terms)
        if not self.concept_ids and not self.fixed_terms:
            raise ValueError("Search track requires at least one concept or fixed term.")
        if not 1 <= self.max_variants <= MAX_VARIANTS_PER_TRACK:
            raise ValueError(
                f"Search track max_variants must be between 1 and {MAX_VARIANTS_PER_TRACK}."
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "purpose": self.purpose,
            "scope": self.scope.value,
            "concept_ids": list(self.concept_ids),
            "fixed_terms": list(self.fixed_terms),
            "max_variants": self.max_variants,
        }


@dataclass(frozen=True)
class QueryVariant:
    """One provider-neutral query string produced for one search track."""

    variant_id: str
    track_id: str
    scope: EvidenceScope
    query: str
    chosen_concept_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identifier("variant_id", self.variant_id)
        _require_identifier("track_id", self.track_id)
        _require_nonblank("query", self.query)
        _require_nonblank_values("chosen_concept_terms", self.chosen_concept_terms)
        if len(self.query) > MAX_QUERY_CHARACTERS:
            raise ValueError(
                f"Query variant exceeds the {MAX_QUERY_CHARACTERS}-character bound."
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "track_id": self.track_id,
            "scope": self.scope.value,
            "query": self.query,
            "chosen_concept_terms": list(self.chosen_concept_terms),
        }


@dataclass(frozen=True)
class GeneralQueryPlan:
    """Versioned, inspectable result of deterministic GQR-2 query compilation."""

    schema_version: int
    question: str
    domain_hint: str | None
    frame_type: QueryFrameType
    pico: PicoFrame | None
    answer_dimensions: tuple[str, ...]
    seed_source_ids: tuple[str, ...]
    concepts: tuple[ConceptGroup, ...]
    tracks: tuple[SearchTrack, ...]
    query_variants: tuple[QueryVariant, ...]
    max_total_variants: int

    def __post_init__(self) -> None:
        if self.schema_version != GENERAL_QUERY_PLAN_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported query-plan schema version {self.schema_version}; "
                f"expected {GENERAL_QUERY_PLAN_SCHEMA_VERSION}."
            )
        _require_nonblank("question", self.question)
        if self.domain_hint is not None:
            _require_nonblank("domain_hint", self.domain_hint)
        _require_unique_nonblank("answer_dimensions", self.answer_dimensions)
        _require_unique_nonblank("seed_source_ids", self.seed_source_ids)
        if not 1 <= self.max_total_variants <= MAX_TOTAL_VARIANTS:
            raise ValueError(
                f"max_total_variants must be between 1 and {MAX_TOTAL_VARIANTS}."
            )

        if self.frame_type is QueryFrameType.PICO and self.pico is None:
            raise ValueError("PICO query plan requires an explicit PicoFrame.")
        if self.frame_type is QueryFrameType.GENERIC and self.pico is not None:
            raise ValueError("Generic query plan must not carry a PicoFrame.")

        concept_ids = tuple(concept.concept_id for concept in self.concepts)
        track_ids = tuple(track.track_id for track in self.tracks)
        variant_ids = tuple(variant.variant_id for variant in self.query_variants)
        _require_unique_nonblank("concept IDs", concept_ids)
        _require_unique_nonblank("track IDs", track_ids)
        _require_unique_nonblank("variant IDs", variant_ids)

        if not self.concepts:
            raise ValueError("Query plan requires at least one concept.")
        if len(self.concepts) > MAX_CONCEPTS:
            raise ValueError(f"Query plan may contain at most {MAX_CONCEPTS} concepts.")
        if not self.tracks:
            raise ValueError("Query plan requires at least one search track.")
        if len(self.tracks) > MAX_SEARCH_TRACKS:
            raise ValueError(f"Query plan may contain at most {MAX_SEARCH_TRACKS} search tracks.")
        if len(self.query_variants) > self.max_total_variants:
            raise ValueError("Query plan contains more variants than its declared total bound.")

        known_track_ids = set(track_ids)
        unknown_variant_tracks = {
            variant.track_id
            for variant in self.query_variants
            if variant.track_id not in known_track_ids
        }
        if unknown_variant_tracks:
            raise ValueError("Query variants reference unknown search tracks.")

        covered_track_ids = {variant.track_id for variant in self.query_variants}
        missing_track_variants = set(track_ids) - covered_track_ids
        if missing_track_variants:
            raise ValueError("Every search track must retain at least one query variant.")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "question": self.question,
            "domain_hint": self.domain_hint,
            "framing": {
                "type": self.frame_type.value,
                "pico": self.pico.to_dict() if self.pico is not None else None,
            },
            "answer_dimensions": list(self.answer_dimensions),
            "seed_source_ids": list(self.seed_source_ids),
            "concepts": [concept.to_dict() for concept in self.concepts],
            "tracks": [track.to_dict() for track in self.tracks],
            "query_variants": [variant.to_dict() for variant in self.query_variants],
            "max_total_variants": self.max_total_variants,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def compile_general_query_plan(
    question: str,
    *,
    concepts: tuple[ConceptGroup, ...],
    tracks: tuple[SearchTrack, ...],
    domain_hint: str | None = None,
    frame_type: QueryFrameType = QueryFrameType.GENERIC,
    pico: PicoFrame | None = None,
    answer_dimensions: tuple[str, ...] = (),
    seed_source_ids: tuple[str, ...] = (),
    max_total_variants: int = 24,
) -> GeneralQueryPlan:
    """Validate a structured question decomposition and compile bounded query variants.

    The function never asks a model to decide how many searches to run.  It
    always emits the canonical (first) variant for every track, then allocates
    additional synonym variants round-robin until the global bound is reached.
    That policy prevents a synonym-rich early track from exhausting the budget
    and silently starving later research objectives.
    """

    _require_nonblank("question", question)
    if domain_hint is not None:
        _require_nonblank("domain_hint", domain_hint)
    _require_unique_nonblank("answer_dimensions", answer_dimensions)
    _require_unique_nonblank("seed_source_ids", seed_source_ids)

    if not concepts:
        raise ValueError("General query plan requires at least one concept.")
    if len(concepts) > MAX_CONCEPTS:
        raise ValueError(f"General query plan supports at most {MAX_CONCEPTS} concepts.")
    if not tracks:
        raise ValueError("General query plan requires at least one search track.")
    if len(tracks) > MAX_SEARCH_TRACKS:
        raise ValueError(
            f"General query plan supports at most {MAX_SEARCH_TRACKS} search tracks."
        )
    if not 1 <= max_total_variants <= MAX_TOTAL_VARIANTS:
        raise ValueError(
            f"max_total_variants must be between 1 and {MAX_TOTAL_VARIANTS}."
        )
    if max_total_variants < len(tracks):
        raise ValueError(
            "max_total_variants must be at least the number of search tracks so "
            "every track keeps one canonical query."
        )

    if frame_type is QueryFrameType.PICO and pico is None:
        raise ValueError("PICO framing was requested without a PicoFrame.")
    if frame_type is QueryFrameType.GENERIC and pico is not None:
        raise ValueError("PicoFrame may be supplied only when frame_type is PICO.")

    concept_by_id: dict[str, ConceptGroup] = {}
    for concept in concepts:
        if concept.concept_id in concept_by_id:
            raise ValueError(f"Duplicate concept_id: {concept.concept_id!r}.")
        concept_by_id[concept.concept_id] = concept

    track_ids: set[str] = set()
    per_track_queries: list[tuple[SearchTrack, tuple[tuple[str, tuple[str, ...]], ...]]] = []
    for track in tracks:
        if track.track_id in track_ids:
            raise ValueError(f"Duplicate track_id: {track.track_id!r}.")
        track_ids.add(track.track_id)

        unknown_concepts = [
            concept_id for concept_id in track.concept_ids if concept_id not in concept_by_id
        ]
        if unknown_concepts:
            raise ValueError(
                f"Search track {track.track_id!r} references unknown concept(s): "
                + ", ".join(unknown_concepts)
            )

        compiled = _compile_track_queries(track, concept_by_id)
        per_track_queries.append((track, compiled))

    selected: list[tuple[SearchTrack, str, tuple[str, ...]]] = []
    for track, queries in per_track_queries:
        query, chosen_terms = queries[0]
        selected.append((track, query, chosen_terms))

    next_index = [1] * len(per_track_queries)
    while len(selected) < max_total_variants:
        added = False
        for track_index, (track, queries) in enumerate(per_track_queries):
            if len(selected) >= max_total_variants:
                break
            index = next_index[track_index]
            if index >= len(queries):
                continue
            query, chosen_terms = queries[index]
            selected.append((track, query, chosen_terms))
            next_index[track_index] += 1
            added = True
        if not added:
            break

    per_track_variant_number: dict[str, int] = {}
    variants: list[QueryVariant] = []
    for track, query, chosen_terms in selected:
        number = per_track_variant_number.get(track.track_id, 0) + 1
        per_track_variant_number[track.track_id] = number
        variants.append(
            QueryVariant(
                variant_id=f"qv-{track.track_id}-{number:02d}",
                track_id=track.track_id,
                scope=track.scope,
                query=query,
                chosen_concept_terms=chosen_terms,
            )
        )

    return GeneralQueryPlan(
        schema_version=GENERAL_QUERY_PLAN_SCHEMA_VERSION,
        question=question,
        domain_hint=domain_hint,
        frame_type=frame_type,
        pico=pico,
        answer_dimensions=answer_dimensions,
        seed_source_ids=seed_source_ids,
        concepts=concepts,
        tracks=tracks,
        query_variants=tuple(variants),
        max_total_variants=max_total_variants,
    )


def _compile_track_queries(
    track: SearchTrack,
    concept_by_id: dict[str, ConceptGroup],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    concept_term_sets = tuple(concept_by_id[concept_id].terms for concept_id in track.concept_ids)
    queries: list[tuple[str, tuple[str, ...]]] = []
    seen_queries: set[str] = set()

    if not concept_term_sets:
        _append_track_query(
            track,
            (),
            queries=queries,
            seen_queries=seen_queries,
        )
        return tuple(queries)

    canonical_terms = tuple(terms[0] for terms in concept_term_sets)
    _append_track_query(
        track,
        canonical_terms,
        queries=queries,
        seen_queries=seen_queries,
    )

    max_term_count = max(len(terms) for terms in concept_term_sets)
    for synonym_index in range(1, max_term_count):
        for concept_index, terms in enumerate(concept_term_sets):
            if synonym_index >= len(terms):
                continue
            chosen = list(canonical_terms)
            chosen[concept_index] = terms[synonym_index]
            _append_track_query(
                track,
                tuple(chosen),
                queries=queries,
                seen_queries=seen_queries,
            )
            if len(queries) >= track.max_variants:
                return tuple(queries)

    combinations: Iterable[tuple[str, ...]] = product(*concept_term_sets)
    for chosen_terms in combinations:
        _append_track_query(
            track,
            chosen_terms,
            queries=queries,
            seen_queries=seen_queries,
        )
        if len(queries) >= track.max_variants:
            break

    if not queries:
        raise ValueError(f"Search track {track.track_id!r} produced no query variants.")
    return tuple(queries)


def _append_track_query(
    track: SearchTrack,
    chosen_terms: tuple[str, ...],
    *,
    queries: list[tuple[str, tuple[str, ...]]],
    seen_queries: set[str],
) -> None:
    query = " ".join((*chosen_terms, *track.fixed_terms))
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(
            f"Compiled query for track {track.track_id!r} exceeds "
            f"{MAX_QUERY_CHARACTERS} characters."
        )
    if query in seen_queries:
        return
    seen_queries.add(query)
    queries.append((query, chosen_terms))


def _require_nonblank(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank.")


def _require_identifier(name: str, value: str) -> None:
    _require_nonblank(name, value)
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} must not contain whitespace.")


def _require_nonblank_values(name: str, values: tuple[str, ...]) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{name} entries must not be blank.")


def _require_unique_nonblank(name: str, values: tuple[str, ...]) -> None:
    _require_nonblank_values(name, values)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} entries must be unique.")


__all__ = [
    "GENERAL_QUERY_PLAN_SCHEMA_VERSION",
    "MAX_CONCEPTS",
    "MAX_QUERY_CHARACTERS",
    "MAX_SEARCH_TRACKS",
    "MAX_SYNONYMS_PER_CONCEPT",
    "MAX_TOTAL_VARIANTS",
    "MAX_VARIANTS_PER_TRACK",
    "ConceptGroup",
    "EvidenceScope",
    "GeneralQueryPlan",
    "PicoFrame",
    "QueryFrameType",
    "QueryVariant",
    "SearchTrack",
    "compile_general_query_plan",
]
