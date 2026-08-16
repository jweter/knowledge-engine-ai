# AI-O7 — Research Session Synthesis

**Status:** Implemented and live-verified (2026-08-11) -- see "Live
verification" below.
**Depends on:** `synthesis.py` (the narrative), `orchestrator/verification.py`
(AI-O6, the check on that narrative), and `models.py`'s `RetrievedPaper`
(already-computed bibliographic fields: `title`, `authors`, `doi`,
`citation`, `source_url`, `license_type`).

## What AI-O7 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O7 milestone:

> Generate a final report from validated structured objects.
>
> **Success criterion:** every material scientific claim resolves to
> evidence IDs and source citations.

Today, `synthesize_answer` produces a narrative citing bare
`[evidence_record_id]` tokens, and AI-O6's `verify_synthesis` checks
those citations are real and grounded -- but neither module resolves a
citation into something a reader could actually use to find the source:
a paper title, DOI, and citation string. AI-O7 is that resolution step:
turn a narrative's citations into a structured list of fully-sourced
claims, assembled from data every prior milestone already computed
(`RetrievedPaper`'s bibliographic fields, already fetched by
`enriched_evidence_report`; `VerificationResult`, already computed by
AI-O6), not from anything newly invented.

## Architecture: resolve citations against `EvidenceReport`, don't regenerate them

New module `knowledge_engine_ai/orchestrator/session_report.py`. One
entry point:

```python
def build_session_report(
    narrative: str, report: EvidenceReport, verification: VerificationResult
) -> SessionReport
```

For each `[evidence_record_id]` citation the narrative actually
contains (the same extraction `verify_synthesis` already does -- this
module reuses `verification._CITATION_RE`... actually exposes it as a
shared constant rather than duplicate the regex, see Implementation
notes), resolve it against `report` to a `SourcedClaim`:

```python
@dataclass(frozen=True)
class SourcedClaim:
    evidence_record_id: str
    claim_text: str | None
    result_summary: str | None
    paper_title: str
    paper_authors: str
    paper_year: str
    paper_doi: str
    paper_citation: str
    paper_source_url: str


@dataclass(frozen=True)
class SessionReport:
    narrative: str
    sourced_claims: tuple[SourcedClaim, ...]
    unresolved_citations: tuple[str, ...]  # from verification.hallucinated_citations
    verification: VerificationResult

    @property
    def is_fully_sourced(self) -> bool:
        """True only when every citation the narrative made resolves to a real source."""
        return not self.unresolved_citations
```

`unresolved_citations` and the embedded `verification` are not
recomputed -- `build_session_report` takes an already-computed
`VerificationResult` as a parameter rather than calling
`verify_synthesis` itself, the same "don't duplicate what an earlier
step already established" discipline `run_fixed_evidence_workflow`
already follows for `EvidenceIntelligence` (computed once by
`enriched_evidence_report`, never recomputed downstream). A caller runs
AI-O6's check first, then hands both the narrative and its verification
result to this module.

## Why paper-level fields, not evidence-record-level alone

`docs/roadmap/future_ai_orchestration_plan.md`'s success criterion says
"source citations," not "evidence record IDs" alone -- an
`evidence_record_id` like `ev-glp1-gao-meta-analysis-body-weight-001` is
an internal identifier, not something a reader outside this project can
verify against. `RetrievedPaper` (the object one level up from
`EvidenceRecord` in `EvidenceReport.papers`) already carries the actual
citation string, DOI, and source URL `ke evidence-report` computed --
this module's only new work is the join from a cited
`evidence_record_id` back up to the `RetrievedPaper` that contains it,
something no existing module does today (`EvidenceReport.papers` is a
list of papers each containing their own records; nothing currently
walks it in the citation-resolution direction).

## What this does not do

- Does not regenerate or improve the narrative. `SessionReport.narrative`
  is the same string `synthesize_answer` produced, unmodified -- this
  module resolves citations, it does not rewrite prose.
- Does not decide whether an unresolved citation should block anything.
  `is_fully_sourced` is a fact the report carries; a caller (a future
  AI-O8+ step, `knowledge-engine-web`, or a human) decides what to do
  with a report that is not fully sourced.
- Does not consume `ResearchSession`/`ResearchEvent`'s persisted event
  log directly in this first slice -- it operates on one narrative +
  one `EvidenceReport` + one `VerificationResult`, the same
  single-call shape AI-O5/AI-O6 used before any orchestrator wiring.
  Assembling a report from an entire session's accumulated event
  history (multiple retrieval/verification rounds) is named here as the
  natural next widening, not attempted yet -- mirrors AI-O5's own
  "no orchestrator wiring yet" boundary.
- Does not attempt "material" claim significance ranking. Every citation
  the narrative makes is resolved and reported; this module does not
  judge which claims are more "material" than others, since that is a
  scientific-importance judgment call this project consistently declines
  to make deterministically (see `core`'s own Evidence Intelligence
  design boundary: it scores individual records, never a claim's
  relative importance within an answer).

## Implementation notes

- `verification.py`'s citation regex (`_CITATION_RE`) moves to a shared,
  exported constant (`CITATION_PATTERN`) both modules import, rather
  than each maintaining its own copy of the same pattern -- a small
  refactor alongside this milestone's new code, not a separate change.
- A citation appearing more than once in the narrative resolves to one
  `SourcedClaim` (order of first appearance), not one per occurrence --
  a reader wants the source once, not repeated per citation instance.

## Testing strategy

Unit tests mirroring `tests/test_verification.py`'s fixture style: a
narrative citing a real record resolves to a `SourcedClaim` with the
correct paper fields; a hallucinated citation lands in
`unresolved_citations`, not `sourced_claims`; a citation repeated twice
resolves to exactly one `SourcedClaim`; `is_fully_sourced` is `True`
only when `unresolved_citations` is empty.

## Live verification

Reused AI-O6's own real live-verification data (the real GLP-1 corpus
retrieval via `enriched_evidence_report`, the real `qwen2.5:1.5b`
narrative `docs/ai_o6_design.md` already captured) rather than re-running
a live Ollama call for no new signal -- `build_session_report` is a pure
resolution step over already-fetched data, so re-verifying it needs the
same inputs, not a fresh model call.

Re-running `verify_synthesis` against that same narrative and a freshly
re-fetched `EvidenceReport` reproduced AI-O6's own recorded result exactly
(`hallucinated_citations=()`, `ungrounded_numbers=()`,
`missed_qualifiers=('ev-glp1-gao-meta-analysis-safety-discontinuation-001',
'ev-glp1-step5-body-weight-week104-001')`), confirming the retrieval and
checker are stable against the live corpus. `build_session_report` then
resolved the narrative's two real citations to `SourcedClaim`s carrying
each paper's actual title, citation string, and DOI:

- `ev-glp1-gao-meta-analysis-body-weight-001` -> "Efficacy and safety of
  semaglutide on weight loss in obese or overweight patients without
  diabetes: A systematic review and meta-analysis of randomized
  controlled trials" (2022), DOI `10.3389/fphar.2022.935823`.
- `ev-glp1-select-trial-weight-loss-208wk-001` -> "Long-term weight loss
  effects of semaglutide in obesity without diabetes in the SELECT trial"
  (2024), DOI `10.1038/s41591-024-02996-7`.

`unresolved_citations=()` and `is_fully_sourced=True` -- both citations in
this narrative were real, so nothing landed in `unresolved_citations`
here; `tests/test_session_report.py`'s
`test_a_hallucinated_citation_lands_in_unresolved_not_sourced_claims`
covers the case where a cited ID does not resolve, using a hand-built
fixture rather than a live model call (no real hallucination has been
observed from `qwen2.5:1.5b` in this project's live checks so far).
