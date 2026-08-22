# Federated Discovery Orchestration Adoption

Status: adopted AI-layer guidance, 2026-08-15.

**2026-08-22 (later still than that): the DOI crosswalk detection layer is
implemented -- the third concrete slice of `answer_session_versioning_design.md`,
and the first item of the "next continuation" the repository-mechanics slice
below left open.** `copilot/research_freshness.py` gains
`session_retrieval_dois()` and `crosswalk_publication_status_flips()`,
implementing the design doc's "the crosswalk" section exactly: for each
`PublicationStatusFlip` a caller already has (from `diff_candidate_snapshots`),
look up its candidate's DOI in the same `current` snapshot, match it against
the session's own retrieval-step DOIs, and keep only the matches where at
least one evidence record sharing that DOI was actually cited in the
session's persisted narrative (`verification.CITATION_PATTERN`, reused a
third time, not reimplemented). Both functions are pure and take
already-fetched data -- no `SessionRepository`/`ke` call inside either one,
matching `assess_rerun_need`/`diff_candidate_snapshots`'s own "caller owns
the I/O" shape. This slice also makes the design doc's open sub-decision
("re-run `ke evidence-report` at check time, or add an additive `doi` field
alongside the retrieval event's existing `source_ids`"): **additive field,
not a re-run.** `ResearchEvent` gains `source_dois` (parallel to
`source_ids`, same order, same additive-field/no-schema-bump pattern as
`duration_ms`), populated by both retrieval-step events in
`orchestrator/workflow.py`. Re-running `evidence-report` at check time was
rejected: retrieval against a corpus that has since changed is not
guaranteed to reproduce the *original* session's citations -- exactly the
kind of drift a crosswalk trying to answer "what did *this* session cite"
must not introduce, and it would add a live subprocess call to what should
stay a cheap, deterministic freshness check. The additive field costs one
`ALTER TABLE` column and no new `ke` call. 14 new tests (385 total pass);
full local quality gate (ruff format/check, mypy, pytest, pip-audit, git
diff --check) clean via `scripts/preflight.py`. Still not implemented: the
invalidates-versus-qualifies trigger that actually calls
`record_narrative_invalidation()`/records a qualifying pending flip for a
`NarrativeTouchingFlip` this slice can now detect, the `AnswerFreshness`
read-side projection, and a caller that mints a version-*N+1* session -- see
the design doc's updated "What this does not do" section. Web is
unaffected, same reasoning as the entry below: `knowledge-engine-web` pins
a specific `knowledge-engine-ai` commit and this change adds no signature
change to any function Web's pin already calls.

**2026-08-22 (later still): the answer/session-versioning repository
mechanics are implemented -- the second concrete slice of
`answer_session_versioning_design.md`.** `ResearchSession` gained the three
remaining additive fields the design names (`answer_version`,
`supersedes_session_id`, `narrative_invalidated_at`, with a guarded
`ALTER TABLE` migration for pre-existing databases), and `SessionRepository`
gained `record_narrative_invalidation()` (appends a `narrative_invalidated`
event and sets the field, guarded to fire at most once per session) and
`supersede_session()` (appends an `answer_superseded` event and flips status
to `SUPERSEDED`, guarded to require the session was `COMPLETED`). 13 new
tests (371 total pass); full local quality gate (ruff format/check, mypy,
pytest, pip-audit, git diff --check) clean via `scripts/preflight.py`. This
is deliberately the "mechanics" half only, matching the design doc's own
staged-delivery pattern: nothing calls either new method yet. The DOI
crosswalk (which candidate flip actually touches a session's own cited
narrative), the invalidates-versus-qualifies trigger wiring, the
`AnswerFreshness` read-side projection, and a caller that mints a
version-*N+1* session remain unimplemented -- see the design doc's updated
"What this does not do" section for the exact remaining scope. Web is
unaffected: `knowledge-engine-web` pins a specific `knowledge-engine-ai` git
commit in its `pyproject.toml` and only constructs
`SessionRepository`/`ResearchSession` through the existing, unchanged
constructor and `run_research_question` call shape, so this change is inert
for Web until a future session both bumps that pin and adds a caller.

**2026-08-22 (later same day): `research_question_id` threading implemented
-- the first concrete wiring slice of `answer_session_versioning_design.md`.**
`run_research_question` now accepts an optional `research_question_id` and
always sets it on the `ResearchSession` it creates (caller-supplied, or
deterministically derived from the question text), threading it down to
the already-existing `ke_client.federated_discover(research_question_id=...)`
call whenever `discovery_policy` is also supplied. See AI-FRD-5's section
below for the full account. Adds no versioning/supersession behavior itself
-- `answer_version`, `supersedes_session_id`, `narrative_invalidated_at`,
the DOI crosswalk, and `SessionStatus.SUPERSEDED`'s first real use remain
unimplemented.

**2026-08-22: `docs/roadmap/answer_session_versioning_design.md` scopes the
answer/session-versioning concept AI-FRD-5's remaining wiring needs.**
Docs-only -- no change to `run_research_question.py`, `sessions/models.py`,
`sessions/repository.py`, `orchestrator/close_gate.py`, or
`copilot/research_freshness.py`. See that document for the full design
(a version is one whole `ResearchSession`, chained by additive
`research_question_id`/`answer_version`/`supersedes_session_id` fields; a
DOI crosswalk from a flagged federated-discovery candidate to the
`evidence_record_id`s a prior narrative actually cited; an invalidates
(`retracted`/`withdrawn`) versus qualifies (`corrected`/
`expression_of_concern`) split; and `SessionStatus.SUPERSEDED` -- already
in the enum, unused anywhere in code before this design -- as the terminal
state for a superseded version, set only once its replacement itself
reaches `COMPLETED`). AI-FRD-5's own exit-criteria section below still
reports both remaining criteria as **not started**: this document is the
scoping step that criterion needed, not the implementation.

This document records the AI-layer lessons taken from the review of
`surendranb/find-research-papers-mcp`. The useful behavior is translated into
Knowledge Engine's own orchestration model. The external MCP server is not a
required dependency, does not define our research method, and does not own our
provider choices.

The matching Core plan is
`knowledge-engine-core/docs/roadmap/federated_research_discovery_adoption.md`.

**2026-08-22: AI-FRD-2's provider-coverage criterion implemented as a first
bounded slice.** `run_research_question` attaches an optional
(`required=False`) `discovery_coverage` ISA criterion whenever a caller
supplies `discovery_policy`, evaluated from the same
`DiscoveryAugmentationResult` AI-FRD-3/AI-FRD-4's wiring already produces
and Core's own `completeness` field -- never a model claim, never a
re-derivation of provider success/failure. See AI-FRD-2's own section below
for the full account; contradiction-search/citation-integrity criteria
already exist independently, and a correction/retraction close-gate
criterion remains future work pending AI-FRD-5's session wiring.

**2026-08-21: AI-FRD-5's rerun/diff reasoning implemented as a first bounded,
tested, standalone slice.** `copilot/research_freshness.py`'s
`assess_rerun_need()`/`diff_candidate_snapshots()` and the new
`ke-ai research-freshness` CLI command answer this milestone's "new evidence
is distinguished from previously seen evidence" exit criterion over data
`federated_discover_history()`/`federated_coverage_report()` already return
-- no new Core change, no new subprocess call shape. Deliberately not wired
into `run_research_question`; see AI-FRD-5's own section below for the full
account and remaining scope.

**2026-08-20: `ke_client.federated_coverage_report()` added, closing the
point-lookup gap the entry below deliberately deferred.** Core's FRD-6
candidate-snapshot follow-up (commit `96d30ac`, "Persist federated-discover
candidate snapshots; add coverage-report --output", merged as PR #394) added
an `--output` option to `ke federated-coverage-report` and started
persisting each run's full deduplicated candidate list (canonical ID,
title, DOI, publication year, every provider's full observation) on the
ledger's `SearchRunRecord.candidates` -- exactly the two conditions the
entry below named as blocking this wrapper. `federated_coverage_report()`
mirrors the existing `federated_discover()`/`federated_discover_history()`
shape: shells out to `ke federated-coverage-report <search_run_id>
--ledger-root <dir> --output <tmp>`, parses the result into a typed
`FederatedCoverageReportResult` pairing that run's `SearchCoverageReport`
with its full candidate snapshot, and discards the temporary file. A run
recorded before Core's candidate-snapshot follow-up existed returns an
honest empty `candidates` tuple, never a fabricated one. Live-verified
against the real `ke` binary (a ledger record seeded via Core's own
`FederatedSearchLedger.record()`, no network provider call involved, since
this command is a pure ledger read). This is purely additive
client-boundary work: no policy here decides what changed between two
runs, diffs them, or renders anything -- that remains the Web-side concern
WEB-FRD-5's design doc names for items 5-7, per that document's own
division of labor. Deliberately out of scope for this change:
`knowledge-engine-web` closing WEB-FRD-5's candidate-level exit criteria on
top of this wrapper.

**2026-08-20: `ke_client.federated_discover_history()` added, plus
`federated_discover()` now forwards `project_id`/`research_question_id` --
closing this repository's two blockers named by `knowledge-engine-web`'s
WEB-FRD-5 design (`web_frd5_freshness_history_design.md` section 5, items
3-4).** Core's FRD-6 follow-up (`ke federated-discover
--research-question-id`/`--project-id` and the new `ke
federated-discover-history <id>` command) had already merged; this repository
had no wrapper reaching either surface. `federated_discover_history()`
mirrors the existing `citation_snowball()`/`federated_discover()` shape:
shells out to `ke federated-discover-history <id> --ledger-root <dir>
--output <tmp>`, parses the typed `SearchCoverageReport` list, and returns a
`FederatedDiscoverHistoryResult` -- an empty `runs` tuple is a valid, honest
"no prior recorded search for this question" result, never an error.
`federated_discover()`'s two new optional keyword parameters default to
`None` and are omitted from the command line entirely when unset, so every
existing caller (`discovery_plan.py`, `cli.py`'s `ke-ai discover`,
`copilot/discovery_policy.py`) is unaffected. This is deliberately just the
subprocess/parse boundary -- no policy here decides when to tag a run with a
`research_question_id`, or diffs two runs; that remains open (see AI-FRD-5
below and WEB-FRD-5's own item 5-7 for the Web-side "tracked question"
product concept this still waits on). A point-lookup wrapper for the
pre-existing `ke federated-coverage-report` command was considered but not
added in this change: that CLI command has no `--output` JSON option today
(confirmed by reading `entrypoint.py`), so wrapping it would mean either
scraping console text (against this project's own established discipline)
or first adding a Core-side `--output` flag -- out of scope for this
AI-only slice. `federated_discover_history()` already returns every run's
full `SearchCoverageReport` for a tracked question in one call, which is
sufficient for WEB-FRD-5's actual "list history, diff two runs" use case
without that point lookup.

**2026-08-19: AI-FRD-3/AI-FRD-4 wired into `run_research_question`'s own
planning via a new `copilot/discovery_policy.py`, closing this milestone's
long-standing "known gap."** Jeremy's explicit product-owner decision,
recorded in this change's PR: "continue with the FRD and widen the
search." Every previous entry below stopped short of this wiring precisely
because *when* to invoke it was flagged as needing that judgment call; this
entry is that call being exercised.

`FederatedDiscoveryPolicy` (opt-in; `run_research_question`'s new
`discovery_policy` parameter defaults to `None`, reproducing prior
behavior exactly) defines two deterministic trigger rules -- never an LLM
judgment call, matching AI-O3/AI-O5's existing "no model dynamically
deciding execution" discipline:

- **Federated discovery** fires when primary corpus retrieval succeeded but
  the fixed workflow's own deduplicated evidence-record coverage (primary
  union contradiction-oriented branch, AI-O5's existing signal) falls below
  a configurable threshold -- conservative default `3` -- "insufficient
  initial evidence coverage," this roadmap's own example trigger. It does
  not fire when primary retrieval itself failed (a Core problem broader
  provider coverage cannot fix).
- **Citation-snowball** fires under the same signal, seeded deterministically
  from the DOIs of the corpus's own already-relevant retrieved papers
  (rank order, capped at a conservative default of `3` seeds) -- "seed
  known landmark work" from this doc's own citation-graph section, grounded
  in the corpus rather than an unvetted discovery candidate. No DOI-bearing
  seed available means the step is skipped and the reason recorded, never a
  failure.

Every conservative numeric default (coverage threshold, provider limits,
snowball depth/seed count, per-call execution-second ceilings tighter than
`discovery_plan.py`'s own person-invoked 600s ceiling since this path runs
autonomously) is `FederatedDiscoveryPolicy`'s own field with a documented
default -- Jeremy's "widen the search" decision authorized building and
wiring the capability, not any one specific number; every default is
overridable and called out in the introducing PR's description as such.

Provenance is preserved end to end without ever treating provider/candidate
*count* as evidence quality: every discovery/snowball attempt records its
own durable `ResearchEvent` (Core's own `search_run_id`/`snowball_run_id`,
`completeness`, candidate count) visible on the session trace and on the
new `ResearchQuestionResult.discovery` field, but candidates are never
written to `source_ids` (that field means "evidence supported the output"),
never fed to `synthesize_answer`, and never treated as an `EvidenceRecord`
-- exactly the same "discovery leads, not evidence, not acquired" framing
`ke-ai discover`/`ke-ai citation-snowball`'s own text output already
prints. The narrative still cites only grounded, corpus-sourced evidence.
`research --broaden-search-on-gap` is this capability's first CLI surface,
also opt-in, mirroring the Python API's default-off posture.

See `CHANGELOG.md`'s matching entry and `knowledge_engine_ai/copilot/discovery_policy.py`'s
own module docstring for the full trigger/budget/provenance policy detail.
AI-FRD-3 and AI-FRD-4's exit-criteria sections below are updated to reflect
this.

**2026-08-19: `FederatedDiscoveryResult.search_run_created_at` added, parsing
Core's `coverage.created_at` (half of `knowledge-engine-web`'s WEB-FRD-2
gap).** `knowledge-engine-core`'s `docs/core_interface_contract.md` already
documents `coverage.created_at` as part of `ke federated-discover --output`'s
public shape; this repository's parser simply never read it.
`parse_federated_discovery_result()` now carries it through as
`FederatedDiscoveryResult.search_run_created_at: str | None`, `None` when a
payload predates or omits the `coverage` block, never a guessed value.
Purely additive -- `knowledge-engine-web`'s current pinned revision is
unaffected. See `CHANGELOG.md`'s matching entry. A future
`knowledge-engine-web` PR still needs to bump its pinned `knowledge-engine-ai`
revision and render the field in `discover.html`'s "Run timestamp" row to
close WEB-FRD-2 fully -- out of this repository's own scope, the same
two-step pattern already used for WEB-FRD-3/WEB-FRD-4.

**2026-08-19: `ke_client.citation_snowball()` added, AI-FRD-4's first client
wrapper for Core's FRD-7 `ke citation-snowball` command.** See AI-FRD-4's
section below for the exit-criteria status; a no-caller, no-seed-selection
gap remains this milestone's own next continuation.

**2026-08-19: `ke-ai citation-snowball` added, the first in-repository
caller of `ke_client.citation_snowball()`.** Closes the "no CLI command
calls it" half of AI-FRD-4's gap noted immediately above, mirroring how
`ke-ai discover` closed the same gap for `federated_discover()`. See
AI-FRD-4's section below and `CHANGELOG.md`'s matching entry. Seed-selection
policy and wiring into `run_research_question`'s own planning remain
unstarted.

**2026-08-19: `FederatedCandidateSummary` now surfaces per-provider
`retracted`/`preprint` observations, unblocking `knowledge-engine-web`'s
WEB-FRD-4.** `knowledge-engine-web`'s
`docs/federated_discovery_transparency_roadmap.md` (WEB-FRD-2/WEB-FRD-4,
merged in Web's PR #64) recorded a concrete cross-repo gap: `/discover`
could not show visitors per-provider `retracted`/`preprint` observations
because this repository's typed `FederatedCandidateSummary` -- the only
value Web's route receives from this repo -- discarded everything from
Core's `ProviderObservation` except the provider name, even though Core's
`ke federated-discover --output` JSON already includes `retracted`,
`preprint`, and `preprint_version` per provider observation. This repository
now parses those fields into a new `FederatedCandidateSummary.observation_flags`
field (`FederatedProviderObservationFlags`, one entry per provider
observation, additive and unmerged across providers). Purely additive --
`providers` and every other existing field/JSON key are unchanged, so Web's
current `/discover` integration remains compatible without modification. A
future `knowledge-engine-web` PR still needs to update its own route/UI to
read `observation_flags` and close WEB-FRD-4 on Web's side; this repository
change was this run's full, authorized scope (Web/Core changes were
explicitly out of bounds for this run). See `CHANGELOG.md`'s matching entry
for live-verification detail (arXiv observations reporting real
`preprint`/`preprint_version`, OpenAlex reporting real `retracted`).

**2026-08-18: `ke_client.federated_discover()` gained its first in-repository
caller, `ke-ai discover`.** The client wrapper existed, was unit-tested, and
was live-verified against the real `ke` binary, but had no caller inside this
repository -- only `knowledge-engine-web`'s `/discover` route used it. The new
CLI command is a direct, bounded way to run one federated discovery search and
inspect Core's recorded coverage/disagreement facts from this repository
without a full Research Copilot session. It is deliberately a standalone
command, not a step inside `run_research_question`'s own planning -- deciding
*when* a research task needs broader provider coverage is AI-FRD-3's
(Discovery-plan compiler) job below, which remains not started pending its own
capability-registry/execution-budget design. This closes the immediate
"built but unreachable" gap without prematurely committing to that larger,
not-yet-authorized design.

## AI-layer role

Core owns provider transport, search-run provenance, canonical identity,
provider health/status, and evidence/source persistence. AI owns research-task
planning and interpretation over those deterministic facts.

The Research Copilot may decide that a task would benefit from:

- broader provider coverage;
- citation/reference expansion from a landmark paper;
- an updated recency search;
- a contradiction-oriented query variant;
- a correction/retraction sweep;
- a provider that covers a domain better than the providers already searched.

It must express that as a bounded discovery request to Core. It must not call
provider APIs directly and then treat unrecorded results as evidence.

## Search coverage becomes part of the Research ISA

A Research ISA should increasingly be able to express search-completion claims
such as:

- the configured relevant scholarly providers were attempted;
- provider failures are visible;
- at least one independent bibliographic index and one domain-specific source
  were searched when appropriate;
- citation/reference expansion was completed when the question requires it;
- contradiction-oriented search was performed;
- correction/retraction status was checked for works used in the final answer;
- every cited claim maps to persisted evidence;
- the system reports unresolved coverage gaps rather than silently closing.

These are criteria, not model self-scores. Core supplies the underlying search
run and provider-status facts; deterministic verification decides whether the
criterion passes.

## Capability-aware planning

The reviewed project demonstrates useful graceful degradation. Knowledge Engine
should take this further by giving Research Copilot an explicit capability view.

Example:

```text
pubmed: available
crossref: available
openalex: available
arxiv: available
semantic_scholar: rate_limited
citation_expansion: available_via_openalex
retraction_check: available
local_llm: available
cloud_reasoner: disabled
```

The planner can adapt the research plan to this state, but must not relabel a
partial plan as complete. `disabled`, `unavailable`, `rate_limited`, `failed`,
and `not_relevant` remain distinct states.

## Provider diversity is a retrieval signal, not a confidence shortcut

Using multiple providers can improve recall and make blind spots visible, but the
number of providers is not evidence quality.

The AI layer must never reason:

> five databases found this paper, therefore the claim is more true.

Multiple provider observations may improve confidence in bibliographic identity
or search coverage. Scientific confidence still depends on the underlying study
evidence and Knowledge Engine's Evidence/Analytical Intelligence contracts.

## Citation graph as a planning primitive

Research Copilot should eventually be able to propose bounded citation-snowball
steps:

```text
seed known landmark work
-> inspect references
-> inspect citing works
-> normalize identities
-> screen for relevance
-> persist candidate provenance
-> repeat only to declared depth/budget
```

Useful cases:

- finding earlier foundational work;
- finding replications or extensions;
- locating corrections/retractions and follow-up studies;
- identifying later contradiction or qualification;
- tracing how a scientific claim changed over time.

The model proposes the strategy; Core executes and records it.

## Provider-generated text is not evidence text

Semantic Scholar and future providers may expose generated TLDRs, summaries, or
other convenience text. These can be useful navigation hints, but they must carry
provider-generated provenance and must never be supplied to grounding validators
as though they were source-paper text.

Priority for substantive interpretation remains:

1. persisted full source text with locator provenance;
2. source abstract/metadata that the scholarly provider reports as source
   metadata;
3. provider-generated summary only as a discovery/navigation hint.

The AI layer should label the distinction in its own internal context.

## Research-plan diversification

One important improvement beyond the reviewed repository is to make discovery
strategies composable instead of using the same query everywhere blindly.

A future planner may produce something like:

```yaml
research_plan:
  - step: federated_search
    providers: [pubmed, crossref, openalex]
    query_intent: primary_question
  - step: domain_search
    provider: pubmed
    query_intent: clinical_synonyms_mesh_expansion
  - step: preprint_sweep
    provider: arxiv
    when: domain_relevant
  - step: citation_expand
    seeds: [landmark_work_ids]
    direction: both
    depth: 1
  - step: contradiction_search
    query_intent: aligned_pico_direction_reversal
  - step: correction_retraction_check
    targets: cited_work_ids
```

Every step must have a deterministic run record and bounded execution budget.

## Keep research doctrine ours

The external project exposes a `get_research_method()` helper. Knowledge Engine
will not import an upstream project's "house method" as scientific authority.

Our own research method evolves through:

- project principles;
- Research ISA criteria;
- Evidence Intelligence;
- Analytical Intelligence;
- source/provenance contracts;
- explicit contradiction policy;
- deterministic verification;
- domain-specific validated methods where needed.

A provider or MCP plugin can say what capability it offers. It does not get to
say what counts as adequate evidence.

## Security and privacy

The external repository's telemetry and environment/client fingerprinting are not
part of Knowledge Engine AI's architecture.

AI-layer rules:

- no default external telemetry;
- no persistent third-party analytics installation identity;
- no research-query analytics sent outside the provider calls actually needed to
  execute the research;
- no tool-sequence or harness fingerprinting sent to third parties;
- provider credentials stay outside prompts and research-session records;
- remote installer convenience is not a reason to weaken reviewed dependency
  management;
- external paper/web text remains untrusted data, never instructions.

## Provider-neutral model and tool routing

The federated-discovery review reinforces the broader LifeOS-derived rule already
adopted in this repository: workflow semantics should name capabilities, not
vendors.

Prefer:

```text
search_scholarly_literature
expand_citation_graph
check_retraction_status
high_reasoning_model
local_private_model
```

rather than hard-coded provider/model names in research doctrine.

Concrete providers remain configurable implementations behind those roles.

## AI roadmap additions

### AI-FRD-1 -- Consume Core discovery coverage

Once Core exposes provider status/search-run contracts, ingest them into the
Research Session without reinterpreting them.

Exit criteria:

- session records can identify complete versus degraded discovery;
- provider status is preserved through synthesis and close-gate verification;
- no model-generated provider status exists.

### AI-FRD-2 -- Coverage-aware Research ISA

Add deterministic close-gate criteria for provider coverage, contradiction
search, citation integrity, and correction/retraction checks where relevant.

**Status: first bounded slice implemented -- provider-coverage criterion
only.** `run_research_question` attaches a fourth, optional
(`required=False`) `discovery_coverage` `IdealStateCriterion` to the ISA
whenever a caller supplies `discovery_policy` (omitted entirely otherwise,
leaving the pre-existing three-criteria path unchanged). It is evaluated
from the same `DiscoveryAugmentationResult` AI-FRD-3/AI-FRD-4's wiring
already produces, reusing Core's own `completeness` field (already derived
only from attempted providers, excluding disabled/skipped ones) rather than
re-deriving provider success/failure locally. Contradiction-search,
citation-integrity, and correction/retraction close-gate criteria are out
of scope for this slice: contradiction review and citation integrity
already have their own ISA criteria (`contradiction_review`,
`citation_integrity`, both pre-existing); a correction/retraction close-gate
criterion needs AI-FRD-5's rerun/diff reasoning wired into a session first
(see AI-FRD-5's own "not yet started" exit criteria below) and remains
future work.

Exit criteria:

- deliberately failed provider fixture blocks a "complete coverage" claim;
  **met** -- `test_discovery_coverage_criterion_fails_on_failed_provider_without_blocking_close`
  proves a rate-limited provider in a triggered discovery run reports the
  `discovery_coverage` criterion `FAILED`, naming the specific provider and
  Core's own recorded reason, never silently `PASSED`
- synthesis can still proceed in degraded mode when policy permits, but the
  limitation is explicit; **met** -- the criterion is `required=False`, so a
  `FAILED` `discovery_coverage` result never blocks `close_result.status`
  from reaching `COMPLETED`, while still being visible on the session's own
  ISA validation
- close gate never passes merely because the model says it searched
  broadly. **met** -- the criterion is a deterministic function of Core's
  own recorded `provider_statuses`/`completeness`, never a model claim; it
  is `NOT_APPLICABLE` (not a fabricated `PASSED`) when discovery was not
  triggered this run at all
- a coverage gap that policy chose not to address is distinguished from a
  provider that was attempted and failed. **met** (2026-08-22 fix) --
  `test_discovery_coverage_criterion_not_applicable_when_federated_discovery_disabled`
  proves a triggered run with `enable_federated_discovery=False` reports
  `NOT_APPLICABLE`, never a fabricated `FAILED` naming a provider that was
  never attempted

### AI-FRD-3 -- Discovery-plan compiler

Allow Research Copilot to produce a typed, bounded plan using Core discovery
capabilities.

**Status: compiler/executor foundation implemented and now wired into
Research Copilot's own planning (2026-08-19).** `discovery_plan.py`'s
`DiscoveryPlan` / `compile_discovery_plan()` / `execute_discovery_plan()`
give this milestone its typed plan and bounded execution primitive:
`DiscoveryPlan` validates provider names against `KNOWN_DISCOVERY_PROVIDERS`
(mirrors Core's own `_federated_discovery_registry` set), a
limit/year/execution-budget bound that fails closed in `__post_init__`
before any subprocess call ever runs, and `execute_discovery_plan()` runs
the plan through the same `ke_client.federated_discover()` boundary every
other caller uses, returning Core's own `search_run_id` (replayable through
Core's ledger, not a second local record of what ran).
`copilot/discovery_policy.py`'s `evaluate_and_run_discovery_augmentation()`
is now that caller: `run_research_question`'s new opt-in `discovery_policy`
parameter evaluates the deterministic coverage-gap trigger described above
and, when it fires, calls `compile_discovery_plan()`/`execute_discovery_plan()`
with `FederatedDiscoveryPolicy`'s own conservative, documented bounds.

Exit criteria:

- provider/tool names validate against capability registry; **met** --
  `DiscoveryPlan.__post_init__` against `KNOWN_DISCOVERY_PROVIDERS`
- execution budget/depth is explicit; **met** -- `max_execution_seconds`
  and `limit_per_provider` are required, bounded `DiscoveryPlan` fields;
  `execute_discovery_plan()` always builds its `ExecutionBudget` from the
  plan's own bound
- unknown tool/provider requests fail closed; **met** -- raises
  `DiscoveryPlanError` at plan construction, before any `ke` subprocess call
- plan execution remains replayable through Core run IDs. **met** --
  `execute_discovery_plan()` returns Core's own `search_run_id`
- wiring a compiled plan into `run_research_question`'s own planning, and
  the policy for deciding *when* to compile/execute one; **met** --
  `copilot/discovery_policy.py`'s coverage-gap trigger, opt-in via
  `discovery_policy`

### AI-FRD-4 -- Citation-snowball planner

Add a bounded strategy for reference/citation expansion from selected seed works.

**Status: `ke_client` wrapper, standalone CLI command, and a
`run_research_question` seed-selection policy all now reachable
(2026-08-19).** `ke_client.citation_snowball()` is the in-repository way to
invoke Core's FRD-7 `ke citation-snowball` command -- it passes seeds,
provider, directions, depth, and per-traversal/candidate bounds straight
through to Core and returns a typed, parsed `CitationSnowballResult`
(mirroring `federated_discover()`'s own shape). `ke-ai citation-snowball`
(2026-08-19) is that command's first in-repository caller, the same "built
but unreachable" gap `ke-ai discover` closed for `federated_discover()` --
a direct, bounded way to run and inspect one citation-snowball expansion
without a full Research Copilot session.
`copilot/discovery_policy.py._seed_dois()` is this milestone's
seed-selection policy: the DOIs of the primary retrieval branch's own
ranked papers, in rank order, deduplicated, capped at a conservative
default of 3 -- "seed known landmark work" grounded in the corpus already
trusted, rather than an unvetted discovery candidate. `run_research_question`'s
opt-in `discovery_policy` parameter is the `run_research_question` caller
this exit criteria section previously named as missing.

Exit criteria:

- seed selection and depth are visible; **met** -- `_seed_dois()`'s policy
  is documented and unit-tested; `citation_snowball_max_depth` is an
  explicit, bounded `FederatedDiscoveryPolicy` field
- results enter normal Core provenance flow; **met** -- every run persists
  to Core's own citation-snowball ledger before `citation_snowball()`
  returns, replayable via Core's `ke citation-snowball-report`
- planner cannot bypass deduplication, acquisition, or evidence validation;
  **met by construction** -- `citation_snowball()` only reads Core's
  discovery/traversal output, the same read-only boundary
  `federated_discover()` uses, and does not touch acquisition
- a `run_research_question` caller and a seed-selection policy; **met** --
  `copilot/discovery_policy.py`, opt-in via `discovery_policy`

### AI-FRD-5 -- Research freshness / rerun reasoning

Given an earlier Research Session, help decide whether a new federated search is
warranted and explain what changed after Core reruns it.

**2026-08-20 status:** the client-boundary prerequisite this milestone needs
is now built -- `ke_client.federated_discover_history()` can list every past
run for a tracked `research_question_id`, and `federated_discover()` can tag
a new run with one. Nothing yet *decides* whether a rerun is warranted or
computes a diff between two runs' `SearchCoverageReport`s; that reasoning
(and the Web-side "tracked question" identity it depends on, per
`knowledge-engine-web`'s WEB-FRD-5 design doc items 5-7) remains this
milestone's actual, unstarted scope.

**2026-08-21: the rerun/diff reasoning itself now exists as a first bounded,
tested, standalone slice -- deliberately not yet wired into a session.**
`copilot/research_freshness.py`'s `assess_rerun_need()` (deterministic:
no run ever recorded, or the most recent run incomplete, or older than a
configurable freshness threshold, each in that order) and
`diff_candidate_snapshots()` (newly discovered candidates and newly
asserted publication-status flags between two specific past runs' full
candidate snapshots, by Core's own `canonical_id`) answer this milestone's
first exit criterion -- new evidence is distinguished from previously seen
evidence -- over data `federated_discover_history()`/
`federated_coverage_report()` already return, no new Core or subprocess
call. `ke-ai research-freshness <research_question_id>` is the first
caller, mirroring the "build the tested primitive, add a standalone CLI
caller, wire into `run_research_question` later" sequencing AI-FRD-3/
AI-FRD-4 already used -- see `CHANGELOG.md`'s matching entry for the
live-verification account. The remaining two exit criteria
(corrections/retractions invalidating or qualifying prior synthesis, and
versioned rather than silently overwritten prior answer text) require a
durable Research Session to attach this reasoning to and are explicitly
this milestone's next continuation, not yet started.

**2026-08-22: `research_question_id` threading, the first concrete slice of
`answer_session_versioning_design.md`'s wiring, is implemented.**
`run_research_question` now accepts an optional `research_question_id`
keyword parameter and always sets it on the `ResearchSession` it creates --
a caller-supplied value used verbatim, or (the common case today) one
derived deterministically from the normalized question text
(`rq-<sha256[:16]>`), the exact origin rule that design doc's "Where
`research_question_id` actually comes from" section specifies. The value
threads down the existing call chain -- `evaluate_and_run_discovery_augmentation`
-> `_run_federated_discovery` -> `execute_discovery_plan` -> the
already-existing `ke_client.federated_discover(research_question_id=...)`
call -- only when `discovery_policy` is also supplied; deliberately not
threaded into citation-snowball (no `research_question_id` parameter exists
on that call, and this design's freshness mechanism only ever reads
federated-discover run history). `ResearchSession` gains only this one
additive field (`schema_version` unchanged, existing rows load it as
`None`); no new `ke_client.py` wrapper function was added (the underlying
`federated_discover`/Core `--research-question-id` flag were already built
and live-verified in an earlier session), so this slice's own verification
is the local test suite -- 8 new tests across `sessions/test_repository.py`,
`test_discovery_plan.py`, `copilot/test_discovery_policy.py`, and
`copilot/test_run_research_question.py` (358 total pass; full local quality
gate -- ruff format/check, mypy, pytest, pip-audit, git diff --check --
clean). This closes only the plumbing gap the design doc named; it adds no
versioning/supersession behavior. `answer_version`, `supersedes_session_id`,
`narrative_invalidated_at`, the crosswalk, the invalidates/qualifies
trigger, and `SessionStatus.SUPERSEDED`'s first real use all remain
unimplemented -- the next continuation below.

**2026-08-22 (later still than that): the repository-layer mechanics
(`answer_version`/`supersedes_session_id`/`narrative_invalidated_at`,
`record_narrative_invalidation()`/`supersede_session()`) and the DOI
crosswalk detection layer (`session_retrieval_dois()`/
`crosswalk_publication_status_flips()`) are both now implemented -- see the
two dated entries at the top of this document for the full account of
each. Detection now exists (a `NarrativeTouchingFlip` can be computed from
a real `diff_candidate_snapshots()` output plus a real session's own
retrieval events and persisted narrative) but nothing yet calls
`record_narrative_invalidation()`/records a qualifying pending flip in
response to one -- that trigger wiring is the remaining piece of the first
"not started" exit criterion below.**

**2026-08-22 (later still than that): the invalidates-versus-qualifies
trigger itself is now implemented.** `copilot/research_freshness.py`'s
`apply_narrative_touching_flips()` takes one batch of `NarrativeTouchingFlip`s
and, for each `retracted`/`withdrawn` one, calls
`record_narrative_invalidation()` (checking the session's current
`narrative_invalidated_at` first so a batch with more than one invalidating
flip, or a session an earlier pass already invalidated, never raises); for
each `corrected`/`expression_of_concern` one, it returns the flip in
`NarrativeFreshnessTriggerResult.qualifying` without persisting anything.
12 new tests (397 total pass); full local quality gate clean via
`scripts/preflight.py`. Still no caller runs this for a real session --
that requires deciding *when* a freshness check happens at all, which
remains explicitly undecided product/policy work (see
`answer_session_versioning_design.md`'s "What this does not do").

**2026-08-22 (later still than that): `ke-ai session-freshness` is the first
real caller of the full chain against an actual Research Session.** It
loads a named session, reads its `research_question_id` and its own
retrieval/synthesis event log, and composes
`assess_rerun_need` -> `diff_candidate_snapshots` -> `session_retrieval_dois`
-> `crosswalk_publication_status_flips` to report exactly which flips, if
any, touch a claim that session actually cited -- split into invalidating
versus qualifying. Read-only by default; `--apply` also calls
`apply_narrative_touching_flips` to persist an invalidating flip. This is
the on-demand, explicitly-invoked case, matching `ke-ai research-freshness`/
`ke-ai discover`'s own "standalone CLI caller" precedent -- it does not
itself decide *when* a freshness check should run (a scheduled job, a
person, a Web page load), which remains open product/policy work, and it
does not mint a version-*N+1* session. 10 new tests
(`tests/test_cli_session_freshness.py`); full local quality gate clean via
`scripts/preflight.py`. See `CHANGELOG.md`'s matching entry for the full
account.

**2026-08-22 (later still than that): the `AnswerFreshness` read-side
projection is now implemented.** `copilot/research_freshness.py` gained
`AnswerFreshness` (`session_id`, `research_question_id`, `answer_version`,
`status`, `supersedes_session_id`, `superseded_by_session_id`,
`narrative_invalidated_at`, `rerun_recommended`, `pending_flips`, and a
`releaseable` property) and `build_answer_freshness()`, a pure projection
over already-fetched data. `SessionRepository` gained
`list_sessions_for_research_question()` so `superseded_by_session_id` can
be derived (no session row stores a forward pointer to whatever replaced
it). `ke-ai session-freshness` is the projection's first real caller: its
text and `--format json` output now include an "Answer freshness" section,
built from state re-read after a possible `--apply` write. 10 new tests
(418 total pass); full local quality gate clean via `scripts/preflight.py`.
See `CHANGELOG.md`'s matching entry for the full account.

Exit criteria:

- new evidence is distinguished from previously seen evidence; **met** --
  `diff_candidate_snapshots()`, live-verified against the real `ke` binary
- corrections/retractions can invalidate or qualify prior synthesis;
  **reasoning, a real caller, and its read-side projection all exist; not
  yet automatic.** Every mechanism is now built and exercised end to end
  against a real session by `ke-ai session-freshness --apply`:
  `research_question_id` threading, the repository-layer mechanics, the
  DOI crosswalk detection layer, the invalidates-versus-qualifies trigger,
  a caller that runs all of it and persists an invalidating flip on
  request, and now the `AnswerFreshness` projection that surfaces the
  result (`releaseable`, `pending_flips`, `superseded_by_session_id`) for
  a caller to consume without re-deriving it (all 2026-08-22). What
  remains is only the decision of *when* a freshness check runs at all --
  this command makes it possible on demand, not automatic
- prior answer text is never silently overwritten as if it had always been the
  updated answer. **not started** -- `answer_session_versioning_design.md`
  scopes the versioning concept this reasoning needs to attach to; the
  `answer_version`/`supersedes_session_id`/`narrative_invalidated_at` fields
  and events are implemented (2026-08-22, later still) and tested in
  isolation, but no caller yet mints a version-*N+1* session or calls
  `supersede_session()` on a prior one

## Improvements beyond the external reference

The external MCP focuses on finding papers. Knowledge Engine can go further by
joining discovery to the rest of its scientific operating system.

### Discovery quality benchmark

Extend retrieval benchmarks to test provider-level recall and identity merging,
not just ranking over already-ingested corpora. Golden fixtures should include:

- papers only one provider finds;
- DOI duplicates returned by several providers;
- preprint and journal-version pairs;
- retracted/corrected works;
- rate-limited provider runs;
- citation-expanded relevant papers missing from lexical search;
- intentionally conflicting provider metadata.

### Stopping rules

Research Copilot should eventually be able to stop discovery for an explicit
reason:

- ISA coverage criteria satisfied;
- execution/time budget reached;
- no material new candidates after bounded expansion;
- required provider unavailable, making completion impossible;
- user intentionally requested a narrow source scope.

"The model feels done" is never a stopping rule.

### Counter-search before conclusion

Before a strong synthesis is released, the planner should be able to issue one
or more adversarial searches designed to find evidence that would weaken or
reverse the emerging conclusion. This should become a standard Research ISA
pattern for consequential questions.

### Search-strategy provenance in the answer

The user-facing answer should eventually be able to summarize, in compact form,
not just which studies were cited but how the evidence search was constructed:
providers searched, important failures, citation expansion, last refresh, and
material limitations. Web owns the presentation; AI owns the grounded narrative
of what those deterministic run facts imply for completeness.

## End state

The AI layer should become capable of planning a research investigation across
many scholarly sources while remaining unable to fake the investigation.

The desired flow is:

```text
question
-> Research ISA
-> capability-aware discovery plan
-> Core executes/persists every discovery step
-> evidence is validated and linked
-> AI analyzes only recorded evidence and run facts
-> Skeptic/close gate tests coverage, contradiction, and citations
-> answer states both the evidence and the limits of the search
```

That is the Knowledge Engine version of the useful idea: broad discovery with
scientific accountability, not an MCP wrapper around five APIs.
