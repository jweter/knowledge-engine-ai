from __future__ import annotations

import copy

from knowledge_engine_ai.copilot.citation_provenance import (
    build_citation_provenance_index,
)


def test_single_excerpt_copies_its_matching_source_fields() -> None:
    sources = [
        {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "title": "A",
        }
    ]
    excerpts = [{"excerpt_id": "s1#abc", "source_id": "s1", "text": "hello"}]

    result = build_citation_provenance_index(sources, excerpts)

    assert result == {
        "s1#abc": {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "title": "A",
        }
    }


def test_excerpt_with_no_matching_source_is_omitted() -> None:
    result = build_citation_provenance_index(
        [], [{"excerpt_id": "s1#abc", "source_id": "s1", "text": "hello"}]
    )

    assert result == {}


def test_duplicate_excerpt_id_keeps_only_first_occurrence() -> None:
    sources = [
        {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "t1",
            "title": None,
        },
        {
            "source_id": "s2",
            "url": "https://b.example/y",
            "provider": "news",
            "retrieved_at": "t2",
            "title": None,
        },
    ]
    excerpts = [
        {"excerpt_id": "e1", "source_id": "s1", "text": "first"},
        {"excerpt_id": "e1", "source_id": "s2", "text": "second"},
    ]

    result = build_citation_provenance_index(sources, excerpts)

    assert result == {
        "e1": {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "t1",
            "title": None,
        }
    }


def test_empty_excerpts_returns_empty_dict() -> None:
    sources = [
        {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "t1",
            "title": "A",
        }
    ]

    assert build_citation_provenance_index(sources, []) == {}


def test_only_the_five_provenance_fields_are_copied() -> None:
    sources = [
        {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "t1",
            "title": "A",
            "raw_content": "this should not appear in the result",
        }
    ]
    excerpts = [{"excerpt_id": "e1", "source_id": "s1", "text": "hello"}]

    result = build_citation_provenance_index(sources, excerpts)

    assert set(result["e1"].keys()) == {
        "source_id",
        "url",
        "provider",
        "retrieved_at",
        "title",
    }


def test_does_not_mutate_its_arguments() -> None:
    sources = [
        {
            "source_id": "s1",
            "url": "https://a.example/x",
            "provider": "web",
            "retrieved_at": "t1",
            "title": "A",
        }
    ]
    excerpts = [{"excerpt_id": "e1", "source_id": "s1", "text": "hello"}]
    sources_before = copy.deepcopy(sources)
    excerpts_before = copy.deepcopy(excerpts)

    build_citation_provenance_index(sources, excerpts)

    assert sources == sources_before
    assert excerpts == excerpts_before
