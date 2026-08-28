"""AI-O6: deterministic Skeptic/Verifier check for a synthesized narrative.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O6 milestone: "Add
independent verification. Success criterion: unsupported-claim and
missed-qualifier rate is lower than direct synthesis baseline." See
`docs/ai_o6_design.md` for the full plan this module implements.

`synthesis.py`'s `synthesize_answer` is the only place this project lets
a local LLM generate free text, strictly instructed (by prompt only) to
cite `[evidence_record_id]` after every claim and use nothing outside
the `EvidenceReport` it was given. This module is the check that
instruction was actually followed -- deterministic, no LLM verifying
another LLM, the same posture `core`'s `golden_map_grounding.py` already
established for a differently-shaped verification problem (a curated
golden-map record's `result_summary` against source-PDF text, rather
than a synthesized narrative against retrieved evidence).

Two checks, both structural or numeric, neither linguistic:

1. Hallucinated citations / ungrounded numbers -- every
   `[evidence_record_id]` the narrative cites must be a record actually
   present in the report; every numeric token the narrative states must
   appear in a field that the synthesis prompt explicitly supplies for a
   retrieved EvidenceRecord (`claim_text`, `result_summary`, `limitations`)
   or in the Evidence Quality/Claim Confidence values it permits the model
   to mention.
2. Missed qualifiers -- any record whose `evidence_direction` is
   `qualifies`/`contradicts`, or which carries a non-empty
   `limitations` list, that the narrative never cites at all.

Neither check inspects tone, emphasis, or whether a citation's
surrounding sentence fairly represents the record -- see the design
doc's "what this does not do" section for why that boundary is
deliberate, not a gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from knowledge_engine_ai.models import EvidenceRecord, EvidenceReport

CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_\-]+)\]")
"""Shared with `session_report.py` (AI-O7) -- both modules extract the
same `[evidence_record_id]` citation shape `synthesis.py`'s prompt
requires, so the pattern lives in one place rather than two copies that
could silently drift apart."""

_NUMBER_RE = re.compile(r"\d+\.\d+|\d+")
_QUALIFYING_DIRECTIONS = {"qualifies", "contradicts"}


@dataclass(frozen=True)
class VerificationResult:
    """One narrative's independent-verification outcome against its own `EvidenceReport`."""

    narrative: str
    hallucinated_citations: tuple[str, ...]
    ungrounded_numbers: tuple[str, ...]
    missed_qualifiers: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        """True only when neither check found anything to flag."""

        return not (
            self.hallucinated_citations or self.ungrounded_numbers or self.missed_qualifiers
        )


def verify_synthesis(narrative: str, report: EvidenceReport) -> VerificationResult:
    """Check a synthesized narrative against the `EvidenceReport` it was built from.

    Never raises on a narrative with problems -- flags them in the
    returned result. A caller (a future orchestrator step, or a human)
    decides what to do with a non-clean result; this function only
    reports what it found.
    """

    records_by_id = {
        record.evidence_record_id: record
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    }

    cited_ids = tuple(dict.fromkeys(CITATION_PATTERN.findall(narrative)))
    hallucinated = tuple(cited_id for cited_id in cited_ids if cited_id not in records_by_id)

    grounded_text = " ".join(
        text
        for record in records_by_id.values()
        for text in (
            record.claim_text,
            record.result_summary,
            *record.limitations,
        )
        if text
    )
    grounded_numbers = set(_NUMBER_RE.findall(grounded_text))
    for record in records_by_id.values():
        intelligence = record.evidence_intelligence
        if intelligence is None:
            continue
        # The synthesis prompt renders both scores on a fixed `/100` scale.
        grounded_numbers.add("100")
        grounded_numbers.add(str(intelligence.evidence_quality.score))
        if intelligence.claim_confidence.score is not None:
            grounded_numbers.add(str(intelligence.claim_confidence.score))
    # Strip citation brackets first -- "[ev-1]" otherwise contributes a
    # spurious numeric token ("1") that has nothing to do with a stated
    # statistic.
    narrative_without_citations = CITATION_PATTERN.sub(" ", narrative)
    narrative_numbers = _NUMBER_RE.findall(narrative_without_citations)
    ungrounded = tuple(
        dict.fromkeys(number for number in narrative_numbers if number not in grounded_numbers)
    )

    cited_id_set = set(cited_ids)
    missed = tuple(
        record_id
        for record_id, record in records_by_id.items()
        if record_id not in cited_id_set and _is_qualifying(record)
    )

    return VerificationResult(
        narrative=narrative,
        hallucinated_citations=hallucinated,
        ungrounded_numbers=ungrounded,
        missed_qualifiers=missed,
    )


def _is_qualifying(record: EvidenceRecord) -> bool:
    return record.evidence_direction in _QUALIFYING_DIRECTIONS or bool(record.limitations)
