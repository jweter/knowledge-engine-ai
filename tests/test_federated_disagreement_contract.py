from __future__ import annotations

import pytest

from knowledge_engine_ai.ke_client import (
    FederatedDiscoveryParseError,
    parse_federated_discovery_result,
)


def _payload() -> dict[str, object]:
    return {
        "search_run_id": "11111111-1111-1111-1111-111111111111",
        "query": {"text": "semaglutide weight loss"},
        "completeness": "complete",
        "provider_statuses": [],
        "candidates": [
            {
                "canonical_id": "doi:10.1000/example",
                "title": "A semaglutide trial",
                "doi": "10.1000/example",
                "publication_year": 2026,
                "observations": [
                    {"provider": "pubmed"},
                    {"provider": "crossref"},
                ],
            }
        ],
        "provider_disagreements": {
            "disagreement_count": 1,
            "candidates": [
                {
                    "canonical_id": "doi:10.1000/example",
                    "disagreements": [
                        {
                            "field": "publication_year",
                            "assertions": [
                                {
                                    "provider": "pubmed",
                                    "provider_id": "pm-1",
                                    "value": 2026,
                                },
                                {
                                    "provider": "crossref",
                                    "provider_id": "cr-1",
                                    "value": 2025,
                                },
                            ],
                        }
                    ],
                }
            ],
        },
    }


def test_parser_preserves_core_canonical_identity_and_provider_disagreement() -> None:
    result = parse_federated_discovery_result(_payload())

    candidate = result.candidates[0]
    assert candidate.canonical_id == "doi:10.1000/example"
    assert candidate.providers == ("crossref", "pubmed")

    assert result.provider_disagreements is not None
    disagreement = result.provider_disagreements[0]
    assert disagreement.canonical_id == candidate.canonical_id
    assert disagreement.disagreements[0].field == "publication_year"
    assertions = disagreement.disagreements[0].assertions
    assert [(item.provider, item.value) for item in assertions] == [
        ("pubmed", 2026),
        ("crossref", 2025),
    ]


def test_parser_keeps_missing_legacy_disagreement_report_explicitly_unavailable() -> None:
    payload = _payload()
    del payload["provider_disagreements"]

    result = parse_federated_discovery_result(payload)

    assert result.provider_disagreements is None


def test_parser_rejects_malformed_disagreement_report_instead_of_guessing() -> None:
    payload = _payload()
    payload["provider_disagreements"] = {"disagreement_count": 1}

    with pytest.raises(FederatedDiscoveryParseError, match="malformed"):
        parse_federated_discovery_result(payload)
