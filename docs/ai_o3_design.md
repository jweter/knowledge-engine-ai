# AI-O3 — Deterministic Orchestrator

**Status:** Implemented and live-verified against the real GLP-1 corpus (2026-08-10).
**Depends on:** AI-O1 (`docs/ai_o1_design.md`), AI-O2 (`docs/ai_o2_design.md`).

## What AI-O3 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O3 milestone:

> Connect existing core retrieval, Evidence Intelligence, evidence-map, and
> statistical-verification capabilities using fixed workflow rules.
>
> **Success criterion:** one session can call multiple existing Knowledge
> Engine capabilities and assemble structured results without an LLM
> dynamically deciding execution.

`knowledge_engine_ai/orchestrator/workflow.py`'s `run_fixed_evidence_workflow`
is that connection, and deliberately nothing more. It is a plain function
that runs a hardcoded sequence of `ke` subprocess calls (via `ke_client.py`)
against an already-created `ResearchSession` (AI-O2), appending one
`ResearchEvent` per step. No LLM call anywhere in this module.

## Why "fixed rules," not a planner

AI-O4 ("Local Query Planner") is where a model decides *which*
capabilities a given question needs. AI-O3 is upstream of that: it proves
the mechanical wiring -- session, event log, subprocess calls, structured
result assembly -- works correctly and durably *before* any model gets to
choose what runs. Concretely, the fixed rules are:

1. **Retrieval + Evidence Intelligence always run.** `enriched_evidence_report`
   (already built for AI's first Retrieval Intelligence slice) answers the
   question against the corpus's lexical index and attaches each matched
   `EvidenceRecord`'s Evidence Intelligence score.
2. **The evidence-map step runs only when the caller supplies a curated
   map path and a relationship-records path.** Not every corpus has an
   evidence map yet (only GLP-1 does, as of this milestone) -- the branch
   is evaluated once per call from the caller's arguments, not decided
   per-question by an executor.
3. **The statistical-verification step runs only when the caller supplies
   a curated statistical-inputs path.** Same reasoning: not every corpus
   has curated statistical inputs.

None of these three conditions inspect the *question's content* -- they
inspect what data exists. That is the load-bearing distinction between
"fixed workflow rules" (AI-O3) and "the system decides what to do based on
what was asked" (AI-O4 onward).

## New `ke_client.py` wrappers

`evidence-map-report` and `statistical-verify` have no `--format json`
mode (unlike `evidence-report`/`evidence-intelligence`) -- both render
deterministic Markdown from curated inputs and there is no richer
structured contract to parse. `evidence_map_report()` and
`statistical_verify()` follow the same subprocess discipline as the
existing wrappers (explicit argument list, never `shell=True`, a clear
`KeCommandError` on any non-zero exit or missing `ke` executable) and
return the Markdown text verbatim -- this project does not re-parse or
re-derive anything from it.

## Durability: every step is recorded, success or failure

Each of the three (up to three) steps appends exactly one `ResearchEvent`
to the session, whether it succeeds or raises `KeCommandError`. A failed
step is real workflow history -- AI-O2's whole point was making
"what happened" durable, not just "what succeeded." A failure in one step
does not stop the remaining fixed steps from being attempted; the workflow
always runs its full fixed sequence, and `WorkflowResult.steps` reports
every outcome.

`output_hash` is a SHA-256 of a step's meaningful output, letting a caller
detect whether a later re-run actually changed anything:

- The retrieval step hashes the retrieved paper IDs and evidence record
  IDs (sorted, JSON-serialized) -- not the human-readable summary text
  and not the papers' floating-point retrieval scores, which could drift
  across runs without the retrieved *set* actually changing.
- The evidence-map and statistical-verification steps hash their full
  Markdown report text, since that text *is* the deterministic output.

A step that raised `KeCommandError` records `output_hash=None` and the
error text in the event's `notes` field -- there is no output to hash,
and the failure itself is what the event durably records.

## What this does not do

- No LLM call, anywhere.
- No orchestrator-level retry logic. A caller who wants to retry a failed
  step calls `run_fixed_evidence_workflow` again (or a future,
  more targeted retry helper); this module does not guess whether a retry
  is safe.
- No new reasoning about the evidence (no comparison, no synthesis, no
  contradiction detection). Those are AI-O5/AI-O6/AI-O7.
- No `ResearchPlan` consumption yet. AI-O1's contracts exist and are
  validated, but nothing here reads a `ResearchPlan` to decide what to
  run -- the fixed sequence is hardcoded in this module's own code. A
  future AI-O4 planner would sit *above* this module, producing a plan
  whose tasks this module (or a generalized version of it) executes.

## Live verification

Run against the real, committed GLP-1 corpus
(`data/corpora/glp1_weight_loss/`) with `core`'s actual `ke` executable,
not a mock: all three steps (retrieval, evidence map, statistical
verification) succeeded, each producing a real `ResearchEvent` with a
non-null `output_hash`. The retrieval step returned 3 papers (bounded by
`limit=3`) with their attached Evidence Intelligence scores; the
evidence-map step rendered the real 14-record GLP-1 golden map; the
statistical-verification step rendered a real report over the corpus's
curated continuous and binary statistical inputs (2 typed inputs, 0
arithmetic discrepancies).

## Tests

- `tests/test_ke_client.py`: the two new wrappers' command construction,
  Markdown pass-through, and error handling (non-zero exit, missing `ke`).
- `tests/test_orchestrator_workflow.py`: fixed step ordering, the
  optional-step "if configured" branching (evidence-map requires *both*
  a map path and a relationships path -- supplying only one still skips
  the step), that a failed step is recorded and does not stop later
  steps, that retrieval's `output_hash` is deterministic across two
  separate runs against identical inputs, that calling the workflow
  against a `session_id` nobody created raises `UnknownSessionError`
  (from AI-O2's own repository, not swallowed here), and that
  `binary_statistical_inputs` is forwarded to `ke_client` correctly.
