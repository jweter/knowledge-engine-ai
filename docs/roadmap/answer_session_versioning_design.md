# Answer / Session Versioning Design

Status: proposed design, 2026-08-22; `research_question_id` threading (one
sub-section below) implemented the same day. **2026-08-22 (later same day):
the repository-layer mechanics are now implemented too** -- `ResearchSession`
gained the three remaining additive fields (`answer_version`,
`supersedes_session_id`, `narrative_invalidated_at`), and
`SessionRepository` gained `record_narrative_invalidation()` (appends the
`narrative_invalidated` event, sets the field, guarded against being called
twice) and `supersede_session()` (appends the `answer_superseded` event,
flips status to `SUPERSEDED`, guarded to require the superseded session was
`COMPLETED`). Both are standalone and tested (13 new tests), but nothing
calls them yet: the DOI crosswalk that would decide *when* an invalidating
or qualifying flip actually touches a session's own cited narrative, and the
policy for when a freshness check runs at all, remain not yet implemented --
see "What this does not do" below, updated to match.

**2026-08-22 (later still): the DOI crosswalk itself is now implemented --
"the crosswalk" section below is built exactly as scoped, and this section's
own open sub-decision is resolved.** `copilot/research_freshness.py` gained
`session_retrieval_dois()` (builds an `evidence_record_id -> doi` mapping
from a session's own retrieval-step events) and
`crosswalk_publication_status_flips()` (the three-step join "the crosswalk"
section describes, returning a `NarrativeTouchingFlip` for each flip that
actually touches the session's persisted, cited narrative). The open
sub-decision that section named -- re-run `ke evidence-report` at check time,
or add an additive `doi` field alongside the retrieval event's existing
`source_ids` -- is resolved as the additive field:
`ResearchEvent.source_dois` (parallel to `source_ids`, same order, same
additive/no-schema-bump precedent as `duration_ms`), populated by both
retrieval-step events in `orchestrator/workflow.py`. Re-running was rejected
because it cannot answer the question this crosswalk actually needs
answered -- "what did *this* session's own retrieval step see," not "what
would retrieval see today" -- and a corpus that has changed since the
session ran (which is exactly the scenario a freshness check exists to
detect) can silently return different papers on a re-run, which would make
the crosswalk's own citation-matching unreliable. 14 new tests (385 total
pass); full local quality gate clean via `scripts/preflight.py`. Both new
functions are pure -- no `SessionRepository`/`ke` call inside either one --
matching `assess_rerun_need`/`diff_candidate_snapshots`'s own shape. Still
not implemented: the invalidates-versus-qualifies trigger that acts on a
`NarrativeTouchingFlip` (calls `record_narrative_invalidation()` or records
a qualifying pending flip), the `AnswerFreshness` read-side projection, and
a caller that mints a version-*N+1* session -- see "What this does not do"
below, updated to match.

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
  update (`update_session_status`, `sessions/repository.py`). This design
  adds exactly one more header field to that same narrow exception --
  `narrative_invalidated_at`, below -- not a new kind of mutation.
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

Concretely, `ResearchSession` gains four additive optional fields (same
"new optional field, no schema-version bump, old rows parse unchanged"
pattern AI-O9 already used for `ResearchEvent.duration_ms`/`source_ids`):

```python
research_question_id: str | None = None  # thread identity across versions
answer_version: int = 1  # 1-based, monotonic within the thread
supersedes_session_id: str | None = None  # the immediately-prior version, if any
narrative_invalidated_at: str | None = None
# Set once, the moment an invalidating flip crosswalks to a citation of
# this session's own narrative; see "Interaction with session close
# gates" below.
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

### Where `research_question_id` actually comes from, and how it reaches `federated_discover`

**Implemented 2026-08-22.** `run_research_question` now accepts an
optional `research_question_id: str | None = None` keyword parameter,
always sets it on the `ResearchSession` it creates (a caller-supplied
value used verbatim, or -- when omitted -- one derived deterministically
via `_derive_research_question_id()`, exactly the
`f"rq-{hashlib.sha256(...).hexdigest()[:16]}"` shape this section
specifies), and threads it through `evaluate_and_run_discovery_augmentation`
-> `_run_federated_discovery` -> `execute_discovery_plan` -> the
already-existing `ke_client.federated_discover(research_question_id=...)`
call, only when `discovery_policy` is also supplied. Not threaded into
citation-snowball, per this section's own point 5. This closes the
concrete plumbing gap this section describes; the rest of this
document -- the crosswalk, invalidates/qualifies trigger, `answer_version`/
`supersedes_session_id`/`narrative_invalidated_at` fields, and
`SessionStatus.SUPERSEDED`'s first real use -- remains unimplemented.

Setting `ResearchSession.research_question_id` is necessary but not
sufficient: Core's `federated_discover_history()`/`federated_coverage_report()`
only have something to find later if the run that produced `S`'s own
discovery data was itself tagged with that same ID at call time, and read
as shipped, nothing in the call chain does that today.

- `run_research_question`'s current signature
  (`copilot/run_research_question.py`) has no `research_question_id`
  parameter at all.
- `evaluate_and_run_discovery_augmentation`/`_run_federated_discovery`
  (`copilot/discovery_policy.py`) call `compile_discovery_plan`/
  `execute_discovery_plan` with `question`, `providers`,
  `limit_per_provider`, and friends -- no question-thread identity
  anywhere in that call.
- `execute_discovery_plan` (`discovery_plan.py`) calls
  `ke_client.federated_discover()` without `research_question_id`, even
  though `federated_discover()` itself already accepts that keyword
  (`ke_client.py`, forwarded to Core's `--research-question-id` flag).
  The underlying Core capability already exists end to end; the AI-side
  plumbing between `run_research_question` and it is simply missing.

The wiring PR needs to close this concretely, not just declare the field:

1. `run_research_question` gains a new keyword-only parameter,
   `research_question_id: str | None = None` -- additive, the same
   opt-in shape `discovery_policy: FederatedDiscoveryPolicy | None = None`
   already uses on that same function, so every existing caller that does
   not pass it keeps today's behavior exactly.
2. **Origin.** When a caller supplies a value, that value is used
   verbatim -- typically a stable per-question-thread identifier a future
   Web caller mints and persists on its own side (WEB-FRD-5-shaped
   follow-up work, not this repository's). When omitted -- the common
   case until such a caller exists -- `run_research_question` derives one
   deterministically from the question text itself, reusing the same
   `hashlib.sha256` this module's own `_hash()` helper already imports
   (a different prefix/truncation than `_hash()`'s own `sha256:` output,
   since this is a thread identity, not a tamper-evidence value): e.g.
   `f"rq-{hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]}"`.
   Deterministic derivation from the question text, not a fresh
   `uuid4()`: `session_id` already gets a random UUID per call, and the
   entire point of `research_question_id` is that it must be the *same*
   value across separate `run_research_question` calls that are really
   "the same question, asked again" -- a random UUID can never produce
   that on its own. This is a named trade-off, not a hidden one: two
   callers who happen to submit verbatim-identical question text without
   coordinating a shared ID get threaded together even if they did not
   intend to share a version chain. The wiring PR should treat a
   caller-supplied ID as the preferred path and the derived fallback as a
   reasonable default for the common single-caller case, not a claim that
   auto-derivation is collision-free in a multi-tenant setting.
3. The derived-or-supplied value threads straight down the existing call
   chain as one new keyword-only parameter per hop -- no new module, no
   new capability, only argument-passing:
   `run_research_question` persists it on `ResearchSession(research_question_id=...)`
   at creation (as above) and, only when `discovery_policy` is also
   supplied, forwards it into
   `evaluate_and_run_discovery_augmentation(..., research_question_id=...)`
   -> `_run_federated_discovery(..., research_question_id=...)` ->
   `execute_discovery_plan(plan, ..., research_question_id=...)` (a new
   keyword-only parameter there too) -> the already-existing
   `federated_discover(..., research_question_id=...)` call -> Core's
   `--research-question-id` flag, exactly as `ke_client.federated_discover`'s
   own docstring already describes for a caller that wants a run
   correlated later.
4. Deliberately **not** added to `DiscoveryPlan`/`compile_discovery_plan`.
   `research_question_id` is call-time run-identity context, the same
   category as `ledger_root` and the provider API keys (already
   execute-time-only arguments on `execute_discovery_plan`), not a search
   parameter a compiled plan's own `providers`/`max_execution_seconds`
   validation needs to see or bound.
5. **Citation-snowball is out of scope for this threading.**
   `ke_client.citation_snowball()` has no `research_question_id`
   parameter at all today, and this design's freshness mechanism only
   ever reads `federated_discover_history()`/`federated_coverage_report()`
   (federated-discover run history) -- never snowball history -- so there
   is nothing for a snowball call to thread an ID into for this design's
   purposes.

Once threaded this way, `federated_discover_history(S.research_question_id)`
is guaranteed to find something the moment any federated-discover call
under that ID has ever run, including the very first one -- which "No
prior discovery snapshot at all: baseline capture and first-seen
assertion" below depends on.

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

### No prior discovery snapshot at all: baseline capture and first-seen assertion

Step 3 above assumes "S's own originating run's coverage report" exists.
It does not whenever `discovery_policy` was omitted entirely, or was
supplied but its coverage-gap trigger did not fire
(`DiscoveryAugmentationResult.triggered=False`, `copilot/discovery_policy.py`)
-- the ordinary case for most sessions, not an edge case.
`S.research_question_id` is still set either way (per the threading above
-- caller-supplied or derived, unconditionally, regardless of whether
discovery itself ran), so `federated_discover_history(S.research_question_id)`
is always a well-formed call; it is simply empty (`history.runs == ()`)
for a session like this until something first calls `federated_discover()`
under that ID.

Two mechanisms follow, both adopted by this design rather than left open:

1. **The first federated-discover run ever recorded for a
   `research_question_id`, whenever it happens, is that thread's
   baseline.** `assess_rerun_need`'s own "never recorded" trigger
   (`history.runs` empty -> `recommended=True`, reason "No
   federated-discovery run has ever been recorded for this tracked
   question") already authorizes exactly this run -- nothing new needed
   there. What this design adds is the rule for what happens right
   after that first run completes: `diff_candidate_snapshots` is **not**
   called against it. There is no second, earlier snapshot to pass as
   `previous`; calling it anyway against a fabricated empty
   `FederatedCoverageReportResult` would -- exactly as
   `diff_candidate_snapshots`'s own docstring already says -- report
   every single candidate as `newly_discovered`, technically accurate but
   a useless, noisy signal to hand a caller as "everything just changed"
   the first time a thread is ever observed. This one run is simply
   persisted as the baseline, and the freshness-check pass ends there for
   this thread, honestly reporting "baseline established, nothing to diff
   yet" rather than manufacturing a diff result. Real diffing -- and
   therefore `newly_flagged`-driven version transitions -- becomes
   possible starting from this thread's *second* later freshness check
   onward, once two runs exist to pass as `previous`/`current`. This is a
   real, bounded latency window this design names rather than hides: a
   session with no originating discovery run cannot have a retraction
   detected via the diff mechanism until at least one later freshness
   check has already run once, to establish the baseline.
2. **That window has a second, sharper cost the diff mechanism alone
   cannot close, even after (1): a citation already retracted *before*
   the baseline run ever happens is invisible to any diff**, because a
   diff can only report a flag *becoming* true between two snapshots, and
   there is no earlier snapshot here at all -- the baseline snapshot's own
   candidates already carry whatever `retracted`/`corrected`/
   `expression_of_concern`/`withdrawn` observations Core currently
   records (the same `FederatedCandidateRecord.observations` fields the
   crosswalk already reads), and a diff against a nonexistent "previous"
   simply cannot turn "already true in the one snapshot we have" into a
   `PublicationStatusFlip`. To close this, the very first freshness-check
   pass for a `research_question_id` (the one that captures the baseline)
   additionally runs the crosswalk directly against that single baseline
   snapshot, not only against future diffs: for each DOI `S` actually
   cites (the same DOI/`evidence_record_id` join "the crosswalk" section
   below defines), if the matching `FederatedCandidateRecord` in the
   baseline snapshot already asserts any of the four flags `True` right
   now, that is treated as an immediate invalidates/qualifies signal --
   a **first-seen assertion**, not a diff-derived flip -- rather than
   silently absorbed into "that's just what the baseline happened to look
   like." The same invalidates-versus-qualifies split and the same
   `narrative_invalidated_at`/version-transition mechanics (see
   "Interaction with session close gates" below) apply identically; only
   the trigger's name (assertion vs. flip) differs, and only for this one
   first-ever check per thread.
3. **This first-seen assertion is itself bounded by how discovery works,
   named honestly rather than oversold.** `federated_discover()` runs a
   topical query against providers -- it is not a DOI-keyed point lookup
   -- so there is no guarantee the specific paper `S` cited reappears as a
   candidate in that first baseline run at all. When it does not, this
   fallback simply has nothing to assert for that DOI: the same
   "discovery returns leads, not a guaranteed re-fetch of one specific
   known paper" gap this project already lives with elsewhere
   (`discovery_policy.py`'s own citation-snowball rationale). It
   measurably narrows the pre-tracking blind spot for whichever cited
   DOIs the baseline query happens to still surface; it does not claim to
   close that blind spot completely. A true DOI-keyed point-status lookup
   (as opposed to a query-shaped federated-discover run) would close the
   remaining gap fully, but no such Core capability exists today -- a
   real, separate, not-decided-here follow-up, the same category of open
   implementation choice as the `RetrievedPaper.doi` persistence gap named
   below, not solved by inventing one here.

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
3. **Resolved 2026-08-22.** `S`'s own retrieval-step `RetrievedPaper` list
   was not persisted as a durable, replayable field on any `ResearchEvent`
   (AI-O9's retrieval events carried `source_ids` -- evidence-record IDs --
   but not each record's `doi`). This is now closed with the additive
   field, not a re-run: `ResearchEvent.source_dois` (`sessions/models.py`)
   is a same-length, same-order parallel to `source_ids`, populated by
   both retrieval-step events in `orchestrator/workflow.py`
   (`_evidence_record_dois()`). `copilot/research_freshness.py`'s
   `session_retrieval_dois()` turns a session's own event log into the
   `evidence_record_id -> doi` mapping this crosswalk needs, and
   `crosswalk_publication_status_flips()` is the crosswalk itself, steps
   1-2 above. Re-running `ke evidence-report` against `S`'s
   `corpus_snapshot_id` was rejected: it answers "what would retrieval see
   *today*," not "what did *this* session's retrieval step actually see" --
   and a corpus that changed since `S` ran (the very scenario a freshness
   check exists to catch) can make a re-run return different papers,
   undermining the citation match this crosswalk depends on. The additive
   field costs one guarded `ALTER TABLE` column and no new `ke` call.

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
  own new citation problem) for a rerun that was triggered by aging or by
  a *qualifying* flip, `S` is deliberately left `COMPLETED` and callers
  keep seeing `S` as the thread's latest good version. A blocked,
  unreleased re-verification attempt must never retroactively invalidate a
  still-good prior answer -- the same "a degraded run must never be
  presented as if it were complete" rule applied in the opposite direction:
  an *incomplete new run* must never silently demote a *complete old one*.
  In this state, a caller asking "is this fresh" sees `S` still
  `COMPLETED`, plus the specific pending flip named as an open,
  unresolved qualification (see below) -- honest about the gap, not
  hidden and not overstated. **This bullet does not cover the case where
  the trigger was an *invalidating* flip** (`retracted`/`withdrawn`) --
  see "Releaseability reacts to an invalidating flip immediately" below
  for why that case needs a stronger, independent signal than `S.status`
  alone.
- A `BLOCKED` session (`S` never reached `COMPLETED` at all) is *not*
  terminal today (`is_terminal_status` omits `BLOCKED`) -- this design
  does not change that. A blocked session was never a "released" answer to
  begin with (`ResearchQuestionResult.narrative_releaseable` already gates
  on `close_result.status is COMPLETED`), so it is not a meaningful subject
  for supersession; the existing "record new criterion results, re-run
  `attempt_session_close` on the same session" resumption path this
  repository already supports is the right mechanism there, unchanged by
  this design.

### Releaseability reacts to an invalidating flip immediately, not only once a replacement exists

The bullets above describe what happens to `S`'s *status* --
`COMPLETED` staying `COMPLETED` until a replacement session supersedes
it. They say nothing yet about whether `S` should still be treated as
safe to *release* the moment an invalidating flip is detected on one of
its own citations, and today's only releaseability check,
`ResearchQuestionResult.narrative_releaseable` (`run_research_question.py`),
reads `self.close_result.status is SessionStatus.COMPLETED` (plus
`narrative`/`verification.is_clean`) and nothing else -- computed once,
in-process, the moment that specific run finishes. It has no notion of
"and has anything invalidating happened to this session's citations
since." A later caller re-reading a persisted, previously-`COMPLETED` `S`
(Web's `/ask`, a scheduled freshness sweep) has, today, no field on `S`
itself to consult for that either -- `SessionStatus` alone cannot
distinguish "still genuinely good" from "was good, now known-invalid,
replacement not ready yet." Left this way, `S` stays `COMPLETED` -- and
therefore indistinguishable from a genuinely current answer to any caller
that only checks `status` -- for as long as re-verification takes,
including indefinitely if `N+1` ends `BLOCKED` rather than `COMPLETED`, or
is never even attempted. That is the gap: a `COMPLETED`-only
releaseability check must never depend on a replacement session's outcome
or existence to start reflecting reality.

The fix is `narrative_invalidated_at` (the fourth additive field listed
under "What 'version' means" above), and the rule for when it gets set:

- The moment step 5 of the crosswalk (above), or the first-seen-assertion
  fallback ("No prior discovery snapshot at all," above), determines that
  an **invalidates** flag (`retracted`/`withdrawn` -- never a
  **qualifies** one) touches `S`'s actual cited narrative, two things
  happen immediately, in that same freshness-check pass, before any
  rerun of `run_research_question` is even attempted: `SessionRepository`
  records an explicit `narrative_invalidated` `ResearchEvent`
  (`executor_type="deterministic_policy"`, `notes` naming the specific
  `canonical_id`/`doi`/`evidence_record_id`/flag), and `S`'s header gets
  `narrative_invalidated_at` set to that event's timestamp -- a small,
  additive sibling to `update_session_status`, not a new kind of write
  discipline.
- `S.status` itself is **not** touched by this -- it stays `COMPLETED`.
  Flipping it to `BLOCKED` would violate the invariant this document
  already states above ("no path that moves a `COMPLETED` session back to
  `RUNNING`/`BLOCKED`"), and flipping it to `SUPERSEDED` here would be
  false: nothing has replaced `S` yet. `narrative_invalidated_at` is
  deliberately a parallel signal, not a status value, for exactly this
  reason.
- **`corrected`/`expression_of_concern` (qualifies) flips do not set
  `narrative_invalidated_at`.** They still trigger a version transition
  (per "Invalidates versus qualifies" above) and still populate
  `pending_flips` below, but "the claim may still stand, must carry a
  visible caveat" is a materially weaker claim than "no longer supported
  at all" -- collapsing the two into one release-blocking field would
  itself be the "graceful degradation must stay honest" violation the
  crosswalk section already warns against.
- **Releaseability becomes a two-field check, not a status-only one:** a
  persisted, previously-completed `S` is safe to release as current if
  and only if `S.status is SessionStatus.COMPLETED` **and**
  `S.narrative_invalidated_at is None`. This is the check any future
  re-query of a stored session must perform -- not just the in-process
  `ResearchQuestionResult.narrative_releaseable` property, which only
  ever evaluates a session at the moment its own run just finished,
  before any later flip could exist, and which this design does not
  change. `AnswerFreshness` below exposes `narrative_invalidated_at`
  directly rather than making a caller reconstruct release-safety from
  `pending_flips` non-emptiness alone.
- **Once `N+1` reaches `COMPLETED`,** `S` moves `COMPLETED -> SUPERSEDED`
  exactly as already described, and `narrative_invalidated_at` is left
  set, permanently -- retained history, not cleared on supersession, the
  same "nothing deleted or rewritten" rule the rest of this design
  already follows.
- **If `N+1` instead ends `BLOCKED`, or no rerun has even been attempted
  yet,** `S` is left exactly as the bullet above says -- `status` still
  `COMPLETED` -- but is now *also* `narrative_invalidated_at`-set, so it
  correctly reads as not-releaseable to any caller applying the two-field
  check above, honestly reflecting "was good, now known-invalid, no good
  replacement yet" instead of silently continuing to look identical to a
  still-current answer. This is what closes the gap the bullet above
  leaves open for an aging- or qualifies-triggered rerun: that bullet's
  "`S` is deliberately left `COMPLETED` and callers keep seeing `S` as the
  thread's latest good version" is correct, honest behavior for that
  case, and was never meant to -- and, with `narrative_invalidated_at`, no
  longer does -- cover the specific case of an invalidating flip with no
  completed replacement yet.

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
    narrative_invalidated_at: str | None  # set once an invalidating flip was detected;
    # see "Releaseability reacts to an invalidating flip immediately" above
    rerun_recommended: RerunRecommendation | None  # live assess_rerun_need() result, or None
    # when research_question_id is unset
    pending_flips: tuple[PublicationStatusFlip, ...]  # detected, crosswalked, not yet
    # resolved into a newer version

    @property
    def releaseable(self) -> bool:
        """Mirrors the two-field check above: COMPLETED and not since invalidated."""

        return self.status is SessionStatus.COMPLETED and self.narrative_invalidated_at is None
```

Three honestly-distinguished states, never collapsed into one:

- **Current** -- latest version in its thread, `releaseable` is `True`,
  no pending crosswalked flip.
- **Flagged, rerun recommended** -- a cited-record flip was detected
  (`pending_flips` non-empty). For a *qualifying* flip, `status` is still
  `COMPLETED` and `releaseable` stays `True` -- the narrative may still be
  shown, with the caveat named in `pending_flips`. For an *invalidating*
  flip, `narrative_invalidated_at` is set and `releaseable` is `False`
  regardless of whether a newer `COMPLETED` version exists yet. Either
  way this is the degraded-but-honest state a caller must be able to see
  distinctly, not silently as either "still fine" or "gone."
- **Superseded by session X** -- `superseded_by_session_id` is set; the
  caller should follow the chain to the named session for the current
  answer, while this session's own text remains inspectable on request.
  `narrative_invalidated_at`, if it was ever set on this session, remains
  set even after supersession -- retained history, per "nothing deleted
  or rewritten."

## What this does not do

- **`research_question_id` threading is implemented (2026-08-22) -- see
  "Where `research_question_id` actually comes from" above. The
  repository-layer mechanics are also now implemented (2026-08-22, later
  the same day):** `ResearchSession.answer_version` /
  `.supersedes_session_id` / `.narrative_invalidated_at` exist as additive
  fields with a guarded `ALTER TABLE` migration
  (`sessions/repository.py::_migrate_schema`), and
  `SessionRepository.record_narrative_invalidation()` /
  `.supersede_session()` implement the `narrative_invalidated` /
  `answer_superseded` `ResearchEvent`-plus-field-update operations the
  "Why a whole new session" and "Releaseability reacts to an invalidating
  flip immediately" sections above describe, each with the guards those
  sections require (narrative invalidation set at most once; a session can
  only be superseded from `COMPLETED`). Both are tested in isolation
  (`tests/sessions/test_repository.py`), not live-verified against a real
  research question (there is no live external call in this slice -- it is
  pure SQLite persistence logic, the same category as `attach_research_isa`
  itself).
- **The DOI crosswalk is implemented (2026-08-22, later still) -- see the
  status header above and "the crosswalk" section's own updated point 3.**
  `copilot/research_freshness.py`'s `session_retrieval_dois()`/
  `crosswalk_publication_status_flips()` can now compute, from a real
  `diff_candidate_snapshots()` output plus a real session's own retrieval
  events and persisted narrative, exactly which flips touch that session's
  cited claims (`NarrativeTouchingFlip`). **Still not implemented:
  everything that decides *when* to call the two repository operations
  above in response to one.** No change to `run_research_question.py` or
  `orchestrator/close_gate.py`. The invalidates-versus-qualifies split's
  actual trigger wiring (reading `NarrativeTouchingFlip.flip.flag` and
  calling `record_narrative_invalidation()` for `retracted`/`withdrawn`, or
  recording a qualifying pending flip for `corrected`/
  `expression_of_concern`, without calling it), the `AnswerFreshness`
  read-side projection, and any caller that mints a version-*N+1* session
  (setting `answer_version`/`supersedes_session_id` at `create_session` time
  and then calling `supersede_session()` on the prior version once *N+1*
  reaches `COMPLETED`) remain proposed only, not implemented.
- **No SQLite schema migration for `research_question_id`/`answer_version`/
  `supersedes_session_id`/`narrative_invalidated_at`/`source_dois` was
  needed beyond the guarded `ALTER TABLE` additions already shipped**
  (`_migrate_schema`, one entry per column, `research_events.source_dois`
  included as of 2026-08-22, later still) -- additive columns following the
  existing `duration_ms`/`source_ids` precedent, with no `schema_version`
  bump.
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
- **The `RetrievedPaper.doi` persistence gap named above under "the
  crosswalk" is resolved (2026-08-22, later still): `ResearchEvent.source_dois`,
  the additive field, not a re-run.** See that section's own updated point 3.

## Relationship to AI-FRD-5's exit criteria

This document is the scoping step `docs/project-status.yaml`'s
`next_continuation` named as blocking AI-FRD-5's remaining two exit
criteria (`federated_discovery_orchestration_adoption.md`'s AI-FRD-5
section):

- *"corrections/retractions can invalidate or qualify prior synthesis"* --
  this design's crosswalk (implemented 2026-08-22, later still --
  `crosswalk_publication_status_flips()`) and the repository-layer
  invalidates/qualifies mechanics (`record_narrative_invalidation()`,
  implemented earlier the same day) are both now built and tested in
  isolation. The remaining piece is the trigger that connects them for a
  real session: reading a detected `NarrativeTouchingFlip.flip.flag` and
  calling one or the other.
- *"prior answer text is never silently overwritten as if it had always
  been the updated answer"* -- this design's whole-session versioning,
  append-only retention, and `SUPERSEDED` transition (only after a real
  replacement reaches `COMPLETED`) is the concrete mechanism for that; the
  fields and `supersede_session()` are implemented, but no caller yet mints
  a version-*N+1* session or calls it.

Both exit criteria remain **not started** in code terms -- every mechanism
either depends on now exists and is tested standalone, but nothing in
`run_research_question.py`/`orchestrator/close_gate.py` calls any of it yet.
A follow-up PR implementing only the invalidates-versus-qualifies trigger
(reading a `NarrativeTouchingFlip` and calling `record_narrative_invalidation()`
or recording a qualifying pending flip) is the next small, coherent slice --
not the `AnswerFreshness` projection or the version-minting caller, which
depend on the trigger existing first.
