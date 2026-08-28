# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **BT-7: early stop on adequacy (issue #92).** `complete_discovered_research`
  (GQR-4/GQR-5) now extracts/grounds/promotes already-indexed candidates
  first, before any network acquisition. If that alone promotes at least
  `GroundedCompletionPolicy.min_promoted_records_for_early_stop` (default `3`)
  grounded EvidenceRecords, every configured acquisition route is skipped --
  recorded as an explicit `AcquisitionRouteResult(attempted=False,
  skipped_reason=...)`, never silently omitted -- and the bounded research
  path proceeds straight to a single final re-retrieval. Otherwise acquisition
  runs across every configured route exactly as before, with the newly
  acquired papers extracted in one additional bounded batch merged with the
  already-indexed batch's results. `GroundedCompletionResult` gained
  `acquisition_skipped_for_adequacy`. All new fields default to preserve prior
  behavior when indexed coverage alone is not adequate; no existing field was
  renamed or removed. See `docs/roadmap/bt7_early_stop_on_adequacy.md`.

- **Executable PMC persistence client (issue #69 Stage 4)**: `ke_client.general_question_acquire_pmc()` reaches Core's shipped, approval-gated `ke general-question-acquire-pmc` boundary with explicit papers/Core working directories and strictly parses Paper/ImportRun/ImportItem lineage. Acquisition-plan items now preserve Core's `acquisition_route`. It is not enabled on any existing session path; acquired Papers remain non-evidence until grounded extraction, validation, and re-retrieval.

- **Acquisition-plan orchestration wiring (issue #69 Stage 4, second
  slice).** `copilot/discovery_policy.py`'s `FederatedDiscoveryPolicy`
  gains a new opt-in toggle, `enable_acquisition_plan` (default `False`),
  plus `acquisition_plan_max_candidates`/`acquisition_plan_max_full_text_acquisitions`/
  `acquisition_plan_max_elapsed_seconds`/`acquisition_plan_allow_metadata_only`
  bounds. When turned on, `evaluate_and_run_discovery_augmentation` now
  decides *when* to request a bounded Core acquisition plan and *which*
  candidates to request it for -- the two gaps the prior session's
  `ke_client.general_question_acquisition_plan()` wrapper (below) left
  open: after a triggered federated-discovery run returns its own
  candidates, this module requests a plan for that run's `search_run_id`
  and deduplicated candidate IDs (capped at
  `acquisition_plan_max_candidates`), gated on a `research_question_id`
  also being available (Core's command requires one). Skipped, with an
  explicit inspectable reason and no subprocess call, when disabled by
  policy, when federated discovery did not run or returned no candidates,
  or when no `research_question_id` is available. The outcome is recorded
  as its own durable `ResearchEvent` (`acquisition_plan` workflow node,
  never writing into `source_ids` -- a plan is still not an Evidence
  Record) and surfaced on `DiscoveryAugmentationResult.acquisition_plan`/
  `.acquisition_plan_error`/`.acquisition_plan_attempted`/
  `.acquisition_plan_skipped_reason`, reachable end-to-end from
  `ResearchQuestionResult.discovery`. `enable_acquisition_plan` defaults
  to `False` (unlike `enable_federated_discovery`/`enable_citation_snowball`,
  both `True`) since no caller has yet opted a real session into this
  distinct, newer GQR-track capability -- every existing
  `FederatedDiscoveryPolicy` caller is unaffected until it explicitly
  turns this on. Still only a *plan*: Core's own CORE-GQR-3 (acquisition
  routing) and CORE-GQR-4 (persist and parse) remain not started, so no
  `eligible_full_text` disposition here implies a source was actually
  acquired or promoted to an Evidence Record. 12 new tests in
  `tests/copilot/test_discovery_policy.py` (449 tests total, 437
  pre-existing plus 12 new); full local quality gate (ruff format --check,
  ruff check, mypy, pytest, pip-audit, git diff --check) passed via
  `scripts/preflight.py`. No schema change; `knowledge-engine-web` is
  unaffected (no caller opts into `enable_acquisition_plan` yet). Next
  continuation for this track: no code path acquires the `eligible_full_text`
  candidates this plan names, since Core's CORE-GQR-3/GQR-4 remain future
  work -- once those land, wiring an actual acquisition-invoking caller
  (and deciding when to turn `enable_acquisition_plan` on for a real
  session) becomes the next slice.

- **`ke_client` wrapper for Core's general-question acquisition plan
  (issue #69 Stage 4 / CORE-GQR-1/GQR-2).** `general_question_acquisition_plan()`
  is the first `ke_client` surface for `knowledge-engine-core`'s `ke
  general-question-acquisition-plan` command
  (`docs/general_question_research_loop_v1.md`,
  `docs/core_interface_contract.md`), which already exists on `main` today
  and does not depend on Core's still-unmerged pmid/arxiv_id-at-ingestion
  continuation. Unlike the other commands this module wraps, Core's command
  takes its request as a JSON *file* argument, not flags, so this wrapper
  writes a `GeneralQuestionAcquisitionRequest` to a private temporary file
  alongside the usual `--output` snapshot file, runs the command, parses
  the typed `GeneralQuestionAcquisitionPlanResult` (schema version, budget
  reconciliation counts, and one `GeneralQuestionAcquisitionItem` per
  resolved candidate with its `disposition`, identity, and selected
  observation), and discards both files. `no_database=True` forwards
  Core's `--no-database` flag. Every returned `disposition`
  (`already_indexed`/`eligible_full_text`/`metadata_only`/
  `skipped_budget`/`not_found_in_run`) describes acquisition eligibility
  only -- it never means a source was actually acquired, parsed, or
  promoted to an Evidence Record; Core's own CORE-GQR-3 (acquisition
  routing) and CORE-GQR-4 (persist and parse) remain future work. This is
  deliberately just the subprocess/parse boundary, the same division
  `citation_snowball` and `federated_discover` already established:
  nothing here decides when to request a plan, selects candidate IDs, or
  wires this into `run_research_question`'s own orchestration -- that
  remains issue #69's own next continuation. 12 new tests in
  `tests/test_ke_client.py`; full local quality gate (ruff format --check,
  ruff check, mypy, pytest, pip-audit, git diff --check) passed via
  `scripts/preflight.py` (437 tests total, 425 pre-existing plus 12 new).
  No schema change, no new `ke` surface on Core's side (the command already
  shipped) -- `knowledge-engine-web` is unaffected.

- **Version-minting caller (AI-FRD-5 / answer-session-versioning).**
  `docs/roadmap/answer_session_versioning_design.md`'s own "next small,
  coherent slice" -- a caller that mints a version-*N+1* session and
  supersedes the prior one -- is now implemented.
  `run_research_question` gains two additive keyword parameters,
  `answer_version: int = 1` and `supersedes_session_id: str | None = None`,
  set verbatim on the `ResearchSession` it creates (same opt-in shape
  `research_question_id` already uses, so every existing caller is
  unaffected). `copilot/research_freshness.py` gains `mint_next_version()`:
  given a prior session that is `COMPLETED` and carries a
  `research_question_id`, it calls `run_research_question` a second time
  (the prior's own question text, the same thread,
  `answer_version=prior.answer_version + 1`,
  `supersedes_session_id=prior.session_id`) and, only if that new run's own
  close gate reaches `COMPLETED`, calls
  `SessionRepository.supersede_session()` on the prior version -- a new
  run that ends `BLOCKED` instead leaves the prior version exactly as it
  was (`COMPLETED`, un-superseded), per the design doc's "Interaction with
  session close gates." Raises `SessionNotCompletedError`/
  `MissingResearchQuestionIdError` up front for a prior session that is
  not `COMPLETED` or has no thread identity, rather than running the full
  pipeline first. 7 new tests (2 in
  `tests/copilot/test_run_research_question.py`, 5 in
  `tests/copilot/test_research_freshness.py::TestMintNextVersion`); full
  local quality gate clean via `scripts/preflight.py` (425 tests total).
  No `ResearchSession`/`ResearchEvent` schema change beyond the fields
  already shipped earlier this session, no new `ke` surface --
  `knowledge-engine-web` is unaffected. Still no caller invokes
  `mint_next_version()` for a real session (no CLI command calls it yet),
  and the still-open policy question of who/what decides *when* a version
  transition should be attempted at all remains undecided -- both are the
  design doc's own next continuation.

- **`AnswerFreshness` read-side projection (AI-FRD-5 / answer-session-
  versioning).** `docs/roadmap/answer_session_versioning_design.md`'s
  "What a caller (Web, later) sees when asking 'is this answer still
  fresh'" sketch is now implemented: `copilot/research_freshness.py` gains
  `AnswerFreshness` (`session_id`, `research_question_id`, `answer_version`,
  `status`, `supersedes_session_id`, `superseded_by_session_id`,
  `narrative_invalidated_at`, `rerun_recommended`, `pending_flips`, and a
  `releaseable` property mirroring the design doc's two-field
  `COMPLETED`-and-not-invalidated check) and `build_answer_freshness()`, a
  pure read-side projection over already-fetched data -- the same "caller
  owns the I/O" boundary `observability.build_session_trace` already
  follows. `pending_flips` is typed as `NarrativeTouchingFlip` rather than
  the design sketch's bare `PublicationStatusFlip`, keeping the
  `doi`/`cited_evidence_record_ids` context a caller needs to explain *why*
  a flip is pending. `superseded_by_session_id` is derived, not stored: no
  session row points forward to whatever replaced it, so
  `SessionRepository` gains `list_sessions_for_research_question()` to list
  every session in one `research_question_id` thread, and
  `build_answer_freshness` scans that list for a session naming this one as
  its `supersedes_session_id`. `ke-ai session-freshness` is this
  projection's first real caller: its text and `--format json` output now
  include an "Answer freshness" section (`answer_version`, `status`,
  `releaseable`, `pending_flips` count, and `narrative_invalidated_at`/
  `superseded_by_session_id` when set), built from the session state
  re-read *after* a possible `--apply` write so it reflects the
  post-invalidation state, not the value read before this run started. 10
  new tests (7 in `tests/copilot/test_research_freshness.py`, 2 in
  `tests/sessions/test_repository.py`, 1 in
  `tests/test_cli_session_freshness.py`, plus strengthened assertions in 3
  pre-existing tests in that last file); full local quality gate clean via
  `scripts/preflight.py` (418 tests total). No change to any existing function's signature, no
  `ResearchSession`/`ResearchEvent` schema change, no new `ke` surface --
  `knowledge-engine-web` is unaffected. Still does not mint a
  version-*N+1* session or call `supersede_session()`, and still does not
  decide *when* a freshness check runs automatically -- both remain the
  design doc's own next continuation, along with the still-open
  who/what/how-often policy question.

- **`ke-ai session-freshness` (AI-FRD-5 / answer-session-versioning, first
  real end-to-end caller).** Every mechanism AI-FRD-5's remaining exit
  criteria need -- `assess_rerun_need`, `diff_candidate_snapshots`,
  `session_retrieval_dois`, `crosswalk_publication_status_flips`, and
  `apply_narrative_touching_flips` -- existed and was tested in isolation,
  but nothing in this repository had ever called the full chain against a
  real, durable `ResearchSession`. `cli.py` gains `session-freshness
  SESSION_ID --ledger-root DIR [--session-db PATH] [--apply]
  [--max-age-seconds N] [--format text|json]`: it loads the named session,
  reads its `research_question_id` and its own retrieval/synthesis event
  log, and composes the same chain `ke-ai research-freshness` already
  exercises for a bare `research_question_id`, plus the two newer session-
  aware steps -- `session_retrieval_dois()` over the session's own events,
  then `crosswalk_publication_status_flips()` against the diff's
  `newly_flagged` candidates and the session's persisted narrative -- to
  report exactly which flips, if any, actually touch a claim this session
  cited, split into what would invalidate (`retracted`/`withdrawn`) versus
  qualify (`corrected`/`expression_of_concern`) it. Read-only by default:
  every touching flip is reported but nothing is written to `--session-db`
  unless `--apply` is passed, in which case `apply_narrative_touching_flips`
  persists the first invalidating flip (idempotently -- a second `--apply`
  run against an already-invalidated session reports that plainly and
  writes nothing further) exactly as that function already guarantees.
  Deliberately does not decide *when* a freshness check should run (still
  an open product/policy question per the design doc's own "What this does
  not do") or mint a version-*N+1* session (`supersede_session()` remains
  uncalled) -- this is the on-demand, explicitly-invoked case, the same
  "build the tested primitive, add a standalone CLI caller" precedent
  `ke-ai research-freshness`/`ke-ai discover` already established, not an
  automatic trigger. 10 new tests
  (`tests/test_cli_session_freshness.py`); full local quality gate (ruff
  format/check, mypy, pytest, pip-audit, git diff --check) clean via
  `scripts/preflight.py`. No change to any existing function's signature,
  no new `ke` surface, no `ResearchSession`/`ResearchEvent` schema change --
  `knowledge-engine-web` is unaffected (it pins a specific
  `knowledge-engine-ai` commit and never calls this module directly).
  Next continuation, per the design doc's "Relationship to AI-FRD-5's exit
  criteria": the `AnswerFreshness` read-side projection (now that a real
  caller exists to populate its `pending_flips`/`narrative_invalidated_at`-
  consuming fields meaningfully), and a caller that mints a version-*N+1*
  session and calls `supersede_session()` on the prior version once it
  reaches `COMPLETED` -- plus the still-open policy question of who/what
  invokes `session-freshness` and how often.

- **Invalidates-versus-qualifies trigger (AI-FRD-5 / answer-session-
  versioning, fourth wiring slice).** `copilot/research_freshness.py` gains
  `apply_narrative_touching_flips()` -- the trigger that decides what to do
  with one batch of already-crosswalked `NarrativeTouchingFlip`s, per
  `docs/roadmap/answer_session_versioning_design.md`'s "Invalidates versus
  qualifies" section. A `retracted`/`withdrawn` touching flip calls
  `SessionRepository.record_narrative_invalidation()`, naming the specific
  `canonical_id`/`doi`/flag/cited evidence-record ids in the appended
  event's `notes`; only the first invalidating flip in a batch is ever
  recorded (`narrative_invalidated_at` is set at most once per session by
  design, so the function checks the session's current state first rather
  than relying on the repository's guard to raise). A `corrected`/
  `expression_of_concern` touching flip is returned in the new
  `NarrativeFreshnessTriggerResult.qualifying` tuple and not persisted --
  the `AnswerFreshness` read-side projection that would track a durable
  `pending_flips` list does not exist yet. Never touches `session.status`
  or calls `supersede_session()`, both of which remain a later slice
  (minting a version-*N+1* session). The precheck-then-persist window
  between reading `narrative_invalidated_at` and calling
  `record_narrative_invalidation()` is not one atomic transaction, so a
  concurrent freshness-check call (scheduled or request-driven) can
  invalidate the same session in between; `apply_narrative_touching_flips`
  now also catches `NarrativeAlreadyInvalidatedError` around that call and
  treats it the same as the precheck's already-invalidated case, so the
  function's documented "never raises `NarrativeAlreadyInvalidatedError`"
  guarantee holds regardless of interleaving. 13 new tests (398 total
  pass); full local quality gate (ruff format/check, mypy, pytest,
  pip-audit, git diff --check) clean via `scripts/preflight.py`.
  `knowledge-engine-web` is unaffected: no change to
  `run_research_question`'s signature, no new `ke` surface, and Web pins a
  specific `knowledge-engine-ai` commit.
  Next continuation, per the design doc's own "What this does not do":
  the `AnswerFreshness` read-side projection, and a caller that mints a
  version-*N+1* session and calls this trigger for a real session.

- **DOI crosswalk (AI-FRD-5 / answer-session-versioning, third wiring
  slice).** `copilot/research_freshness.py` gains `session_retrieval_dois()`
  (builds an `evidence_record_id -> doi` mapping from a session's own
  retrieval-step `ResearchEvent`s) and `crosswalk_publication_status_flips()`
  (the join `docs/roadmap/answer_session_versioning_design.md`'s "the
  crosswalk" section scopes: for each `PublicationStatusFlip`, look up its
  candidate's DOI in the current coverage snapshot, match it against the
  session's own retrieval DOIs, and keep only the matches actually cited in
  the session's persisted narrative via `verification.py`'s existing
  `CITATION_PATTERN` -- returns a new `NarrativeTouchingFlip` per real hit).
  Both functions are pure and deterministic, taking already-fetched data;
  neither calls `SessionRepository` or `ke` itself, matching
  `assess_rerun_need`/`diff_candidate_snapshots`'s own shape. Resolves the
  design doc's own named open sub-decision -- re-run `ke evidence-report` at
  check time, or add an additive `doi` field alongside the retrieval event's
  existing `source_ids` -- as the additive field: `ResearchEvent` gains
  `source_dois` (parallel to `source_ids`, same order, same additive/no-
  schema-bump precedent as `duration_ms`), populated by both retrieval-step
  events in `orchestrator/workflow.py`, with a guarded `ALTER TABLE`
  migration for `research_events` in `sessions/repository.py::_migrate_schema`.
  Re-running was rejected: it answers "what would retrieval see today," not
  "what did this session's retrieval step actually see," and a corpus that
  changed since the session ran -- the exact scenario a freshness check
  exists to detect -- can make a re-run return different papers, undermining
  the citation match this crosswalk depends on. 14 new tests (385 total
  pass); full local quality gate (ruff format/check, mypy, pytest, pip-audit,
  git diff --check) clean via `scripts/preflight.py`. The
  invalidates-versus-qualifies trigger that acts on a detected
  `NarrativeTouchingFlip`, the `AnswerFreshness` read-side projection, and a
  caller that mints a version-*N+1* session remain future work -- see
  `docs/roadmap/answer_session_versioning_design.md`'s updated "What this
  does not do" section. `knowledge-engine-web` is unaffected: it pins a
  specific `knowledge-engine-ai` commit; this change adds new functions and
  additive fields/columns only, and changes no existing function's required
  signature.

- **Answer/session-versioning repository mechanics (AI-FRD-5 /
  answer-session-versioning, second wiring slice).** `ResearchSession`
  gains three additive fields: `answer_version` (1-based, monotonic within
  a `research_question_id` thread), `supersedes_session_id` (the
  immediately-prior version's `session_id`, if any), and
  `narrative_invalidated_at` (set at most once, independent of `status`,
  the moment an invalidating publication-status flip is found to touch a
  session's own cited narrative -- see
  `docs/roadmap/answer_session_versioning_design.md`'s "Releaseability
  reacts to an invalidating flip immediately" section). `sessions/repository.py`
  gains two new methods implementing the design's version-transition
  mechanics: `SessionRepository.record_narrative_invalidation()` appends a
  `narrative_invalidated` `ResearchEvent` and sets the field (raises
  `NarrativeAlreadyInvalidatedError` if called twice on the same session);
  `SessionRepository.supersede_session()` appends an `answer_superseded`
  `ResearchEvent` and moves the session's status to `SessionStatus.SUPERSEDED`
  (raises the new `SessionNotSupersedableError` unless the session is
  currently `COMPLETED`). Both are additive, purely local SQLite changes
  (guarded `ALTER TABLE` migration for pre-existing databases, no
  `schema_version` bump, old rows load the three new columns as `1`/`None`/
  `None`) with no effect on any existing caller: nothing in this repository
  calls either new method yet. 13 new tests (371 total pass); full local
  quality gate (ruff format/check, mypy, pytest, pip-audit, git diff
  --check) clean via `scripts/preflight.py`. The DOI crosswalk that would
  decide *when* to call these (matching a flagged federated-discovery
  candidate to a session's own cited evidence records) and a caller that
  mints a version-*N+1* session remain future work -- see
  `docs/roadmap/answer_session_versioning_design.md`'s updated "What this
  does not do" section. `knowledge-engine-web` is unaffected: it pins a
  specific `knowledge-engine-ai` commit and only uses the pre-existing
  `SessionRepository`/`run_research_question` call shapes, both unchanged.

- **`research_question_id` threading (AI-FRD-5 / answer-session-versioning,
  first wiring slice).** `run_research_question` now accepts an optional
  `research_question_id` keyword parameter and always sets it on the
  `ResearchSession` it creates: a caller-supplied value used verbatim, or
  (the common case today) one derived deterministically from the
  normalized question text (`rq-<sha256[:16]>`), so separate calls that are
  really "the same question, asked again" thread together without a
  caller coordinating an ID. The value threads down the existing call
  chain -- `evaluate_and_run_discovery_augmentation` ->
  `_run_federated_discovery` -> `execute_discovery_plan` -> the
  already-existing `ke_client.federated_discover(research_question_id=...)`
  call -- only when `discovery_policy` is also supplied; deliberately not
  threaded into citation-snowball (no `research_question_id` parameter
  exists there). `ResearchSession` gains one additive field
  (`schema_version` unchanged; existing rows load it as `None`). No new
  `ke_client.py` wrapper function was added -- the underlying
  `federated_discover`/Core `--research-question-id` flag were already
  built and live-verified in an earlier session -- so this closes only the
  concrete plumbing gap `docs/roadmap/answer_session_versioning_design.md`'s
  "Where `research_question_id` actually comes from" section named, adding
  no versioning/supersession behavior itself. 8 new tests (358 total pass);
  full local quality gate (ruff format/check, mypy, pytest, pip-audit,
  git diff --check) clean. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s matching
  2026-08-22 entry.

- **`docs/roadmap/answer_session_versioning_design.md`: scopes the
  answer/session-versioning concept AI-FRD-5's remaining wiring needs.**
  Docs-only -- no change to `run_research_question.py`, `sessions/models.py`,
  `sessions/repository.py`, `orchestrator/close_gate.py`, or
  `copilot/research_freshness.py`. Defines: a version as one whole
  `ResearchSession` (never a second synthesis event folded into an existing
  session), chained by three new additive `ResearchSession` fields
  (`research_question_id`, `answer_version`, `supersedes_session_id`); how
  `assess_rerun_need()`/`diff_candidate_snapshots()` map onto a version
  transition via a DOI crosswalk from a flagged federated-discovery
  candidate to the `evidence_record_id`s a prior narrative actually cited;
  an invalidates (`retracted`/`withdrawn`) versus qualifies (`corrected`/
  `expression_of_concern`) split; and why `SessionStatus.SUPERSEDED`
  (already defined in the enum, unused anywhere in code before this
  design) is the right terminal state for a superseded version, set only
  once its replacement itself reaches `COMPLETED`. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s matching
  2026-08-22 entry. AI-FRD-5's own remaining two exit criteria stay **not
  started** -- this is the scoping step they needed, not the
  implementation.

- **AI-FRD-2 (coverage-aware Research ISA): first bounded slice.**
  `run_research_question` now attaches a fourth, *optional*
  (`required=False`) `discovery_coverage` Ideal State criterion whenever a
  caller supplies `discovery_policy` -- it is omitted from the ISA entirely
  when no `discovery_policy` is supplied, leaving the pre-existing
  three-criteria path unchanged byte for byte. The criterion is evaluated
  from the same `DiscoveryAugmentationResult` AI-FRD-3/AI-FRD-4's wiring
  already produces: `NOT_APPLICABLE` when federated discovery was not
  triggered this run (coverage already sufficient, or primary retrieval
  already failed and is blocked by `workflow_integrity`); `FAILED` --
  naming the specific unsuccessful provider(s) and Core's own recorded
  reason -- whenever a triggered run's Core-derived `completeness` is not
  `"complete"`; `PASSED` otherwise. Core's own `completeness` (already
  computed only from *attempted* providers, excluding disabled/skipped
  ones) is the single source of truth here -- AI never re-derives provider
  success/failure. Being optional means a degraded federated-discovery
  broadening never silently blocks session close (synthesis may still
  proceed in degraded mode, per this milestone's own exit criteria), but
  the limitation is always explicit and inspectable on the session's ISA
  validation, never hidden behind an unverified "searched broadly" claim.
  See `docs/roadmap/federated_discovery_orchestration_adoption.md`'s
  AI-FRD-2 section for the full account.

  Fix (same slice, pre-review): a coverage gap triggered while
  `enable_federated_discovery=False` was misreported as `FAILED` (naming a
  provider that was never attempted) because the criterion could not tell
  "disabled by policy" apart from "attempted and failed". A new
  `federated_discovery_attempted` field on `DiscoveryAugmentationResult`
  distinguishes the two, so this case now correctly reports
  `NOT_APPLICABLE`.

- **AI-FRD-5 (research freshness / rerun reasoning): a first bounded slice,
  deterministic and unwired.** `copilot/research_freshness.py` adds two pure
  functions over data `ke_client.federated_discover_history()` and
  `ke_client.federated_coverage_report()` already return:
  `assess_rerun_need()` recommends whether a fresh `federated_discover()`
  call is warranted for a tracked `research_question_id` (no run ever
  recorded, or the most recent run did not complete, or it is older than a
  configurable -- default 7-day -- freshness threshold), and
  `diff_candidate_snapshots()` compares two specific past runs' full
  candidate snapshots to report newly discovered candidates and candidates
  whose retraction/correction/expression-of-concern/withdrawal flag newly
  flipped to asserted-`True`. Both are deterministic rules -- never an LLM
  judgment call -- and neither merges, votes on, or picks an authoritative
  provider value across observations, the same discipline
  `discovery_policy.py` already established for AI-FRD-3/AI-FRD-4. New
  `ke-ai research-freshness <research_question_id>` command is this
  module's first caller: it fetches this tracked question's full run
  history, prints the rerun recommendation, and -- once at least two runs
  are recorded -- diffs the two most recent runs' candidate snapshots.
  Live-verified against the real `ke` binary: a ledger was seeded directly
  via Core's own `FederatedSearchLedger.record()` with two runs for one
  tracked question (an older run with one clear candidate, a newer run with
  that same candidate now retracted plus one brand-new candidate), and
  `ke-ai research-freshness` correctly reported both the newly discovered
  candidate and the newly flagged retraction through the real subprocess
  boundary, in both `--format text` and `--format json`. Deliberately *not*
  wired into `run_research_question` or a Research Session -- deciding that
  a correction or retraction invalidates a prior narrative, and versioning
  prior answer text accordingly, remains open work; see AI-FRD-5's own exit
  criteria in
  `docs/roadmap/federated_discovery_orchestration_adoption.md`.

- **Core's `corrected`/`expression_of_concern`/`withdrawn` provider
  observation flags are now parsed at the `ke_client` boundary.**
  `knowledge-engine-core`'s `ProviderObservation` gained these three flags
  alongside the existing `retracted`, and Core PR #396 ("Wire Crossref
  update-to relation into ProviderObservation publication-status flags",
  `4866ebd`) made Crossref's `update-to` relation a real source of data for
  them rather than present-but-always-`None` schema fields. Both
  `FederatedProviderObservationFlags` (the at-request-time subset shared by
  `parse_federated_discovery_result` and `parse_citation_snowball_result`)
  and `FederatedCandidateObservation` (the richer persisted shape that
  documents itself as mirroring Core's `CandidateObservationRecord.to_dict()`
  field for field, and had drifted from it) carry the three new fields. Each
  defaults to `None`, so an older Core payload -- or a provider that never
  reports the flag -- parses to explicit unknown rather than a guessed
  `False`, the same "absent is not negative" contract already applied to
  `retracted`. The four flags are independent, not one status enum: a work
  may carry more than one at once, and a provider asserting one says nothing
  about the others. `ke-ai discover` and `ke-ai citation-snowball` surface
  each flag in their per-provider note line only when a provider actually
  asserted it `True`. Purely additive -- no existing caller's behavior
  changes, and nothing here merges, votes on, or picks an authoritative
  value across providers, nor decides what a publication-status flag means
  for evidence quality.

- **`ke_client.federated_coverage_report()` added -- the point-lookup wrapper
  previously deferred pending a Core `--output` option.** Core's FRD-6
  candidate-snapshot follow-up (`96d30ac`, "Persist federated-discover
  candidate snapshots; add coverage-report --output") added `--output` to
  `ke federated-coverage-report` and started persisting each run's full
  deduplicated candidate list (canonical ID, title, DOI, publication year,
  every provider's full observation) on `SearchRunRecord.candidates`. This
  wrapper shells out to `ke federated-coverage-report <search_run_id>
  --ledger-root <dir> --output <tmp>` and parses the result into a typed
  `FederatedCoverageReportResult` (`coverage: SearchCoverageReport`,
  `candidates: tuple[FederatedCandidateRecord, ...]`), mirroring the
  existing `federated_discover()`/`federated_discover_history()` shape.
  `FederatedCandidateRecord`/`FederatedCandidateObservation` are a richer,
  distinct shape from `federated_discover()`'s existing
  `FederatedCandidateSummary`/`FederatedProviderObservationFlags` (those
  only carry the at-request-time provider set and retraction/preprint
  flags); this wrapper exposes every field Core persisted for a specific
  past run's candidate observations. A run recorded before Core's
  candidate-snapshot follow-up existed parses to an honest empty
  `candidates` tuple, never a fabricated one. Purely additive
  client-boundary work: no policy here decides what changed between runs
  or renders anything. Live-verified against the real `ke` binary.

- **`ke_client.federated_discover_history()` added; `federated_discover()`
  now forwards `project_id`/`research_question_id`.** Closes the two
  `knowledge-engine-ai` blockers named by `knowledge-engine-web`'s WEB-FRD-5
  design doc (`web_frd5_freshness_history_design.md` section 5, items 3-4),
  now that Core's FRD-6 follow-up (`ke federated-discover
  --research-question-id`/`--project-id`, `ke federated-discover-history
  <id>`) has merged. `federated_discover_history()` shells out to Core's new
  history command and parses its `--output` JSON into a typed
  `FederatedDiscoverHistoryResult` (a tuple of `SearchCoverageReport`, one
  per persisted run for the tracked question, newest first); a
  `research_question_id` with no prior recorded search returns an empty,
  non-error result. `federated_discover()`'s two new optional keyword
  parameters default to `None` and are omitted from the command line when
  unset, so every existing caller is unaffected. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s matching
  entry for why a `ke federated-coverage-report` point-lookup wrapper was
  not added in this change.

- **AI-FRD-3/AI-FRD-4 wired into `run_research_question`'s own planning
  (`copilot/discovery_policy.py`), closing this milestone's long-standing
  "known gap."** Jeremy's explicit product-owner decision: "continue with
  the FRD and widen the search." A new opt-in `FederatedDiscoveryPolicy`
  (`run_research_question`'s new `discovery_policy` parameter, default
  `None`, reproducing prior behavior exactly) defines two deterministic
  trigger rules, never an LLM judgment call: federated discovery
  (AI-FRD-3's `discovery_plan.py` compiler) fires when primary corpus
  retrieval succeeded but deduplicated evidence-record coverage falls
  below a configurable threshold (conservative default `3`); citation
  snowball (AI-FRD-4) fires under the same signal, seeded deterministically
  from the corpus's own already-relevant papers' DOIs (conservative default
  cap of 3 seeds). Every other numeric bound (provider limit, snowball
  depth/candidates, per-call execution-second ceilings tighter than
  `discovery_plan.py`'s own person-invoked 600s ceiling) is a documented,
  overridable `FederatedDiscoveryPolicy` field -- see the introducing PR's
  description for the full reasoning trail on each default. Every
  discovery/snowball attempt is recorded as its own durable `ResearchEvent`
  (Core's own `search_run_id`/`snowball_run_id`, completeness, candidate
  count), surfaced on the new `ResearchQuestionResult.discovery` field and
  the session trace, but candidates are never written to `source_ids`,
  never fed to `synthesize_answer`, and never treated as `EvidenceRecord`s
  -- provider/candidate count is never treated as evidence quality, and the
  narrative still cites only grounded, corpus-sourced evidence. New CLI
  surface: `research --broaden-search-on-gap --discovery-ledger-root
  <dir>` (also opt-in, off by default), plus a `discovery` field on
  `research --format json`'s payload. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s matching
  entry for the full trigger/budget/provenance policy.

- **`ke-ai citation-snowball` -- the first CLI caller of
  `ke_client.citation_snowball()` (AI-FRD-4).**
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s AI-FRD-4
  named this repository's next continuation explicitly: the
  `citation_snowball()` client wrapper (below) existed and was
  unit-tested, but had no in-repository caller -- the same
  "built but unreachable" gap `ke-ai discover` closed for
  `federated_discover()`. This command is that caller: `--seeds`,
  `--ledger-root`, `--provider` (`semantic_scholar` default or
  `openalex`), `--directions`, `--max-depth`,
  `--limit-per-traversal`, `--max-candidates`, and the existing
  `--openalex-api-key`/`--semantic-scholar-api-key` options pass straight
  through to Core's `ke citation-snowball`, mirroring `discover`'s own
  option shape and text/JSON output styling (coverage color, per-provider
  `retracted`/`preprint` flags, a "not Evidence Records" disclaimer).
  Deliberately *not* wired into `run_research_question`'s own planning --
  deciding *when* a Research Session should run a snowball and from which
  seeds remains open policy work, unchanged by this command.

- **`FederatedDiscoveryResult.search_run_created_at` -- parses Core's
  `coverage.created_at` (closes half of `knowledge-engine-web`'s WEB-FRD-2
  gap).** `knowledge-engine-web`'s
  `docs/federated_discovery_transparency_roadmap.md` (WEB-FRD-2) recorded
  that `/discover`'s "Run timestamp" row could not be rendered because this
  repository's `parse_federated_discovery_result()` never parsed the
  `coverage` block at all, even though `knowledge-engine-core`'s
  `docs/core_interface_contract.md` already documents `coverage.created_at`
  as part of `ke federated-discover --output`'s public shape (built by
  `federated_result_snapshot.build_public_federated_result_payload`, which
  always attaches Core's own `SearchCoverageReport.to_dict()`). Adds
  `FederatedDiscoveryResult.search_run_created_at: str | None`, parsed from
  `payload["coverage"]["created_at"]`. A payload that predates, or omits,
  the `coverage` block parses this to explicit `None` rather than raising --
  the same "absent is not negative" contract already used for
  `provider_disagreements` and per-provider observation flags. Purely
  additive: every existing field is unchanged, so `knowledge-engine-web`'s
  current pinned revision keeps working without modification. `ke-ai
  discover`'s text output now also prints a "Search run started" line when
  the field is present. Closing WEB-FRD-2 fully still needs a
  `knowledge-engine-web` PR to bump its pinned `knowledge-engine-ai` revision
  and render the new field -- out of this run's own scope (Web changes were
  not made here), the same two-step pattern this project already used for
  WEB-FRD-3 and WEB-FRD-4 (an AI PR merges first, then a follow-up Web PR
  consumes it).

- **`ke_client.citation_snowball()` -- the first client wrapper for Core's
  FRD-7 `ke citation-snowball` command (AI-FRD-4's named prerequisite).**
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s AI-FRD-4
  ("Citation-snowball planner") had no `ke_client` wrapper for Core's
  `ke citation-snowball` command at all -- it was built and reachable from
  Core's own CLI (`knowledge-engine-core` PR #391) but unreachable from this
  repository, the same "built but unreachable" gap this project has
  repeatedly found and fixed for other Core capabilities (most recently
  `federated_discover`'s own `ke-ai discover` command). `citation_snowball()`
  mirrors `federated_discover()`'s shape exactly: seeds, provider,
  directions, depth, and per-traversal/candidate bounds pass straight
  through as explicit CLI arguments; structured output is written to a
  private `--output` temp file (Core's `citation-snowball` has no
  `--format json`) and parsed into a typed `CitationSnowballResult`
  (`snowball_run_id`, `provider`, plan fields, `completeness`, `truncated`,
  `candidates`, `edges`). Candidate observations reuse the existing
  `FederatedProviderObservationFlags` parsing discipline -- a provider
  observation that omits `retracted`/`preprint`/`preprint_version` parses to
  explicit `None`, never a guessed `False`. Deliberately scoped to just the
  subprocess/parse boundary: nothing here decides *when* a Research Session
  should run a citation snowball, selects seeds, or wires this into
  `run_research_question`'s own planning -- that policy remains AI-FRD-4's
  own next continuation, the same way AI-FRD-3's compiler exists today
  without being called from planning yet.

- **Per-provider `retracted`/`preprint` observations surfaced through
  `FederatedCandidateSummary` (unblocks `knowledge-engine-web` WEB-FRD-4).**
  `knowledge-engine-web`'s `docs/federated_discovery_transparency_roadmap.md`
  (WEB-FRD-2/WEB-FRD-4, PR #64) recorded that `/discover` could not surface
  per-provider `retracted`/`preprint` observations to visitors, because this
  repository's `FederatedCandidateSummary` -- the only typed value Web's
  route receives from `knowledge-engine-ai` -- discarded everything from
  Core's `ProviderObservation` except the provider name. Core's
  `ke federated-discover --output` JSON already carries `retracted`,
  `preprint`, and `preprint_version` per provider observation (confirmed by
  reading `knowledge-engine-core/knowledge_engine/federated_discovery.py`'s
  `ProviderObservation` and live-verifying real `ke federated-discover`
  output: arXiv observations report `preprint=true` with a real
  `preprint_version`, OpenAlex observations report `retracted` from
  `is_retracted`).
  Adds `FederatedProviderObservationFlags` (provider, `retracted`,
  `preprint`, `preprint_version`) and a new
  `FederatedCandidateSummary.observation_flags` field -- one entry per
  provider observation, unmerged and unvoted-on across providers, matching
  the existing `FederatedProviderAssertion`/disagreement-report pattern. A
  provider observation that omits these fields (an older Core run, or a
  provider -- PubMed, Crossref, Semantic Scholar today -- that does not yet
  report them) parses to explicit `None` per field, never a guessed `False`,
  and never raises. Purely additive: no existing field, CLI flag, or JSON key
  changed; `providers` (the pre-existing provider-name-only field) is
  untouched, so existing consumers (Web, `ke-ai discover --format json`)
  remain byte-for-byte compatible. `ke-ai discover`'s text output now also
  prints a `retracted`/`preprint vN` line per provider observation when
  present. This closes the AI-repo side of WEB-FRD-4; a future
  `knowledge-engine-web` PR still has to add the route/UI change that reads
  `observation_flags`, which this run does not implement (per this run's
  own scope -- Web is out of bounds here).

- **`discovery_plan.py` -- Discovery-plan compiler (AI-FRD-3, opening slice).**
  Adds `DiscoveryPlan` (a typed, validated, bounded request against Core's
  discovery capability), `compile_discovery_plan()`, and
  `execute_discovery_plan()`. A plan naming an unknown provider, an
  out-of-range `limit_per_provider`, invalid year bounds, or a missing/invalid
  execution budget fails to construct at all -- fail-closed before any
  subprocess or network call, never a request Core has to reject. Execution
  always builds its `ExecutionBudget` from the plan's own
  `max_execution_seconds`, and returns Core's own `search_run_id`, so a
  compiled plan's run remains independently replayable through Core's ledger.
  This is a foundational slice of AI-FRD-3, not full Research Copilot
  wiring -- deciding *when* `run_research_question` should compile and
  execute a plan (rather than searching only the local corpus) remains
  future work, same as `ke-ai discover`'s own docstring already noted. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`'s AI-FRD-3
  exit criteria.

- **`ke-ai discover` CLI command.** The first caller of `ke_client.federated_discover()`
  inside this repository (previously called only from `knowledge-engine-web`'s
  `/discover` route) -- the "built but unreachable" gap
  `docs/project-status.yaml`'s `next_continuation` and this file's own prior
  entry named explicitly. Prints Core's recorded per-provider outcome
  (never inferred from result count) and, when Core's snapshot includes it,
  a per-run provider-metadata-disagreement summary, explicitly labeled a
  metadata-quality fact and never reinterpreted as scientific contradiction.
  Supports `--format json` for a programmatic caller, matching `ask`/`research`'s
  existing convention. Deliberately not wired into `run_research_question`'s
  own planning -- deciding *when* broader provider coverage is needed is
  AI-FRD-3's (Discovery-plan compiler) job, not this command's. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`.

- **Federated discovery client wiring.** Added `ke_client.federated_discover()`,
  the AI-side boundary function for Core's `ke federated-discover` command
  (Core FRD-1/FRD-2/FRD-3: PubMed, Crossref, OpenAlex, and Semantic Scholar
  providers behind one recorded, deduplicated search run). It follows the
  same subprocess-safety pattern as `evidence_report()`/`evidence_map_report()`
  (no shell, structured output via `--output`, sanitized errors as
  `KeCommandError`), returning a narrower `FederatedDiscoveryResult` --
  `search_run_id`, `completeness`, per-provider `FederatedProviderStatus`, and
  `FederatedCandidateSummary` -- than Core's full ledger contract, sized to
  `knowledge-engine-web`'s first display need per
  `docs/federated_discovery_transparency_roadmap.md` (WEB-FRD-1) in that repo.
  Live-verified against the real `ke` binary and a real PubMed/Crossref search
  (a genuine `unsupported_query` Crossref outcome surfaced correctly as a
  degraded, not failed, run) before this was committed. This function has no
  caller yet in this repository; wiring it into `run_research_question` or a
  new CLI path is separate follow-up work.

- **AI-O17 measured local end-to-end verification.** Ran one real GLP-1
  question through Web, both Core retrieval branches, local Ollama synthesis,
  deterministic verification, the Research ISA close gate, durable Research
  Session storage, and rendered citations. The rehearsal found and fixed three
  fail-closed contract defects: qualifier metadata was absent from the prompt,
  blocked drafts remained displayable, and failed deterministic workflows could
  close vacuously. `ResearchQuestionResult.narrative_releaseable` now provides
  an explicit consumer boundary, Evidence Intelligence numbers supplied by the
  prompt are recognized by numeric grounding, and every session has a required
  workflow-integrity criterion. Hosted Research Copilot remains disabled until
  its operator prerequisites are actually provisioned.

- **AI-O16 execution-budget foundation.** Added an optional shared monotonic
  deadline to `run_research_question`. Core `ke` subprocesses and Ollama
  generation now consume the same remaining wall-clock budget, timed-out
  subprocesses are terminated and reported without leaking arguments or paths,
  and callers that omit a budget retain existing behavior. This is the AI-side
  prerequisite for Web's bounded public-endpoint, concurrency, and rate-limit
  controls; it does not enable public Research Copilot by itself.

- **Cross-repository AI-O13 through AI-O15 status alignment.** Updated the web
  integration design after `knowledge-engine-web` PRs #41, #49, and #50: the AI
  package dependency is wired through real web settings, `/ask` capability-gates
  the composed Research Copilot while preserving deterministic retrieval, and
  hosted Research Sessions require a canonically contained persistent mount.
  The Render alpha remains retrieval-only until an operator provisions and
  verifies that mount and the remaining hosted-runtime controls. Durable SQLite
  reopen behavior is recorded separately from a future user-facing resume
  workflow. No AI runtime behavior changes in this repository.

- **Launch-gate dependency security.** Upgraded Typer to the current release
  line and removed the obsolete direct Click compatibility pin that held the
  environment on a vulnerable Click release. CI now audits the resolved Python
  environment with `pip-audit`, and Dependabot monitors Python and GitHub
  Actions dependencies weekly.

- **Correction to the AI-O12-O17 architecture decision's reasoning.**
  The original decision text (this file's "Web Integration plan"
  entry below) claimed `knowledge-engine-web` "already imports
  `knowledge-engine-core` directly as a Python package," making
  `knowledge-engine-ai` "cost almost nothing" to add alongside it.
  Verified false while starting AI-O13: `web`'s `pyproject.toml` has
  no `core` dependency, and `web`'s own `docs/web_design.md` explains
  why -- it deliberately reads `core`'s SQLite database via reflection
  specifically to avoid that dependency weight. `web` has zero ML
  dependencies today. The real cost of adding `ai`: `ai`'s retrieval
  shells out to the `ke` CLI, so `run_research_question` only actually
  works in `web` (not just imports) once `core`'s full dependency
  stack -- torch included -- is available too, and `web`'s deployed
  data snapshot has no `sources.csv` (`ke evidence-report` needs one).
  The decision (library integration over a standalone service) still
  stands -- it just no longer stands on a "this is nearly free" claim
  that was never true. See `docs/web_integration_design.md`'s
  Architecture decision section for the corrected reasoning, and its
  AI-O13 section for what this changes about that step's own scope.
  The historical entry below is left as written -- this is a new entry
  documenting the correction, not a silent edit of the record.

- **AI-O12: compose the orchestrator into one callable pipeline.** The
  actual missing piece `docs/web_integration_design.md` identified --
  `knowledge_engine_ai/copilot/run_research_question.py`'s
  `run_research_question` is this repo's first caller that composes
  `SessionRepository.create_session` -> `run_fixed_evidence_workflow`
  (AI-O3/AI-O5) -> `synthesize_answer` (opt-in local LLM) ->
  `verify_synthesis` (AI-O6 Skeptic check) -> `build_session_report`
  (AI-O7) -> `attempt_session_close` (AI-O2's ISA close gate) ->
  `build_session_trace` (AI-O9) into one call, end to end. A
  `ResearchISA` with two fixed criteria (citation integrity, no
  qualifying/contradicting evidence silently omitted) is attached to
  every session this creates; both criteria pass vacuously when no
  narrative was produced (no evidence to narrate, or the local LLM call
  itself failed) rather than requiring a dynamic `required` flag the
  write-once ISA contract does not allow. A synthesis-step failure is
  still durable and visible (its own failed `ResearchEvent`, surfaced on
  `ResearchQuestionResult.synthesis_error`) without blocking session
  close -- the close gate is scoped to narrative correctness, not
  synthesis availability. New `ke-ai research` CLI command exercises the
  composed pipeline (`--session-db` for the durable SQLite session
  store, `--llm-model`/`--ollama-host` matching `ask --synthesize`'s
  existing flags), so this repo's own CLI dogfoods the orchestrator
  before `knowledge-engine-web` ever calls it (AI-O14). Live-verified
  against the real GLP-1 corpus with real Ollama models, three real runs
  read in full (not just checked for a non-error exit code), each a
  genuinely different outcome: a `qwen2.5:1.5b` run produced a real
  synthesized narrative that the Skeptic check correctly flagged for
  missing bracket citations -- a real catch, not a contrived test
  fixture -- blocking that session's close exactly as designed; a
  `qwen3:4b` run against a narrower slice of the corpus (no evidence
  record with a stated claim in the top matches) completed cleanly with
  no narrative to verify, the vacuous-pass path exercised for real; and
  a first `qwen3:4b` attempt at the wider slice **found a real,
  pre-existing bug this live run is what surfaced**: `llm.py`'s
  `UrllibOllamaTransport.post` only wrapped connect-phase failures into
  `LocalLLMError` via `except URLError` -- a slow generation (Qwen3's
  "thinking" mode) can time out reading the response body itself, which
  `urlopen` raises as a bare `TimeoutError`, not a `URLError`, so it
  escaped unwrapped and crashed the whole command instead of being
  reported as an ordinary synthesis failure. Fixed with a dedicated
  `except TimeoutError` catch and a regression test
  (`test_urllib_transport_wraps_a_slow_response_timeout_as_local_llm_error`);
  this was a pre-existing gap in `ask --synthesize` too, not something
  AI-O12 introduced, just the first live run patient enough (a slower,
  reasoning model over more evidence) to hit it.

- **`docs/web_integration_design.md`: the Web Integration plan (AI-O12-O17),
  doc-only.** Audited the actual current state rather than assuming it from
  milestone names: AI-O1-O9's orchestrator (`run_fixed_evidence_workflow`,
  `verify_synthesis`, `build_session_report`, `attempt_session_close`,
  `build_session_trace`) is fully built and tested, but grepping the whole
  repo for callers outside `tests/` finds none -- not even this repo's own
  `ke-ai ask` CLI command uses it, and `knowledge-engine-web`'s live `/ask`
  page doesn't import `knowledge-engine-ai` at all (it reimplements a
  simpler version directly against `core`). Three layers, none connected.
  Recorded the architecture decision (library integration into
  `knowledge-engine-web`, not a standalone orchestration service, for this
  phase -- the reasoning: `ai` has no web-framework dependency today, `web`
  already imports `core` directly as a package so the "shell out to `ke`,
  never import `core`" weight-avoidance concern `ke_client.py` was built
  around doesn't apply the same way to `ai` itself becoming a `web`
  dependency; a standalone service is deferred to AI-O18+, not rejected, for
  when a second consumer or real multi-tenant load justifies it) and the
  full step-wise breakdown, each step with its own definition of done:
  AI-O12 (compose the orchestrator into one callable pipeline -- the actual
  missing piece everything else depends on), AI-O13 (add `knowledge-engine-ai`
  as a `knowledge-engine-web` dependency), AI-O14 (route `/ask` through it),
  AI-O15 (session-persistence decision for the deployed environment), AI-O16
  (guardrails for a real, publicly-reachable, LLM-cost-bearing endpoint),
  AI-O17 (live end-to-end verification, then close
  `long_term_vision.md`'s "finished product" claim in `knowledge-engine-core`
  for real). Also engages honestly with two things a first pass missed:
  `knowledge-engine-web/docs/web_design.md`'s existing "Decision: local
  LLM" section already rejected a `knowledge-engine-ai` dependency once,
  for a much smaller case (~150 lines of Ollama-client duplication) --
  that reasoning stands for that decision but doesn't apply the same way
  to reusing the entire orchestrator, and AI-O13 should update that
  section rather than leave two contradictory rationales on record; and
  the deployed Render alpha has **no LLM inference in production at all
  today** (`web_design.md`: "deliberately presents retrieval-only Ask
  until it gets a separately hosted, secured, and operationally durable
  inference architecture -- not attempted here") -- AI-O12-O14 are fully
  buildable and live-verifiable in local/dev now, but AI-O17's
  public-alpha half is blocked on that unresolved hosting question,
  named explicitly rather than silently assumed away by AI-O15/AI-O16's
  guardrail work. See `docs/roadmap/future_ai_orchestration_plan.md`'s
  new "Web Integration" section for the pointer. Nothing implemented
  yet -- this is the plan, not the work.

- **AI-O9: Observability + Budgeting.** Closed two real gaps in AI-O2's
  `ResearchEvent` schema and added a read-side reporting layer over it,
  rather than a new persistence mechanism. `ResearchEvent` gains an
  additive `duration_ms: int | None` field (no schema-version bump);
  `orchestrator/workflow.py`'s `_record_step` now times every fixed
  step and populates `duration_ms`, and populates the already-existing
  but previously-never-written `source_ids` field with each retrieval
  step's retrieved evidence-record IDs. New
  `knowledge_engine_ai/orchestrator/observability.py`:
  `build_session_trace(session, events)` projects a session's event log
  into a `SessionTrace` (deduplicated `evidence_record_ids` in
  first-appearance order, `total_duration_ms` summing only events with
  a known duration, `failed_events`); `render_session_trace` renders it
  as plain text with one section per success-criterion question. "Why"
  is answered at the session level (`session.user_question_original`),
  not a per-step field -- this project has no per-step reasoning data
  today, since `run_fixed_evidence_workflow`'s step sequence is fixed by
  its own code (AI-O3), not chosen by a model that could explain a
  choice. Resource/cost budgeting beyond wall-clock duration is
  explicitly out of scope for this slice -- nothing in this project
  tracks a cost unit today (Ollama is local and free per-call, no cloud
  provider is wired in). 12 new tests (`tests/test_observability.py`
  plus new duration/source_ids assertions in
  `tests/test_orchestrator_workflow.py`). Live-verified end to end
  against the real GLP-1 corpus with `core`'s actual `ke` executable,
  all four fixed steps: all six trace sections rendered with real data
  -- 4 real evidence-record IDs surfaced via `source_ids` for the first
  time, `total_duration_ms=120,058` (58,166ms for the combined
  parallel-retrieval call, itself a genuine and worth-keeping
  observation rather than tuned away), `all_succeeded=True`. See
  `docs/ai_o9_design.md`.

- **AI-O8: Model Router.** New `knowledge_engine_ai/model_benchmark.py`:
  `run_model_benchmark` runs a set of role-tagged `BenchmarkTask` probes
  against each candidate model, reusing this project's own existing
  deterministic graders rather than inventing a new scoring method --
  the planning probe wraps AI-O4's `plan_from_question` + AI-O1's
  `validate_research_plan`, the synthesis probe wraps `synthesize_answer`
  + AI-O6's `verify_synthesis` (passing only when neither
  `hallucinated_citations` nor `ungrounded_numbers` fired).
  `recommend_models_by_role` picks the smallest candidate
  (`approx_parameter_count_billions`, caller-supplied) that passed every
  task for a `ModelRole`, meeting the roadmap's literal success
  criterion ("use the smallest model meeting task-quality thresholds");
  a role with zero qualifying candidates is omitted, not an error.
  `provider_specs_from_benchmark` closes the loop into the
  provider-role-routing work merged just ahead of this milestone
  (`routing.py`'s `ProviderSpec`/`select_provider`): a benchmark
  recommendation becomes better-informed input to that one routing
  mechanism instead of a second one, `max_privacy` never exceeding
  `SENSITIVE`. 9 new tests in `tests/test_model_benchmark.py`.
  Live-verified against both models actually pulled in this environment
  (`qwen2.5:1.5b`, `qwen3:4b`) with a real running Ollama server, a real
  planning question, and the same real GLP-1 `EvidenceReport` AI-O6/AI-O7
  live-verified against: `qwen2.5:1.5b` passed both the planning and
  synthesis/citation-compliance probes; `qwen3:4b` failed both (planning
  timed out even at a 300s per-call budget; synthesis returned an empty
  response because its "thinking" tokens consumed the entire response
  budget, reproducing AI-O4's prior anecdotal finding as an automated,
  repeatable benchmark result). A real timeout-tuning artifact was found
  and corrected during verification -- `OllamaLLM`'s 120s default timeout
  made even `qwen2.5:1.5b`'s planning probe appear to fail on a cold
  model load, when an isolated retry with a longer timeout completed in
  36.2 seconds; re-run with `timeout_seconds=300.0` for an honest read.
  See `docs/ai_o8_design.md`.

- **AI-O7: Research Session Synthesis.** New
  `knowledge_engine_ai/orchestrator/session_report.py`:
  `build_session_report(narrative, report, verification)` resolves each
  `[evidence_record_id]` citation a `synthesis.py` narrative actually
  makes into a `SourcedClaim` carrying the containing `RetrievedPaper`'s
  real title, authors, year, DOI, citation string, and source URL -- the
  join from an evidence-record-level citation up to paper-level
  bibliography that no earlier module performed.
  `SessionReport.unresolved_citations` reuses AI-O6's own
  `VerificationResult.hallucinated_citations` (taken as a parameter, not
  recomputed) so a citation is never independently re-checked twice; a
  citation repeated more than once in the narrative resolves to exactly
  one `SourcedClaim`, in order of first appearance.
  `SessionReport.is_fully_sourced` is `True` only when
  `unresolved_citations` is empty. `verification.py`'s citation regex
  moved from a private `_CITATION_RE` to a shared, exported
  `CITATION_PATTERN` constant both modules now import, rather than each
  maintaining its own copy. 5 new tests in `tests/test_session_report.py`.
  Live-verified by re-resolving the real narrative and `EvidenceReport`
  AI-O6's own live check already captured against the real GLP-1 corpus:
  both of the narrative's genuine citations resolved to their correct
  source papers with real DOIs
  (`10.3389/fphar.2022.935823`, `10.1038/s41591-024-02996-7`), zero
  unresolved citations, `is_fully_sourced=True`. See `docs/ai_o7_design.md`.

- **AI-O6: deterministic Skeptic/Verifier.** New
  `knowledge_engine_ai/orchestrator/verification.py`: `verify_synthesis`
  checks a `synthesis.py`-generated narrative against the
  `EvidenceReport` it was built from -- hallucinated citations (a cited
  `[evidence_record_id]` absent from the report), ungrounded numbers (a
  numeric token not present in any cited record's
  `claim_text`/`result_summary`, reusing `core`'s
  `golden_map_grounding.py` numeric-presence technique), and missed
  qualifiers (a `qualifies`/`contradicts`-direction or
  `limitations`-bearing record never cited at all). No LLM verifying
  another LLM, matching AI-O3/AI-O5's deterministic-first precedent. 9
  new tests; one real bug the tests themselves caught (the number
  regex initially matched the "1" inside `[ev-1]` citation brackets as
  a false ungrounded-number finding, fixed by stripping citations
  before extracting numbers). Live-verified end to end against the real
  GLP-1 corpus, `core`'s actual `ke` executable, and a real running
  Ollama model (`qwen2.5:1.5b`): the model's real narrative cited only
  2 of 4 retrieved evidence records, and the checker correctly flagged
  the 2 silently-dropped records as missed qualifiers, with zero
  hallucinated citations or ungrounded numbers -- a genuine first
  real-world signal, not a contrived example. See `docs/ai_o6_design.md`.

- **AI-O5: parallel retrieval + contradiction-oriented retrieval.** New
  `knowledge_engine_ai/orchestrator/parallel_retrieval.py`:
  `run_parallel_retrieval` widens AI-O3's single always-run retrieval
  step into two, run concurrently via a `ThreadPoolExecutor` -- the
  unmodified question (primary) and the same question with `core`'s own
  already-validated same-PICO-contradiction-audit negative-signal
  phrase set appended (contradiction-oriented). No new `core`-side
  capability and no LLM call; each branch's `KeCommandError` is caught
  independently rather than aborting its sibling, matching AI-O3's
  "one step's failure does not stop the rest" discipline.
  `ParallelRetrievalResult.contradiction_only_evidence_record_ids` is
  the concrete recall-gain signal AI-O5's success criterion asks to
  measure. `run_fixed_evidence_workflow` now records both branches as
  separate `ResearchEvent`s (`retrieval_and_evidence_intelligence`,
  `contradiction_oriented_retrieval`); `WorkflowResult.parallel_retrieval`
  carries the full two-branch detail, `evidence_report` still points at
  the primary branch alone for backward compatibility. Optional
  external discovery is an injectable callable, deliberately left
  unwired to any concrete `core` capability (`ke discovery-cycle-run`'s
  persisted pagination-offset semantics do not fit a per-question call
  -- see the design doc). Live-verified against `core`'s real GLP-1 and
  oncology corpora with the actual `ke` executable, at two retrieval
  depths for the oncology check: at a shallow window (`--limit 5`/`8`)
  both corpora showed zero recall gain (the GLP-1 result matches
  `core`'s own contradiction audit finding no contradiction exists
  there -- a correct null result); at a deeper window (`--limit 20`)
  the oncology corpus showed a real, substantial gain -- 63 primary IDs
  vs. 145 contradiction IDs, 121 net-new against only 37 lost, roughly
  3.3x net-new records vs. lost. Retrieval depth, not just query
  wording, materially changes whether the gain is visible at all --
  whether those 121 net-new records are disproportionately genuine
  contradiction candidates was not manually spot-checked and is named
  explicit follow-up work. See `docs/ai_o5_design.md`'s "what this does
  not establish" section for the full honest interpretation. A real,
  narrow concurrency defect was found and
  worked around during verification (two `ke` subprocesses racing to
  apply the same pending schema migration to one on-disk SQLite file on
  first concurrent use), documented rather than silently patched. 6 new
  tests in `tests/test_parallel_retrieval.py`; `tests/test_orchestrator_workflow.py`
  updated for the two-event retrieval step. See `docs/ai_o5_design.md`.

- **AI-O4: local LLM query planner.** New
  `knowledge_engine_ai/copilot/planner.py`: `plan_from_question` prompts
  a local Ollama model to decompose a natural-language question into a
  `ResearchPlan` JSON object, extracts it with a brace-balanced scan
  (survives markdown-fence wrapping), force-overwrites the model's
  `plan_id`/`created_at` with deterministically generated values rather
  than trusting the model to echo them, and validates the result through
  AI-O1's unmodified `parse_research_plan`/`validate_research_plan`.
  Raises `PlannerError` with the raw model output attached on any parse
  or validation failure -- no retry, no repair. Live-verified against a
  real, running `ollama serve` process: 3 of 3 real questions (one per
  this project's three corpus domains) produced a schema-valid,
  correctly domain-matched plan on the first attempt. `qwen3:4b`'s
  hybrid-reasoning "thinking" mode was found unusable at default
  settings in this CPU-only environment (its reasoning tokens consumed
  the entire response budget); verification instead used `qwen2.5:1.5b`.
  16 new tests in `tests/copilot/test_planner.py`. See
  `docs/ai_o4_design.md`.

- **AI-O3: fixed-order deterministic orchestrator.** New
  `knowledge_engine_ai/orchestrator/workflow.py`:
  `run_fixed_evidence_workflow` connects retrieval + Evidence
  Intelligence (always) and the evidence-map / statistical-verification
  steps (only when the caller supplies their required curated inputs)
  to an AI-O2 `ResearchSession`, appending one `ResearchEvent` per step
  whether it succeeds or fails. No LLM call anywhere -- the step
  sequence and each step's run condition are fixed by this module's own
  code, meeting the roadmap's AI-O3 success criterion verbatim ("one
  session can call multiple existing Knowledge Engine capabilities and
  assemble structured results without an LLM dynamically deciding
  execution"). Two new `ke_client.py` wrappers
  (`evidence_map_report`/`statistical_verify`) support this -- neither
  underlying `ke` command has a `--format json` mode, so both return
  their rendered Markdown verbatim. Live-verified end to end against
  the real GLP-1 corpus with `core`'s actual `ke` executable. 12 new
  tests. See `docs/ai_o3_design.md`.

- **AI-O2: durable `ResearchSession`/`ResearchEvent` persistence.**
  New `knowledge_engine_ai/sessions/` subpackage
  (`models.py`/`repository.py`): `SessionStatus` (the design doc's
  nine lifecycle states), frozen `ResearchSession`/`ResearchEvent`
  dataclasses (the session stores only header fields -- everything the
  design doc's `retrieval_runs[]`-style list fields represent is
  derived from the event log, not duplicated), and a SQLite-backed
  `SessionRepository` whose `create_session`/`append_event` raise
  typed `Duplicate*Error`s on a re-used ID rather than silently
  duplicating a row. Success criterion ("a workflow can stop and
  resume without losing or duplicating state") verified end to end by
  a test that closes and reopens a real file-backed database
  connection mid-session. No orchestrator, no LLM call. 12 new tests
  in `tests/sessions/`. See `docs/ai_o2_design.md`.

- **AI-O1: `ResearchPlan`/`ResearchTask` contracts, `TaskType` enum,
  execution-consequence policy, and schema validator.** New
  `knowledge_engine_ai/copilot/` subpackage
  (`contracts.py`/`validation.py`): a seven-value `TaskType` enum
  matching `docs/roadmap/future_ai_orchestration_plan.md`'s
  `required_capabilities` flags, a five-level `ConsequenceLevel` plus
  `execution_decision_for()` implementing that document's default
  execution policy verbatim, frozen `ResearchTask`/`ResearchPlan`
  dataclasses, and `validate_research_plan()`/`parse_research_plan()`
  checking schema version, unique task IDs, resolvable/acyclic
  dependencies, per-task-type consequence-level floors, and
  `required_capabilities`-to-`tasks` agreement. No LLM call, no
  autonomous tool execution, no orchestrator -- the design doc's own
  "Recommended Immediate Decision" section names formalizing these
  contracts as the unconditional next step, ahead of the evidence-base
  thickness gate that applies to later workflow-execution milestones
  (AI-O3 onward). 16 new tests in `tests/copilot/`. See
  `docs/ai_o1_design.md`.

### Changed

- **Reframed AI-O11 (Hypothesis / Experiment Assistance)'s "human
  scientific review" language in `docs/roadmap/future_ai_orchestration_plan.md`.**
  `knowledge-engine-core`'s M72 (jweter/knowledge-engine-core#343)
  established this project's real default for review: an LLM proposes,
  a deterministic grounding check accepts or drops the proposal, and
  human review stays available without being a required gate for every
  record. AI-O11's own text still said a generated hypothesis requires
  human scientific review outright, which no longer matches the pattern
  this project has since built and applied consistently (M52, M69,
  M72). Reframed to name the same grounding-verification pattern as the
  default acceptance mechanism, with human review available and
  expected before acting on a hypothesis outside this system, but not a
  blocking gate this project imposes on every proposal at scale.
  Left `Level 4 -- external consequential action`'s "explicit human
  authorization" language untouched: that gate is about irreversible
  real-world side effects (an action outside this system, not a
  scientific-content classification), a different risk category from
  the review-gate language this pass targets.

### Fixed

- Preserve core's three-way Evidence Quality `extraction_tier`
  (`manual`, `llm_grounded`, or `automated`) when parsing
  `ke evidence-intelligence --format json`. This prevents an
  LLM-grounded record from being reduced to the legacy
  `manually_reviewed: false` view. Synthesis remains core's own
  pre-rendered text and is not reimplemented here.
