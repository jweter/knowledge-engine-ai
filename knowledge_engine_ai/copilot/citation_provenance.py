"""Map excerpt_id -> its source's citeable provenance fields.

A pure lookup join between two plain-dict lists: Core's per-call `sources`
(one entry per retrieved source, keyed by `source_id`) and `excerpts` (one
entry per quoted excerpt, each naming the `source_id` it was drawn from).
Callers resolve a ResearchReport's cited `excerpt_id`s back to a stable
`{source_id, url, provider, retrieved_at, title}` record after Core's
temporary retrieved content has been discarded.
"""

from __future__ import annotations

from typing import Any


def build_citation_provenance_index(
    sources: list[dict[str, Any]], excerpts: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_by_id[source["source_id"]] = source

    index: dict[str, dict[str, Any]] = {}
    seen_excerpt_ids: set[str] = set()
    for excerpt in excerpts:
        excerpt_id = excerpt["excerpt_id"]
        if excerpt_id in seen_excerpt_ids:
            continue
        seen_excerpt_ids.add(excerpt_id)
        matched_source = source_by_id.get(excerpt["source_id"])
        if matched_source is None:
            continue
        index[excerpt_id] = {
            "source_id": matched_source["source_id"],
            "url": matched_source["url"],
            "provider": matched_source["provider"],
            "retrieved_at": matched_source["retrieved_at"],
            "title": matched_source["title"],
        }
    return index
