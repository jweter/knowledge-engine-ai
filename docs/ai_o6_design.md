# AI-O6 — Skeptic + Verifier

**Status:** Planned, not yet implemented (this document is the plan;
implementation follows in the same branch).
**Depends on:** `knowledge_engine_ai/synthesis.py` (the only place a
model-generated narrative string exists in this project) and AI-O1's
`TaskType.CONTRADICTION_SEARCH` docstring, which already named the
"Skeptic / Adversarial Evidence Worker" role this milestone builds.

## What AI-O6 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O6 milestone:

> Add independent verification.
>
> **Success criterion:** unsupported-claim and missed-qualifier rate is
> lower than direct synthesis baseline.

`synthesis.py`'s `synthesize_answer` is the one place this project lets
a local LLM generate free text: a narrative paragraph citing
`[evidence_record_id]` after each claim, strictly instructed to use only
the `EvidenceReport` it was given. That instruction is a prompt, not a
guarantee -- nothing today checks whether the model actually followed
it. AI-O6 is that check: a second pass over an already-generated
narrative, run against the same `EvidenceReport` it was built from,
that flags exactly two failure classes the success criterion names --
**unsupported claims** (the narrative asserts something the cited
evidence does not contain) and **missed qualifiers** (the narrative
omits a caveat, limitation, or contradicting signal a cited record
actually carries).

## Principle: deterministic first, no LLM verifying an LLM

Every prior AI-O milestone that could stay deterministic did --
AI-O3's fixed orchestrator, AI-O5's contradiction-oriented retrieval,
both explicitly "no LLM dynamically deciding execution." AI-O6 follows
the same discipline for the same reason a second model checking a first
model's work would: an LLM-based verifier just relocates the trust
problem rather than solving it (what verifies the verifier?), and this
project already has a working non-LLM pattern for exactly this shape of
check -- `core`'s `knowledge_engine.extraction.grounding.verify_grounding`
and `knowledge_engine/golden_map_grounding.py` both verify a piece of
generated/curated text against source data using pure string/number
presence checks, never a second model call. AI-O6's verifier reuses that
same posture: string and structural checks against the `EvidenceReport`
already in hand, nothing more.

## Architecture: two deterministic checks

New module `knowledge_engine_ai/orchestrator/verification.py` (sits
alongside `parallel_retrieval.py` in the same package, since both are
post-retrieval, pre-trust steps). One entry point:

```python
def verify_synthesis(narrative: str, report: EvidenceReport) -> VerificationResult
```

**Check 1 -- unsupported claims (citation + numeric grounding).**
Mirrors `golden_map_grounding.py`'s numeric-token-presence technique,
applied to a synthesized narrative instead of a curated golden-map
record:

- Extract every `[evidence_record_id]`-shaped citation from the
  narrative (regex over the same bracket format the synthesis prompt
  requires). Any cited ID that does not match a record actually present
  in `report` is a **hallucinated citation** -- the model referenced
  evidence it was never given.
- Extract every numeric token (percentages, ratios, confidence
  intervals, sample sizes -- the same token shapes
  `golden_map_grounding.py` already extracts) from the narrative. Any
  number not present in the `claim_text`/`result_summary` of *any*
  cited record is an **ungrounded number** -- a statistic the model
  stated but did not source from the evidence it was given.

**Check 2 -- missed qualifiers (structural, not linguistic).**
Deliberately narrow and structural, not an attempt to detect "softened
language" in prose (a job that needs judgment this module does not
have): a record in `report` counts as **qualifying** if its
`evidence_direction` is `"qualifies"` or `"contradicts"`, or if its
`limitations` list is non-empty. Any qualifying record that the
narrative never cites at all is a **missed qualifier** -- the synthesis
built an answer from the report but silently dropped a record whose own
authors (or M52's automated classifier) already flagged it as
complicating the picture. This is checkable without deciding *how* a
qualifier should be phrased, only *whether* it was acknowledged at all.

```python
@dataclass(frozen=True)
class VerificationResult:
    narrative: str
    hallucinated_citations: tuple[str, ...]
    ungrounded_numbers: tuple[str, ...]
    missed_qualifiers: tuple[str, ...]  # evidence_record_ids

    @property
    def is_clean(self) -> bool:
        return not (self.hallucinated_citations or self.ungrounded_numbers
                     or self.missed_qualifiers)
```

## What this does not do

- Does not call an LLM, and does not attempt to verify *tone*,
  *emphasis*, or whether the narrative's summary is a fair reading of
  qualifying evidence -- only whether a qualifying record was cited at
  all. A future milestone could add a model-based fairness check; this
  one does not, on purpose.
- Does not modify or "fix" the narrative. A verifier that rewrites the
  text it is checking is no longer independent verification -- it
  reports what it found; a caller (a future orchestrator step, or a
  human) decides what to do about it.
- Does not consume `ResearchPlan`/`TaskType` directly -- like AI-O5, no
  orchestrator wiring into `run_fixed_evidence_workflow` in this first
  slice. `TaskType.CONTRADICTION_SEARCH`'s "Skeptic / Adversarial
  Evidence Worker" naming in AI-O1 is the conceptual anchor, not a
  literal task-type dispatch this milestone must implement yet.
- Does not establish the "lower than direct synthesis baseline"
  comparison as a formal benchmark. That needs a labeled dataset of
  known-good/known-bad syntheses this project does not have (the same
  gap AI-O5's design doc named for a recall/precision benchmark). What
  this milestone *can* do, and will, is live-verify the checker against
  real `synthesize_answer` output for a few real questions and report
  honestly whether it fires zero, some, or many findings -- the same
  "measured, not asserted" small-sample live check every prior AI-O
  milestone has done, not a claim that the success criterion's
  comparative benchmark is fully met.

## Testing strategy

- Unit tests against hand-built `EvidenceReport`/narrative pairs
  (mirroring `tests/test_parallel_retrieval.py`'s fixture style): a
  clean narrative (all citations real, all numbers grounded, all
  qualifying records cited) returns `is_clean=True`; a narrative citing
  a nonexistent ID is caught; a narrative stating a number absent from
  every cited record's text is caught; a report containing a
  `qualifies`-direction record never cited by the narrative is caught.
- A CLI-level or direct-call live verification against a real
  `synthesize_answer` output from a real Ollama model and a real
  `EvidenceReport`, the same "not mocked" discipline AI-O4's and AI-O5's
  live checks used, reported honestly in this document's own follow-up
  status section once run.

## Open questions (not resolved here)

- Whether `missed_qualifiers` should distinguish "never cited" from
  "cited but its qualifying content specifically wasn't mentioned" --
  the latter needs some position-aware text matching this design
  deliberately avoids for now, since it edges back toward the
  judgment-call territory Check 2 is designed to stay out of.
- Whether a numeric-token false-positive rate (a number that's
  genuinely grounded but phrased differently than the source, e.g. a
  rounded percentage) needs tolerance -- `golden_map_grounding.py`'s own
  module docstring already documents this exact tradeoff for its
  sentence-window-vs-exact-match choice; this module inherits the same
  choice and the same open question, not a new one.
