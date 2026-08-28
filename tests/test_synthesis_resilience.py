from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from knowledge_engine_ai.llm import LocalLLMError
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.verification import verify_synthesis
from knowledge_engine_ai.synthesis import build_synthesis_prompt, synthesize_answer


class _FakeLLM:
    def __init__(self, response: str | None = None, *, error: str | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del prompt, max_tokens, timeout_seconds
        self.calls += 1
        if self.error is not None:
            raise LocalLLMError(self.error)
        assert self.response is not None
        return self.response


def _report() -> EvidenceReport:
    records = [
        SimpleNamespace(
            evidence_record_id="ev-support",
            claim_text="Music increased time to exhaustion by 8%.",
            evidence_direction="supports",
            result_summary="Time to exhaustion increased by 8%.",
            limitations=[],
            evidence_intelligence=None,
        ),
        SimpleNamespace(
            evidence_record_id="ev-qualifier",
            claim_text="The observed benefit was not significant in the low-intensity subgroup.",
            evidence_direction="qualifies",
            result_summary="The low-intensity subgroup showed no significant difference.",
            limitations=["The subgroup sample was small."],
            evidence_intelligence=None,
        ),
    ]
    paper = SimpleNamespace(evidence_records=records)
    return cast(
        EvidenceReport,
        SimpleNamespace(
            question="Does music improve exercise endurance?",
            papers=[paper],
        ),
    )


def test_prompt_names_mandatory_qualifier_citations() -> None:
    prompt = build_synthesis_prompt(_report())

    assert "Mandatory qualification citations: [ev-qualifier]" in prompt
    assert "final answer is incomplete" in prompt


def test_zero_citation_model_output_falls_back_to_complete_evidence_summary() -> None:
    answer = synthesize_answer(
        _report(),
        _FakeLLM("Music appears to improve endurance."),
    )

    assert answer is not None
    assert answer.startswith("Evidence-only summary (deterministic fallback):")
    assert "[ev-support]" in answer
    assert "[ev-qualifier]" in answer
    assert "The subgroup sample was small." in answer
    assert verify_synthesis(answer, _report()).is_clean is True


def test_cited_model_answer_is_not_repaired_before_verification() -> None:
    model_answer = "Music increased time to exhaustion by 8% [ev-support]."

    answer = synthesize_answer(_report(), _FakeLLM(model_answer))

    assert answer == model_answer
    verification = verify_synthesis(answer, _report())
    assert verification.missed_qualifiers == ("ev-qualifier",)
    assert verification.is_clean is False


def test_unknown_citation_is_preserved_for_verifier_to_reject() -> None:
    model_answer = "Music improves endurance [ev-invented]."

    answer = synthesize_answer(_report(), _FakeLLM(model_answer))

    assert answer == model_answer
    verification = verify_synthesis(answer, _report())
    assert verification.hallucinated_citations == ("ev-invented",)
    assert verification.is_clean is False


def test_local_model_failure_uses_deterministic_grounded_fallback() -> None:
    llm = _FakeLLM(error="model timed out")

    answer = synthesize_answer(_report(), llm, timeout_seconds=1.0)

    assert llm.calls == 1
    assert answer is not None
    assert "[ev-support]" in answer
    assert "[ev-qualifier]" in answer
    assert verify_synthesis(answer, _report()).is_clean is True
