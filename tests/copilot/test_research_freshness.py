from __future__ import annotations

from datetime import UTC, datetime

import pytest

from knowledge_engine_ai.copilot.research_freshness import (
    DEFAULT_MAX_AGE_SECONDS,
    ResearchFreshnessError,
    assess_rerun_need,
    diff_candidate_snapshots,
)
from knowledge_engine_ai.ke_client import (
    FederatedCandidateObservation,
    FederatedCandidateRecord,
    FederatedCoverageReportResult,
    FederatedDiscoverHistoryResult,
    SearchCoverageReport,
)

_NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)


def _coverage(
    search_run_id: str = "run-1",
    created_at: str = "2026-08-21T00:00:00Z",
    completeness: str = "complete",
) -> SearchCoverageReport:
    return SearchCoverageReport(
        search_run_id=search_run_id,
        created_at=created_at,
        query_text="does semaglutide reduce body weight",
        year_from=None,
        year_to=None,
        limit_per_provider=20,
        completeness=completeness,
        candidate_count=0,
        providers_requested=("pubmed",),
        providers_attempted=("pubmed",),
        providers_completed=("pubmed",),
        providers_failed=(),
    )


def _history(*runs: SearchCoverageReport) -> FederatedDiscoverHistoryResult:
    return FederatedDiscoverHistoryResult(
        research_question_id="q-1", run_count=len(runs), runs=runs
    )


def _observation(
    provider: str = "crossref",
    *,
    retracted: bool | None = None,
    corrected: bool | None = None,
    expression_of_concern: bool | None = None,
    withdrawn: bool | None = None,
) -> FederatedCandidateObservation:
    return FederatedCandidateObservation(
        provider=provider,
        provider_id="p-1",
        title="A trial of semaglutide",
        authors=(),
        publication_year=2024,
        venue=None,
        abstract=None,
        doi="10.1000/example",
        pmid=None,
        pmcid=None,
        arxiv_id=None,
        openalex_id=None,
        semantic_scholar_id=None,
        landing_url=None,
        full_text_url=None,
        xml_url=None,
        license=None,
        metadata_source=None,
        pmcid_source=None,
        open_access_source=None,
        citation_count=None,
        open_access=None,
        retracted=retracted,
        preprint=None,
        preprint_version=None,
        related_journal_doi=None,
        related_journal_reference=None,
        retrieved_at=None,
        corrected=corrected,
        expression_of_concern=expression_of_concern,
        withdrawn=withdrawn,
    )


def _candidate(
    canonical_id: str, *, observations: tuple[FederatedCandidateObservation, ...] = ()
) -> FederatedCandidateRecord:
    return FederatedCandidateRecord(
        canonical_id=canonical_id,
        title="A trial of semaglutide",
        observations=observations,
        doi="10.1000/example",
        publication_year=2024,
    )


def _snapshot(
    *candidates: FederatedCandidateRecord, search_run_id: str = "run-1"
) -> FederatedCoverageReportResult:
    return FederatedCoverageReportResult(
        search_run_id=search_run_id,
        coverage=_coverage(search_run_id=search_run_id),
        candidates=candidates,
    )


class TestAssessRerunNeed:
    def test_no_prior_run_recommends_a_first_run(self) -> None:
        recommendation = assess_rerun_need(_history(), now=_NOW)

        assert recommendation.recommended is True
        assert "No federated-discovery run" in recommendation.reason
        assert recommendation.last_run is None
        assert recommendation.age_seconds is None

    def test_incomplete_last_run_recommends_rerun_regardless_of_age(self) -> None:
        run = _coverage(created_at="2026-08-21T11:59:00Z", completeness="partial")

        recommendation = assess_rerun_need(_history(run), now=_NOW)

        assert recommendation.recommended is True
        assert "completeness='partial'" in recommendation.reason
        assert recommendation.last_run == run
        assert recommendation.age_seconds == pytest.approx(60.0)

    def test_stale_complete_run_recommends_rerun(self) -> None:
        run = _coverage(created_at="2026-08-01T00:00:00Z", completeness="complete")

        recommendation = assess_rerun_need(_history(run), now=_NOW, max_age_seconds=60.0)

        assert recommendation.recommended is True
        assert "past the configured 60s" in recommendation.reason

    def test_fresh_complete_run_recommends_against_rerun(self) -> None:
        run = _coverage(created_at="2026-08-21T11:00:00Z", completeness="complete")

        recommendation = assess_rerun_need(
            _history(run), now=_NOW, max_age_seconds=DEFAULT_MAX_AGE_SECONDS
        )

        assert recommendation.recommended is False
        assert "within the configured" in recommendation.reason
        assert recommendation.age_seconds == pytest.approx(3600.0)

    def test_picks_the_most_recent_run_out_of_order_history(self) -> None:
        older = _coverage(search_run_id="run-older", created_at="2026-08-01T00:00:00Z")
        newer = _coverage(search_run_id="run-newer", created_at="2026-08-21T11:00:00Z")

        recommendation = assess_rerun_need(_history(older, newer), now=_NOW)

        assert recommendation.last_run is not None
        assert recommendation.last_run.search_run_id == "run-newer"

    def test_malformed_timestamp_raises_research_freshness_error(self) -> None:
        run = _coverage(created_at="not-a-timestamp")

        with pytest.raises(ResearchFreshnessError):
            assess_rerun_need(_history(run), now=_NOW)


class TestDiffCandidateSnapshots:
    def test_new_candidate_in_current_is_newly_discovered(self) -> None:
        previous = _snapshot(_candidate("c-1"))
        current = _snapshot(_candidate("c-1"), _candidate("c-2"))

        diff = diff_candidate_snapshots(previous, current)

        assert [c.canonical_id for c in diff.newly_discovered] == ["c-2"]
        assert diff.newly_flagged == ()

    def test_candidate_absent_from_current_is_not_reported(self) -> None:
        previous = _snapshot(_candidate("c-1"), _candidate("c-2"))
        current = _snapshot(_candidate("c-1"))

        diff = diff_candidate_snapshots(previous, current)

        assert diff.newly_discovered == ()
        assert diff.newly_flagged == ()

    def test_retraction_flip_is_reported(self) -> None:
        previous = _snapshot(_candidate("c-1", observations=(_observation(retracted=False),)))
        current = _snapshot(_candidate("c-1", observations=(_observation(retracted=True),)))

        diff = diff_candidate_snapshots(previous, current)

        assert diff.newly_discovered == ()
        assert len(diff.newly_flagged) == 1
        flip = diff.newly_flagged[0]
        assert flip.canonical_id == "c-1"
        assert flip.flag == "retracted"

    def test_unreported_to_true_also_counts_as_a_flip(self) -> None:
        previous = _snapshot(_candidate("c-1", observations=(_observation(retracted=None),)))
        current = _snapshot(_candidate("c-1", observations=(_observation(retracted=True),)))

        diff = diff_candidate_snapshots(previous, current)

        assert len(diff.newly_flagged) == 1
        assert diff.newly_flagged[0].flag == "retracted"

    def test_already_true_in_previous_is_not_reported_again(self) -> None:
        previous = _snapshot(_candidate("c-1", observations=(_observation(retracted=True),)))
        current = _snapshot(_candidate("c-1", observations=(_observation(retracted=True),)))

        diff = diff_candidate_snapshots(previous, current)

        assert diff.newly_flagged == ()

    def test_all_four_flags_are_independent(self) -> None:
        previous = _snapshot(_candidate("c-1", observations=(_observation(),)))
        current = _snapshot(
            _candidate(
                "c-1",
                observations=(
                    _observation(
                        retracted=True,
                        corrected=True,
                        expression_of_concern=True,
                        withdrawn=True,
                    ),
                ),
            )
        )

        diff = diff_candidate_snapshots(previous, current)

        flags = {flip.flag for flip in diff.newly_flagged}
        assert flags == {"retracted", "corrected", "expression_of_concern", "withdrawn"}

    def test_new_candidate_is_not_also_reported_as_newly_flagged(self) -> None:
        previous = _snapshot()
        current = _snapshot(_candidate("c-1", observations=(_observation(retracted=True),)))

        diff = diff_candidate_snapshots(previous, current)

        assert [c.canonical_id for c in diff.newly_discovered] == ["c-1"]
        assert diff.newly_flagged == ()

    def test_empty_previous_snapshot_reports_every_current_candidate_as_new(self) -> None:
        previous = _snapshot()
        current = _snapshot(_candidate("c-1"), _candidate("c-2"))

        diff = diff_candidate_snapshots(previous, current)

        assert {c.canonical_id for c in diff.newly_discovered} == {"c-1", "c-2"}
