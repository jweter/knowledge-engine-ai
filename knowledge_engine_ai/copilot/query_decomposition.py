"""Validated arbitrary-question decomposition for GQR-2 query planning.

The local model may propose search concepts, synonyms, answer dimensions, and
search tracks.  It does not execute a provider, cite a source, or decide the
scientific answer.  Every proposal is parsed through strict structural checks
and then compiled by :mod:`knowledge_engine_ai.general_query_plan`, whose hard
bounds remain authoritative.

Source identifiers are deliberately absent from the model-owned schema.  Known
PMIDs/DOIs may be supplied only by the caller as discovery seeds when compiling
the validated proposal.  This prevents a planning model from fabricating a
source identity and having that fabrication acquire special status downstream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from knowledge_engine_ai.general_query_plan import (
    ConceptGroup,
    EvidenceScope,
    GeneralQueryPlan,
    PicoFrame,
    QueryFrameType,
    SearchTrack,
    compile_general_query_plan,
)
from knowledge_engine_ai.llm import LocalLLM

QUERY_DECOMPOSITION_SCHEMA_VERSION = 1
DEFAULT_QUERY_DECOMPOSITION_MAX_TOKENS = 2000

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "domain_hint",
        "frame_type",
        "pico",
        "answer_dimensions",
        "concepts",
        "tracks",
    }
)
_CONCEPT_KEYS = frozenset({"concept_id", "canonical_term", "synonyms"})
_TRACK_KEYS = frozenset(
    {"track_id", "purpose", "scope", "concept_ids", "fixed_terms", "max_variants"}
)
_PICO_KEYS = frozenset({"population", "intervention", "comparator", "outcomes"})


class QueryDecompositionError(RuntimeError):
    """The model proposal could not become a validated general query plan."""


@dataclass(frozen=True)
class QueryDecomposition:
    """Model-proposed search structure after strict parsing, before compilation."""

    schema_version: int
    domain_hint: str | None
    frame_type: QueryFrameType
    pico: PicoFrame | None
    answer_dimensions: tuple[str, ...]
    concepts: tuple[ConceptGroup, ...]
    tracks: tuple[SearchTrack, ...]

    def __post_init__(self) -> None:
        if self.schema_version != QUERY_DECOMPOSITION_SCHEMA_VERSION:
            raise QueryDecompositionError(
                f"Unsupported query-decomposition schema version {self.schema_version}; "
                f"expected {QUERY_DECOMPOSITION_SCHEMA_VERSION}."
            )
        if self.domain_hint is not None and not self.domain_hint.strip():
            raise QueryDecompositionError("domain_hint must be null or a nonblank string.")
        if self.frame_type is QueryFrameType.PICO and self.pico is None:
            raise QueryDecompositionError("PICO framing requires an explicit pico object.")
        if self.frame_type is QueryFrameType.GENERIC and self.pico is not None:
            raise QueryDecompositionError("Generic framing must not carry a pico object.")


def build_query_decomposition_prompt(question: str) -> str:
    """Build the strict local-model prompt for arbitrary-question search planning."""

    if not question.strip():
        raise ValueError("question must not be blank.")

    return f"""You are planning literature searches for a research system.
Do NOT answer the research question. Do NOT state scientific conclusions.
Do NOT invent citations, PMIDs, DOIs, paper titles, authors, or provider results.
Your output is only a bounded search decomposition that will be validated before use.

Return EXACTLY ONE JSON object and no prose outside it.

Required schema:
{{
  "schema_version": 1,
  "domain_hint": "short_lowercase_domain_label" or null,
  "frame_type": "generic" or "pico",
  "pico": null OR {{
    "population": "...",
    "intervention": "...",
    "comparator": "..." or null,
    "outcomes": ["..."]
  }},
  "answer_dimensions": ["short_machine_readable_dimension", "..."],
  "concepts": [
    {{
      "concept_id": "short_identifier",
      "canonical_term": "search term",
      "synonyms": ["bounded alias", "..."]
    }}
  ],
  "tracks": [
    {{
      "track_id": "short_identifier",
      "purpose": "what this search track is intended to find",
      "scope": "direct" | "class_level" | "indirect_context" | "guidance" | "counterevidence",
      "concept_ids": ["concept_id", "..."],
      "fixed_terms": ["optional literal search term", "..."],
      "max_variants": 1
    }}
  ]
}}

Rules:
- Preserve the meaning of the user's question; search terms are not factual claims.
- Use 1-16 concepts, no more than 8 synonyms per concept.
- Use 1-16 search tracks; each track must use at least one concept or fixed term.
- Keep max_variants between 1 and 12; prefer 2-4 unless a track genuinely needs more.
- Every track may reference only concept_ids declared in this same object.
- Use scope="direct" for the exact exposure/entity/comparison in the question.
- Use scope="class_level" only for a broader but still closely related class.
- Use scope="indirect_context" for evidence that can inform but cannot directly prove the main claim.
- Use scope="guidance" for measurement, methods, or professional guidance searches.
- Use scope="counterevidence" for null, negative, contradictory, or tolerance findings when relevant.
- Keep answer_dimensions distinct when the question contains materially different outcomes, timescales, variants, or mechanisms.
- Default to frame_type="generic". Use PICO only when the question is genuinely a clinical population/intervention/comparator/outcome question. Never force PICO onto chemistry, materials science, physics, astronomy, machine learning, or general biology.
- Do not include provider names or source identifiers. Provider selection and known seed sources are caller-owned.

User question:
{question}

JSON:"""


def parse_query_decomposition(payload: object) -> QueryDecomposition:
    """Strictly parse one model proposal into typed query-planning objects."""

    if not isinstance(payload, dict):
        raise QueryDecompositionError("Query decomposition must be a JSON object.")

    keys = set(payload)
    missing = _TOP_LEVEL_KEYS - keys
    unknown = keys - _TOP_LEVEL_KEYS
    if missing:
        raise QueryDecompositionError(
            "Query decomposition is missing required field(s): " + ", ".join(sorted(missing))
        )
    if unknown:
        raise QueryDecompositionError(
            "Query decomposition contains unsupported field(s): " + ", ".join(sorted(unknown))
        )

    schema_version = payload["schema_version"]
    if type(schema_version) is not int:
        raise QueryDecompositionError("schema_version must be an integer.")

    domain_hint_value = payload["domain_hint"]
    if domain_hint_value is not None and not isinstance(domain_hint_value, str):
        raise QueryDecompositionError("domain_hint must be a string or null.")

    frame_type_value = payload["frame_type"]
    if not isinstance(frame_type_value, str):
        raise QueryDecompositionError("frame_type must be a string.")
    try:
        frame_type = QueryFrameType(frame_type_value)
    except ValueError as exc:
        raise QueryDecompositionError(
            f"Unsupported frame_type {frame_type_value!r}; expected 'generic' or 'pico'."
        ) from exc

    pico = _parse_pico(payload["pico"])
    answer_dimensions = _string_tuple(payload["answer_dimensions"], "answer_dimensions")
    concepts = _parse_concepts(payload["concepts"])
    tracks = _parse_tracks(payload["tracks"])

    return QueryDecomposition(
        schema_version=schema_version,
        domain_hint=domain_hint_value,
        frame_type=frame_type,
        pico=pico,
        answer_dimensions=answer_dimensions,
        concepts=concepts,
        tracks=tracks,
    )


def compile_query_plan_from_decomposition(
    question: str,
    decomposition: QueryDecomposition,
    *,
    seed_source_ids: tuple[str, ...] = (),
    max_total_variants: int = 24,
) -> GeneralQueryPlan:
    """Compile one validated proposal through the deterministic GQR-2 compiler."""

    try:
        return compile_general_query_plan(
            question,
            concepts=decomposition.concepts,
            tracks=decomposition.tracks,
            domain_hint=decomposition.domain_hint,
            frame_type=decomposition.frame_type,
            pico=decomposition.pico,
            answer_dimensions=decomposition.answer_dimensions,
            seed_source_ids=seed_source_ids,
            max_total_variants=max_total_variants,
        )
    except ValueError as exc:
        raise QueryDecompositionError(f"Validated proposal could not compile: {exc}") from exc


def query_plan_from_question(
    question: str,
    llm: LocalLLM,
    *,
    seed_source_ids: tuple[str, ...] = (),
    max_total_variants: int = 24,
    max_tokens: int = DEFAULT_QUERY_DECOMPOSITION_MAX_TOKENS,
) -> GeneralQueryPlan:
    """Ask a local model for search structure, validate it, and compile a bounded plan.

    The model never supplies `seed_source_ids`; caller-owned known identities are
    appended only after model output has passed parsing.  No retries or automatic
    repairs are attempted.  A malformed or out-of-bounds proposal fails closed.
    """

    prompt = build_query_decomposition_prompt(question)
    raw_output = llm.generate(prompt, max_tokens=max_tokens)
    payload_text = _extract_json_object(raw_output)
    if payload_text is None:
        raise QueryDecompositionError(
            f"Model output contained no complete JSON object.\nRaw output:\n{raw_output}"
        )

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise QueryDecompositionError(
            f"Model output was not valid JSON: {exc}\nRaw output:\n{raw_output}"
        ) from exc

    try:
        decomposition = parse_query_decomposition(payload)
        return compile_query_plan_from_decomposition(
            question,
            decomposition,
            seed_source_ids=seed_source_ids,
            max_total_variants=max_total_variants,
        )
    except QueryDecompositionError as exc:
        raise QueryDecompositionError(f"{exc}\nRaw output:\n{raw_output}") from exc


def _parse_pico(value: object) -> PicoFrame | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise QueryDecompositionError("pico must be an object or null.")
    _require_exact_keys(value, _PICO_KEYS, "pico")

    population = _required_string(value["population"], "pico.population")
    intervention = _required_string(value["intervention"], "pico.intervention")
    comparator_value = value["comparator"]
    if comparator_value is not None and not isinstance(comparator_value, str):
        raise QueryDecompositionError("pico.comparator must be a string or null.")
    outcomes = _string_tuple(value["outcomes"], "pico.outcomes")
    try:
        return PicoFrame(
            population=population,
            intervention=intervention,
            comparator=comparator_value,
            outcomes=outcomes,
        )
    except ValueError as exc:
        raise QueryDecompositionError(f"Invalid pico object: {exc}") from exc


def _parse_concepts(value: object) -> tuple[ConceptGroup, ...]:
    if not isinstance(value, list):
        raise QueryDecompositionError("concepts must be a JSON array.")
    concepts: list[ConceptGroup] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise QueryDecompositionError(f"concepts[{index}] must be an object.")
        _require_exact_keys(item, _CONCEPT_KEYS, f"concepts[{index}]")
        try:
            concepts.append(
                ConceptGroup(
                    concept_id=_required_string(
                        item["concept_id"], f"concepts[{index}].concept_id"
                    ),
                    canonical_term=_required_string(
                        item["canonical_term"], f"concepts[{index}].canonical_term"
                    ),
                    synonyms=_string_tuple(item["synonyms"], f"concepts[{index}].synonyms"),
                )
            )
        except ValueError as exc:
            raise QueryDecompositionError(f"Invalid concepts[{index}]: {exc}") from exc
    return tuple(concepts)


def _parse_tracks(value: object) -> tuple[SearchTrack, ...]:
    if not isinstance(value, list):
        raise QueryDecompositionError("tracks must be a JSON array.")
    tracks: list[SearchTrack] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise QueryDecompositionError(f"tracks[{index}] must be an object.")
        _require_exact_keys(item, _TRACK_KEYS, f"tracks[{index}]")
        scope_value = item["scope"]
        if not isinstance(scope_value, str):
            raise QueryDecompositionError(f"tracks[{index}].scope must be a string.")
        try:
            scope = EvidenceScope(scope_value)
        except ValueError as exc:
            raise QueryDecompositionError(
                f"tracks[{index}].scope has unsupported value {scope_value!r}."
            ) from exc
        max_variants = item["max_variants"]
        if type(max_variants) is not int:
            raise QueryDecompositionError(f"tracks[{index}].max_variants must be an integer.")
        try:
            tracks.append(
                SearchTrack(
                    track_id=_required_string(item["track_id"], f"tracks[{index}].track_id"),
                    purpose=_required_string(item["purpose"], f"tracks[{index}].purpose"),
                    scope=scope,
                    concept_ids=_string_tuple(item["concept_ids"], f"tracks[{index}].concept_ids"),
                    fixed_terms=_string_tuple(item["fixed_terms"], f"tracks[{index}].fixed_terms"),
                    max_variants=max_variants,
                )
            )
        except ValueError as exc:
            raise QueryDecompositionError(f"Invalid tracks[{index}]: {exc}") from exc
    return tuple(tracks)


def _require_exact_keys(value: dict[object, object], expected: frozenset[str], label: str) -> None:
    keys = set(value)
    missing = expected - keys
    unknown = keys - expected
    if missing:
        raise QueryDecompositionError(
            f"{label} is missing required field(s): " + ", ".join(sorted(missing))
        )
    if unknown:
        raise QueryDecompositionError(
            f"{label} contains unsupported field(s): "
            + ", ".join(sorted(str(key) for key in unknown))
        )


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QueryDecompositionError(f"{label} must be a nonblank string.")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise QueryDecompositionError(f"{label} must be a JSON array of strings.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise QueryDecompositionError(f"{label}[{index}] must be a nonblank string.")
        result.append(item)
    return tuple(result)


def _extract_json_object(text: str) -> str | None:
    """Return the first brace-balanced JSON-like object, tolerating model framing prose."""

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


__all__ = [
    "DEFAULT_QUERY_DECOMPOSITION_MAX_TOKENS",
    "QUERY_DECOMPOSITION_SCHEMA_VERSION",
    "QueryDecomposition",
    "QueryDecompositionError",
    "build_query_decomposition_prompt",
    "compile_query_plan_from_decomposition",
    "parse_query_decomposition",
    "query_plan_from_question",
]
