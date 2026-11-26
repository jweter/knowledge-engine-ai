"""Cycle-free stage-hook helper shared by discovery and grounded completion.

``ResearchProgressStage`` lives in ``progress_report.py``, which imports the modules that
announce stages; they therefore pass plain stage-name strings through a
``(stage, detail)`` hook. See ``stage_updates.py`` for the notifier that receives them.
"""

from __future__ import annotations

from collections.abc import Callable

StageHook = Callable[[str, str], None]


def signal_stage(hook: StageHook | None, stage: str, detail: str = "") -> None:
    """Announce a stage that is about to run; an observer failure never affects research."""

    if hook is None:
        return
    try:
        hook(stage, detail)
    except Exception:  # noqa: BLE001 - an observer must never break research
        return
