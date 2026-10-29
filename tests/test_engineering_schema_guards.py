"""Engineering control-plane readers reject malformed JSON roots explicitly."""

import json
from pathlib import Path
from typing import Any

import pytest

from engineering import execution_director, growth_engine, iron_memory, orchestrator_ops


def _write_root(tmp_path: Path, name: str, payload: Any) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_iron_memory_rejects_non_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iron_memory, "LOCAL_MEMORY", _write_root(tmp_path, "memory.json", []))
    with pytest.raises(ValueError, match="schema_version 1"):
        iron_memory.load_local_memory()


def test_orchestrator_control_rejects_non_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator_ops, "CONTROL", _write_root(tmp_path, "control.json", []))
    with pytest.raises(ValueError, match="must be an object"):
        orchestrator_ops.load_control()


def test_growth_control_rejects_non_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(growth_engine, "CONTROL", _write_root(tmp_path, "control.json", []))
    with pytest.raises(SystemExit, match="must be an object"):
        growth_engine.load_control()


def test_growth_attestation_rejects_non_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        growth_engine, "PRODUCT_REALITY_ATTESTATIONS", _write_root(tmp_path, "attest.json", [])
    )
    with pytest.raises(SystemExit, match="must be an object"):
        growth_engine.load_attestations("jweter/knowledge-engine-ai")


def test_dependency_graph_rejects_non_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution_director, "DEPENDENCIES", _write_root(tmp_path, "deps.json", []))
    with pytest.raises(SystemExit, match="invalid schema"):
        execution_director.dependency_graph({})
