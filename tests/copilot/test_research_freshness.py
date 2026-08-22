from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from knowledge_engine_ai.copilot.research_freshness import (
    DEFAULT_MAX_AGE_SECONDS,
    NarrativeTouchingFlip,
    PublicationStatusFlip,
    ResearchFreshnessError,
    apply_narrative_touching_flips,
    assess_rerun_need,
    crosswalk_publication_status_flips,
    diff_candidate_snapshots,
    session_retrieval_dois,
)
from knowledge_engine_ai.ke_client import (
    FederatedCandidateObservation,
    FederatedCandidateRecord,
    FederatedCoverageReportResult,
    FederatedDiscoverHistoryResult,
    SearchCoverageReport,
)
from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import (
    SessionRepository,
    UnknownSessionError,
    new_connection,
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


def _retrieval_event(
    *,
    source_ids: tuple[str, ...],
    source_dois: tuple[str, ...],
    event_id: str = "e-retrieval",
) -> ResearchEvent:
    return ResearchEvent(
        event_id=event_id,
        session_id="session-1",
        timestamp="2026-08-22T00:00:00Z",
        workflow_node="retrieval_and_evidence_intelligence",
        executor_type="deterministic_tool",
        source_ids=source_ids,
        source_dois=source_dois,
    )


class TestSessionRetrievalDois:
    def test_maps_evidence_record_id_to_doi(self) -> None:
        events = [_retrieval_event(source_ids=("ev-1", "ev-2"), source_dois=("10.1/a", "10.1/b"))]

        assert session_retrieval_dois(events) == {"ev-1": "10.1/a", "ev-2": "10.1/b"}

    def test_combines_across_multiple_retrieval_events(self) -> None:
        events = [
            _retrieval_event(event_id="e-1", source_ids=("ev-1",), source_dois=("10.1/a",)),
            _retrieval_event(
                event_id="e-2",
                source_ids=("ev-2",),
                source_dois=("10.1/b",),
            ),
        ]

        assert session_retrieval_dois(events) == {"ev-1": "10.1/a", "ev-2": "10.1/b"}

    def test_old_event_with_no_source_dois_contributes_nothing(self) -> None:
        # Pre-existing rows persisted before `source_dois` existed have an
        # empty `source_dois` even though `source_ids` is non-empty.
        events = [_retrieval_event(source_ids=("ev-1",), source_dois=())]

        assert session_retrieval_dois(events) == {}

    def test_empty_doi_string_is_not_included(self) -> None:
        events = [_retrieval_event(source_ids=("ev-1", "ev-2"), source_dois=("", "10.1/b"))]

        assert session_retrieval_dois(events) == {"ev-2": "10.1/b"}

    def test_non_retrieval_events_with_empty_source_ids_are_harmless(self) -> None:
        synthesis_event = ResearchEvent(
            event_id="e-synth",
            session_id="session-1",
            timestamp="2026-08-22T00:00:01Z",
            workflow_node="synthesis",
            executor_type="local_llm",
        )

        assert session_retrieval_dois([synthesis_event]) == {}


class TestCrosswalkPublicationStatusFlips:
    def test_flip_touching_a_cited_evidence_record_is_reported(self) -> None:
        flip = PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="retracted")
        current = _snapshot(_candidate("c-1"))  # doi="10.1000/example"

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.1000/example"},
            narrative="The effect was significant [ev-1].",
        )

        assert len(touching) == 1
        assert touching[0].flip == flip
        assert touching[0].doi == "10.1000/example"
        assert touching[0].cited_evidence_record_ids == ("ev-1",)

    def test_flip_whose_doi_was_retrieved_but_never_cited_is_a_freshness_signal_only(
        self,
    ) -> None:
        flip = PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="retracted")
        current = _snapshot(_candidate("c-1"))

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.1000/example"},
            narrative="Nothing here cites that record at all.",
        )

        assert touching == ()

    def test_flip_whose_doi_was_never_retrieved_is_not_reported(self) -> None:
        flip = PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="retracted")
        current = _snapshot(_candidate("c-1"))

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.9999/unrelated"},
            narrative="The effect was significant [ev-1].",
        )

        assert touching == ()

    def test_flip_with_no_matching_candidate_in_current_is_skipped(self) -> None:
        flip = PublicationStatusFlip(canonical_id="c-missing", title="A trial", flag="retracted")
        current = _snapshot(_candidate("c-1"))

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.1000/example"},
            narrative="[ev-1]",
        )

        assert touching == ()

    def test_multiple_evidence_records_sharing_a_doi_are_all_named_when_cited(self) -> None:
        flip = PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="withdrawn")
        current = _snapshot(_candidate("c-1"))

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.1000/example", "ev-2": "10.1000/example"},
            narrative="[ev-1] and also [ev-2].",
        )

        assert len(touching) == 1
        assert touching[0].cited_evidence_record_ids == ("ev-1", "ev-2")

    def test_qualifying_flag_is_reported_the_same_way_as_invalidating(self) -> None:
        # crosswalk_publication_status_flips does not itself split
        # invalidates-versus-qualifies -- that reads `.flip.flag` downstream.
        flip = PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="corrected")
        current = _snapshot(_candidate("c-1"))

        touching = crosswalk_publication_status_flips(
            (flip,),
            current=current,
            retrieval_dois={"ev-1": "10.1000/example"},
            narrative="[ev-1]",
        )

        assert len(touching) == 1
        assert touching[0].flip.flag == "corrected"


def _touching_flip(
    flag: str, *, canonical_id: str = "c-1", doi: str = "10.1000/example"
) -> NarrativeTouchingFlip:
    return NarrativeTouchingFlip(
        flip=PublicationStatusFlip(canonical_id=canonical_id, title="A trial", flag=flag),
        doi=doi,
        cited_evidence_record_ids=("ev-1",),
    )


def _repository_with_session(
    status: SessionStatus = SessionStatus.COMPLETED,
) -> SessionRepository:
    repository = SessionRepository(new_connection(":memory:"))
    repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id="session-1",
            created_at="2026-08-09T00:00:00Z",
            updated_at="2026-08-09T00:00:00Z",
            user_question_original="Does semaglutide produce long-term weight loss?",
            status=status,
        )
    )
    return repository


class _RacesAnotherInvalidationOnFirstRead(SessionRepository):
    """Test double reproducing the precheck/persist race, without threads.

    The first `get_session` call this repository sees (`apply_narrative_
    touching_flips`'s own `narrative_invalidated_at is None` precheck)
    triggers a real, independent `record_narrative_invalidation` call
    first -- simulating a second, concurrent freshness-check call winning
    the race right after the precheck reads but before the original call's
    own `record_narrative_invalidation` runs. Every call after that first
    one behaves exactly like the base repository.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(connection)
        self._raced = False

    def get_session(self, session_id: str) -> ResearchSession | None:
        session = super().get_session(session_id)
        if not self._raced and session is not None and session.narrative_invalidated_at is None:
            self._raced = True
            racing_event = ResearchEvent(
                event_id="racing-event",
                session_id=session_id,
                timestamp="2026-08-22T11:59:59Z",
                workflow_node="narrative_invalidated",
                executor_type="deterministic_policy",
                notes="canonical_id='c-racer' doi='10.1000/racer' flag='retracted' "
                "cited_evidence_record_ids=['ev-racer']",
            )
            super().record_narrative_invalidation(
                racing_event, invalidated_at="2026-08-22T11:59:59Z"
            )
        return session


class TestApplyNarrativeTouchingFlips:
    def test_invalidating_flip_records_narrative_invalidation(self) -> None:
        repository = _repository_with_session()
        flip = _touching_flip("retracted")

        result = apply_narrative_touching_flips(
            repository, (flip,), session_id="session-1", now="2026-08-22T12:00:00Z"
        )

        assert result.invalidating == (flip,)
        assert result.qualifying == ()
        assert result.already_invalidated is False
        assert result.narrative_invalidated_event is not None
        assert result.narrative_invalidated_event.workflow_node == "narrative_invalidated"

        fetched = repository.get_session("session-1")
        assert fetched is not None
        assert fetched.narrative_invalidated_at == "2026-08-22T12:00:00Z"
        # status is untouched by design -- see record_narrative_invalidation.
        assert fetched.status == SessionStatus.COMPLETED

    def test_withdrawn_flip_also_invalidates(self) -> None:
        repository = _repository_with_session()
        flip = _touching_flip("withdrawn")

        result = apply_narrative_touching_flips(repository, (flip,), session_id="session-1")

        assert result.invalidating == (flip,)
        assert result.narrative_invalidated_event is not None

    def test_qualifying_flip_is_reported_but_not_persisted(self) -> None:
        repository = _repository_with_session()
        flip = _touching_flip("corrected")

        result = apply_narrative_touching_flips(repository, (flip,), session_id="session-1")

        assert result.invalidating == ()
        assert result.qualifying == (flip,)
        assert result.narrative_invalidated_event is None
        fetched = repository.get_session("session-1")
        assert fetched is not None
        assert fetched.narrative_invalidated_at is None

    def test_expression_of_concern_flip_also_qualifies(self) -> None:
        repository = _repository_with_session()
        flip = _touching_flip("expression_of_concern")

        result = apply_narrative_touching_flips(repository, (flip,), session_id="session-1")

        assert result.qualifying == (flip,)
        assert result.invalidating == ()

    def test_mixed_batch_splits_into_both_lists(self) -> None:
        repository = _repository_with_session()
        invalidating_flip = _touching_flip("retracted", canonical_id="c-1")
        qualifying_flip = _touching_flip("corrected", canonical_id="c-2")

        result = apply_narrative_touching_flips(
            repository, (invalidating_flip, qualifying_flip), session_id="session-1"
        )

        assert result.invalidating == (invalidating_flip,)
        assert result.qualifying == (qualifying_flip,)
        assert result.narrative_invalidated_event is not None

    def test_no_touching_flips_is_a_no_op(self) -> None:
        repository = _repository_with_session()

        result = apply_narrative_touching_flips(repository, (), session_id="session-1")

        assert result.invalidating == ()
        assert result.qualifying == ()
        assert result.already_invalidated is False
        assert result.narrative_invalidated_event is None

    def test_no_touching_flips_does_not_require_an_existing_session(self) -> None:
        repository = SessionRepository(new_connection(":memory:"))

        result = apply_narrative_touching_flips(repository, (), session_id="does-not-exist")

        assert result.narrative_invalidated_event is None

    def test_second_invalidating_flip_in_same_batch_does_not_raise(self) -> None:
        repository = _repository_with_session()
        first = _touching_flip("retracted", canonical_id="c-1")
        second = _touching_flip("withdrawn", canonical_id="c-2")

        result = apply_narrative_touching_flips(repository, (first, second), session_id="session-1")

        assert result.invalidating == (first, second)
        assert result.narrative_invalidated_event is not None
        # Only the first flip's detail is recorded in the event notes.
        assert "c-1" in (result.narrative_invalidated_event.notes or "")

    def test_already_invalidated_session_is_not_recorded_again(self) -> None:
        repository = _repository_with_session()
        first_flip = _touching_flip("retracted")
        apply_narrative_touching_flips(repository, (first_flip,), session_id="session-1")

        second_flip = _touching_flip("withdrawn", canonical_id="c-2")
        result = apply_narrative_touching_flips(repository, (second_flip,), session_id="session-1")

        assert result.already_invalidated is True
        assert result.narrative_invalidated_event is None
        assert result.invalidating == (second_flip,)

    def test_concurrent_invalidation_between_precheck_and_persist_is_not_raised(self) -> None:
        # Regression test: `apply_narrative_touching_flips` reads
        # `session.narrative_invalidated_at` (the precheck) and later calls
        # `record_narrative_invalidation` (the persist) as two separate
        # steps, not one atomic transaction. If a second, concurrent
        # freshness-check call invalidates the same session in between --
        # scheduled and request-driven checks racing each other -- this
        # call's own precheck still sees `None`, but the persist step below
        # it loses the race and would otherwise surface
        # `NarrativeAlreadyInvalidatedError`, violating this function's
        # documented "never raises `NarrativeAlreadyInvalidatedError`"
        # guarantee.
        repository = _RacesAnotherInvalidationOnFirstRead(new_connection(":memory:"))
        repository.create_session(
            ResearchSession(
                schema_version=1,
                session_id="session-1",
                created_at="2026-08-09T00:00:00Z",
                updated_at="2026-08-09T00:00:00Z",
                user_question_original="Does semaglutide produce long-term weight loss?",
                status=SessionStatus.COMPLETED,
            )
        )
        flip = _touching_flip("retracted")

        result = apply_narrative_touching_flips(
            repository, (flip,), session_id="session-1", now="2026-08-22T12:00:00Z"
        )

        assert result.already_invalidated is True
        assert result.narrative_invalidated_event is None
        assert result.invalidating == (flip,)
        # The event the racing call recorded is untouched -- this call did
        # not overwrite it or append a second one.
        fetched = repository.get_session("session-1")
        assert fetched is not None
        assert fetched.narrative_invalidated_at == "2026-08-22T11:59:59Z"

    def test_unknown_session_with_invalidating_flip_raises(self) -> None:
        repository = SessionRepository(new_connection(":memory:"))
        flip = _touching_flip("retracted")

        with pytest.raises(UnknownSessionError):
            apply_narrative_touching_flips(repository, (flip,), session_id="does-not-exist")

    def test_unrecognized_flag_raises(self) -> None:
        repository = _repository_with_session()
        bad_flip = NarrativeTouchingFlip(
            flip=PublicationStatusFlip(canonical_id="c-1", title="A trial", flag="preprint"),
            doi="10.1000/example",
            cited_evidence_record_ids=("ev-1",),
        )

        with pytest.raises(ValueError, match="Unrecognized"):
            apply_narrative_touching_flips(repository, (bad_flip,), session_id="session-1")

    def test_default_timestamp_is_used_when_now_not_supplied(self) -> None:
        repository = _repository_with_session()
        flip = _touching_flip("retracted")

        result = apply_narrative_touching_flips(repository, (flip,), session_id="session-1")

        assert result.narrative_invalidated_event is not None
        assert result.narrative_invalidated_event.timestamp
        fetched = repository.get_session("session-1")
        assert fetched is not None
        assert fetched.narrative_invalidated_at == result.narrative_invalidated_event.timestamp
