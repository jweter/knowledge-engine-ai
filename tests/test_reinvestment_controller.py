from __future__ import annotations

from engineering.reinvestment_controller import (
    MAX_SYSTEM_REINVESTMENT,
    MIN_SYSTEM_REINVESTMENT,
    recommend,
    self_test,
)


def test_self_test_is_green() -> None:
    assert self_test() == []


def test_degraded_evidence_is_bounded() -> None:
    report = {
        "schema_version": 2,
        "windows": {
            "current": {
                "repeat_failure_rate": 0.6,
                "dependency_unlock_rate": 0.0,
                "human_intervention_rate": 0.8,
            }
        },
        "evidence_derived": {
            "throughput_factor": 0.7,
            "cycle_time_factor": 0.7,
            "engineering_multiplication_factor": 0.49,
            "compounding_rate": -0.2,
        },
    }
    result = recommend(report)
    assert result["system_reinvestment_fraction"] == MAX_SYSTEM_REINVESTMENT
    assert result["product_delivery_fraction"] == 0.8


def test_healthy_evidence_returns_product_bias() -> None:
    report = {
        "schema_version": 2,
        "windows": {
            "current": {
                "repeat_failure_rate": 0.0,
                "dependency_unlock_rate": 0.4,
                "human_intervention_rate": 0.0,
            }
        },
        "evidence_derived": {
            "throughput_factor": 1.3,
            "cycle_time_factor": 1.2,
            "engineering_multiplication_factor": 1.56,
            "compounding_rate": 0.15,
        },
    }
    result = recommend(report)
    assert result["system_reinvestment_fraction"] == MIN_SYSTEM_REINVESTMENT
    assert result["product_delivery_fraction"] == 0.95
    assert any(row["kind"] == "PRODUCT_BIAS" for row in result["actions"])


def test_unknown_metrics_increase_measurement_not_claims() -> None:
    report = {
        "schema_version": 2,
        "windows": {"current": {}},
        "evidence_derived": {},
    }
    result = recommend(report)
    assert result["confidence"] == "EVIDENCE_LIMITED"
    assert result["system_reinvestment_fraction"] > MIN_SYSTEM_REINVESTMENT
    assert all(row["kind"] == "MEASUREMENT" for row in result["actions"])
