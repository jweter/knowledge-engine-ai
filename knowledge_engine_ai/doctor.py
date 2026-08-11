"""Live capability reporting for the Research Copilot.

The Doctor distinguishes a capability that is verified, degraded, unavailable, or
intentionally disabled. Callers should surface these states rather than allowing an
orchestrator to pretend a configured capability exists when it is broken or off.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from knowledge_engine_ai.llm import LocalLLM, LocalLLMError


class CapabilityStatus(StrEnum):
    VERIFIED = "verified"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Capability:
    """One inspectable capability-health observation."""

    name: str
    status: CapabilityStatus
    evidence: str


CapabilityProbe = Callable[[], Capability]


def run_doctor(probes: tuple[CapabilityProbe, ...]) -> tuple[Capability, ...]:
    """Run independent capability probes without letting one failure hide others."""

    reports: list[Capability] = []
    for probe in probes:
        try:
            reports.append(probe())
        except Exception as exc:  # noqa: BLE001 - Doctor must report, not crash the whole scan.
            reports.append(
                Capability(
                    name=getattr(probe, "__name__", "unknown_probe"),
                    status=CapabilityStatus.DEGRADED,
                    evidence=f"Probe raised {type(exc).__name__}: {exc}",
                )
            )
    return tuple(reports)


def ollama_generation_probe(
    llm: LocalLLM, *, capability_name: str = "local_generation"
) -> Capability:
    """Verify that the configured local model can complete a minimal generation."""

    try:
        response = llm.generate("Reply with exactly OK.", max_tokens=8)
    except LocalLLMError as exc:
        return Capability(
            name=capability_name,
            status=CapabilityStatus.UNAVAILABLE,
            evidence=str(exc),
        )

    if response.strip().upper() != "OK":
        return Capability(
            name=capability_name,
            status=CapabilityStatus.DEGRADED,
            evidence=f"Local generation returned unexpected probe response: {response!r}",
        )

    return Capability(
        name=capability_name,
        status=CapabilityStatus.VERIFIED,
        evidence="Configured local model completed the deterministic OK probe.",
    )


def disabled_capability(name: str, reason: str) -> Capability:
    """Represent an intentionally unavailable capability without calling it broken."""

    return Capability(name=name, status=CapabilityStatus.DISABLED, evidence=reason)


__all__ = [
    "Capability",
    "CapabilityProbe",
    "CapabilityStatus",
    "disabled_capability",
    "ollama_generation_probe",
    "run_doctor",
]
