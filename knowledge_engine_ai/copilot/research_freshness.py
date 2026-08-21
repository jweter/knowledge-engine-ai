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
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from knowledge_engine_ai.ke_client import (
    FederatedCandidateRecord,
    FederatedCoverageReportResult,
    FederatedDiscoverHistoryResult,
    SearchCoverageReport,
)

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
    "PublicationStatusFlip",
    "RerunRecommendation",
    "ResearchFreshnessError",
    "assess_rerun_need",
    "diff_candidate_snapshots",
]
