"""Bounded process-local cache for successful indexed retrieval results.

The cache is intentionally conservative: entries are keyed by normalized query,
retrieval limit, content-addressed source/evidence revisions, and the concrete
execution context. Failed or unreadable retrievals are never cached. Returning a
cached report does not change evidence semantics; it reuses a previously parsed
and enriched Core result only while the underlying indexed inputs are unchanged.
"""

from __future__ import annotations

import copy
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from knowledge_engine_ai.models import EvidenceReport

_MAX_CACHE_ENTRIES = 64


@dataclass(frozen=True)
class RetrievalCacheKey:
    """Stable identity for one reusable indexed-retrieval result."""

    normalized_query: str
    limit: int
    sources_revision: str
    evidence_revision: str
    sources_path: str
    evidence_path: str
    working_directory: str
    ke_executable: str


_CACHE: OrderedDict[RetrievalCacheKey, EvidenceReport] = OrderedDict()
_CACHE_LOCK = RLock()


def normalize_retrieval_query(query: str) -> str:
    """Collapse insignificant whitespace and case for cache identity only."""

    return " ".join(query.split()).casefold()


def content_revision(path: Path) -> str | None:
    """Return a SHA-256 revision, or ``None`` when the file cannot be read.

    Returning ``None`` disables caching for that call rather than changing the
    existing retrieval failure semantics by raising before Core gets a chance to
    report the real error.
    """

    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None
    return f"sha256:{digest}"


def build_retrieval_cache_key(
    query: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int,
    ke_executable: str,
) -> RetrievalCacheKey | None:
    """Build a cache key only when both indexed inputs are content-addressable."""

    sources_revision = content_revision(sources)
    evidence_revision = content_revision(evidence)
    if sources_revision is None or evidence_revision is None:
        return None

    return RetrievalCacheKey(
        normalized_query=normalize_retrieval_query(query),
        limit=limit,
        sources_revision=sources_revision,
        evidence_revision=evidence_revision,
        sources_path=str(sources.resolve()),
        evidence_path=str(evidence.resolve()),
        working_directory=str(Path.cwd().resolve()),
        ke_executable=ke_executable,
    )


def get_cached_retrieval_report(key: RetrievalCacheKey | None) -> EvidenceReport | None:
    """Return an isolated copy of a cached successful report, if present."""

    if key is None:
        return None
    with _CACHE_LOCK:
        report = _CACHE.get(key)
        if report is None:
            return None
        _CACHE.move_to_end(key)
        return copy.deepcopy(report)


def store_cached_retrieval_report(
    key: RetrievalCacheKey | None,
    report: EvidenceReport,
) -> None:
    """Store one successful report and evict least-recently-used entries."""

    if key is None:
        return
    with _CACHE_LOCK:
        _CACHE[key] = copy.deepcopy(report)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_CACHE_ENTRIES:
            _CACHE.popitem(last=False)


def clear_retrieval_cache() -> None:
    """Clear process-local retrieval reuse state; primarily useful for tests."""

    with _CACHE_LOCK:
        _CACHE.clear()


def retrieval_cache_size() -> int:
    """Return the current bounded cache entry count."""

    with _CACHE_LOCK:
        return len(_CACHE)


__all__ = [
    "RetrievalCacheKey",
    "build_retrieval_cache_key",
    "clear_retrieval_cache",
    "content_revision",
    "get_cached_retrieval_report",
    "normalize_retrieval_query",
    "retrieval_cache_size",
    "store_cached_retrieval_report",
]
