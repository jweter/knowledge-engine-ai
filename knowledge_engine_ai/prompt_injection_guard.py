"""Deterministic quarantine for retrieved text shaped like a model directive.

`docs/INDUSTRY_REALITY_CHECK.md`'s "Add adversarial source/prompt-injection
evaluation" (P1): "Treat retrieved documents and provider metadata as
untrusted input. Test that source text cannot alter system policy or
evidence authority." `EvidenceRecord` fields (`claim_text`,
`result_summary`, `population`, `intervention`, `comparator`, `outcome`,
`uncertainty_notes`, `confidence_note`, `limitations`) and `RetrievedPaper`
metadata (`title`) are populated from `core`'s extraction of third-party
source documents and provider APIs -- an attacker who controls (or
manipulates) an acquired source controls that text.

This module never judges whether scientific content is *true*; `core`
already owns grounding/provenance, and this project's own verifier
(`orchestrator/verification.py`) deliberately stays structural rather than
linguistic. This module only recognizes text shaped like an instruction
aimed at an AI system -- role overrides, "ignore previous instructions",
chat-template control tokens -- and keeps it out of any prompt a caller
builds for `LocalLLM.generate`.

A flagged ("quarantined") record is never silently dropped. Callers must
still surface it to the reader, quoted verbatim and labeled, exactly as
this project already surfaces a missed qualifier
(`synthesis.ensure_required_evidence_coverage`) rather than hiding it.
Quarantine removes text from the model's input surface; it does not
remove evidence from the report.

Known limitation: these are literal/regex pattern checks, not a semantic
classifier. Obfuscation (zero-width characters, homoglyphs, translation,
splitting a trigger phrase across fields) can evade detection. This is a
deterministic first layer, not a claim that prompt injection is solved.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from knowledge_engine_ai.models import EvidenceRecord

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|preceding)\s+instructions?\b",
        r"\bdisregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|preceding)\s+instructions?\b",
        r"\bforget\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|preceding)\s+(instructions?|rules?)\b",
        r"\bnew\s+instructions?\s*:",
        r"\byou\s+are\s+now\s+(a|an)\b",
        r"\byour\s+(new\s+|only\s+)?(task|job|instruction)\s+is\s+(now\s+)?to\b",
        r"\b(system|assistant)\s*:\s*\S",
        r"<\|?\s*(system|im_start|im_end|endoftext)\s*\|?>",
        r"\[/?\s*(system|instructions?|inst)\s*\]",
        r"\bdo\s+not\s+cite\b",
        r"\bwithout\s+citing\s+(any\s+)?(source|evidence)\b",
        r"\boverride\s+(the\s+)?(system|previous)\s+(prompt|instructions?)\b",
        r"\brespond\s+only\s+with\b",
        r"\bact\s+as\s+(if\s+you\s+are\s+|a\s+)\b",
        r"\bstate\s+with\s+(100%|absolute|complete)\s+certainty\b",
    )
)

_RECORD_TEXT_FIELD_NAMES: tuple[str, ...] = (
    "claim_text",
    "population",
    "intervention",
    "comparator",
    "outcome",
    "result_summary",
    "uncertainty_notes",
    "confidence_note",
)


@dataclass(frozen=True)
class InjectionScanResult:
    """Which (if any) injection-shaped patterns a piece of text matched."""

    matched_patterns: tuple[str, ...]

    @property
    def is_suspect(self) -> bool:
        return bool(self.matched_patterns)


def scan_text_for_injection(text: str | None) -> InjectionScanResult:
    """Check one piece of untrusted text for a known injection shape."""

    if not text:
        return InjectionScanResult(matched_patterns=())
    matches = tuple(pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text))
    return InjectionScanResult(matched_patterns=matches)


def record_injection_matches(
    record: EvidenceRecord, *, extra_texts: Iterable[str | None] = ()
) -> tuple[str, ...]:
    """Union of injection-pattern matches across one record's untrusted text fields.

    `extra_texts` lets a caller fold in text that lives outside
    `EvidenceRecord` but is rendered alongside it in the same prompt (for
    example `RetrievedPaper.title`), so one record's quarantine decision
    accounts for everything a renderer actually puts in front of the model.

    Field access is defensive (`getattr(..., None)`): some existing tests
    exercise this code with a lightweight stand-in that only defines the
    fields its own scenario needs, not the full `EvidenceRecord` shape.
    """

    texts: list[str | None] = [getattr(record, name, None) for name in _RECORD_TEXT_FIELD_NAMES]
    texts.extend(getattr(record, "limitations", None) or ())
    texts.extend(extra_texts)

    matched: list[str] = []
    for text in texts:
        matched.extend(scan_text_for_injection(text).matched_patterns)
    return tuple(dict.fromkeys(matched))


def is_record_suspect(record: EvidenceRecord, *, extra_texts: Iterable[str | None] = ()) -> bool:
    return bool(record_injection_matches(record, extra_texts=extra_texts))


def partition_records(
    records: Iterable[EvidenceRecord],
) -> tuple[tuple[EvidenceRecord, ...], tuple[EvidenceRecord, ...]]:
    """Split records into (clean, quarantined) using each record's own text fields only.

    Use this when no extra per-record text (such as a paper title) needs to
    be folded into the suspicion check; otherwise call `is_record_suspect`
    directly with `extra_texts=`.
    """

    clean: list[EvidenceRecord] = []
    quarantined: list[EvidenceRecord] = []
    for record in records:
        (quarantined if is_record_suspect(record) else clean).append(record)
    return tuple(clean), tuple(quarantined)


__all__ = [
    "InjectionScanResult",
    "is_record_suspect",
    "partition_records",
    "record_injection_matches",
    "scan_text_for_injection",
]
