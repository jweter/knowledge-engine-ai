"""AI-FRD-5: research freshness / rerun reasoning -- a first bounded slice.

`docs/roadmap/federated_discovery_orchestration_adoption.md`'s AI-FRD-5:
"Given an earlier Research Session, help decide whether a new federated
search is warranted and explain what changed after Core reruns it." The
client-boundary prerequisites this milestone needs were already built --
`ke_client.federated_discover_history()` lists every past run for a tracked
`research_question_id`, and `ke_client.federated_coverage_report()` fetches
one specific past run's full candidate snapshot -- but nothing yet decided
whether a rerun is warranted or diffed two runs' facts. This module is that
reasoning, expressed as two independent, deterministic, pure functions over
data those two `ke_client` wrappers already return:

- `assess_rerun_need` looks only at a tracked question's run history
  (`FederatedDiscoverHistoryResult`, i.e. each run's `SearchCoverageReport`)
  and recommends whether a fresh `federated_discover()` call is warranted --
  never recorded, degraded, or stale enough to trust as-is.
- `diff_candidate_snapshots` looks at two *specific* past runs' full
  candidate snapshots (`FederatedCoverageReportResult`, from two
  `federated_coverage_report()` point lookups) and reports which candidates
  are newly discovered and which publication-status flag newly flipped to
  asserted-`True` between them.

Both are deterministic rules, never an LLM judgment call -- the same
"no model dynamically deciding execution" discipline `discovery_policy.py`
already established for AI-FRD-3/AI-FRD-4's trigger. Nothing here merges,
votes on, or picks an authoritative provider value; a candidate is "newly
flagged" if *any* provider newly asserts the flag `True`, mirroring
`discovery_policy.py`'s and `ke_client.py`'s own "absent is not negative,
per-provider observations are preserved unmerged" contract.

Deliberately out of scope for this slice (see AI-FRD-5's own exit
criteria and this milestone's "next continuation" note in
`docs/project-status.yaml`): neither function is wired into
`run_research_question`, a Research Session, or synthesis. Nothing here
decides that a correction/retraction *invalidates* a prior narrative, and
no prior answer text is versioned or rewritten -- that judgment belongs to
a future slice once this bounded reasoning has a caller inside a session.
`ke-ai research-freshness` (see `cli.py`) is this slice's first caller, the
same "build the tested primitive, add a standalone CLI caller, wire into
`run_research_question` later" sequencing AI-FRD-3/AI-FRD-4 already used.

A later slice (2026-08-22, `docs/roadmap/answer_session_versioning_design.md`'s
"the crosswalk" section) added `crosswalk_publication_status_flips` and its
`session_retrieval_dois` helper below -- the detection layer that decides
*whether* a `PublicationStatusFlip` this module already computes actually
touches one specific session's own cited narrative, as opposed to a
discovery lead that session never promoted to a claim.

A still later slice (2026-08-22, later still) added
`apply_narrative_touching_flips` below -- the "invalidates versus qualifies"
trigger the design doc's "What this does not do" named as the next small,
coherent step: for one batch of already-crosswalked `NarrativeTouchingFlip`s,
decide which are `retracted`/`withdrawn` (invalidates -- call
`SessionRepository.record_narrative_invalidation`, at most once per session)
versus `corrected`/`expression_of_concern` (qualifies -- reported back to the
caller, not persisted; the `AnswerFreshness` read-side projection that would
track a durable `pending_flips` list does not exist yet). Still deliberately
out of scope: the `AnswerFreshness` projection itself, and any caller that
mints a version-*N+1* session (`SessionRepository.supersede_session` remains
uncalled by this module). `assess_rerun_need`/`diff_candidate_snapshots`/
`session_retrieval_dois`/`crosswalk_publication_status_flips` are pure,
deterministic, and take already-fetched data -- no `SessionRepository` call,
no `ke` subprocess -- the same "caller owns the I/O" boundary
`observability.build_session_trace` already follows.
`apply_narrative_touching_flips` is deliberately the one exception in this
module: it is the trigger itself, so it reads one session's current state
and, when warranted, writes to `SessionRepository` -- but it still never
calls `ke`, never runs the crosswalk itself, and never decides *when* a
freshness check happens at all, matching this module's existing "reasoning
lives here, I/O orchestration lives with the caller" split for everything
upstream of it.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from knowledge_engine_ai.ke_client import (
    FederatedCandidateRecord,
    FederatedCoverageReportResult,
    FederatedDiscoverHistoryResult,
    SearchCoverageReport,
)
from knowledge_engine_ai.orchestrator.verification import CITATION_PATTERN
from knowledge_engine_ai.sessions.models import ResearchEvent
from knowledge_engine_ai.sessions.repository import SessionRepository, UnknownSessionError

# A conservative, documented, overridable default -- not a claim about how
# quickly the scholarly literature actually changes. Callers with a
# different tolerance (e.g. a person requesting freshness ad hoc) should
# pass their own `max_age_seconds`.
DEFAULT_MAX_AGE_SECONDS: float = float(7 * 24 * 60 * 60)  # 7 days

_PUBLICATION_STATUS_FLAGS: tuple[str, ...] = (
    "retracted",
    "corrected",
    "expression_of_concern",
    "withdrawn",
)


class ResearchFreshnessError(ValueError):
    """A `SearchCoverageReport.created_at` timestamp could not be parsed."""


@dataclasses.dataclass(frozen=True)
class RerunRecommendation:
    """Whether a fresh federated-discovery run is warranted, and the specific reason why.

    `last_run`/`age_seconds` are `None` only when `history.runs` is empty --
    no prior recorded search for this tracked question is itself the
    reason a rerun (really, a first run) is recommended.
    """

    recommended: bool
    reason: str
    last_run: SearchCoverageReport | None
    age_seconds: float | None


def assess_rerun_need(
    history: FederatedDiscoverHistoryResult,
    *,
    now: datetime,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> RerunRecommendation:
    """Recommend whether to run `federated_discover()` again for this tracked question.

    Two independent, deterministic triggers, evaluated in order:

    1. No run has ever been recorded, or the most recent recorded run did
       not complete (`completeness != "complete"`) -- a rerun may recover
       providers that did not finish, regardless of age.
    2. The most recent *complete* run is older than `max_age_seconds`.

    A complete, recent run recommends against rerunning -- provider count
    and candidate count are never read here; only Core's own recorded
    `completeness` and `created_at` are, matching this project's
    "provider diversity is a retrieval signal, not a confidence shortcut"
    rule applied to freshness reasoning too.
    """

    if not history.runs:
        return RerunRecommendation(
            recommended=True,
            reason=("No federated-discovery run has ever been recorded for this tracked question."),
            last_run=None,
            age_seconds=None,
        )

    last_run = _most_recent_run(history.runs)
    age_seconds = _age_seconds(last_run.created_at, now)

    if last_run.completeness != "complete":
        return RerunRecommendation(
            recommended=True,
            reason=(
                f"The most recent recorded run ({last_run.search_run_id}) finished with "
                f"completeness={last_run.completeness!r}, not 'complete'; a rerun may "
                "recover the providers that did not finish."
            ),
            last_run=last_run,
            age_seconds=age_seconds,
        )

    if age_seconds > max_age_seconds:
        return RerunRecommendation(
            recommended=True,
            reason=(
                f"The most recent recorded run ({last_run.search_run_id}) completed "
                f"{age_seconds:.0f}s ago, past the configured {max_age_seconds:.0f}s "
                "freshness threshold."
            ),
            last_run=last_run,
            age_seconds=age_seconds,
        )

    return RerunRecommendation(
        recommended=False,
        reason=(
            f"The most recent recorded run ({last_run.search_run_id}) completed fully "
            f"{age_seconds:.0f}s ago, within the configured {max_age_seconds:.0f}s "
            "freshness threshold."
        ),
        last_run=last_run,
        age_seconds=age_seconds,
    )


@dataclasses.dataclass(frozen=True)
class PublicationStatusFlip:
    """One candidate whose publication-status flag newly reads asserted-`True`.

    `flag` is one of `_PUBLICATION_STATUS_FLAGS`. "Newly" means at least one
    provider observation in `current` asserts the flag `True` while no
    provider observation for the same candidate in `previous` did --
    `previous` reporting `False` or `None` (not reported) are treated alike
    as "not yet flagged," matching `discovery_policy.py`'s own
    "absent is not negative, but also not a status to diff against" posture.
    """

    canonical_id: str
    title: str
    flag: str


@dataclasses.dataclass(frozen=True)
class CandidateFreshnessDiff:
    """What changed between two specific past runs' full candidate snapshots.

    `newly_discovered` and `newly_flagged` are independent: a candidate can
    appear in `newly_discovered` only (first time this question's search
    ever recorded it) or in `newly_flagged` only (already known, now
    carries a new publication-status assertion) -- never both, since a
    brand-new candidate has nothing in `previous` to diff a flag against.
    """

    newly_discovered: tuple[FederatedCandidateRecord, ...]
    newly_flagged: tuple[PublicationStatusFlip, ...]


def diff_candidate_snapshots(
    previous: FederatedCoverageReportResult,
    current: FederatedCoverageReportResult,
) -> CandidateFreshnessDiff:
    """Diff two point-lookup snapshots by Core's own `canonical_id`.

    Both snapshots ordinarily come from two `federated_coverage_report()`
    calls for the same tracked question's two most recent runs (oldest as
    `previous`, newest as `current`), but this function does not itself
    fetch, order, or select runs -- that remains the caller's job (see
    `assess_rerun_need` above for the separate "is a rerun warranted"
    question, and `cli.py`'s `research-freshness` command for a caller that
    does both). A run recorded before Core's candidate-snapshot follow-up
    existed carries an honest empty `candidates` tuple (not a fabricated
    one); diffing against it reports every current candidate as newly
    discovered, which is the accurate description of "we have no earlier
    snapshot to compare against," not a false positive.
    """

    previous_by_id = {candidate.canonical_id: candidate for candidate in previous.candidates}
    current_by_id = {candidate.canonical_id: candidate for candidate in current.candidates}

    newly_discovered = tuple(
        candidate
        for canonical_id, candidate in current_by_id.items()
        if canonical_id not in previous_by_id
    )

    newly_flagged: list[PublicationStatusFlip] = []
    for canonical_id, candidate in current_by_id.items():
        previous_candidate = previous_by_id.get(canonical_id)
        if previous_candidate is None:
            continue
        for flag in _PUBLICATION_STATUS_FLAGS:
            if _any_observation_asserts(candidate, flag) and not _any_observation_asserts(
                previous_candidate, flag
            ):
                newly_flagged.append(
                    PublicationStatusFlip(
                        canonical_id=canonical_id, title=candidate.title, flag=flag
                    )
                )

    return CandidateFreshnessDiff(
        newly_discovered=newly_discovered,
        newly_flagged=tuple(newly_flagged),
    )


@dataclasses.dataclass(frozen=True)
class NarrativeTouchingFlip:
    """One `PublicationStatusFlip` the crosswalk confirmed actually touches a session's narrative.

    "Touches" means: the flagged candidate's DOI matches a DOI from the
    session's own retrieval step, *and* at least one evidence record from
    that same paper was actually cited (`[evidence_record_id]`,
    `verification.CITATION_PATTERN`) in the session's persisted narrative --
    not merely retrieved as a discovery lead. `cited_evidence_record_ids`
    names every one of the session's own evidence-record ids from that DOI
    that was cited (there can be more than one paper->evidence-record edge
    for the same DOI); it is never empty on a returned `NarrativeTouchingFlip`.
    """

    flip: PublicationStatusFlip
    doi: str
    cited_evidence_record_ids: tuple[str, ...]


def session_retrieval_dois(events: Sequence[ResearchEvent]) -> dict[str, str]:
    """Map each of a session's own retrieved evidence-record ids to its paper's DOI.

    Built from `ResearchEvent.source_dois` -- additive, parallel to the
    pre-existing `source_ids` (see `sessions/models.py`), populated by the
    two retrieval-step events `orchestrator/workflow.py` records. Identified
    structurally (any event whose `source_ids`/`source_dois` pair up), not
    by workflow-node name, so this stays correct even if a future retrieval
    branch is added under a new node. An event from before `source_dois`
    existed contributes nothing here (empty `source_dois`), which is the
    correct "DOI unknown for this old record," never "no DOI" -- and an
    event whose paper had no DOI contributes an empty string, filtered out
    below, since an empty DOI can never legitimately match a flagged
    candidate's own DOI.

    A caller feeds this a session's *own* full event log
    (`SessionRepository.list_events(session_id)`), not this function --
    matching `assess_rerun_need`/`diff_candidate_snapshots`'s "caller owns
    the repository/CLI call" boundary above.
    """

    dois: dict[str, str] = {}
    for event in events:
        for evidence_record_id, doi in zip(event.source_ids, event.source_dois, strict=False):
            if doi and evidence_record_id not in dois:
                dois[evidence_record_id] = doi
    return dois


def crosswalk_publication_status_flips(
    flips: tuple[PublicationStatusFlip, ...],
    *,
    current: FederatedCoverageReportResult,
    retrieval_dois: Mapping[str, str],
    narrative: str,
) -> tuple[NarrativeTouchingFlip, ...]:
    """Which of `flips` actually touch `narrative`'s cited evidence, per "the crosswalk."

    For each flip: 1) look up its `canonical_id` in `current.candidates` to
    get the flagged candidate's own DOI (a flip whose candidate is missing
    from `current`, or whose candidate carries no DOI, cannot be crosswalked
    and is skipped -- Core's own `canonical_id`/`doi` are read verbatim,
    never re-derived); 2) find every one of the session's own retrieval-step
    evidence-record ids that share that DOI (`retrieval_dois`, typically
    built by `session_retrieval_dois()` above); 3) keep only the ones that
    were actually cited in `narrative` (`CITATION_PATTERN.findall`, the
    same pattern `verification.py`/`session_report.py` already share). A
    flip with a DOI match but no citation match is a discovery lead the
    session never promoted to a claim -- a freshness signal only,
    correctly absent from the returned tuple, per the design doc's own
    "the retracted/corrected work was a discovery lead S never promoted to
    a cited claim" rule. Order-preserving over `flips`; does not itself
    decide invalidates-versus-qualifies -- that split reads
    `NarrativeTouchingFlip.flip.flag` (see "Invalidates versus qualifies"
    in the design doc) and is intentionally left to the still-future
    trigger-wiring slice.
    """

    candidates_by_id = {candidate.canonical_id: candidate for candidate in current.candidates}
    cited_evidence_record_ids = frozenset(CITATION_PATTERN.findall(narrative))

    evidence_record_ids_by_doi: dict[str, list[str]] = {}
    for evidence_record_id, doi in retrieval_dois.items():
        if doi:
            evidence_record_ids_by_doi.setdefault(doi, []).append(evidence_record_id)

    touching: list[NarrativeTouchingFlip] = []
    for flip in flips:
        candidate = candidates_by_id.get(flip.canonical_id)
        if candidate is None or not candidate.doi:
            continue
        matching_ids = evidence_record_ids_by_doi.get(candidate.doi, ())
        cited_matching_ids = tuple(
            evidence_record_id
            for evidence_record_id in matching_ids
            if evidence_record_id in cited_evidence_record_ids
        )
        if cited_matching_ids:
            touching.append(
                NarrativeTouchingFlip(
                    flip=flip,
                    doi=candidate.doi,
                    cited_evidence_record_ids=cited_matching_ids,
                )
            )

    return tuple(touching)


_INVALIDATING_FLAGS: frozenset[str] = frozenset({"retracted", "withdrawn"})
_QUALIFYING_FLAGS: frozenset[str] = frozenset({"corrected", "expression_of_concern"})
_NARRATIVE_INVALIDATED_NODE = "narrative_invalidated"
_TRIGGER_EXECUTOR_TYPE = "deterministic_policy"


@dataclasses.dataclass(frozen=True)
class NarrativeFreshnessTriggerResult:
    """What `apply_narrative_touching_flips` did with one batch of `NarrativeTouchingFlip`s.

    Implements `docs/roadmap/answer_session_versioning_design.md`'s
    "Invalidates versus qualifies" split: `retracted`/`withdrawn` flips
    invalidate (a claim resting on that record can no longer be treated as
    supported by it at all); `corrected`/`expression_of_concern` flips
    qualify (the claim may still stand, but must carry a visible caveat).
    Both are version-transition triggers per the design doc; only the
    invalidating half is durably recorded by this call. `qualifying` is
    returned for an immediate caller (logging, an ad hoc report) to act on,
    not persisted -- the `AnswerFreshness` read-side projection that would
    track a durable `pending_flips` list does not exist yet (see the design
    doc's own "What this does not do").

    `invalidating`/`qualifying` report every touching flip found in this
    call's input, regardless of whether `narrative_invalidated_event` ended
    up set -- `narrative_invalidated_at` is set at most once per session
    (`SessionRepository.record_narrative_invalidation`'s own guard), so a
    second invalidating flip in the same batch, or a call against a session
    an earlier batch already invalidated, is still reported here but
    recorded nowhere new. `already_invalidated` distinguishes that case
    (invalidating flips were found, but the session was already
    invalidated before this call) from "an event was newly appended this
    call" (`narrative_invalidated_event is not None`) and from "no
    invalidating flip was present at all" (`invalidating == ()`).
    """

    invalidating: tuple[NarrativeTouchingFlip, ...]
    qualifying: tuple[NarrativeTouchingFlip, ...]
    already_invalidated: bool
    narrative_invalidated_event: ResearchEvent | None


def apply_narrative_touching_flips(
    session_repository: SessionRepository,
    touching_flips: Sequence[NarrativeTouchingFlip],
    *,
    session_id: str,
    now: str | None = None,
) -> NarrativeFreshnessTriggerResult:
    """Decide invalidates-versus-qualifies for one batch of crosswalked flips, and act on it.

    `crosswalk_publication_status_flips` above already decided *which*
    flips touch a session's own cited narrative; this function decides what
    to *do* about each one, per the design doc's "Invalidates versus
    qualifies" section:

    - `retracted`/`withdrawn` -- calls
      `SessionRepository.record_narrative_invalidation`, naming the
      specific `canonical_id`/`doi`/`flag`/cited evidence-record ids in the
      appended event's `notes`, exactly as
      "Releaseability reacts to an invalidating flip immediately" specifies.
      Only the *first* invalidating flip in `touching_flips` is ever
      recorded -- `narrative_invalidated_at` is set at most once per
      session by design, and this function checks the session's current
      state first so a batch containing more than one invalidating flip,
      or a call against a session an earlier freshness-check pass already
      invalidated, never raises `NarrativeAlreadyInvalidatedError`.
    - `corrected`/`expression_of_concern` -- nothing is persisted; see
      `NarrativeFreshnessTriggerResult`'s own docstring for why.

    Never touches `session.status` (`record_narrative_invalidation` itself
    already leaves it untouched, per the design doc) and never calls
    `supersede_session`, which belongs to a later, separate slice (minting
    a version-*N+1* session once one reaches `COMPLETED`).

    Does not itself run the crosswalk, fetch a session's events/narrative,
    or decide *when* a freshness check happens -- `touching_flips` is the
    caller's own `crosswalk_publication_status_flips()` result, matching
    this module's "caller owns the I/O" boundary for everything upstream of
    this function.
    """

    invalidating = tuple(flip for flip in touching_flips if flip.flip.flag in _INVALIDATING_FLAGS)
    qualifying = tuple(flip for flip in touching_flips if flip.flip.flag in _QUALIFYING_FLAGS)
    unrecognized = sorted(
        {
            flip.flip.flag
            for flip in touching_flips
            if flip.flip.flag not in _INVALIDATING_FLAGS and flip.flip.flag not in _QUALIFYING_FLAGS
        }
    )
    if unrecognized:
        raise ValueError(
            f"Unrecognized publication-status flag(s) in touching_flips: {unrecognized!r}; "
            f"expected one of {sorted(_INVALIDATING_FLAGS | _QUALIFYING_FLAGS)!r}."
        )

    if not invalidating:
        return NarrativeFreshnessTriggerResult(
            invalidating=(),
            qualifying=qualifying,
            already_invalidated=False,
            narrative_invalidated_event=None,
        )

    session = session_repository.get_session(session_id)
    if session is None:
        raise UnknownSessionError(f"No session with session_id {session_id!r}.")

    if session.narrative_invalidated_at is not None:
        return NarrativeFreshnessTriggerResult(
            invalidating=invalidating,
            qualifying=qualifying,
            already_invalidated=True,
            narrative_invalidated_event=None,
        )

    occurred_at = now if now is not None else _now_iso()
    first = invalidating[0]
    event = ResearchEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=occurred_at,
        workflow_node=_NARRATIVE_INVALIDATED_NODE,
        executor_type=_TRIGGER_EXECUTOR_TYPE,
        notes=(
            f"canonical_id={first.flip.canonical_id!r} doi={first.doi!r} "
            f"flag={first.flip.flag!r} "
            f"cited_evidence_record_ids={list(first.cited_evidence_record_ids)!r}"
        ),
    )
    session_repository.record_narrative_invalidation(event, invalidated_at=occurred_at)

    return NarrativeFreshnessTriggerResult(
        invalidating=invalidating,
        qualifying=qualifying,
        already_invalidated=False,
        narrative_invalidated_event=event,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _any_observation_asserts(candidate: FederatedCandidateRecord, flag: str) -> bool:
    return any(bool(getattr(observation, flag)) for observation in candidate.observations)


def _most_recent_run(runs: tuple[SearchCoverageReport, ...]) -> SearchCoverageReport:
    return max(runs, key=lambda run: _parse_timestamp(run.created_at))


def _age_seconds(created_at: str, now: datetime) -> float:
    return (now - _parse_timestamp(created_at)).total_seconds()


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchFreshnessError(
            f"Could not parse `SearchCoverageReport.created_at` as an ISO 8601 timestamp: {value!r}"
        ) from exc


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "CandidateFreshnessDiff",
    "NarrativeFreshnessTriggerResult",
    "NarrativeTouchingFlip",
    "PublicationStatusFlip",
    "RerunRecommendation",
    "ResearchFreshnessError",
    "apply_narrative_touching_flips",
    "assess_rerun_need",
    "crosswalk_publication_status_flips",
    "diff_candidate_snapshots",
    "session_retrieval_dois",
]
