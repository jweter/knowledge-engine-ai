"""Fail-closed, corpus-free input boundary for Core's online evidence JSON.

This adapter checks that quoted passages match the supplied temporary retrieved
text and its recorded SHA-256. It does not fetch URLs, validate provider claims,
establish scientific truth, or manufacture legacy corpus EvidenceRecords.
Callers must keep the Core retrieval/validation receipt and source provenance.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "ke-online-evidence/v1"
_STATUSES = frozenset({"retrieved", "unavailable", "not_permitted", "failed"})
_STANCES = frozenset({"supports", "contradicts", "inconclusive"})
_MAX_EXCERPT_CHARS = 1200


class OnlineEvidenceParseError(ValueError):
    """The online evidence cannot be safely used as grounded report input."""


@dataclass(frozen=True)
class OnlineSource:
    source_id: str
    url: str
    provider: str
    retrieved_at: str
    status: str
    content_sha256: str | None
    failure_reason: str | None
    title: str | None


@dataclass(frozen=True)
class OnlineExcerpt:
    excerpt_id: str
    source_id: str
    text: str
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True)
class OnlineCitation:
    excerpt_id: str
    stance: str


@dataclass(frozen=True)
class OnlineClaim:
    claim_id: str
    text: str
    status: str
    citations: tuple[OnlineCitation, ...]


@dataclass(frozen=True)
class ContentCheckedOnlineEvidence:
    """Evidence whose supplied text matches hashes and every excerpt.

    Content consistency is not independent verification of the URL, provider,
    source authenticity, scientific claims, or suitability for synthesis.
    """

    question: str
    sources: tuple[OnlineSource, ...]
    excerpts: tuple[OnlineExcerpt, ...]
    claims: tuple[OnlineClaim, ...]


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OnlineEvidenceParseError(f"{label} must be an object.")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise OnlineEvidenceParseError(f"{label} must be an array.")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnlineEvidenceParseError(f"{label} must be non-empty text.")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OnlineEvidenceParseError(f"{label} must be text or null.")
    return value


def _unique(identifier: str, seen: set[str], label: str) -> None:
    if identifier in seen:
        raise OnlineEvidenceParseError(f"Duplicate {label}.")
    seen.add(identifier)


def parse_content_checked_online_evidence(
    payload: Mapping[str, Any], contents: Mapping[str, str]
) -> ContentCheckedOnlineEvidence:
    """Parse Core's v1 bundle without an indexed corpus or local LLM.

    `contents` maps Core source IDs to the exact UTF-8 text fetched for this
    request. Every retrieved source must have matching content; non-retrieved
    sources are retained as unavailable, never treated as citeable.
    """
    if not isinstance(payload, Mapping) or not isinstance(contents, Mapping):
        raise OnlineEvidenceParseError("Online evidence and contents must be objects.")
    if payload.get("schema") != SCHEMA:
        raise OnlineEvidenceParseError("Unsupported online evidence schema.")
    question = _text(payload.get("question"), "question")
    sources: list[OnlineSource] = []
    source_by_id: dict[str, OnlineSource] = {}
    source_ids: set[str] = set()
    for index, raw in enumerate(_array(payload.get("sources"), "sources")):
        item = _object(raw, f"source {index}")
        source_id = _text(item.get("source_id"), "source_id")
        _unique(source_id, source_ids, "source_id")
        url = _text(item.get("url"), "source URL")
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise OnlineEvidenceParseError("Malformed source URL.") from exc
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise OnlineEvidenceParseError("Source URL must be HTTP(S).")
        provider = _text(item.get("provider"), "provider")
        retrieved_at = _text(item.get("retrieved_at"), "retrieved_at")
        try:
            parsed_time = datetime.fromisoformat(retrieved_at)
        except ValueError as exc:
            raise OnlineEvidenceParseError("Invalid retrieval timestamp.") from exc
        if parsed_time.utcoffset() != timedelta(0):
            raise OnlineEvidenceParseError("Retrieval timestamp must be UTC.")
        status = _text(item.get("status"), "retrieval status")
        if status not in _STATUSES:
            raise OnlineEvidenceParseError("Unsupported retrieval status.")
        digest = _optional_text(item.get("content_sha256"), "content_sha256")
        failure_reason = _optional_text(item.get("failure_reason"), "failure_reason")
        title = _optional_text(item.get("title"), "title")
        if status == "retrieved":
            if (
                digest is None
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise OnlineEvidenceParseError("Retrieved source lacks a valid SHA-256.")
            if failure_reason is not None:
                raise OnlineEvidenceParseError("Retrieved source cannot report a failure.")
            content = contents.get(source_id)
            if not isinstance(content, str):
                raise OnlineEvidenceParseError("Retrieved source content is unavailable.")
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != digest:
                raise OnlineEvidenceParseError("Retrieved source content hash mismatch.")
        elif digest is not None or not (failure_reason or "").strip() or source_id in contents:
            raise OnlineEvidenceParseError("Unavailable source cannot provide citeable content.")
        source = OnlineSource(
            source_id, url, provider, retrieved_at, status, digest, failure_reason, title
        )
        sources.append(source)
        source_by_id[source_id] = source

    if any(source_id not in source_by_id for source_id in contents):
        raise OnlineEvidenceParseError("Unrecognized retrieved content source.")

    excerpts: list[OnlineExcerpt] = []
    excerpt_ids: set[str] = set()
    for index, raw in enumerate(_array(payload.get("excerpts", []), "excerpts")):
        item = _object(raw, f"excerpt {index}")
        excerpt_id = _text(item.get("excerpt_id"), "excerpt_id")
        _unique(excerpt_id, excerpt_ids, "excerpt_id")
        source_id = _text(item.get("source_id"), "excerpt source_id")
        excerpt_source = source_by_id.get(source_id)
        if excerpt_source is None or excerpt_source.status != "retrieved":
            raise OnlineEvidenceParseError("Excerpt cites a missing or unavailable source.")
        quote = _text(item.get("text"), "excerpt text")
        if len(quote) > _MAX_EXCERPT_CHARS:
            raise OnlineEvidenceParseError("Excerpt exceeds Core's length limit.")
        start, end = item.get("char_start"), item.get("char_end")
        if (start is None) != (end is None):
            raise OnlineEvidenceParseError("Excerpt offsets must be paired.")
        if start is not None and (
            type(start) is not int or type(end) is not int or start < 0 or end - start != len(quote)
        ):
            raise OnlineEvidenceParseError("Invalid excerpt offsets.")
        # Core hashes source ID, newline, offset (or empty), newline and quote.
        material = f"{source_id}\n{start if start is not None else ''}\n{quote}"
        expected_id = f"{source_id}#{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"
        if excerpt_id != expected_id:
            raise OnlineEvidenceParseError("Excerpt identity does not match its text.")
        content = contents[source_id]
        if (content[start:end] if start is not None else quote) != quote or (
            start is None and quote not in content
        ):
            raise OnlineEvidenceParseError("Excerpt is not present in retrieved content.")
        excerpts.append(OnlineExcerpt(excerpt_id, source_id, quote, start, end))

    claims: list[OnlineClaim] = []
    claim_ids: set[str] = set()
    for index, raw in enumerate(_array(payload.get("claims", []), "claims")):
        item = _object(raw, f"claim {index}")
        claim_id = _text(item.get("claim_id"), "claim_id")
        _unique(claim_id, claim_ids, "claim_id")
        text = _text(item.get("text"), "claim text")
        citations: list[OnlineCitation] = []
        for raw_citation in _array(item.get("citations", []), "citations"):
            citation = _object(raw_citation, "citation")
            excerpt_id = _text(citation.get("excerpt_id"), "citation excerpt_id")
            stance = _text(citation.get("stance"), "citation stance")
            if excerpt_id not in excerpt_ids or stance not in _STANCES:
                raise OnlineEvidenceParseError("Claim contains an invalid citation.")
            citations.append(OnlineCitation(excerpt_id, stance))
        stances = {citation.stance for citation in citations}
        computed = (
            "contested"
            if {"supports", "contradicts"} <= stances
            else "supported"
            if "supports" in stances
            else "contradicted"
            if "contradicts" in stances
            else "insufficient_evidence"
        )
        if item.get("status") != computed:
            raise OnlineEvidenceParseError("Claim status disagrees with its citations.")
        claims.append(OnlineClaim(claim_id, text, computed, tuple(citations)))

    return ContentCheckedOnlineEvidence(question, tuple(sources), tuple(excerpts), tuple(claims))
