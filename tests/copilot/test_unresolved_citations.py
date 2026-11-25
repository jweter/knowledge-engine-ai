from __future__ import annotations

import copy

from knowledge_engine_ai.copilot.unresolved_citations import find_unresolved_citations


def test_empty_cited_ids_returns_empty_list() -> None:
    assert find_unresolved_citations([], {}) == []
    assert find_unresolved_citations([], {"e1": {"source_id": "s1"}}) == []


def test_ids_with_a_provenance_key_are_resolved() -> None:
    assert find_unresolved_citations(["e1", "e2"], {"e1": {"source_id": "s1"}}) == ["e2"]


def test_all_resolved_returns_empty_list() -> None:
    provenance = {"e1": {"source_id": "s1"}, "e2": {"source_id": "s2"}}

    assert find_unresolved_citations(["e1", "e2", "e1"], provenance) == []


def test_duplicate_unresolved_ids_are_reported_once_in_first_occurrence_order() -> None:
    assert find_unresolved_citations(["e1", "e2", "e1"], {}) == ["e1", "e2"]
    assert find_unresolved_citations(["b", "a", "b", "a"], {}) == ["b", "a"]


def test_matching_is_exact_string_equality() -> None:
    assert find_unresolved_citations(["E1", "e1 "], {"e1": {}}) == ["E1", "e1 "]


def test_arguments_are_not_mutated_and_a_new_list_is_returned() -> None:
    cited = ["e1", "e2"]
    provenance = {"e1": {"source_id": "s1"}}
    cited_before = copy.deepcopy(cited)
    provenance_before = copy.deepcopy(provenance)

    result = find_unresolved_citations(cited, provenance)

    assert cited == cited_before
    assert provenance == provenance_before
    assert result is not cited
