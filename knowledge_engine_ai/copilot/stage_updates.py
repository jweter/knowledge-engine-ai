"""BT-6 follow-on (issue #90, tracked from #84/#87): in-flight research stage updates.

`ResearchProgressReport` (``progress_report.py``) can only be built once a research call
has returned, so Web could never observe the reserved in-flight stages
(``searching_indexed_evidence``, ``discovering_sources``, ``acquiring_sources``,
``validating_extracting_evidence``, ``reretrieving``). This module is the small,
dependency-free seam that lets ``run_research_question`` announce each stage the moment
it is actually entered, through an optional caller-supplied callback, and record the same
ordered updates on the result.

Safety invariants:

* **Observation only.** A stage update never changes retrieval, discovery, grounded
  completion, adequacy, or release behavior. Nothing here writes session state.
* **A broken observer cannot break research.** Exceptions raised by the callback are
  swallowed and counted (``callback_error_count``); the research call continues.
* **Honest stages.** An update is emitted only when the work for that stage is about to
  run (for example ``acquiring_sources`` is never emitted when acquisition is skipped for
  adequacy). There is no percent-complete estimate.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from knowledge_engine_ai.copilot.progress_report import ResearchProgressStage

RESEARCH_STAGE_UPDATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ResearchStageUpdate:
    """One stage the research call has just entered."""

    schema_version: int
    sequence: int
    session_id: str
    stage: ResearchProgressStage
    elapsed_ms: int
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "stage": self.stage.value,
            "elapsed_ms": self.elapsed_ms,
            "detail": self.detail,
        }


ResearchStageCallback = Callable[[ResearchStageUpdate], None]
#: Narrow hook shape handed to lower layers (e.g. grounded completion) that must not
#: import the progress contract: ``(stage_value, detail)``.
StageHook = Callable[[str, str], None]


class ResearchStageNotifier:
    """Collects ordered stage updates and forwards each to an optional callback."""

    def __init__(
        self,
        session_id: str,
        callback: ResearchStageCallback | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_id = session_id
        self._callback = callback
        self._clock = clock
        self._started = clock()
        self._updates: list[ResearchStageUpdate] = []
        self._callback_error_count = 0

    @property
    def updates(self) -> tuple[ResearchStageUpdate, ...]:
        return tuple(self._updates)

    @property
    def callback_error_count(self) -> int:
        return self._callback_error_count

    def notify(self, stage: ResearchProgressStage | str, detail: str = "") -> None:
        """Record and forward one update; never raises for observer failures.

        An unknown stage name is swallowed (counted as a callback error) rather than
        raised, because this is called from inside live research.
        """

        try:
            resolved = ResearchProgressStage(stage)
        except ValueError:
            self._callback_error_count += 1
            return
        elapsed_ms = max(0, int((self._clock() - self._started) * 1000))
        update = ResearchStageUpdate(
            schema_version=RESEARCH_STAGE_UPDATE_SCHEMA_VERSION,
            sequence=len(self._updates) + 1,
            session_id=self._session_id,
            stage=resolved,
            elapsed_ms=elapsed_ms,
            detail=detail,
        )
        self._updates.append(update)
        if self._callback is None:
            return
        try:
            self._callback(update)
        except Exception:  # noqa: BLE001 - an observer must never break research
            self._callback_error_count += 1

    def as_hook(self) -> StageHook:
        """A ``(stage_value, detail)`` hook for layers that cannot import this module."""

        return self.notify
