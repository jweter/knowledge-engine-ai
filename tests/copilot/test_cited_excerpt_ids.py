from __future__ import annotations

import copy

from knowledge_engine_ai.copilot.cited_excerpt_ids import extract_cited_excerpt_ids


def test_empty_conclusion_rows_returns_empty_list() -> None:
    assert extract_cited_excerpt_ids([]) == []


def test_single_row_orders_supporting_before_contradicting() -> None:
    rows = [
        {
            "supporting_evidence_ids": ["e1", "e2"],
            "contradicting_or_null_evidence_ids": ["e3"],
        }
    ]

    assert extract_cited_excerpt_ids(rows) == ["e1", "e2", "e3"]


def test_duplicate_ids_across_rows_are_deduplicated_by_first_occurrence() -> None:
    rows = [
        {
            "supporting_evidence_ids": ["e1", "e3"],
            "contradicting_or_null_evidence_ids": ["e2"],
        },
        {
            "supporting_evidence_ids": ["e3", "e5"],
            "contradicting_or_null_evidence_ids": ["e4", "e6"],
        },
    ]

    assert extract_cited_excerpt_ids(rows) == ["e1", "e3", "e2", "e5", "e4", "e6"]


def test_duplicate_within_a_single_row_keeps_first_occurrence_position() -> None:
    rows = [
        {
            "supporting_evidence_ids": ["e1"],
            "contradicting_or_null_evidence_ids": ["e1", "e2"],
        }
    ]

    assert extract_cited_excerpt_ids(rows) == ["e1", "e2"]


def test_matching_is_exact_string_no_case_or_numeric_normalization() -> None:
    rows = [
        {
            "supporting_evidence_ids": ["E1", "e1", "01"],
            "contradicting_or_null_evidence_ids": ["1.0"],
        }
    ]

    assert extract_cited_excerpt_ids(rows) == ["E1", "e1", "01", "1.0"]


def test_input_list_is_not_mutated() -> None:
    rows = [
        {
            "supporting_evidence_ids": ["e1"],
            "contradicting_or_null_evidence_ids": ["e2"],
        }
    ]
    original = copy.deepcopy(rows)

    extract_cited_excerpt_ids(rows)

    assert rows == original
