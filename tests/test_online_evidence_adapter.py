"""AI's corpus-free bridge must not promote unverified Core online evidence."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from knowledge_engine_ai.copilot.online_evidence_adapter import (
    OnlineEvidenceParseError,
    parse_content_checked_online_evidence,
)

SOURCE = "doi:10.1/abc"
CONTENT = "Intro.\r\nTrial found a 12% reduction.\nOther results."
QUOTE = "Trial found a 12% reduction."
START = CONTENT.index(QUOTE)
UNAVAILABLE_URL = "https://example.org/missing"
UNAVAILABLE_ID = "url:" + hashlib.sha256(UNAVAILABLE_URL.encode()).hexdigest()[:16]


def bundle() -> dict[str, Any]:
    excerpt_id = (
        SOURCE + "#" + hashlib.sha256(f"{SOURCE}\n{START}\n{QUOTE}".encode()).hexdigest()[:12]
    )
    return {
        "schema": "ke-online-evidence/v1",
        "question": "What changed?",
        "sources": [
            {
                "source_id": SOURCE,
                "url": "https://example.org/study",
                "retrieved_at": "2026-11-02T10:00:00+00:00",
                "status": "retrieved",
                "provider": "openalex",
                "title": "Study",
                "doi": "10.1/ABC",
                "content_sha256": hashlib.sha256(CONTENT.encode()).hexdigest(),
                "failure_reason": None,
            },
            {
                "source_id": UNAVAILABLE_ID,
                "url": UNAVAILABLE_URL,
                "retrieved_at": "2026-11-02T10:00:00+00:00",
                "status": "unavailable",
                "provider": "openalex",
                "content_sha256": None,
                "failure_reason": "HTTP 404",
            },
        ],
        "excerpts": [
            {
                "excerpt_id": excerpt_id,
                "source_id": SOURCE,
                "text": QUOTE,
                "char_start": START,
                "char_end": START + len(QUOTE),
                "locator": "Results",
            }
        ],
        "claims": [
            {
                "claim_id": "c1",
                "text": "The trial found a reduction.",
                "status": "supported",
                "citations": [{"excerpt_id": excerpt_id, "stance": "supports"}],
            }
        ],
    }


def test_content_checked_bundle_keeps_online_provenance_without_a_corpus() -> None:
    result = parse_content_checked_online_evidence(bundle(), {SOURCE: CONTENT})
    assert result.question == "What changed?"
    assert [source.status for source in result.sources] == ["retrieved", "unavailable"]
    assert result.sources[0].content_sha256 == hashlib.sha256(CONTENT.encode()).hexdigest()
    assert result.sources[1].failure_reason == "HTTP 404"
    assert result.excerpts[0].text == QUOTE
    assert (result.excerpts[0].char_start, result.excerpts[0].char_end) == (
        START,
        START + len(QUOTE),
    )
    assert result.claims[0].status == "supported"
    assert result.claims[0].citations[0].excerpt_id == result.excerpts[0].excerpt_id


def test_empty_claims_and_unavailable_sources_do_not_become_evidence() -> None:
    payload = bundle()
    payload["claims"] = []
    payload["excerpts"] = []
    result = parse_content_checked_online_evidence(payload, {SOURCE: CONTENT})
    assert result.claims == () and result.excerpts == ()
    assert len(result.sources) == 2


def test_contested_claim_is_computed_from_both_stances() -> None:
    payload = bundle()
    claim = payload["claims"][0]
    claim["citations"].append(
        {"excerpt_id": payload["excerpts"][0]["excerpt_id"], "stance": "contradicts"}
    )
    claim["status"] = "contested"
    result = parse_content_checked_online_evidence(payload, {SOURCE: CONTENT})
    assert result.claims[0].status == "contested"


@pytest.mark.parametrize(
    "change",
    [
        "bad_schema",
        "missing_source",
        "bad_hash",
        "bad_offset",
        "bad_excerpt_id",
        "unknown_citation",
        "false_claim_status",
        "duplicate_source",
        "duplicate_excerpt",
        "non_utc",
        "bad_status",
        "bad_url",
        "unavailable_quote",
        "unavailable_hash",
        "missing_failure_reason",
        "wrong_excerpt_text",
        "oversized_excerpt",
    ],
)
def test_bad_online_evidence_fails_closed(change: str) -> None:
    payload = copy.deepcopy(bundle())
    contents = {SOURCE: CONTENT}
    source = payload["sources"][0]
    excerpt = payload["excerpts"][0]
    claim = payload["claims"][0]

    if change == "bad_schema":
        payload["schema"] = "unknown/v1"
    elif change == "missing_source":
        contents.clear()
    elif change == "bad_hash":
        source["content_sha256"] = "0" * 64
    elif change == "bad_offset":
        excerpt["char_start"] = START + 1
        excerpt["char_end"] = START + 1 + len(QUOTE)
    elif change == "bad_excerpt_id":
        excerpt["excerpt_id"] = "forged"
    elif change == "unknown_citation":
        claim["citations"][0]["excerpt_id"] = "not-an-excerpt"
    elif change == "false_claim_status":
        claim["status"] = "contested"
    elif change == "duplicate_source":
        payload["sources"].append(copy.deepcopy(source))
    elif change == "duplicate_excerpt":
        payload["excerpts"].append(copy.deepcopy(excerpt))
    elif change == "non_utc":
        source["retrieved_at"] = "2026-11-02T10:00:00-06:00"
    elif change == "bad_status":
        source["status"] = "trusted"
    elif change == "bad_url":
        source["url"] = "file:///private"
    elif change == "unavailable_quote":
        excerpt["source_id"] = UNAVAILABLE_ID
    elif change == "unavailable_hash":
        payload["sources"][1]["content_sha256"] = "0" * 64
    elif change == "missing_failure_reason":
        payload["sources"][1]["failure_reason"] = None
    elif change == "wrong_excerpt_text":
        contents[SOURCE] = CONTENT.replace("12%", "99%")
        source["content_sha256"] = hashlib.sha256(contents[SOURCE].encode()).hexdigest()
    elif change == "oversized_excerpt":
        excerpt["text"] = "x" * 1201

    with pytest.raises(OnlineEvidenceParseError):
        parse_content_checked_online_evidence(payload, contents)


def test_unavailable_content_and_unrecognized_content_are_rejected() -> None:
    with pytest.raises(OnlineEvidenceParseError):
        parse_content_checked_online_evidence(
            bundle(), {SOURCE: CONTENT, UNAVAILABLE_ID: "not citeable"}
        )
    with pytest.raises(OnlineEvidenceParseError):
        parse_content_checked_online_evidence(
            bundle(), {SOURCE: CONTENT, "unknown": "not citeable"}
        )


def test_content_without_offsets_must_still_be_verbatim() -> None:
    payload = bundle()
    excerpt = payload["excerpts"][0]
    excerpt["char_start"] = None
    excerpt["char_end"] = None
    excerpt["excerpt_id"] = (
        SOURCE + "#" + hashlib.sha256(f"{SOURCE}\n\n{QUOTE}".encode()).hexdigest()[:12]
    )
    payload["claims"][0]["citations"][0]["excerpt_id"] = excerpt["excerpt_id"]
    result = parse_content_checked_online_evidence(payload, {SOURCE: CONTENT})
    assert result.excerpts[0].char_start is None

    excerpt["text"] = "invented"
    excerpt["excerpt_id"] = (
        SOURCE + "#" + hashlib.sha256(f"{SOURCE}\n\ninvented".encode()).hexdigest()[:12]
    )
    with pytest.raises(OnlineEvidenceParseError):
        parse_content_checked_online_evidence(payload, {SOURCE: CONTENT})
