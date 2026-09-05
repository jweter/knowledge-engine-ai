from __future__ import annotations

from datetime import UTC, datetime

from engineering.compounding_metrics import (
    UNKNOWN,
    automation_attributed,
    dependency_unlock_rate,
    pull_has_human_intervention,
    repeat_failure_rate,
    safe_ratio,
    window_metrics,
)


def test_safe_ratio_rejects_bool_and_zero_denominator() -> None:
    assert safe_ratio(True, 1) == UNKNOWN
    assert safe_ratio(1, False) == UNKNOWN
    assert safe_ratio(1, 0) == UNKNOWN


def test_automation_attribution_is_conservative_proxy() -> None:
    assert automation_attributed({"head": {"ref": "orchestrator/example"}, "user": {}})
    assert automation_attributed({"head": {"ref": "main"}, "user": {"type": "Bot"}})
    assert not automation_attributed(
        {"head": {"ref": "feature/manual"}, "user": {"type": "User", "login": "alice"}}
    )


def test_repeat_failure_rate_counts_repeated_workflow_signatures() -> None:
    runs = [
        {
            "name": "CI",
            "created_at": "2026-08-02T00:00:00Z",
            "conclusion": "failure",
        },
        {
            "name": "CI",
            "created_at": "2026-08-03T00:00:00Z",
            "conclusion": "failure",
        },
        {
            "name": "Security",
            "created_at": "2026-08-04T00:00:00Z",
            "conclusion": "failure",
        },
        {
            "name": "CI",
            "created_at": "2026-07-01T00:00:00Z",
            "conclusion": "failure",
        },
    ]
    rate = repeat_failure_rate(
        runs,
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert rate == 0.3333


def test_dependency_unlock_rate_requires_explicit_dependency_edges() -> None:
    issues = [
        {
            "number": 10,
            "body": "blocked by #11",
            "closed_at": "2026-08-20T00:00:00Z",
        },
        {
            "number": 11,
            "body": "",
            "closed_at": "2026-08-10T00:00:00Z",
        },
        {
            "number": 12,
            "body": "unrelated prose",
            "closed_at": "2026-08-11T00:00:00Z",
        },
    ]
    rate = dependency_unlock_rate(
        issues,
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        merged_prs=2,
    )
    assert rate == 0.5


def test_human_intervention_requires_non_bot_activity() -> None:
    reviews = [{"user": {"login": "reviewer", "type": "User"}}]
    comments = [{"user": {"login": "github-actions[bot]", "type": "Bot"}}]
    merged_at = datetime(2026, 8, 10, tzinfo=UTC)
    reviews[0]["submitted_at"] = "2026-08-09T00:00:00Z"
    comments[0]["created_at"] = "2026-08-09T00:00:00Z"
    assert pull_has_human_intervention(1, reviews, comments, merged_at)
    assert not pull_has_human_intervention(
        1,
        [
            {
                "user": {"login": "codex[bot]", "type": "Bot"},
                "submitted_at": "2026-08-09T00:00:00Z",
            }
        ],
        comments,
        merged_at,
    )


def test_window_metrics_collects_all_four_new_rates() -> None:
    pulls = [
        {
            "number": 1,
            "created_at": "2026-08-01T00:00:00Z",
            "merged_at": "2026-08-02T00:00:00Z",
            "head": {"ref": "orchestrator/test"},
            "user": {"login": "alice", "type": "User"},
        },
        {
            "number": 2,
            "created_at": "2026-08-03T00:00:00Z",
            "merged_at": "2026-08-05T00:00:00Z",
            "head": {"ref": "feature/manual"},
            "user": {"login": "bob", "type": "User"},
        },
    ]
    runs = [
        {
            "name": "CI",
            "created_at": "2026-08-03T00:00:00Z",
            "conclusion": "failure",
        },
        {
            "name": "CI",
            "created_at": "2026-08-04T00:00:00Z",
            "conclusion": "failure",
        },
    ]
    issues = [
        {
            "number": 10,
            "body": "blocked by #11",
            "closed_at": "2026-08-20T00:00:00Z",
        },
        {
            "number": 11,
            "body": "",
            "closed_at": "2026-08-10T00:00:00Z",
        },
    ]
    result = window_metrics(
        pulls,
        runs,
        issues,
        {1: False, 2: True},
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert result["merged_prs"] == 2
    assert result["median_pr_cycle_hours"] == 36.0
    assert result["repeat_failure_rate"] == 0.5
    assert result["autonomous_completion_rate"] == 0.5
    assert result["dependency_unlock_rate"] == 0.5
    assert result["human_intervention_rate"] == 0.5


def test_post_merge_human_activity_does_not_rewrite_history() -> None:
    merged_at = datetime(2026, 8, 10, tzinfo=UTC)
    reviews = [
        {
            "user": {"login": "reviewer", "type": "User"},
            "submitted_at": "2026-08-11T00:00:00Z",
        }
    ]
    comments = [
        {
            "user": {"login": "reviewer", "type": "User"},
            "created_at": "2026-08-12T00:00:00Z",
        }
    ]
    assert not pull_has_human_intervention(1, reviews, comments, merged_at)
