# AI-O9 — Observability + Budgeting

**Status:** Implemented and live-verified (2026-08-11) -- see "Live
verification" below.
**Depends on:** AI-O2's `ResearchSession`/`ResearchEvent`/`SessionRepository`
(the durable event log this milestone reports over, not a new store),
and `orchestrator/workflow.py`'s `run_fixed_evidence_workflow` (the one
place `ResearchEvent`s are actually produced today).

## What AI-O9 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O9 milestone:

> Add workflow tracing and resource metrics.
>
> **Success criterion:** every session can answer what ran, why, what
> model/tool was used, where time was spent, what failed, and what
> evidence supported the output.

AI-O2 already built the durable, append-only event log
(`ResearchEvent`) every workflow step writes to. Reading that log back
in a form that actually answers the six questions above is not
automatic, though: today a caller gets a flat list of `ResearchEvent`
rows and has to derive everything themselves. Two of the six questions
also expose a genuine, previously-unfilled gap in the event schema
itself once you try to answer them from real event data:

- **"Where time was spent"** -- `ResearchEvent` has no timing field at
  all. `workflow.py`'s `_record_step` writes one `timestamp` (when the
  event was appended), not a duration.
- **"What evidence supported the output"** -- `ResearchEvent` already
  has a `source_ids: tuple[str, ...]` field (AI-O2's own design docstring
  names it), but `workflow.py` has never actually populated it on any
  step. A retrieval step's `output_hash` covers the same evidence-record
  identities for tamper-evidence, but nothing surfaces them as a
  directly queryable field today.

AI-O9 is: (1) close those two real gaps additively, and (2) add a
reporting layer that assembles one session's event log into a single
structured, renderable answer to all six questions -- not a new
persistence mechanism, since AI-O2 already built the one this project
needs.

## Part 1 -- close the two real schema gaps

Both are additive optional fields on `ResearchEvent`
(`knowledge_engine_ai/sessions/models.py`), the same "new optional
field, no schema-version bump, old rows still parse" pattern AI-O5 used
for `EvidenceRecord.evidence_intelligence`:

```python
duration_ms: int | None = None
```

`source_ids` already exists on `ResearchEvent` -- this milestone starts
*populating* it, not adding it.

`orchestrator/workflow.py`'s `_record_step` gains `duration_ms` and
(already-existing-field, newly-passed) `source_ids` parameters. Callers
supply both:

- **Retrieval steps** (primary and contradiction-oriented): timed as one
  combined span around the single `run_parallel_retrieval` call (both
  branches run concurrently inside a `ThreadPoolExecutor`, so a true
  per-branch decomposition would need deeper instrumentation of
  `parallel_retrieval.py` itself -- named here as follow-up, not
  attempted in this slice; both retrieval events get the same
  `duration_ms` for now, clearly documented as "the whole concurrent
  call's wall-clock time," not an isolated per-branch cost).
  `source_ids` is each branch's own report's evidence-record IDs (the
  same identity list `_retrieval_output_hash` already computes,
  extracted into one shared helper instead of duplicated).
- **Evidence-map and statistical-verification steps**: each timed
  individually around its own single `ke_client` call, since neither
  runs concurrently with anything else. Neither produces evidence-record
  IDs of its own (`core`'s Markdown output does not enumerate them
  machine-readably), so `source_ids` stays empty for these two steps --
  a known, named limitation, not silently guessed.

## Part 2 -- `orchestrator/observability.py`: assemble the trace

New module. Two entry points:

```python
def build_session_trace(
    session: ResearchSession, events: tuple[ResearchEvent, ...]
) -> SessionTrace

def render_session_trace(trace: SessionTrace) -> str
```

```python
@dataclass(frozen=True)
class EventTrace:
    event_id: str
    workflow_node: str
    executor_type: str
    tool_name: str | None
    model_name: str | None
    succeeded: bool
    duration_ms: int | None
    notes: str | None
    source_ids: tuple[str, ...]

@dataclass(frozen=True)
class SessionTrace:
    session_id: str
    question: str
    events: tuple[EventTrace, ...]
    failed_events: tuple[EventTrace, ...]
    total_duration_ms: int | None
    evidence_record_ids: tuple[str, ...]

    @property
    def all_succeeded(self) -> bool:
        return not self.failed_events
```

`build_session_trace` is a pure read-side projection over data AI-O2
already persisted -- it queries nothing itself (`events` is passed in,
already fetched via `SessionRepository.list_events`, the same "caller
owns the repository call" boundary `run_fixed_evidence_workflow`
already follows). `total_duration_ms` sums every event's `duration_ms`
that is not `None`; an event with no recorded duration is excluded from
the sum, not treated as zero -- a session with some untimed legacy or
future events still reports an honest partial total rather than a
silently-wrong one. `evidence_record_ids` is the deduplicated union of
every event's `source_ids`, in order of first appearance (the same
"first appearance, not sorted" convention AI-O7's `build_session_report`
already uses for its own citation list).

`render_session_trace` turns a `SessionTrace` into one human-readable
text block with a section per success-criterion question -- what ran
(event list with `workflow_node`/`tool_name`), why (`session.question`,
the original question that triggered the run), what model/tool was used
(`tool_name`/`model_name` per event), where time was spent
(`duration_ms` per event plus the total), what failed (`failed_events`
with their `notes`), and what evidence supported the output
(`evidence_record_ids`). This is deliberately plain text, not a new
schema of its own -- a caller that wants the structured `SessionTrace`
object directly (a future CLI command, `knowledge-engine-web` page, or
another orchestrator step) uses `build_session_trace` and formats it
however that surface needs; `render_session_trace` is the
`docs/roadmap/future_ai_orchestration_plan.md` "answer what ran, why,
..." success criterion's simplest possible fulfillment, not the only
one a future caller must use.

## Why "why" maps to the session's original question, not a per-step field

The success criterion's "why" is answered here at the session level --
`session.user_question_original` is the reason any of these events ran
at all. This project has no per-step "reasoning" data today: every step
`run_fixed_evidence_workflow` runs is fixed by that module's own code
(AI-O3's own success criterion, still true), not chosen by a model that
could explain its choice. A future milestone that lets a model choose
which capabilities to run (closer to AI-O4's planner, widened into
actual dynamic dispatch) would have a real per-step "why" to record;
inventing one now would mean fabricating a justification this project
does not actually compute.

## What this does not do

- Does not add resource/cost metrics beyond wall-clock duration (token
  counts, dollar cost, memory). The roadmap's own AI-O9 heading says
  "Observability **+ Budgeting**," but nothing in this project tracks a
  budget or a cost unit today -- Ollama is local and free per-call, and
  no cloud provider is wired in (`routing.py`'s `cloud_allowed` gate
  stays deny-by-default). Budgeting has no real quantity to measure
  until a cost-bearing provider exists; adding a placeholder cost field
  now would be exactly the kind of invented capability this project's
  discipline avoids. Named here as explicit follow-up once (if) a
  cost-bearing provider is added.
- Does not decompose the two-branch retrieval step's combined timing
  into a true per-branch cost. Named above as a real, acknowledged
  limitation of this slice, not silently hidden.
- Does not add a CLI command, session-close gate, or web page consuming
  `SessionTrace`/`render_session_trace` yet -- this milestone is the
  reporting primitive itself, matching AI-O5/AI-O6/AI-O7/AI-O8's own
  "no orchestrator/CLI wiring yet" boundary for a first slice.
- Does not retroactively backfill `duration_ms`/`source_ids` on events
  already persisted by an older version of `workflow.py` before this
  change. Those rows simply have `duration_ms=None`/`source_ids=()`,
  which `build_session_trace` already handles honestly (excluded from
  the duration total, absent from the evidence-record union) rather
  than requiring a migration.

## Testing strategy

Unit tests for `build_session_trace`/`render_session_trace` against
hand-built `ResearchSession`/`ResearchEvent` fixtures (mirroring
`tests/test_orchestrator_workflow.py`'s fixture style): a session with
all-succeeded events reports `all_succeeded=True` and the correct
summed duration; a session with one failed event surfaces it in
`failed_events` with its `notes`; an event with `duration_ms=None` is
excluded from the total, not counted as zero; `evidence_record_ids` is
the deduplicated, first-appearance-ordered union across events;
`render_session_trace`'s output contains the key facts (spot-checked
substrings, not exact-string matching, since exact wording is not this
module's contract). New `workflow.py` tests confirm `duration_ms` is
populated (`>= 0`, not `None`) and `source_ids` carries the expected
evidence-record IDs for the two retrieval steps specifically.

## Live verification

Ran `run_fixed_evidence_workflow` against the real GLP-1 corpus with
`core`'s actual `ke` executable -- all four fixed steps supplied
(retrieval, contradiction-oriented retrieval, evidence map, statistical
verification) -- then `build_session_trace` + `render_session_trace`
over the resulting real event log. All six sections rendered with real
data, not placeholders:

- **What ran** -- all 4 steps, all `[succeeded]`.
- **Why** -- the real question, "does semaglutide reduce body weight
  more than placebo."
- **What model/tool was used** -- the real `ke` subcommand per step
  (`ke evidence-report`, `ke evidence-report (contradiction-oriented)`,
  `ke evidence-map-report`, `ke statistical-verify`).
- **Where time was spent** -- real durations: the combined
  parallel-retrieval call took 58,166ms (both retrieval events, same
  combined-span duration as designed), evidence-map 1,994ms,
  statistical-verification 1,732ms, for a real
  `total_duration_ms=120,058`.
- **What failed** -- nothing; `all_succeeded=True`.
- **What evidence supported the output** -- 4 real, deduplicated
  evidence-record IDs (`ev-glp1-gao-meta-analysis-body-weight-001`,
  `ev-glp1-gao-meta-analysis-safety-discontinuation-001`,
  `ev-glp1-select-trial-weight-loss-208wk-001`,
  `ev-glp1-step5-body-weight-week104-001`) -- a field
  `workflow.py` never actually populated before this milestone.

The 58-second retrieval duration is itself a genuine, worth-keeping
observation (not tuned away): both `ke evidence-report` calls include
Evidence Intelligence enrichment per matched record
(`enriched_evidence_report`), and this environment has previously shown
first-call SQLite migration/lock contention (documented in
`docs/ai_o5_design.md`); this run did not isolate which factor
dominates. That question -- decomposing the combined retrieval span
further -- is the same follow-up already named above ("does not
decompose the two-branch retrieval step's combined timing"), not
resolved by this observation, only made concrete by it.
