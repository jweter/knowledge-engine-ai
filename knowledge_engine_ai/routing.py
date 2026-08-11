"""Provider-neutral, privacy-aware model routing policy.

Research workflows select an abstract capability role, never a model brand.
Provider identity is a deployment concern. The policy is deliberately local-first
and cloud-deny by default so adding a hosted provider later cannot silently change
data-egress behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from knowledge_engine_ai.copilot.intent import PrivacyClass


class ModelRole(StrEnum):
    """Abstract inference roles used by research workflows."""

    ROUTINE = "routine"
    REASONER = "reasoner"
    SYNTHESIS = "synthesis"


class TaskComplexity(IntEnum):
    """Coarse, policy-visible reasoning requirement."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass(frozen=True)
class RoutingRequest:
    """Facts the policy may use when choosing an inference provider."""

    role: ModelRole
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    cloud_allowed: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    """One configured provider/model endpoint and its allowed role envelope."""

    provider_id: str
    roles: frozenset[ModelRole]
    local: bool
    max_privacy: PrivacyClass
    priority: int = 100
    enabled: bool = True


class ModelRoutingError(RuntimeError):
    """No configured provider may execute a routing request safely."""


_PRIVACY_RANK = {
    PrivacyClass.PUBLIC: 0,
    PrivacyClass.INTERNAL: 1,
    PrivacyClass.SENSITIVE: 2,
    PrivacyClass.SECRET: 3,
}


def select_provider(
    request: RoutingRequest,
    providers: tuple[ProviderSpec, ...],
) -> ProviderSpec:
    """Choose the safest eligible provider deterministically.

    Invariants:
    - SECRET data never enters model context.
    - SENSITIVE data must remain local.
    - remote providers require explicit ``cloud_allowed=True``.
    - workflows request roles, not concrete model names.
    - ties resolve by numeric priority then provider_id for reproducibility.
    """

    if request.privacy_class is PrivacyClass.SECRET:
        raise ModelRoutingError("SECRET-class data must not be placed in model context.")

    eligible: list[ProviderSpec] = []
    for provider in providers:
        if not provider.enabled:
            continue
        if request.role not in provider.roles:
            continue
        if _PRIVACY_RANK[request.privacy_class] > _PRIVACY_RANK[provider.max_privacy]:
            continue
        if request.privacy_class is PrivacyClass.SENSITIVE and not provider.local:
            continue
        if not provider.local and not request.cloud_allowed:
            continue
        eligible.append(provider)

    if not eligible:
        raise ModelRoutingError(
            "No enabled provider satisfies role/privacy/egress policy for "
            f"role={request.role.value!r}, privacy={request.privacy_class.value!r}."
        )

    eligible.sort(key=lambda provider: (provider.priority, not provider.local, provider.provider_id))
    return eligible[0]


__all__ = [
    "ModelRole",
    "ModelRoutingError",
    "ProviderSpec",
    "RoutingRequest",
    "TaskComplexity",
    "select_provider",
]
