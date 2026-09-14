from pathlib import Path


def test_reconcile_workflow_publishes_branch_without_token_pr_creation() -> None:
    workflow = Path(".github/workflows/reconcile-live-status.yml").read_text(encoding="utf-8")

    assert 'BRANCH="automation/status-reconcile"' in workflow
    assert 'git push --force-with-lease origin "$BRANCH"' in workflow
    assert "gh pr create" not in workflow
    assert "GH_TOKEN:" not in workflow
    assert "pull-requests: write" not in workflow
