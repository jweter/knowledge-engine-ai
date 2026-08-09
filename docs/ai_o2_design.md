# AI-O2 Design: Durable Research Session

Status: implementation-ready design for this repository's second
Research Copilot milestone, immediately after AI-O1 (`ResearchPlan`/
`ResearchTask`, merged). Same precedent as `docs/ai_o1_design.md`: this
document scopes down to what AI-O2 actually builds, not the full
architecture -- see `docs/roadmap/future_ai_orchestration_plan.md` for
that.

## Mission

Build `ResearchSession`/`ResearchEvent` persistence, an append-only
event log, and the guarantees needed for a workflow to stop and resume
without losing or duplicating state -- AI-O2's stated success
criterion, verbatim from the roadmap.

## Why `ResearchSession` does not carry the design doc's list fields directly

`future_ai_orchestration_plan.md`'s "Durable Research Workflow State"
section sketches a `ResearchSession` with many list fields
(`retrieval_runs[]`, `discovery_runs[]`, `analyses[]`,
`statistical_checks[]`, `contradiction_checks[]`, `gap_assessments[]`,
`verification_results[]`, `syntheses[]`, `user_decisions[]`,
`unresolved_questions[]`, `workflow_events[]`). This design
deliberately does not store those as columns or JSON blobs on the
session row. The same section states the governing rule immediately
above that sketch: "Every important action becomes an append-only or
versioned event." Storing both a mutable list of, say,
`statistical_checks[]` on the session *and* a separate append-only
`ResearchEvent` log for the same information would be two sources of
truth for one fact, which is exactly what BLOCK 10 (non-deterministic
research continuation) and BLOCK 13 (memory poisoning) warn against.

So `ResearchSession` here is the durable *header* record only
(identity, timestamps, the original question, lifecycle status,
snapshot references); every category the sketch's list fields
represent is a query over `ResearchEvent` rows for that `session_id`
(`workflow_node = "corpus_retrieval"` for `retrieval_runs`,
`workflow_node = "statistics"` for `statistical_checks`, and so on).
`SessionRepository.list_events` returns the full ordered log; a
future read-side view (AI-O3+, once real workflow nodes exist to
populate it) can group by `workflow_node` to reconstruct any of the
sketch's per-category lists without this module changing.

## What this milestone builds

Two things, in `knowledge_engine_ai/sessions/`:

1. **`models.py`** -- `SessionStatus` (the design doc's "Durable
   Workflow Engine" section's nine suggested states verbatim:
   `pending`, `running`, `blocked`, `awaiting_input`,
   `awaiting_approval`, `completed`, `failed`, `cancelled`,
   `superseded`), `is_terminal_status()`, and the frozen
   `ResearchSession`/`ResearchEvent` dataclasses described above.
2. **`repository.py`** -- `SessionRepository`, a SQLite-backed store
   with the two guarantees the success criterion actually needs:
   - `create_session` raises `DuplicateSessionError` on a re-used
     `session_id` (a `UNIQUE` primary key constraint underneath) -- a
     resuming caller must explicitly `get_session` first and branch,
     rather than this module silently guessing whether a second
     `create_session` call means "resume" or "a real bug."
   - `append_event` raises `DuplicateEventError` on a re-used
     `event_id` -- an orchestrator that does not know whether a step
     already ran (exactly the situation a crash-and-resume leaves it
     in) gets an unambiguous signal instead of a silent duplicate
     insert. `has_event()` lets a caller check first instead of
     relying on the exception for normal control flow.

   `list_events` returns a session's full event log in the order
   events were appended (an integer `sequence_number` column, not
   wall-clock `timestamp`, is the ordering key -- a caller could pass
   an out-of-order or backdated timestamp for a retried event, and
   insertion order is what actually happened). `update_session_status`
   updates the header row's lifecycle state.

   `new_connection(path)` opens a `sqlite3.Connection` with
   `row_factory = sqlite3.Row` set (this module's row-parsing helpers
   depend on column-name access); `SessionRepository` itself takes an
   already-open connection rather than a path, the same
   dependency-injection shape `knowledge_engine.database` uses in
   `core` -- a future caller (a test, a CLI command, an orchestrator)
   controls the connection's lifecycle, not this module.

`tests/sessions/test_repository.py`'s
`test_workflow_can_stop_and_resume_without_losing_or_duplicating_state`
exercises the actual success criterion end to end against a real
file-backed SQLite database (not `:memory:`): create a session, append
one event, close the connection entirely (simulating a crash), open a
*new* connection and repository against the same file, check
`has_event()` before re-appending the same event, append a second new
event, and assert the final event log is exactly the two events in
order with no duplicate row -- then separately assert that
re-appending the first event without checking first correctly raises
`DuplicateEventError`.

## No LLM, no orchestrator, no real workflow node

Nothing in this milestone calls an LLM, `ke`, or any retrieval/
Evidence Intelligence/statistics capability. `ResearchEvent.workflow_node`
and `executor_type` are free-text fields a future caller populates;
this module does not define or enforce a fixed vocabulary for them,
since AI-O3 (the deterministic orchestrator that actually connects real
capabilities) is where those vocabularies would first have real
callers to validate against -- inventing one now, with no orchestrator
to constrain it, would be guessing.

## Out of scope (this milestone)

- **Any orchestrator that creates sessions, appends events, or decides
  what workflow node runs next.** AI-O3 ("Deterministic Orchestrator")
  connects existing `core` retrieval/Evidence Intelligence/statistical-
  verification capabilities using fixed workflow rules; AI-O2 stops at
  the persistence layer those future calls will use.
- **A CLI command** (`ke-ai session show`/`session continue`, from the
  design doc's "Suggested Future CLI" section). There is nothing to
  show or continue yet without AI-O3's orchestrator producing real
  session data -- the same "create modules when the second real
  implementation requires them" discipline `ai_o1_design.md` already
  applied to its own package-structure question.
- **A fixed vocabulary for `workflow_node`/`executor_type`.** Left
  free-text until AI-O3 gives them real callers to constrain against.
- **Concurrent/multi-process write safety beyond SQLite's own default
  locking.** `core`'s `knowledge_engine.database` module does not
  layer additional application-level locking on top of SQLite either;
  this milestone matches that precedent rather than inventing a new
  policy. Revisit if AI-O3's orchestrator needs true concurrent writers.
- **Schema migrations.** `_SCHEMA` uses `CREATE TABLE IF NOT EXISTS`,
  matching a from-scratch bootstrap; no migration tooling exists yet
  because there is only one schema version so far.

## Open questions (owner decisions, not resolved here)

- **Where `research_plan_id` actually gets set from.** `ResearchSession`
  carries an optional link to an AI-O1 `ResearchPlan.plan_id`, but
  nothing in this milestone creates a plan and attaches it to a
  session -- that wiring is AI-O3/AI-O4's job once a real planner
  exists.
- **Whether session/event rows ever need to be deleted or archived**
  (e.g. a data-retention policy). Not addressed; the design doc's own
  "Research Memory" section discusses *what* should be durable but not
  *how long*, and no real usage exists yet to size that decision
  against.
