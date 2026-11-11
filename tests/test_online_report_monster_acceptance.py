"""Monster Energy (#79, ``monster-energy-bp-one-year``) acceptance run through the
online-evidence report path.

This exercises the real ingestion boundary end to end:
``parse_content_checked_online_evidence`` (Core's ``ke-online-evidence/v1``
bundle contract) followed by ``build_online_research_report`` (the
deterministic, no-LLM Research Report v1 projection). The bundle below is a
fixed, hand-authored recording -- a "deterministic recorded bundle" -- of
what such a Core capture looks like for the Monster case; nothing here makes a
network call, invokes Core, or touches Ollama, and nothing is fetched or
generated at test time.

Dimensions and question text are pulled from the live golden-case contract in
``research_case_benchmark.default_golden_research_cases`` so this test tracks
the authoritative case definition in ``docs/roadmap/research_report_v1.md``
rather than a second, drifting copy of it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from knowledge_engine_ai.copilot.online_evidence_adapter import (
    SCHEMA,
    parse_content_checked_online_evidence,
)
from knowledge_engine_ai.copilot.online_report import build_online_research_report
from knowledge_engine_ai.copilot.research_report import ReportCertainty
from knowledge_engine_ai.research_case_benchmark import default_golden_research_cases

MONSTER_CASE = next(
    c for c in default_golden_research_cases() if c.case_id == "monster-energy-bp-one-year"
)
RETRIEVED_AT = "2026-11-10T00:00:00+00:00"

# source_id -> (provider, full retrieved content)
_RETRIEVED: dict[str, tuple[str, str]] = {
    "acute-monster-trial": (
        "pubmed",
        "Crossover trial: two 16 fl oz servings of Monster Energy (Original) in one day "
        "produced a transient systolic blood pressure rise of 6.2 mmHg measured 30 minutes "
        "post-consumption, resolving within hours.",
    ),
    "chronic-energy-drink-cohort": (
        "pubmed",
        "Prospective cohort of habitual commercial energy-drink consumers (brand "
        "unspecified) found a small increase in resting ambulatory blood pressure after "
        "12 months of near-daily exposure.",
    ),
    "chronic-null-cohort": (
        "pubmed",
        "A separate cohort found no significant persistent ambulatory blood-pressure "
        "difference between habitual energy-drink consumers and non-consumers after "
        "adjusting for confounders.",
    ),
    "sugar-sweetened-beverage-cohort": (
        "pubmed",
        "Longitudinal cohort linking habitual sugar-sweetened beverage intake, not energy "
        "drinks specifically, to a modestly elevated incident-hypertension hazard ratio.",
    ),
    "bp-measurement-guidance": (
        "pubmed",
        "Clinical hypertension-measurement guidance: readings taken within 30 minutes of "
        "caffeine ingestion overstate resting blood pressure and should be deferred.",
    ),
    "artificial-sweetener-observation": (
        "pubmed",
        "Observational study of consumers of artificially sweetened beverages generally "
        "(sweetener class, not Zero Ultra specifically) reported an association with "
        "altered metabolic markers over multi-year follow-up.",
    ),
    "caffeine-coffee-soda-meta-analysis": (
        "pubmed",
        "Meta-analysis of caffeine, coffee, and soda intake and blood pressure found small, "
        "inconsistent associations across caffeinated-beverage sources generally.",
    ),
}

# source_id -> an exact substring of its content above, used as the cited excerpt.
_QUOTE: dict[str, str] = {
    "acute-monster-trial": "a transient systolic blood pressure rise of 6.2 mmHg",
    "chronic-energy-drink-cohort": "a small increase in resting ambulatory blood pressure",
    "chronic-null-cohort": "no significant persistent ambulatory blood-pressure difference",
    "sugar-sweetened-beverage-cohort": "a modestly elevated incident-hypertension hazard ratio",
    "bp-measurement-guidance": "overstate resting blood pressure and should be deferred",
    "artificial-sweetener-observation": "an association with altered metabolic markers",
    "caffeine-coffee-soda-meta-analysis": (
        "small, inconsistent associations across caffeinated-beverage sources generally"
    ),
}

# The one direct one-year Monster trial Core looked for and did not find.
_MISSING_ONE_YEAR_SOURCE_ID = "monster-one-year-direct-trial"
_MISSING_ONE_YEAR_REASON = (
    "No direct approximately-one-year randomized or cohort trial of Monster Energy drink "
    "consumption was retrieved online."
)

# dimension -> (claim text, [(source_id, stance), ...])
_DIMENSION_CLAIMS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "acute_pressor_effect": (
        "A direct Monster Energy (Original) crossover trial found a transient 6.2 mmHg "
        "systolic rise within 30 minutes of consumption; this is an acute effect only, not "
        "evidence of a sustained change.",
        [("acute-monster-trial", "supports")],
    ),
    "persistent_chronic_bp_effect": (
        "Class-level commercial energy-drink cohort evidence is mixed and not "
        "Monster-specific: one cohort found a small persistent ambulatory blood-pressure "
        "increase after 12 months of habitual use, while a separate cohort found no "
        "significant difference.",
        [("chronic-energy-drink-cohort", "supports"), ("chronic-null-cohort", "contradicts")],
    ),
    "incident_hypertension_risk": (
        "Indirect sugar-sweetened-beverage cohort evidence, not direct energy-drink or "
        "Monster evidence, found a modestly elevated incident-hypertension hazard ratio.",
        [("sugar-sweetened-beverage-cohort", "supports")],
    ),
    "measurement_artifact": (
        "Clinical guidance indicates blood-pressure readings taken soon after caffeine "
        "intake overstate resting values, so recent consumption can confound acute readings.",
        [("bp-measurement-guidance", "supports")],
    ),
    "original_vs_zero_long_term_risk": (
        "An artificial-sweetener observational study (sweetener class generally, not Zero "
        "Ultra specifically) found a metabolic association, but this does not establish "
        "Zero-Ultra-specific long-term cardiovascular risk distinct from Original.",
        [("artificial-sweetener-observation", "supports")],
    ),
    "direct_vs_class_level_evidence": (
        "Caffeine/coffee/soda meta-analysis evidence is indirect context for energy-drink "
        "exposure generally; it is not direct Monster Energy causal evidence and must not "
        "be read as establishing Monster-specific blood-pressure causality.",
        [("caffeine-coffee-soda-meta-analysis", "supports")],
    ),
    "certainty_and_missing_evidence": (
        "No direct approximately-one-year trial or cohort study of Monster Energy drink "
        "consumption was retrieved online; certainty about sustained one-year effects is "
        "unavailable absent that direct long-duration evidence.",
        [],
    ),
}


def _excerpt_id(source_id: str, start: int, quote: str) -> str:
    material = f"{source_id}\n{start}\n{quote}"
    return source_id + "#" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _claim_status(stances: list[str]) -> str:
    present = set(stances)
    if {"supports", "contradicts"} <= present:
        return "contested"
    if "supports" in present:
        return "supported"
    if "contradicts" in present:
        return "contradicted"
    return "insufficient_evidence"


def _recorded_bundle() -> tuple[dict[str, Any], dict[str, str]]:
    """Build the deterministic recorded ``ke-online-evidence/v1`` bundle fixture."""

    contents = {source_id: content for source_id, (_, content) in _RETRIEVED.items()}

    sources: list[dict[str, Any]] = [
        {
            "source_id": source_id,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{source_id}",
            "provider": provider,
            "retrieved_at": RETRIEVED_AT,
            "status": "retrieved",
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "failure_reason": None,
            "title": None,
        }
        for source_id, (provider, content) in _RETRIEVED.items()
    ]
    sources.append(
        {
            "source_id": _MISSING_ONE_YEAR_SOURCE_ID,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{_MISSING_ONE_YEAR_SOURCE_ID}",
            "provider": "pubmed",
            "retrieved_at": RETRIEVED_AT,
            "status": "unavailable",
            "content_sha256": None,
            "failure_reason": _MISSING_ONE_YEAR_REASON,
            "title": None,
        }
    )

    excerpt_id_by_source: dict[str, str] = {}
    excerpts: list[dict[str, Any]] = []
    for source_id, quote in _QUOTE.items():
        content = contents[source_id]
        start = content.index(quote)
        end = start + len(quote)
        excerpt_id = _excerpt_id(source_id, start, quote)
        excerpt_id_by_source[source_id] = excerpt_id
        excerpts.append(
            {
                "excerpt_id": excerpt_id,
                "source_id": source_id,
                "text": quote,
                "char_start": start,
                "char_end": end,
            }
        )

    claims: list[dict[str, Any]] = []
    for dimension in MONSTER_CASE.required_dimensions:
        text, citation_specs = _DIMENSION_CLAIMS[dimension]
        citations = [
            {"excerpt_id": excerpt_id_by_source[source_id], "stance": stance}
            for source_id, stance in citation_specs
        ]
        claims.append(
            {
                "claim_id": dimension,
                "text": text,
                "status": _claim_status([c["stance"] for c in citations]),
                "citations": citations,
            }
        )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "question": MONSTER_CASE.question,
        "sources": sources,
        "excerpts": excerpts,
        "claims": claims,
    }
    return payload, contents


def test_monster_case_online_report_separates_dimensions_and_preserves_evidence_boundaries() -> (
    None
):
    payload, contents = _recorded_bundle()
    evidence = parse_content_checked_online_evidence(payload, contents)
    report = build_online_research_report(evidence, search_run_id="monster-online-acceptance-1")

    assert report.question == MONSTER_CASE.question
    assert report.session_id == "monster-online-acceptance-1"

    # Every required golden-case dimension gets its own conclusion row -- no
    # merging acute/chronic, direct/indirect, or Monster/class-level dimensions
    # into one averaged conclusion.
    dimensions = [row.question_dimension for row in report.conclusion_rows]
    assert dimensions == list(MONSTER_CASE.required_dimensions)
    assert len(set(dimensions)) == len(MONSTER_CASE.required_dimensions)
    for row in report.conclusion_rows:
        assert row.certainty_rationale.strip()

    by_dim = {row.question_dimension: row for row in report.conclusion_rows}

    def _sources_of(row_ids: tuple[str, ...]) -> set[str]:
        return {e.source_id for e in evidence.excerpts if e.excerpt_id in row_ids}

    # Indirect caffeine/coffee/soda evidence is never labelled direct Monster
    # causality: its row is grounded only in the indirect meta-analysis source
    # and its own text disclaims direct Monster causation.
    indirect_row = by_dim["direct_vs_class_level_evidence"]
    assert _sources_of(indirect_row.supporting_evidence_ids) == {
        "caffeine-coffee-soda-meta-analysis"
    }
    assert "indirect" in indirect_row.conclusion.lower()
    assert "must not be read as establishing monster-specific" in indirect_row.conclusion.lower()

    # Zero Ultra vs Original: an artificial-sweetener observation cannot be
    # inflated into Zero-Ultra-specific causality.
    sweetener_row = by_dim["original_vs_zero_long_term_risk"]
    assert "does not establish zero-ultra-specific" in sweetener_row.conclusion.lower()

    # Acute and persistent/chronic effects are distinct, non-collapsed rows.
    acute_row = by_dim["acute_pressor_effect"]
    chronic_row = by_dim["persistent_chronic_bp_effect"]
    assert acute_row.conclusion != chronic_row.conclusion
    assert _sources_of(acute_row.supporting_evidence_ids) == {"acute-monster-trial"}

    # Null/contradictory evidence for the chronic dimension is retained, not
    # silently dropped.
    assert chronic_row.certainty == ReportCertainty.LOW
    assert _sources_of(chronic_row.contradicting_or_null_evidence_ids) == {"chronic-null-cohort"}

    # The missing direct one-year Monster trial is stated explicitly in the
    # report-level missing-evidence disclosure, and no claim asserts that a
    # one-year Monster trial exists.
    certainty_row = by_dim["certainty_and_missing_evidence"]
    assert certainty_row.certainty == ReportCertainty.UNAVAILABLE
    assert certainty_row.supporting_evidence_ids == ()
    assert "no direct approximately-one-year" in certainty_row.conclusion.lower()
    assert any(
        _MISSING_ONE_YEAR_SOURCE_ID in m and "no direct" in m.lower()
        for m in report.missing_evidence
    )
    assert not any(
        "one-year" in m.lower() and "trial exists" in m.lower() for m in report.missing_evidence
    )

    # Deterministic projection only: never a fully synthesized/researched answer.
    assert report.research_state in {"partial_answer", "insufficient_evidence"}
