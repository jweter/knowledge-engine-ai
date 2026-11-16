"""Collect every excerpt_id cited by a ResearchReport's conclusion rows.

Pure extraction over plain-dict conclusion rows: each row names the
excerpt_ids backing it as `supporting_evidence_ids` and
`contradicting_or_null_evidence_ids`. Callers use the combined,
deduplicated, order-preserving list to resolve citations without
re-walking the full report structure themselves.
"""

from __future__ import annotations

from typing import Any


def extract_cited_excerpt_ids(conclusion_rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in conclusion_rows:
        for excerpt_id in row["supporting_evidence_ids"]:
            if excerpt_id not in seen:
                seen.add(excerpt_id)
                result.append(excerpt_id)
        for excerpt_id in row["contradicting_or_null_evidence_ids"]:
            if excerpt_id not in seen:
                seen.add(excerpt_id)
                result.append(excerpt_id)
    return result
