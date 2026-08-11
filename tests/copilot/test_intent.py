from knowledge_engine_ai.copilot.intent import (
    CriterionResult,
    CriterionStatus,
    IdealStateCriterion,
    ResearchISA,
    evaluate_isa_close_gate,
    validate_research_isa,
)


def _isa() -> ResearchISA:
    return ResearchISA(
        schema_version=1,
        run_id="RUN-001",
        question="Does compound X have evidence of mitochondrial toxicity?",
        ideal_state="Produce a provenance-complete assessment with contradictions and uncertainty.",
        criteria=(
            IdealStateCriterion(
                criterion_id="ISC-01",
                claim="Every material scientific assertion has evidence links.",
                probe="orphan_claim_count == 0",
            ),
            IdealStateCriterion(
                criterion_id="ISC-02",
                claim="Contradictory evidence was reviewed.",
                probe="contradiction_review_complete",
            ),
            IdealStateCriterion(
                criterion_id="ISC-03",
                claim="Exploratory search coverage is reported.",
                probe="coverage_disclosure_check",
                required=False,
            ),
        ),
    )


def test_valid_research_isa_has_no_structural_errors() -> None:
    assert validate_research_isa(_isa()) == ()


def test_duplicate_criterion_ids_are_rejected() -> None:
    isa = ResearchISA(
        schema_version=1,
        run_id="RUN-002",
        question="Question",
        ideal_state="Verified answer",
        criteria=(
            IdealStateCriterion("ISC-01", "Claim one", "probe_one"),
            IdealStateCriterion("ISC-01", "Claim two", "probe_two"),
        ),
    )

    assert "duplicate criterion_id: ISC-01" in validate_research_isa(isa)


def test_close_gate_requires_every_required_criterion_to_pass() -> None:
    result = evaluate_isa_close_gate(
        _isa(),
        (
            CriterionResult("ISC-01", CriterionStatus.PASSED, "0 orphan claims"),
            CriterionResult("ISC-02", CriterionStatus.BLOCKED, "relationship review incomplete"),
        ),
    )

    assert result.complete is False
    assert result.unresolved_required_criteria == ("ISC-02",)


def test_optional_criterion_does_not_block_close_gate() -> None:
    result = evaluate_isa_close_gate(
        _isa(),
        (
            CriterionResult("ISC-01", CriterionStatus.PASSED, "0 orphan claims"),
            CriterionResult("ISC-02", CriterionStatus.PASSED, "skeptic pass completed"),
        ),
    )

    assert result.complete is True
    assert result.unresolved_required_criteria == ()
