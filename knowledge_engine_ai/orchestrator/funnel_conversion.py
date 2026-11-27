"""BT-2: per-stage conversion rates and the largest drop-off of a research funnel (issue #88).

Pure arithmetic over a finished `ResearchConversionFunnelReport`: it never re-reads a session
and never invents a count. The report already holds the counts; this module links the stages
that are present into one chain and says, for each link, how many entered, how many came
through, the conversion rate, and which link lost the most.

Chain (a stage is skipped, and the chain bridges across it, when the report has no data for it):

```text
federated candidates -> plan-resolved candidates -> acquirable (already indexed + full-text
eligible) -> papers obtained (already indexed + persisted + reused) -> draft items ->
classified -> staged -> grounded -> promoted
```

A link where more came out than went in (reuse can inflate a later count) is reported with its
raw rate and ``consistent=False`` and is never chosen as the largest drop-off. A link that
nothing entered has ``rate=None`` (undefined, never 0 or 1). The largest drop-off is the
consistent link with the most items lost; ties go to the earlier link; it is ``None`` when no
link lost anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_engine_ai.orchestrator.funnel_report import ResearchConversionFunnelReport


@dataclass(frozen=True)
class StageConversion:
    """One link of the funnel chain."""

    from_stage: str
    to_stage: str
    entered: int
    converted: int
    lost: int
    rate: float | None
    consistent: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "entered": self.entered,
            "converted": self.converted,
            "lost": self.lost,
            "rate": self.rate,
            "consistent": self.consistent,
        }


@dataclass(frozen=True)
class FunnelConversion:
    """All links in pipeline order plus the one that lost the most items."""

    links: tuple[StageConversion, ...]
    largest_drop_off: StageConversion | None

    def to_dict(self) -> dict[str, object]:
        return {
            "links": [link.to_dict() for link in self.links],
            "largest_drop_off": (
                self.largest_drop_off.to_dict() if self.largest_drop_off is not None else None
            ),
        }


def _stage_counts(report: ResearchConversionFunnelReport) -> list[tuple[str, int]]:
    stages: list[tuple[str, int]] = []
    if report.discovery_triggered:
        stages.append(("federated_candidates", report.federated_discovery_candidate_count))
    plan = report.acquisition_plan
    if plan is not None:
        stages.append(("plan_resolved", plan.resolved_candidate_count))
        stages.append(("acquirable", plan.already_indexed_count + plan.full_text_eligible_count))
    acquisition = report.acquisition
    if acquisition is not None:
        # Already-indexed papers go straight to extraction (they are not acquisition-route
        # results), so they count as obtained; otherwise reusing the index would look like an
        # acquisition loss.
        already_indexed = plan.already_indexed_count if plan is not None else 0
        stages.append(
            (
                "papers_obtained",
                already_indexed + acquisition.papers_persisted + acquisition.papers_reused,
            )
        )
    extraction = report.extraction
    if extraction is not None:
        stages.append(("draft_items", extraction.draft_item_count))
        stages.append(("classified", extraction.classified_item_count))
        stages.append(("staged", extraction.staged_record_count))
        stages.append(("grounded", extraction.grounded_record_count))
        stages.append(("promoted", extraction.promoted_record_count))
    return stages


def compute_funnel_conversion(report: ResearchConversionFunnelReport) -> FunnelConversion:
    """Link the present stages of ``report`` and compute each link's conversion."""
    stages = _stage_counts(report)
    links: list[StageConversion] = []
    for (from_name, entered), (to_name, converted) in zip(stages, stages[1:], strict=False):
        links.append(
            StageConversion(
                from_stage=from_name,
                to_stage=to_name,
                entered=entered,
                converted=converted,
                lost=max(entered - converted, 0),
                rate=(converted / entered) if entered > 0 else None,
                consistent=converted <= entered,
            )
        )
    best: StageConversion | None = None
    for link in links:
        if not link.consistent or link.lost <= 0:
            continue
        if best is None or link.lost > best.lost:
            best = link
    return FunnelConversion(links=tuple(links), largest_drop_off=best)
