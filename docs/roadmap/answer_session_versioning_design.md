# Answer / Session Versioning Design

Status: proposed design, not yet implemented, 2026-08-22.

This document scopes the answer/session-versioning concept that
`docs/project-status.yaml`'s `next_continuation` names as a prerequisite for
AI-FRD-5's remaining work: wiring `copilot/research_freshness.py`'s
`assess_rerun_need()`/`diff_candidate_snapshots()` into `run_research_question`
so a correction or retraction can actually qualify or invalidate a prior
narrative, and so prior answer text is versioned rather than silently
overwritten. That wiring is explicitly **not** done by this document -- see
"What this does not do" below. This document only answers the question
`docs/project-status.yaml` posed: what does "version" mean here, concretely,
grounded in what already exists in this repository, not invented machinery.

The matching AI-FRD-5 status entries are in
`federated_discovery_orchestration_adoption.md` (this directory); read that
file's AI-FRD-5 section first for the full history this design continues.

## What already exists that this design must not duplicate

Four pieces of already-implemented machinery constrain every choice below:

- **`ResearchSession`/`ResearchEvent`** (`sessions/models.py`): a session is
  a durable *header* record; every important action is a separate,
  immutable, append-only `ResearchEvent` row, ordered by
  `sequence_number` (`sessions/repository.py`). Nothing in this store is
  ever updated or deleted once appended -- `SessionRepository` has no
  `UPDATE`/`DELETE` on `research_events` or `research_isas` at all, only
  `INSERT` and, for the session header alone, a `status`/`updated_at`
  update.
- **`ResearchISA` is write-once per session**
  (`SessionRepository.attach_research_isa`): "If the research objective
  changes materially, create a new run/session rather than rewriting the
  original completion contract" is that method's own docstring, already
  stated before this design exists.
- **`SessionStatus` already has an unused terminal state for exactly this
  case.** `sessions/models.py`'s `SessionStatus` enum defines `SUPERSEDED`
  and `is_terminal_status()` already treats it as terminal alongside
  `COMPLETED`/`FAILED`/`CANCELLED` ("a status a session cannot resume
  from"). No code path in this repository sets `SUPERSEDED` today --
  `run_research_question`/`close_gate.py` only ever produce `RUNNING`,
  `COMPLETED`, or `BLOCKED`. `future_ai_orchestration_plan.md`'s original
  "Durable Workflow Engine" sketch listed `superseded` among its suggested
  states from the start; this design is simply the first concrete use of a
  state the project already anticipated needing.
- **The narrative's actual text already survives, durably, today** --
  `run_research_question.py`'s `_record_synthesis_event` writes the full
  narrative into the synthesis `ResearchEvent.notes` field (plus a
  `sha256:` `output_hash` for tamper-evidence) whenever synthesis
  succeeds. "Prior answer text is never silently overwritten" is therefore
  already half-true by construction: no code path in this repository
  mutates an existing `ResearchEvent`. What is missing is not durability of
  old text, but an explicit way to say *this newer event/session is the
  one to trust now*, and *why* -- which is what version identity below
  provides.

## What "version" means

**A version is one whole `ResearchSession`, never a second synthesis event
folded into an existing session.**

Concretely, `ResearchSession` gains three additive optional fields (same
"new optional field, no schema-version bump, old rows parse unchanged"
pattern AI-O9 already used for `ResearchEvent.duration_ms`/`source_ids`):

```python
research_question_id: str | None = None  # thread identity across versions
answer_version: int = 1  # 1-based, monotonic within the thread
supersedes_session_id: str | None = None  # the immediately-prior version, if any
```

`research_question_id` is not a new concept -- it is the same string
`ke_client.federated_discover()`/`federated_discover_history()` already
accept and key on (`docs/roadmap/federated_discovery_orchestration_adoption.md`'s
2026-08-20 entries). Setting `ResearchSession.research_question_id` to the
same value a caller supplies to `federated_discover(research_question_id=...)`
makes it the single join key between Core's federated-discovery run history
(what `assess_rerun_need`/`diff_candidate_snapshots` read) and AI's own
session/version chain (what a caller asking "is this answer still fresh"
reads) -- one shared identity, not two identities that could drift.

### Why a whole new session, not a second event in the same session

Two options were considered:

1. **Reuse the existing session**: append a second synthesis
   `ResearchEvent` with the refreshed narrative, record new ISA criterion
   results, call `attempt_session_close` again. Structurally possible --
   `record_criterion_result`/`append_event` are append-only and
   `update_session_status` does not itself restrict which transitions are
   legal.
2. **Mint a new session** that references the old one, and move the old
   session to `SUPERSEDED`.

Option 1 is rejected. `is_terminal_status`'s own docstring is explicit:
`COMPLETED` is a status "a session cannot resume from." The case this
design exists for is precisely a session that already reached `COMPLETED`
-- that is what makes its narrative a "prior answer" worth protecting. Re-opening
a `COMPLETED` session to append a new synthesis event would violate an
invariant this repository already documents, for the most common case this
design needs to handle. It would also leave `SessionStatus.SUPERSEDED`
permanently unused, when the enum plainly anticipates a session-level
supersession event, not an in-place answer edit.

Option 2 is this design. A version transition is a session transition:
version *N+1* is a brand-new `session_id`, created by calling
`run_research_question` again (unchanged signature; see "What this does
not do"), with its own fresh `ResearchISA`, its own independent close-gate
run, and its own full `ResearchEvent` log. Nothing about version *N*'s
session is ever rewritten. Only after version *N+1* itself reaches
`COMPLETED` does version *N*'s session move `COMPLETED -> SUPERSEDED`,
recorded the same way `close_gate.py` already records its own lifecycle
transitions: an explicit `ResearchEvent` (`workflow_node="answer_superseded"`,
`executor_type="deterministic_policy"`) whose `notes` names the specific
reason (see below), not just a bare status flip.

### Why not a content hash, and why not a bare timestamp

`ResearchEvent.output_hash` already exists per event as a tamper-evidence
check -- it answers "has this exact text changed," not "which version is
this, and does a newer one exist." A hash alone gives no ordering, no
thread identity, and no link to *why* a new version was warranted; a bare
timestamp gives ordering but no thread identity or causal link either.
`answer_version`/`research_question_id`/`supersedes_session_id` supply
exactly the three things a hash or a timestamp alone do not: which thread
this session belongs to, where it sits in that thread, and what it
replaced -- while `output_hash` keeps doing the integrity job it already
does within one version.

## How `assess_rerun_need`/`diff_candidate_snapshots` map onto a version transition

Both functions are read exactly as shipped in `copilot/research_freshness.py`
(PR #58) -- this design adds no new parameters or return fields to either.

```python
def assess_rerun_need(
    history: FederatedDiscoverHistoryResult, *, now: datetime,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> RerunRecommendation

def diff_candidate_snapshots(
    previous: FederatedCoverageReportResult,
    current: FederatedCoverageReportResult,
) -> CandidateFreshnessDiff
```

The proposed (not-yet-implemented) trigger sequence, for a session `S` with
`S.research_question_id` set:

1. `assess_rerun_need(federated_discover_history(S.research_question_id), now=...)`.
   `recommended=False` means nothing further happens -- `S` stays the
   thread's latest version, no new `ResearchEvent`, no status change. This
   reuses `assess_rerun_need`'s existing three deterministic triggers
   (never recorded, incomplete, stale) unchanged.
2. `recommended=True` authorizes (does not itself perform) a fresh
   `federated_discover()` call, producing a new `SearchCoverageReport`.
3. `diff_candidate_snapshots(previous=<S's own originating run's coverage
   report>, current=<the new run's coverage report>)`. "S's own originating
   run" is already available without a new field: `ResearchQuestionResult.discovery`
   (`DiscoveryAugmentationResult`, from the existing AI-FRD-3/4 wiring)
   records the `search_run_id` a session's own discovery step used, when one
   ran.
4. `diff.newly_discovered` alone (candidates nobody has seen before, no
   flag involved) is a **freshness signal, not a version trigger** -- it is
   surfaced to a caller (see "what a caller sees" below) but never by
   itself supersedes `S`. New evidence existing is not the same claim as
   *this session's own narrative is now wrong or incomplete*.
5. `diff.newly_flagged: tuple[PublicationStatusFlip, ...]` is where a real
   trigger can originate, but only for a flip that actually reaches `S`'s
   narrative -- see the crosswalk below. A flip on a candidate `S` never
   cited is the same "freshness signal, not a version trigger" case as
   `newly_discovered`.

### The crosswalk: does a flagged candidate actually touch this narrative

`diff_candidate_snapshots` operates over federated-discovery candidates
(`FederatedCandidateRecord`, keyed by Core's `canonical_id`, carrying
`doi`). A narrative's actual citations are `[evidence_record_id]` tokens
inside the persisted text, extracted with `verification.py`'s existing
`CITATION_PATTERN` (already shared between `verification.py` and
`session_report.py`; this design reuses it a third time rather than
writing a fourth citation-extraction regex). The join between the two is
DOI: `EvidenceReport.papers[].doi` (`RetrievedPaper.doi`, already parsed by
`models.py`) versus a flagged `FederatedCandidateRecord.doi`.

For each `PublicationStatusFlip` in `diff.newly_flagged`:

1. Look up its `canonical_id` in `current.candidates` to get the
   candidate's `doi`.
2. If that `doi` matches a `RetrievedPaper.doi` from `S`'s own retrieval
   step, **and** at least one of that paper's `evidence_records[].evidence_record_id`
   appears in `CITATION_PATTERN.findall(S's persisted narrative text)`,
   the flip touches `S`'s actual narrative. Otherwise it does not -- the
   retracted/corrected work was a discovery lead `S` never promoted to a
   cited claim (matching this project's existing "discovery leads, not
   evidence" rule), and the flip stays a freshness signal only.
3. `S`'s own retrieval-step `RetrievedPaper` list is not currently
   persisted as a durable, replayable field on any `ResearchEvent` (AI-O9's
   retrieval events carry `source_ids` -- evidence-record IDs -- but not
   each record's `doi`). Reconstructing it today means re-running
   `ke evidence-report` against `S`'s own `corpus_snapshot_id` (already a
   `ResearchSession` field) rather than reading a persisted value. This is
   a real, named gap this design does not silently paper over: the
   wiring PR should either accept the re-run cost (bounded, read-only,
   `ConsequenceLevel.READ_ONLY` per AI-O1's own table) or add a small
   additive `doi` field alongside the retrieval step's existing
   `source_ids`. Either is a small, separate implementation decision left
   to that PR -- not decided here.

### Invalidates versus qualifies

The four flags `diff_candidate_snapshots` already tracks
(`_PUBLICATION_STATUS_FLAGS = retracted, corrected, expression_of_concern,
withdrawn`) do not carry equal weight, and treating them identically would
itself violate "graceful degradation must stay honest" (Core's
`agent-development-policy.md` section 7, and this repository's own
addendum): a full retraction is not the same claim as a milder correction.

- **`retracted` / `withdrawn` -- invalidates.** A claim resting on this
  record can no longer be treated as supported by it at all.
- **`corrected` / `expression_of_concern` -- qualifies.** The claim may
  still stand, but must carry a visible caveat, not silent omission --
  the same standard the ISA's own existing `contradiction_review`
  criterion (`run_research_question.py`'s `_build_isa`) already applies to
  qualifying evidence found during the original run.

Either outcome is a version-transition trigger. Neither rewrites `S`'s own
narrative text in place -- see below.

### What is retained from the prior version

Everything. `S`'s full session header, its write-once `ResearchISA`, its
entire `ResearchEvent` log (including the exact narrative text that was
once presented as current, its `output_hash`, and every ISA criterion
result that justified its original `COMPLETED` status) stay in
`SessionRepository` exactly as they were persisted, permanently
queryable by `S`'s own `session_id`. The only change `S` itself ever
receives is the single, explicit `answer_superseded` event and the status
flip to `SUPERSEDED`, both added *after* a real replacement version exists
-- never a rewritten `notes` field, never a deleted row. This is the
concrete mechanism by which "provenance survives normalization" applies to
answer text, not just to source records: the old answer is not merged away
into the new one, it is superseded and kept.

## Interaction with session close gates

A version transition never reopens a closed session's own close gate.

- `S` reaching `COMPLETED` is what makes it a candidate for later
  supersession in the first place -- and `COMPLETED` is already documented
  as terminal (`is_terminal_status`). This design adds no path that moves a
  `COMPLETED` session back to `RUNNING`/`BLOCKED` to re-run its gate. Any
  re-verification is a new session's own gate, evaluated independently by
  `attempt_session_close` exactly as it is today.
- Rerunning is always "create a new session referencing the old one," never
  "reopen the old session." Concretely: version *N+1* is produced by a
  second `run_research_question` call (same public shape, a new
  `session_id`), which independently creates its own `ResearchISA`, runs
  its own workflow/synthesis/verification, and reaches its own close-gate
  decision -- `COMPLETED` or `BLOCKED`, on its own merits, exactly like any
  other call to that function today.
- **`S` is moved to `SUPERSEDED` only once *N+1* itself reaches `COMPLETED`.**
  If *N+1* ends `BLOCKED` (e.g. the refreshed evidence set introduces its
  own new citation problem), `S` is deliberately left `COMPLETED` and
  callers keep seeing `S` as the thread's latest good version. A blocked,
  unreleased re-verification attempt must never retroactively invalidate a
  still-good prior answer -- the same "a degraded run must never be
  presented as if it were complete" rule applied in the opposite direction:
  an *incomplete new run* must never silently demote a *complete old one*.
  In this state, a caller asking "is this fresh" sees `S` still
  `COMPLETED`, plus the specific pending flip named as an open,
  unresolved qualification (see below) -- honest about the gap, not
  hidden and not overstated.
- A `BLOCKED` session (`S` never reached `COMPLETED` at all) is *not*
  terminal today (`is_terminal_status` omits `BLOCKED`) -- this design
  does not change that. A blocked session was never a "released" answer to
  begin with (`ResearchQuestionResult.narrative_releaseable` already gates
  on `close_result.status is COMPLETED`), so it is not a meaningful subject
  for supersession; the existing "record new criterion results, re-run
  `attempt_session_close` on the same session" resumption path this
  repository already supports is the right mechanism there, unchanged by
  this design.

## What a caller (Web, later) sees when asking "is this answer still fresh"

A read-only projection, in the same spirit as `observability.py`'s
`build_session_trace` ("a pure read-side projection over data ... already
persisted -- it queries nothing itself"). Sketch, not a committed API:

```python
@dataclass(frozen=True)
class AnswerFreshness:
    session_id: str
    research_question_id: str | None
    answer_version: int
    status: SessionStatus
    supersedes_session_id: str | None
    superseded_by_session_id: str | None  # None if this is the thread's latest version
    rerun_recommended: RerunRecommendation | None  # live assess_rerun_need() result, or None
    # when research_question_id is unset
    pending_flips: tuple[PublicationStatusFlip, ...]  # detected, crosswalked, not yet
    # resolved into a newer version
```

Three honestly-distinguished states, never collapsed into one:

- **Current** -- latest version in its thread, no pending crosswalked flip.
- **Flagged, rerun recommended** -- a cited-record flip was detected
  (`pending_flips` non-empty) but no newer `COMPLETED` version exists yet.
  This is the degraded-but-honest state a caller must be able to see
  distinctly, not silently as either "still fine" or "gone."
- **Superseded by session X** -- `superseded_by_session_id` is set; the
  caller should follow the chain to the named session for the current
  answer, while this session's own text remains inspectable on request.

## What this does not do

- **No change to `run_research_question.py`, `sessions/models.py`,
  `sessions/repository.py`, `orchestrator/close_gate.py`, or
  `copilot/research_freshness.py`.** This is a design document only; every
  field, method, and event shape above is proposed, not implemented, not
  tested, and not live-verified.
- **No SQLite schema migration.** `research_question_id`/`answer_version`/
  `supersedes_session_id` are described as additive columns following the
  existing `duration_ms`/`source_ids` precedent, but no `ALTER TABLE`
  exists yet.
- **No decision on who/what triggers a freshness check** (a scheduled job,
  a person, a Web page load) or how often -- that is
  `discovery_policy.py`-shaped follow-up policy work, deliberately left
  open the same way `discovery_policy.py`'s own trigger thresholds were
  named as tunable, not fixed, when AI-FRD-3/AI-FRD-4 were wired.
- **No execution-budget/cost policy for the rerun call chain** this design
  describes (fresh `federated_discover()` plus a full second
  `run_research_question()` call). The existing `FederatedDiscoveryPolicy`
  bounds (`copilot/discovery_policy.py`) are the natural reuse target, not
  a new budget invented here.
- **No Web-facing API or UI for `AnswerFreshness`.** That sketch exists to
  make this design's "what a caller sees" answer concrete, not as a
  committed contract for `knowledge-engine-web` to implement against yet.
- **Does not resolve the `RetrievedPaper.doi` persistence gap** named
  above under "the crosswalk" -- named as an open implementation choice for
  the eventual wiring PR, not decided here.

## Relationship to AI-FRD-5's exit criteria

This document is the scoping step `docs/project-status.yaml`'s
`next_continuation` named as blocking AI-FRD-5's remaining two exit
criteria (`federated_discovery_orchestration_adoption.md`'s AI-FRD-5
section):

- *"corrections/retractions can invalidate or qualify prior synthesis"* --
  this design's crosswalk and invalidates/qualifies split is the concrete
  mechanism a future implementation PR would build.
- *"prior answer text is never silently overwritten as if it had always
  been the updated answer"* -- this design's whole-session versioning,
  append-only retention, and `SUPERSEDED` transition (only after a real
  replacement reaches `COMPLETED`) is the concrete mechanism for that.

Both exit criteria remain **not started** in code terms until a follow-up
PR implements the fields, the crosswalk, and the trigger wiring this
document describes.
