from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.synthesis import build_synthesis_prompt


def test_prompt_lists_every_required_qualifier_and_limitation_citation() -> None:
    records = [
        SimpleNamespace(
            evidence_record_id="ev-support",
            claim_text="Music improved time to exhaustion.",
            evidence_direction="supports",
            result_summary=None,
            limitations=[],
            evidence_intelligence=None,
        ),
        SimpleNamespace(
            evidence_record_id="ev-qualifies",
            claim_text="The benefit was smaller in one subgroup.",
            evidence_direction="qualifies",
            result_summary=None,
            limitations=[],
            evidence_intelligence=None,
        ),
        SimpleNamespace(
            evidence_record_id="ev-limited",
            claim_text="A second study reported a benefit.",
            evidence_direction="supports",
            result_summary=None,
            limitations=["The sample was small."],
            evidence_intelligence=None,
        ),
    ]
    report = cast(
        EvidenceReport,
        SimpleNamespace(
            question="Does music improve exercise endurance?",
            papers=[SimpleNamespace(evidence_records=records)],
        ),
    )

    prompt = build_synthesis_prompt(report)

    assert "Mandatory qualification citations: [ev-qualifies], [ev-limited]" in prompt
    assert (
        "[ev-support]"
        not in prompt.split("Mandatory qualification citations:", 1)[1].splitlines()[0]
    )
    assert "The final answer is incomplete unless every mandatory citation above appears." in prompt
