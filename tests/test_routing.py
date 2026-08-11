from __future__ import annotations

import pytest

from knowledge_engine_ai.copilot.intent import PrivacyClass
from knowledge_engine_ai.routing import (
    ModelRole,
    ModelRoutingError,
    ProviderSpec,
    RoutingRequest,
    select_provider,
)


def _local(provider_id: str = "ollama-fast", *, priority: int = 10) -> ProviderSpec:
    return ProviderSpec(
        provider_id=provider_id,
        roles=frozenset({ModelRole.ROUTINE, ModelRole.SYNTHESIS}),
        local=True,
        max_privacy=PrivacyClass.SENSITIVE,
        priority=priority,
    )


def _cloud() -> ProviderSpec:
    return ProviderSpec(
        provider_id="cloud-reasoner",
        roles=frozenset({ModelRole.REASONER, ModelRole.SYNTHESIS}),
        local=False,
        max_privacy=PrivacyClass.INTERNAL,
        priority=1,
    )


def test_local_provider_handles_routine_work_by_role() -> None:
    selected = select_provider(
        RoutingRequest(role=ModelRole.ROUTINE),
        (_local(), _cloud()),
    )

    assert selected.provider_id == "ollama-fast"


def test_remote_provider_requires_explicit_cloud_permission() -> None:
    with pytest.raises(ModelRoutingError):
        select_provider(
            RoutingRequest(role=ModelRole.REASONER, cloud_allowed=False),
            (_cloud(),),
        )

    selected = select_provider(
        RoutingRequest(role=ModelRole.REASONER, cloud_allowed=True),
        (_cloud(),),
    )
    assert selected.provider_id == "cloud-reasoner"


def test_sensitive_data_never_routes_to_remote_provider() -> None:
    with pytest.raises(ModelRoutingError):
        select_provider(
            RoutingRequest(
                role=ModelRole.REASONER,
                privacy_class=PrivacyClass.SENSITIVE,
                cloud_allowed=True,
            ),
            (_cloud(),),
        )


def test_secret_data_never_routes_to_any_model() -> None:
    with pytest.raises(ModelRoutingError, match="SECRET-class"):
        select_provider(
            RoutingRequest(
                role=ModelRole.ROUTINE,
                privacy_class=PrivacyClass.SECRET,
            ),
            (_local(),),
        )


def test_disabled_provider_is_not_selected() -> None:
    disabled = ProviderSpec(
        provider_id="disabled-local",
        roles=frozenset({ModelRole.ROUTINE}),
        local=True,
        max_privacy=PrivacyClass.SENSITIVE,
        enabled=False,
    )

    with pytest.raises(ModelRoutingError):
        select_provider(RoutingRequest(role=ModelRole.ROUTINE), (disabled,))


def test_provider_selection_is_deterministic_by_priority_then_id() -> None:
    selected = select_provider(
        RoutingRequest(role=ModelRole.ROUTINE),
        (_local("local-b", priority=10), _local("local-a", priority=10)),
    )

    assert selected.provider_id == "local-a"
