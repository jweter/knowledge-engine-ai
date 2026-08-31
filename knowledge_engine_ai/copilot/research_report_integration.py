"""Safe integration seam from a completed Research Copilot run to Research Report v1.

`run_research_question` remains the authority for retrieval, grounded completion,
synthesis verification, and the Research ISA close gate. This module deliberately
runs *after* that result exists. It refuses to build a user-facing structured report
unless the underlying narrative passed the existing release gates, and it never
reconstructs provider/evidence provenance from narrative text.

The wrapper returns stable error codes instead of raising model/runtime failures into
Web. That keeps the already-verified ResearchQuestionResult usable if the optional
structured-report projection cannot be generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from knowledge_engine_ai.copilot.progress_report import ResearchProgressReport
from knowledge_engine_ai.copilot.research_report import (
    DEFAULT_RESEARCH_REPORT_MAX_TOKENS,
    ResearchReport,
    ResearchReportError,
    generate_research_report,
)
from knowledge_engine_ai.llm import LocalLLM, LocalLLMError
from knowledge_engine_ai.models import EvidenceReport


class ResearchResultForReport(Protocol):
    """Minimum completed-run surface needed to build a structured report."""

    @property
    def question(self) -> str: ...

    @property
    def narrative_releaseable(self) -> bool: ...

    @property
    def effective_evidence_report(self) -> EvidenceReport | None: ...

    @property
    def progress_report(self) -> ResearchProgressReport | None: ...


@dataclass(frozen=True)
class ResearchReportBuildResult:
    """Additive structured-report outcome that cannot invalidate the base run."""

    report: ResearchReport | None
    error_code: str | None

    @property
    def available(self) -> bool:
        return self.report is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "error_code": self.error_code,
            "report": self.report.to_dict() if self.report is not None else None,
        }


def build_research_report_for_result(
    result: ResearchResultForReport,
    llm: LocalLLM,
    *,
    answer_dimensions: tuple[str, ...] = (),
    max_tokens: int = DEFAULT_RESEARCH_REPORT_MAX_TOKENS,
    timeout_seconds: float | None = None,
) -> ResearchReportBuildResult:
    """Build Research Report v1 only from a releaseable completed research result.

    Failure is intentionally additive: the verified base research result survives and
    callers receive a stable reason code rather than an exception containing model,
    provider, filesystem, or deployment details.
    """

    if not result.narrative_releaseable:
        return ResearchReportBuildResult(report=None, error_code="base_answer_not_releaseable")

    evidence_report = result.effective_evidence_report
    if evidence_report is None:
        return ResearchReportBuildResult(report=None, error_code="evidence_report_unavailable")

    progress_report = result.progress_report
    if progress_report is None:
        return ResearchReportBuildResult(report=None, error_code="progress_report_unavailable")

    try:
        report = generate_research_report(
            result.question,
            evidence_report,
            progress_report,
            llm,
            answer_dimensions=answer_dimensions,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    except (ResearchReportError, LocalLLMError):
        return ResearchReportBuildResult(
            report=None, error_code="research_report_generation_failed"
        )

    return ResearchReportBuildResult(report=report, error_code=None)


__all__ = [
    "ResearchReportBuildResult",
    "ResearchResultForReport",
    "build_research_report_for_result",
]
