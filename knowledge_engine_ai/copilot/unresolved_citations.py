"""Report which cited excerpt ids have no provenance entry.

Pure check over plain values: an id is unresolved when it is not a key of
the citation provenance mapping. Matching is exact string equality, the
result is deduplicated in first-occurrence order, and neither argument is
mutated.
"""

from __future__ import annotations

from typing import Any


def find_unresolved_citations(
    cited_excerpt_ids: list[str], citation_provenance: dict[str, Any]
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for excerpt_id in cited_excerpt_ids:
        if excerpt_id in citation_provenance or excerpt_id in seen:
            continue
        seen.add(excerpt_id)
        result.append(excerpt_id)
    return result
