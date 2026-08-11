"""AI-O3/AI-O5: the fixed-order orchestrator. See `workflow.py`/`parallel_retrieval.py`."""

from __future__ import annotations

from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    CONTRADICTION_SIGNAL_PHRASES,
    ExternalDiscoveryCallable,
    ParallelRetrievalResult,
    RetrievalBranchResult,
    build_contradiction_query,
    run_parallel_retrieval,
)
from knowledge_engine_ai.orchestrator.verification import (
    VerificationResult,
    verify_synthesis,
)
from knowledge_engine_ai.orchestrator.workflow import (
    WorkflowResult,
    WorkflowStepResult,
    run_fixed_evidence_workflow,
)

__all__ = [
    "CONTRADICTION_SIGNAL_PHRASES",
    "ExternalDiscoveryCallable",
    "ParallelRetrievalResult",
    "RetrievalBranchResult",
    "VerificationResult",
    "WorkflowResult",
    "WorkflowStepResult",
    "build_contradiction_query",
    "run_fixed_evidence_workflow",
    "run_parallel_retrieval",
    "verify_synthesis",
]
