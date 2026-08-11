from __future__ import annotations

from knowledge_engine_ai.doctor import (
    Capability,
    CapabilityStatus,
    disabled_capability,
    ollama_generation_probe,
    run_doctor,
)
from knowledge_engine_ai.llm import LocalLLMError


class FakeLLM:
    def __init__(self, response: str = "OK", error: LocalLLMError | None = None) -> None:
        self._response = response
        self._error = error

    def generate(self, prompt: str, *, max_tokens: int = 400) -> str:
        del prompt, max_tokens
        if self._error is not None:
            raise self._error
        return self._response


def test_ollama_generation_probe_verified_on_expected_response() -> None:
    result = ollama_generation_probe(FakeLLM())

    assert result.status is CapabilityStatus.VERIFIED


def test_ollama_generation_probe_unavailable_on_transport_error() -> None:
    result = ollama_generation_probe(FakeLLM(error=LocalLLMError("offline")))

    assert result.status is CapabilityStatus.UNAVAILABLE
    assert "offline" in result.evidence


def test_ollama_generation_probe_degraded_on_unexpected_output() -> None:
    result = ollama_generation_probe(FakeLLM(response="probably OK"))

    assert result.status is CapabilityStatus.DEGRADED


def test_disabled_capability_is_distinct_from_unavailable() -> None:
    result = disabled_capability("cloud_reasoner", "Cloud inference is intentionally disabled.")

    assert result == Capability(
        name="cloud_reasoner",
        status=CapabilityStatus.DISABLED,
        evidence="Cloud inference is intentionally disabled.",
    )


def test_doctor_keeps_running_when_one_probe_raises() -> None:
    def good_probe() -> Capability:
        return Capability("database", CapabilityStatus.VERIFIED, "SQLite opened successfully.")

    def broken_probe() -> Capability:
        raise RuntimeError("boom")

    results = run_doctor((good_probe, broken_probe))

    assert results[0].status is CapabilityStatus.VERIFIED
    assert results[1].name == "broken_probe"
    assert results[1].status is CapabilityStatus.DEGRADED
    assert "RuntimeError" in results[1].evidence
