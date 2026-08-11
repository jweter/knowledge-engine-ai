# AI-O5 — Parallel Retrieval + Contradiction Search

**Status:** Implemented and live-verified against the real GLP-1 and
oncology corpora with `core`'s actual `ke` executable (2026-08-11).
**Depends on:** AI-O3 (`docs/ai_o3_design.md`, the fixed-order
orchestrator this milestone's retrieval step now widens).

## What AI-O5 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O5 milestone:

> Run primary retrieval, contradiction-oriented retrieval, and optional
> external discovery in parallel.
>
> **Success criterion:** measured contradiction recall improves without
> materially reducing precision.

`knowledge_engine_ai/orchestrator/parallel_retrieval.py`'s
`run_parallel_retrieval` is that step. AI-O3's fixed workflow already
ran one retrieval call (`enriched_evidence_report(question, ...)`) as
its always-run first step; AI-O5 widens that single call into two,
run concurrently: the unmodified question (primary), and the same
question with a fixed, already-validated negative-signal phrase set
appended (contradiction-oriented). Both are still `ke evidence-report`
calls against the same fused lexical+vector retrieval primitive --
`core` exposes no separate "contradiction search" endpoint, and this
milestone does not add one. What changes is the *query text* handed to
that one existing primitive, not the retrieval mechanism itself.

## Why the phrase set is reused, not invented

`CONTRADICTION_SIGNAL_PHRASES` is not a new heuristic. It is
`knowledge-engine-core`'s own same-PICO contradiction-search audit
vocabulary ("no significant", "not significant", "no difference", "did
not", "failed to", "no benefit", "no improvement", "worse
survival/outcome", "inferior", "shorter overall
survival/progression-free survival/survival", "increased mortality/risk
of death", "higher risk of death"), copied verbatim from
`docs/oncology_same_pico_contradiction_search_audit.md` and
`docs/mental_health_same_pico_contradiction_search_audit.md` in `core`.
Those audits already validated this vocabulary as a genuine
contradiction-candidate signal at corpus scale (oncology: 1,534 records
screened, 108 matched, 1 real `contradicts`-labeled candidate
investigated in full; mental health: 133 records screened, 17 matched,
0 same-PICO contradictions found). Reusing it here — as a query
reformulation rather than a corpus-wide text scan — keeps this
milestone's contradiction-orientation grounded in a technique `core`'s
own reviewers already trust, instead of this project independently
guessing a new phrase list with no track record.

## Concurrency: threads, not async or multiprocessing

Both retrieval branches (plus an optional third, external-discovery
branch) run inside a `concurrent.futures.ThreadPoolExecutor`. Each
branch is one `ke` subprocess call — I/O-bound, not CPU-bound — so
threads are the correct primitive; `asyncio` would need every call site
up through `ke_client.py` rewritten to be async for no real benefit, and
multiprocessing would add process-startup overhead this project's
"shell out to `ke`" boundary (`ai_design.md`) does not need. Each
branch's own `KeCommandError` (or, for external discovery, any
exception at all, since it is a caller-supplied callable this module
cannot type-constrain) is caught inside that branch and reported via the
result's own `error`/`external_discovery_error` field -- never allowed
to abort a sibling branch still running. This is the same "one step's
failure does not stop the remaining fixed steps" discipline AI-O3's
`run_fixed_evidence_workflow` already established for its own fixed
steps, now applied within a single step's two (or three) concurrent
branches.

## The recall-gain signal: `contradiction_only_evidence_record_ids`

`ParallelRetrievalResult` computes the set difference between the two
branches' evidence-record ID sets. This is the concrete, honest
operationalization of "measured contradiction recall improves": not a
subjective judgment about whether new results are "more contradictory,"
but a literal count of evidence records the contradiction-oriented query
surfaced that the primary query did not. A caller (a future AI-O6
Skeptic step, or a human reading `WorkflowResult.parallel_retrieval`)
decides what to do with that set; this module only computes it.

## External discovery: deliberately left unwired

`external_discovery` is an optional, injectable callable
(`Callable[[str], object]`), `None` by default. It is **not** wired to
`core`'s one real external-discovery command, `ke discovery-cycle-run`,
and that omission is deliberate, not an oversight: `discovery-cycle-run`
advances a persisted `--state` pagination offset on every call and is
designed for a scheduled, corpus-growth cadence (see
`docs/core_interface_contract.md`), not a per-question, in-session
lookup. Wiring a live research question straight into it would silently
mutate that offset as a side effect of answering one question -- the
opposite of what a per-question "optional external discovery" step
should do. A future milestone that builds a genuinely per-question-safe
external-lookup primitive in `core` (read-only, no persisted state
mutated) can supply one to this parameter without this module changing;
until then, leaving the seam open and undecorated is more honest than
forcing a bad fit.

## Live verification: what was measured, and what it does and does not show

Run against `core`'s real, on-disk corpora with `core`'s actual `ke`
executable (not mocked), from a fresh checkout with the local database
already migrated to its current schema:

- **GLP-1 corpus** (`does semaglutide reduce body weight more than
  placebo`, `--limit 5`): primary retrieval returned 4 evidence-record
  IDs (`ev-glp1-gao-meta-analysis-body-weight-001`,
  `ev-glp1-gao-meta-analysis-safety-discontinuation-001`,
  `ev-glp1-select-trial-weight-loss-208wk-001`,
  `ev-glp1-step5-body-weight-week104-001`). The contradiction-oriented
  branch returned 0 evidence-record IDs at `--limit 5` -- both branches
  succeeded (no error on either side), but the reformulated query did
  not surface any new evidence record in the top-5 window. This is
  consistent, not contradictory, with `core`'s own GLP-1 same-PICO
  contradiction audit's conclusion that no same-PICO contradiction
  exists in this corpus for the STEP5/SELECT-family finding: a
  contradiction-oriented query correctly finding nothing extra, in a
  corpus that genuinely contains nothing extra to find, is the expected
  result, not a failure of the mechanism.
- **Oncology corpus** (`do immune checkpoint inhibitors improve overall
  survival in advanced non-small-cell lung cancer`, `--limit 8`):
  primary retrieval returned 25 evidence-record IDs, contradiction
  retrieval returned 24 -- `contradiction_only_evidence_record_ids` was
  empty (every ID the contradiction branch found was already in the
  primary set). The two branches did return different *papers*
  (different top-ranked titles -- e.g. an STK11-biomarker paper, an
  opioid/immune-checkpoint crosstalk paper -- surfaced only on the
  contradiction-oriented branch), but those differently-ranked papers
  did not happen to carry a promoted `EvidenceRecord`, so they
  contributed no new IDs to the recall-gain count.

**What this establishes:** the mechanism itself works correctly end to
end against real data (concurrent execution, independent per-branch
error handling, a genuinely computed set-difference), and precision was
not materially reduced (the contradiction branch never returned an
evidence record absent from a sane, on-topic result set). **What this
does not establish:** that appending this specific 16-phrase block to a
question reliably increases measured recall of genuinely contradicting
evidence at corpus scale. Two real questions against two real corpora is
a small-sample live-verification check confirming the plumbing is
correct, not a systematic recall/precision benchmark -- the same
"what a small sample does and does not establish" caveat
`docs/ai_o4_design.md` already named for its own 3-question live check.
A real benchmark would need a labeled set of question/known-contradiction
pairs to measure recall against, which does not exist yet in this
project; building one is named here as follow-up work, not attempted in
this milestone.

## A real concurrency finding: migration races under concurrent `ke` calls

Live verification surfaced one genuine defect before it was
mitigated: the very first concurrent run against a local database that
had not yet been migrated to its current schema version failed both
branches with `sqlite3.OperationalError: database is locked` on `ALTER
TABLE "graph_claims" ADD COLUMN "corpus_id"` -- two `ke` subprocesses
racing to apply the same pending schema migration to the same on-disk
SQLite file at once. Running one serial `ke evidence-report` call first
(forcing the migration to complete before any concurrent call) resolved
it; every subsequent concurrent run in this verification succeeded
cleanly. This is a real, if narrow, operational hazard worth naming
plainly rather than silently working around: `run_parallel_retrieval`
assumes its `evidence`/`sources` paths point at an already-migrated
local database, the same assumption every other AI-O module already
makes about `core`'s database state, but this is the first milestone
where two `ke` subprocesses can race on that assumption simultaneously.
No code change was made to guard against this in `core` or here -- a
caller responsible for corpus setup (e.g. running `ke init` or one
warm-up `ke` call before first concurrent use) already avoids it, and
adding retry/locking logic here for a one-time migration race would be
exactly the kind of speculative machinery this project's "don't build
for a hypothetical" discipline warns against, absent evidence it
recurs beyond first-run migration.

## What AI-O5 does not do

- Does not call an LLM. Matches AI-O3's "no LLM dynamically deciding
  execution" precedent -- AI-O6 (Skeptic + Verifier), not this
  milestone, is where independent model-based verification first
  enters the pipeline.
- Does not build a new `core`-side retrieval or contradiction-detection
  capability. `ke evidence-report`'s fused search is unchanged; only the
  query text handed to it, twice instead of once, is new.
- Does not wire a concrete external-discovery implementation (see
  above).
- Does not consume a `ResearchPlan`'s `contradiction_search` task type
  yet -- `run_fixed_evidence_workflow` still runs the widened retrieval
  step unconditionally (matching AI-O3's "always run" retrieval
  status), the same way it does not yet consume the rest of a
  `ResearchPlan`'s `tasks` list. Connecting a plan's specific task
  types to specific workflow branches remains future orchestrator work.
