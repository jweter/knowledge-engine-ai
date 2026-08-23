from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import preflight


def test_fix_mode_runs_safe_fixes_before_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], *, check: bool) -> SimpleNamespace:
        assert check is False
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    assert preflight.main(["--fix"]) == 0
    assert calls == [*preflight.FIXES, *preflight.CHECKS]


def test_preflight_stops_on_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], *, check: bool) -> SimpleNamespace:
        assert check is False
        calls.append(command)
        return SimpleNamespace(returncode=3 if command == preflight.CHECKS[1] else 0)

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    assert preflight.main([]) == 3
    assert calls == list(preflight.CHECKS[:2])
