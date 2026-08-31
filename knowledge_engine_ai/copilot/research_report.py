"""Structured Research Report v1 generation and deterministic validation.

Research Report v1 is a machine-readable answer projection over the same grounded
EvidenceReport and ResearchProgressReport facts the Research Copilot already owns.
The local model may perform judgment-layer synthesis, but it may not invent source
identities or provider facts. Model-proposed evidence IDs and answer dimensions are
strictly validated before deterministic provenance is attached.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from knowledge_engine_ai.copilot.progress_report import (
    ProviderStatusSummary,
    ResearchProgressReport,
)
from knowledge_engine_ai.llm import LocalLLM
from knowledge_engine_ai.models import EvidenceRecord, EvidenceReport, RetrievedPaper

RESEARCH_REPORT_SCHEMA_VERSION = 1
DEFAULT_RESEARCH_REPORT_MAX_TOKENS = 2200

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "bottom_line",
        "conclusion_rows",
        "narrative_sections",
        "missing_evidence",
        "direct_evidence_summary",
        "indirect_evidence_summary",
    }
)
_CONCLUSION_KEYS = frozenset(
    {
        "question_dimension",
        "conclusion",
        "certainty",
        "certainty_rationale",
        "supporting_evidence_ids",
        "contradicting_or_null_evidence_ids",
        "directness",
        "missing_direct_evidence",
    }
)
_SECTION_KEYS = frozenset({"heading", "body"})
_QUALIFYING_DIRECTIONS = frozenset({"qualifies", "contradicts"})
_HEALTHY_PROVIDER_OUTCOMES = frozenset({None, "success", "ok", "complete", "completed"})


class ResearchReportError(RuntimeError):
    """A model proposal could not become a valid structured Research Report."""


class ReportCertainty(StrEnum):
    """Small ordinal certainty vocabulary; never a fabricated numeric score."""

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    UNAVAILABLE = "unavailable"


class EvidenceDirectness(StrEnum):
    """How directly the cited evidence bears on one answer dimension."""

    DIRECT = "direct"
    CLASS_LEVEL = "class_level"
    INDIRECT_CONTEXT = "indirect_context"
    GUIDANCE = "guidance"
    MIXED = "mixed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ConclusionRow:
    """One answer dimension plus its grounded evidence relationships."""

    question_dimension: str
    conclusion: str
    certainty: ReportCertainty
    certainty_rationale: str
    supporting_evidence_ids: tuple[str, ...]
    contradicting_or_null_evidence_ids: tuple[str, ...]
    directness: EvidenceDirectness
    missing_direct_evidence: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "question_dimension": self.question_dimension,
            "conclusion": self.conclusion,
            "certainty": self.certainty.value,
            "certainty_rationale": self.certainty_rationale,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_or_null_evidence_ids": list(self.contradicting_or_null_evidence_ids),
            "directness": self.directness.value,
            "missing_direct_evidence": self.missing_direct_evidence,
        }


@dataclass(frozen=True)
class NarrativeSection:
    """One optional reader-facing report section, still source-cited prose."""

    heading: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return {"heading": self.heading, "body": self.body}


@dataclass(frozen=True)
class ResearchReportProposal:
    """Strictly parsed model-owned portion before deterministic provenance is attached."""

    schema_version: int
    bottom_line: str
    conclusion_rows: tuple[ConclusionRow, ...]
    narrative_sections: tuple[NarrativeSection, ...]
    missing_evidence: tuple[str, ...]
    direct_evidence_summary: str
    indirect_evidence_summary: str


@dataclass(frozen=True)
class ResearchReport:
    """Stable Research Report v1 contract consumed by Web and benchmarks."""

    schema_version: int
    question: str
    bottom_line: str
    conclusion_rows: tuple[ConclusionRow, ...]
    narrative_sections: tuple[NarrativeSection, ...]
    missing_evidence: tuple[str, ...]
    direct_evidence_summary: str
    indirect_evidence_summary: str
    provider_coverage_completeness: str | None
    degraded_providers: tuple[str, ...]
    provider_statuses: tuple[ProviderStatusSummary, ...]
    indexed_before_run_evidence_ids: tuple[str, ...]
    acquired_during_run_evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    session_id: str
    research_state: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "question": self.question,
            "bottom_line": self.bottom_line,
            "conclusion_rows": [row.to_dict() for row in self.conclusion_rows],
            "narrative_sections": [section.to_dict() for section in self.narrative_sections],
            "missing_evidence": list(self.missing_evidence),
            "direct_evidence_summary": self.direct_evidence_summary,
            "indirect_evidence_summary": self.indirect_evidence_summary,
            "provider_coverage_completeness": self.provider_coverage_completeness,
            "degraded_providers": list(self.degraded_providers),
            "provider_statuses": [status.to_dict() for status in self.provider_statuses],
            "indexed_before_run_evidence_ids": list(self.indexed_before_run_evidence_ids),
            "acquired_during_run_evidence_ids": list(self.acquired_during_run_evidence_ids),
            "limitations": list(self.limitations),
            "session_id": self.session_id,
            "research_state": self.research_state,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_research_report_prompt(
    question: str,
    evidence_report: EvidenceReport,
    *,
    answer_dimensions: tuple[str, ...] = (),
) -> str:
    """Build an evidence-only JSON synthesis prompt for Research Report v1."""

    if not question.strip():
        raise ValueError("question must not be blank.")

    evidence_blocks = [
        _render_evidence_record(paper, record)
        for paper in evidence_report.papers
        for record in paper.evidence_records
        if record.evidence_record_id and record.claim_text
    ]
    if not evidence_blocks:
        raise ResearchReportError("Research Report requires at least one grounded EvidenceRecord.")

    dimension_instruction = (
        "Use exactly these question_dimension values, once each, in this order:\n- "
        + "\n- ".join(answer_dimensions)
        if answer_dimensions
        else (
            "Identify a small set of distinct answer dimensions from the user's question. "
            "Do not collapse materially different timescales, outcomes, variants, or mechanisms."
        )
    )

    return f"""You are producing a structured evidence report for a researcher.
Use ONLY the EvidenceRecords listed below. Do not use model memory as evidence.
Do not invent citations, evidence IDs, provider results, study durations, effect sizes,
or confidence numbers. Evidence IDs are opaque identifiers: copy only IDs shown below.

Return EXACTLY ONE JSON object and no prose outside it.

Required schema:
{{
  "schema_version": 1,
  "bottom_line": "concise answer-first synthesis with [evidence-id] citations",
  "conclusion_rows": [
    {{
      "question_dimension": "...",
      "conclusion": "dimension-specific conclusion with [evidence-id] citations",
      "certainty": "high" | "moderate" | "low" | "unavailable",
      "certainty_rationale": "why, tied to the evidence and missing evidence",
      "supporting_evidence_ids": ["evidence-id"],
      "contradicting_or_null_evidence_ids": ["evidence-id"],
      "directness": "direct" | "class_level" | "indirect_context" |
        "guidance" | "mixed" | "unavailable",
      "missing_direct_evidence": "specific missing direct evidence" or null
    }}
  ],
  "narrative_sections": [
    {{"heading": "short heading", "body": "source-cited explanatory prose"}}
  ],
  "missing_evidence": ["specific evidence gap", "..."],
  "direct_evidence_summary": "what the most direct evidence establishes, with citations",
  "indirect_evidence_summary": "what indirect evidence can and cannot establish, with citations"
}}

Rules:
- Answer the user's question first; methodology comes later.
- {dimension_instruction}
- Every substantive factual statement must carry one or more [evidence-id] citations.
- Evidence ID arrays may contain only IDs shown below.
- Deliberately represent null, contradicting, and qualifying evidence; never hide it.
- Acute evidence must not be phrased as proof of a chronic or one-year effect.
- Distinguish direct evidence from broader class-level or indirect-context evidence.
- Use certainty=unavailable when the grounded evidence cannot support a responsible rating.
- Certainty is ordinal judgment, not a numeric score. Explain the rationale.
- If direct long-duration evidence is missing, state it explicitly rather than extrapolating.
- Do not claim a study design, duration, result, or limitation not present below.

User question:
{question}

EvidenceRecords:
{chr(10).join(evidence_blocks)}

JSON:"""


def parse_research_report_proposal(
    payload: object,
    *,
    known_evidence_ids: frozenset[str],
    required_dimensions: tuple[str, ...] = (),
    required_counter_evidence_ids: frozenset[str] = frozenset(),
) -> ResearchReportProposal:
    """Strictly parse and validate the model-owned portion of Research Report v1."""

    if not isinstance(payload, dict):
        raise ResearchReportError("Research Report proposal must be a JSON object.")
    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "Research Report proposal")

    schema_version = payload["schema_version"]
    if type(schema_version) is not int:
        raise ResearchReportError("schema_version must be an integer.")
    if schema_version != RESEARCH_REPORT_SCHEMA_VERSION:
        raise ResearchReportError(
            f"Unsupported Research Report schema version {schema_version}; "
            f"expected {RESEARCH_REPORT_SCHEMA_VERSION}."
        )

    rows = _parse_conclusion_rows(payload["conclusion_rows"], known_evidence_ids)
    if not rows:
        raise ResearchReportError("Research Report requires at least one conclusion row.")

    dimensions = tuple(row.question_dimension for row in rows)
    if len(set(dimensions)) != len(dimensions):
        raise ResearchReportError("conclusion_rows must use unique question_dimension values.")
    if required_dimensions and dimensions != required_dimensions:
        raise ResearchReportError(
            "conclusion_rows must match the caller-supplied answer dimensions exactly and in order."
        )

    represented_counter_ids = frozenset(
        evidence_id for row in rows for evidence_id in row.contradicting_or_null_evidence_ids
    )
    missing_counter_ids = required_counter_evidence_ids - represented_counter_ids
    if missing_counter_ids:
        raise ResearchReportError(
            "Research Report omitted required qualifying/counter-evidence ID(s): "
            + ", ".join(sorted(missing_counter_ids))
        )

    return ResearchReportProposal(
        schema_version=schema_version,
        bottom_line=_required_string(payload["bottom_line"], "bottom_line"),
        conclusion_rows=rows,
        narrative_sections=_parse_sections(payload["narrative_sections"]),
        missing_evidence=_string_tuple(payload["missing_evidence"], "missing_evidence"),
        direct_evidence_summary=_required_string(
            payload["direct_evidence_summary"], "direct_evidence_summary"
        ),
        indirect_evidence_summary=_required_string(
            payload["indirect_evidence_summary"], "indirect_evidence_summary"
        ),
    )


def generate_research_report(
    question: str,
    evidence_report: EvidenceReport,
    progress_report: ResearchProgressReport,
    llm: LocalLLM,
    *,
    answer_dimensions: tuple[str, ...] = (),
    max_tokens: int = DEFAULT_RESEARCH_REPORT_MAX_TOKENS,
    timeout_seconds: float | None = None,
) -> ResearchReport:
    """Generate, validate, and attach deterministic provenance to Research Report v1."""

    known_ids = frozenset(
        record.evidence_record_id
        for paper in evidence_report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    )
    required_counter_ids = frozenset(
        record.evidence_record_id
        for paper in evidence_report.papers
        for record in paper.evidence_records
        if record.evidence_record_id and _requires_counter_coverage(record)
    )

    raw_output = llm.generate(
        build_research_report_prompt(
            question,
            evidence_report,
            answer_dimensions=answer_dimensions,
        ),
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    payload_text = _extract_json_object(raw_output)
    if payload_text is None:
        raise ResearchReportError(
            f"Model output contained no complete JSON object.\nRaw output:\n{raw_output}"
        )
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ResearchReportError(
            f"Model output was not valid JSON: {exc}\nRaw output:\n{raw_output}"
        ) from exc

    proposal = parse_research_report_proposal(
        payload,
        known_evidence_ids=known_ids,
        required_dimensions=answer_dimensions,
        required_counter_evidence_ids=required_counter_ids,
    )

    return ResearchReport(
        schema_version=RESEARCH_REPORT_SCHEMA_VERSION,
        question=question,
        bottom_line=proposal.bottom_line,
        conclusion_rows=proposal.conclusion_rows,
        narrative_sections=proposal.narrative_sections,
        missing_evidence=proposal.missing_evidence,
        direct_evidence_summary=proposal.direct_evidence_summary,
        indirect_evidence_summary=proposal.indirect_evidence_summary,
        provider_coverage_completeness=progress_report.provider_coverage_completeness,
        degraded_providers=_degraded_provider_names(progress_report),
        provider_statuses=progress_report.provider_statuses,
        indexed_before_run_evidence_ids=progress_report.indexed_evidence_record_ids,
        acquired_during_run_evidence_ids=progress_report.newly_acquired_evidence_record_ids,
        limitations=progress_report.limitations,
        session_id=progress_report.session_id,
        research_state=progress_report.research_state.value,
    )


def _parse_conclusion_rows(
    value: object,
    known_evidence_ids: frozenset[str],
) -> tuple[ConclusionRow, ...]:
    if not isinstance(value, list):
        raise ResearchReportError("conclusion_rows must be a JSON array.")

    rows: list[ConclusionRow] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResearchReportError(f"conclusion_rows[{index}] must be an object.")
        _require_exact_keys(item, _CONCLUSION_KEYS, f"conclusion_rows[{index}]")

        certainty = _enum_value(
            ReportCertainty,
            item["certainty"],
            f"conclusion_rows[{index}].certainty",
        )
        directness = _enum_value(
            EvidenceDirectness,
            item["directness"],
            f"conclusion_rows[{index}].directness",
        )
        supporting = _evidence_id_tuple(
            item["supporting_evidence_ids"],
            f"conclusion_rows[{index}].supporting_evidence_ids",
            known_evidence_ids,
        )
        counter = _evidence_id_tuple(
            item["contradicting_or_null_evidence_ids"],
            f"conclusion_rows[{index}].contradicting_or_null_evidence_ids",
            known_evidence_ids,
        )

        overlap = set(supporting) & set(counter)
        if overlap:
            raise ResearchReportError(
                f"conclusion_rows[{index}] classifies the same evidence ID as both supporting "
                f"and contradicting/null: {', '.join(sorted(overlap))}"
            )
        if certainty is not ReportCertainty.UNAVAILABLE and not (supporting or counter):
            raise ResearchReportError(
                f"conclusion_rows[{index}] assigns certainty without any grounded evidence IDs."
            )

        missing_direct = item["missing_direct_evidence"]
        if missing_direct is not None and not isinstance(missing_direct, str):
            raise ResearchReportError(
                f"conclusion_rows[{index}].missing_direct_evidence must be a string or null."
            )
        if isinstance(missing_direct, str) and not missing_direct.strip():
            raise ResearchReportError(
                f"conclusion_rows[{index}].missing_direct_evidence must not be blank."
            )

        rows.append(
            ConclusionRow(
                question_dimension=_required_string(
                    item["question_dimension"],
                    f"conclusion_rows[{index}].question_dimension",
                ),
                conclusion=_required_string(
                    item["conclusion"],
                    f"conclusion_rows[{index}].conclusion",
                ),
                certainty=certainty,
                certainty_rationale=_required_string(
                    item["certainty_rationale"],
                    f"conclusion_rows[{index}].certainty_rationale",
                ),
                supporting_evidence_ids=supporting,
                contradicting_or_null_evidence_ids=counter,
                directness=directness,
                missing_direct_evidence=missing_direct,
            )
        )
    return tuple(rows)


def _parse_sections(value: object) -> tuple[NarrativeSection, ...]:
    if not isinstance(value, list):
        raise ResearchReportError("narrative_sections must be a JSON array.")

    sections: list[NarrativeSection] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResearchReportError(f"narrative_sections[{index}] must be an object.")
        _require_exact_keys(item, _SECTION_KEYS, f"narrative_sections[{index}]")
        sections.append(
            NarrativeSection(
                heading=_required_string(
                    item["heading"],
                    f"narrative_sections[{index}].heading",
                ),
                body=_required_string(
                    item["body"],
                    f"narrative_sections[{index}].body",
                ),
            )
        )
    return tuple(sections)


def _evidence_id_tuple(
    value: object,
    field_name: str,
    known_evidence_ids: frozenset[str],
) -> tuple[str, ...]:
    evidence_ids = _string_tuple(value, field_name)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ResearchReportError(f"{field_name} must not contain duplicate IDs.")

    unknown = set(evidence_ids) - known_evidence_ids
    if unknown:
        raise ResearchReportError(
            f"{field_name} contains unknown evidence ID(s): {', '.join(sorted(unknown))}"
        )
    return evidence_ids


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ResearchReportError(f"{field_name} must be a JSON array.")
    return tuple(
        _required_string(item, f"{field_name}[{index}]") for index, item in enumerate(value)
    )


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchReportError(f"{field_name} must be a nonblank string.")
    return value


def _require_exact_keys(
    value: dict[object, object],
    expected: frozenset[str],
    label: str,
) -> None:
    keys = set(value)
    missing = expected - keys
    unknown = keys - expected
    if missing:
        raise ResearchReportError(
            f"{label} is missing required field(s): {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ResearchReportError(
            f"{label} contains unsupported field(s): "
            + ", ".join(sorted(str(key) for key in unknown))
        )


def _enum_value[T: StrEnum](
    enum_type: type[T],
    value: object,
    field_name: str,
) -> T:
    if not isinstance(value, str):
        raise ResearchReportError(f"{field_name} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ResearchReportError(
            f"{field_name} has unsupported value {value!r}; expected one of: {allowed}."
        ) from exc


def _render_evidence_record(paper: RetrievedPaper, record: EvidenceRecord) -> str:
    assert record.evidence_record_id is not None
    assert record.claim_text is not None

    fields = [
        f"id={record.evidence_record_id}",
        f"paper_title={paper.title}",
        f"paper_year={paper.year}",
        f"claim={record.claim_text}",
    ]
    optional_fields = (
        ("evidence_direction", record.evidence_direction),
        ("population", record.population),
        ("intervention_or_exposure", record.intervention),
        ("comparator", record.comparator),
        ("outcome", record.outcome),
        ("result", record.result_summary),
        ("uncertainty", record.uncertainty_notes),
        ("confidence_note", record.confidence_note),
    )
    fields.extend(f"{name}={value}" for name, value in optional_fields if value)
    if record.limitations:
        fields.append("limitations=" + "; ".join(record.limitations))
    return " | ".join(fields)


def _requires_counter_coverage(record: EvidenceRecord) -> bool:
    return record.evidence_direction in _QUALIFYING_DIRECTIONS or bool(record.limitations)


def _degraded_provider_names(progress_report: ResearchProgressReport) -> tuple[str, ...]:
    if not progress_report.provider_degraded:
        return ()
    return tuple(
        status.provider
        for status in progress_report.provider_statuses
        if status.attempted and status.outcome not in _HEALTHY_PROVIDER_OUTCOMES
    )


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced top-level JSON object from model output."""

    start = text.find("{")
    if start < 0:
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
    "ConclusionRow",
    "DEFAULT_RESEARCH_REPORT_MAX_TOKENS",
    "EvidenceDirectness",
    "NarrativeSection",
    "RESEARCH_REPORT_SCHEMA_VERSION",
    "ReportCertainty",
    "ResearchReport",
    "ResearchReportError",
    "ResearchReportProposal",
    "build_research_report_prompt",
    "generate_research_report",
    "parse_research_report_proposal",
]
