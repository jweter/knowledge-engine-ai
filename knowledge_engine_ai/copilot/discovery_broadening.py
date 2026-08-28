"""Deterministic recall-oriented query broadening for zero-yield discovery.

The production discovery policy starts with the researcher's full natural-language
question.  Some scholarly providers interpret that text too literally and return no
candidates even when relevant literature exists.  This module provides a small,
provider-neutral fallback that removes question scaffolding and emits a bounded set
of progressively broader keyword queries.

These strings are discovery artifacts only.  They are never Evidence Records, never
scientific claims, and never bypass acquisition, grounding, or re-retrieval gates.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

MAX_ZERO_YIELD_BROADENING_QUERIES = 3

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "between",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "than",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "those",
        "to",
        "versus",
        "vs",
        "was",
        "were",
        "what",
        "when",
        "whether",
        "which",
        "while",
        "who",
        "with",
        "without",
        "would",
    }
)

# Verbs/adjectives that usually express the *question being asked* rather than
# the literature topic itself.  Removing them broadens recall without asserting
# that the effect exists.
_QUESTION_SCAFFOLDING = frozenset(
    {
        "affect",
        "affected",
        "affecting",
        "affects",
        "associate",
        "associated",
        "association",
        "associations",
        "cause",
        "caused",
        "causes",
        "causing",
        "compare",
        "compared",
        "compares",
        "comparing",
        "decrease",
        "decreased",
        "decreases",
        "decreasing",
        "effect",
        "effects",
        "impact",
        "impacts",
        "improve",
        "improved",
        "improves",
        "improving",
        "increase",
        "increased",
        "increases",
        "increasing",
        "influence",
        "influences",
        "reduce",
        "reduced",
        "reduces",
        "reducing",
        "relationship",
        "relationships",
    }
)

# These terms can be important in the full fallback query, but they are usually
# weak anchors for the most aggressive compact recall query.  They are therefore
# excluded only from compact-tail selection, never from the complete content set.
_LOW_INFORMATION_COMPACT_TERMS = frozenset(
    {
        "adult",
        "adults",
        "evidence",
        "healthy",
        "human",
        "humans",
        "participant",
        "participants",
        "patient",
        "patients",
        "people",
        "person",
        "persons",
        "research",
        "study",
        "studies",
    }
)


@dataclass(frozen=True)
class _TermFamily:
    family: str
    surface: str
    first_index: int
    frequency: int


def compile_zero_yield_broadening_queries(
    question: str,
    *,
    max_queries: int = 2,
) -> tuple[str, ...]:
    """Return bounded, deterministic recall-oriented queries for a zero-yield question.

    The first fallback is intentionally compact.  Repeated lexical families become
    anchors because repetition in a natural-language question is a useful, fully
    deterministic signal of topic centrality.  One outcome/context term from the
    question tail is then retained so the query does not collapse to a single entity.

    A second, slightly richer query retains two tail terms.  A third optional query
    contains the broader content-word set.  Duplicate strings are removed while
    preserving order.  No model, provider result, or scientific judgment is used.
    """

    if not question.strip():
        raise ValueError("question must not be blank.")
    if not 0 <= max_queries <= MAX_ZERO_YIELD_BROADENING_QUERIES:
        raise ValueError(f"max_queries must be between 0 and {MAX_ZERO_YIELD_BROADENING_QUERIES}.")
    if max_queries == 0:
        return ()

    families = _extract_term_families(question)
    if len(families) < 2:
        return ()

    ordered = [item.surface for item in families]
    repeated = [item.surface for item in families if item.frequency > 1]
    high_information_singletons = [
        item.surface
        for item in families
        if item.frequency == 1 and item.surface not in _LOW_INFORMATION_COMPACT_TERMS
    ]

    candidates: list[str] = []

    if repeated:
        compact_tail = high_information_singletons[-2:-1] or high_information_singletons[-1:]
        _append_query(candidates, (*repeated, *compact_tail))
        _append_query(candidates, (*repeated, *high_information_singletons[-2:]))
    else:
        compact_terms = _edge_terms(high_information_singletons or ordered, leading=1, trailing=2)
        focused_terms = _edge_terms(high_information_singletons or ordered, leading=2, trailing=2)
        _append_query(candidates, compact_terms)
        _append_query(candidates, focused_terms)

    _append_query(candidates, tuple(ordered[:8]))

    return tuple(candidates[:max_queries])


def _extract_term_families(question: str) -> tuple[_TermFamily, ...]:
    raw_tokens = [token.casefold().strip("'-") for token in _TOKEN_PATTERN.findall(question)]
    retained: list[tuple[int, str, str]] = []
    counts: Counter[str] = Counter()

    for index, token in enumerate(raw_tokens):
        if len(token) < 2 or token in _STOPWORDS or token in _QUESTION_SCAFFOLDING:
            continue
        family = _normalize_family(token)
        if not family:
            continue
        retained.append((index, family, token))
        counts[family] += 1

    selected: dict[str, tuple[int, str]] = {}
    for index, family, surface in retained:
        current = selected.get(family)
        if current is None or len(surface) < len(current[1]):
            selected[family] = (index if current is None else current[0], surface)

    ordered = sorted(selected.items(), key=lambda item: item[1][0])
    return tuple(
        _TermFamily(
            family=family,
            surface=surface,
            first_index=first_index,
            frequency=counts[family],
        )
        for family, (first_index, surface) in ordered
    )


def _normalize_family(token: str) -> str:
    value = token.removesuffix("'s")
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("ing") and len(value) > 5:
        stem = value[:-3]
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        if stem.endswith("is"):
            stem += "e"
        return stem
    if value.endswith("ed") and len(value) > 4:
        return value[:-2]
    if value.endswith("s") and len(value) > 4 and not value.endswith("ss"):
        return value[:-1]
    return value


def _edge_terms(values: list[str], *, leading: int, trailing: int) -> tuple[str, ...]:
    if not values:
        return ()
    chosen = [*values[:leading], *values[-trailing:]]
    return tuple(dict.fromkeys(chosen))


def _append_query(target: list[str], terms: tuple[str, ...]) -> None:
    query = " ".join(dict.fromkeys(term for term in terms if term)).strip()
    if len(query.split()) < 2 or query in target:
        return
    target.append(query)


__all__ = [
    "MAX_ZERO_YIELD_BROADENING_QUERIES",
    "compile_zero_yield_broadening_queries",
]
