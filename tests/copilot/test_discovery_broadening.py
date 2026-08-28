from __future__ import annotations

import pytest

from knowledge_engine_ai.copilot.discovery_broadening import (
    compile_zero_yield_broadening_queries,
)


def test_music_endurance_question_compiles_high_recall_fallbacks() -> None:
    question = (
        "In healthy adults, does listening to music during exercise improve endurance "
        "performance compared with exercising without music?"
    )

    assert compile_zero_yield_broadening_queries(question) == (
        "music exercise endurance",
        "music exercise endurance performance",
    )


def test_nonrepeating_question_uses_edge_concepts_without_question_scaffolding() -> None:
    question = "Does creatine improve short-term memory in sleep-deprived adults?"

    queries = compile_zero_yield_broadening_queries(question, max_queries=3)

    assert queries[0] == "creatine memory sleep-deprived"
    assert queries[1] == "creatine short-term memory sleep-deprived"
    assert queries[2] == "creatine short-term memory sleep-deprived adults"
    assert all("improve" not in query for query in queries)
    assert all("does" not in query for query in queries)


def test_repeated_inflectional_family_is_used_once_as_an_anchor() -> None:
    question = "Does exercise while exercising with music change musical endurance?"

    queries = compile_zero_yield_broadening_queries(question)

    assert queries[0].split().count("exercise") == 1
    assert "exercising" not in queries[0]
    assert queries[0].startswith("exercise")


def test_max_queries_zero_disables_broadening() -> None:
    assert compile_zero_yield_broadening_queries("music exercise endurance", max_queries=0) == ()


@pytest.mark.parametrize("max_queries", [-1, 4])
def test_invalid_query_budget_is_rejected(max_queries: int) -> None:
    with pytest.raises(ValueError, match="max_queries"):
        compile_zero_yield_broadening_queries("music exercise endurance", max_queries=max_queries)


def test_blank_question_is_rejected() -> None:
    with pytest.raises(ValueError, match="question"):
        compile_zero_yield_broadening_queries("   ")
