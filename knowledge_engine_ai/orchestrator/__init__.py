"""Research Copilot orchestration primitives."""

from __future__ import annotations

from knowledge_engine_ai.orchestrator.close_gate import (
    SessionCloseResult,
    attempt_session_close,
)
from knowledge_engine_ai.orchestrator.observability import (
    EventTrace,
    SessionTrace,
    build_session_trace,
    render_session_trace,
)
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    CONTRADICTION_SIGNAL_PHRASES,
    ExternalDiscoveryCallable,
    ParallelRetrievalResult,
    RetrievalBranchResult,
    build_contradiction_query,
    run_parallel_retrieval,
)
from knowledge_engine_ai.orchestrator.session_report import (
    SessionReport,
    SourcedClaim,
    build_session_report,
)
from knowledge_engine_ai.orchestrator.verification import (
    CITATION_PATTERN,
    VerificationResult,
    verify_synthesis,
)
from knowledge_engine_ai.orchestrator.workflow import (
    WorkflowResult,
    WorkflowStepResult,
    run_fixed_evidence_workflow,
)

__all__ = [
    "CITATION_PATTERN",
    "CONTRADICTION_SIGNAL_PHRASES",
    "EventTrace",
    "ExternalDiscoveryCallable",
    "ParallelRetrievalResult",
    "RetrievalBranchResult",
    "SessionCloseResult",
    "SessionReport",
    "SessionTrace",
    "SourcedClaim",
    "VerificationResult",
    "WorkflowResult",
    "WorkflowStepResult",
    "attempt_session_close",
    "build_contradiction_query",
    "build_session_report",
    "build_session_trace",
    "render_session_trace",
    "run_fixed_evidence_workflow",
    "run_parallel_retrieval",
    "verify_synthesis",
]
