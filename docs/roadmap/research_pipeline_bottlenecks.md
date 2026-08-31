# Research Pipeline Bottlenecks and Time-to-Information Plan

Status: **active optimization program**  
Parent: issue #84  
First diagnostic case: issue #79 (Monster Energy / one-year blood pressure)  
Cross-repository companions: `knowledge-engine-core` #433, `knowledge-engine-web` #93

## Product invariant

The target product is a researcher using the website like this:

```text
research question
  -> immediate indexed-evidence check
  -> useful progress / grounded partial information when available
  -> bounded external research when needed
  -> newly acquired evidence validated into the reusable corpus
  -> original question re-run against that evidence
  -> grounded report with citations, coverage, contradictions, and limitations
```

An initial indexed-corpus miss is **not** a scientific conclusion and must not be
presented as the final `no research papers found` result when the bounded research
path is available. A final insufficient-evidence result is valid only after the
eligible research path has actually been attempted (or a specific non-repairable
block is recorded).

## Why bottlenecks are a first-class feature

Research latency is structurally different from a normal web search. Some work can
return in milliseconds/seconds; provider discovery, full-text acquisition, parsing,
grounded extraction, and verification can take much longer. The product therefore
needs two optimization targets:

1. **time to first grounded information**, and
2. **time to final bounded report**.

Optimizing only total runtime can make the UX worse if the system withholds already
validated information until every optional research task finishes. Conversely,
showing provider snippets early would make the UX look fast by weakening the trust
boundary. The correct strategy is progressive release of *validated* information
while the rest of the bounded evidence loop continues.

## Stable stage taxonomy

BT-1 introduces a stable engineering taxonomy independent of scientific domain:

1. `question_interpretation`
2. `indexed_retrieval`
3. `adequacy`
4. `discovery`
5. `acquisition`
6. `extraction_promotion`
7. `reretrieval`
8. `synthesis_verification`
9. `report_close`
10. `other` for an unclassified future node (never silently guessed)

This taxonomy is intended to become the common language used by AI traces, Core
operation metrics, Web progress states, and golden performance benchmarks.

## BT-1: deterministic trace-to-bottleneck report

`knowledge_engine_ai.orchestrator.bottleneck_report` projects the existing durable
`SessionTrace` into a typed `SessionBottleneckReport`.

It reports:

- observed stage durations;
- slowest stage;
- slowest individual event;
- failed events;
- untimed events and whether timing coverage is complete;
- raw summed event duration;
- adjusted known duration after known parallel overlap is removed;
- explicit parallel-overlap adjustment.

This is deliberately a read-side projection. It does not modify execution or infer
scientific quality from runtime.

### Parallel retrieval accounting

Primary retrieval and contradiction-oriented retrieval already run concurrently.
`workflow.py` intentionally records the same combined wall-clock duration on both
ResearchEvents so each branch remains independently inspectable. Summing those two
values would claim twice the actual elapsed time.

The BT-1 report therefore treats those two known nodes as one parallel group and
uses the maximum of their durations for the `indexed_retrieval` stage. Future
parallel provider/acquisition groups need similarly explicit semantics rather than
ad hoc subtraction.

## Current bottleneck priority

### 1. Automatic grounded extraction/promotion — functional blocker

Discovery can find a relevant paper, and the acquisition bridge can plan/reuse some
sources, but the arbitrary-question loop is not complete until newly acquired text
can automatically become validated Evidence Records. This is GQR-4 and is the
largest current functional bottleneck.

Optimization direction:

```text
acquired source
  -> parse
  -> grounded domain-general extraction
  -> source-text verification
  -> EvidenceRecord validation
  -> promotion or explicit rejection reason
```

Run this under explicit per-session source/record/time budgets.

### 2. Re-retrieval after promotion — functional blocker

Newly discovered/provider-returned papers must never go directly to synthesis.
After promotion, the original question must be re-run against Core's validated
store. This is GQR-5.

Optimization direction: promote in bounded batches, re-retrieve after each useful
batch, and stop the *blocking* research path when deterministic adequacy is met.

### 3. Production-path research policy — functional/product blocker

A caller that omits the research/discovery policy can still behave corpus-only.
Production Research mode must not interpret a zero-record local retrieval as the
final result.

Optimization direction: explicit stable state transition:

```text
indexed miss -> research_required -> researching ->
partial_answer | final_answer | insufficient_evidence | provider_degraded | blocked
```

`insufficient_evidence` is terminal only after bounded research completion, not at
the first retrieval step.

### 4. Acquisition throughput/access — functional + latency bottleneck

Prioritize work that can become evidence:

1. already indexed / already acquired;
2. stable-identity reusable open access;
3. permitted full-text acquisition;
4. metadata-only leads last for the blocking answer path.

Deduplicate before download, persist receipts, and never repeatedly retry known
access failures without a changed condition.

### 5. Federated query/provider fan-out — latency + cost bottleneck

GQR-2 query planning intentionally broadens coverage, but variants multiplied by
providers can grow quickly. The bounded discovery adapter caps this fan-out and
preserves track/provider provenance.

Next optimization should be evidence-driven:

- measure provider latency/degradation;
- reuse sufficiently fresh prior search runs where policy permits;
- use bounded safe concurrency for genuinely independent calls;
- retain at least one query for each scientifically required track before spending
  budget on synonym breadth.

### 6. Core subprocess/cold-start overhead — likely latency bottleneck, measure first

The AI/Core contract currently shells out to `ke` commands. The architecture already
anticipates a persistent host when deployment needs justify it. Do not replace the
boundary because it *sounds* slow: first separate startup/model/index-load time from
useful retrieval time on cold and warm golden runs.

If startup dominates, move the production path toward the planned warm persistent
Core host while retaining the same read-only contracts and provenance semantics.

### 7. Synthesis/local-model latency — latency + reliability bottleneck

Synthesis remains citation-gated and can fail when the local model is unavailable.
The UX should not hide already grounded facts while waiting for optional breadth.
A partial answer is allowed only from validated retrieved Evidence Records, with an
explicit partial/coverage state; discovery candidates remain ineligible.

## Optimization control loop

Optimize **time to sufficient grounded evidence**, not maximum paper count:

```text
indexed retrieve
  -> deterministic adequacy
  -> if insufficient: bounded discovery
  -> bounded candidate/acquisition batch
  -> bounded grounded extraction/promotion batch
  -> re-retrieve original question
  -> deterministic adequacy again
  -> finish if sufficient; otherwise next bounded batch while budget remains
```

This provides a natural early-stop point without weakening evidence validation.

## Measurement roadmap

### BT-0 — golden performance baseline

Run at least:

- #79 on a corpus that does not already contain the required evidence;
- immediate repeat of #79 to measure reuse;
- indexed GLP-1 fast path;
- one unfamiliar chemistry/materials question.

Record cold/warm status, evidence-store revision, bottleneck report, funnel counts,
time to first grounded information, final state, and final-report time.

### BT-1 — trace-to-bottleneck report

Implemented by this slice. It makes existing ResearchEvent timing actionable and
fixes the known parallel-retrieval double-counting problem.

### BT-2 — research conversion funnel

**Status: implemented.** `knowledge_engine_ai.orchestrator.funnel_report`
projects `run_research_question`'s already-recorded facts into a
`ResearchConversionFunnelReport`: federated-discovery/citation-snowball
candidate counts (Core already returns these deduplicated); the
acquisition plan's already-indexed/full-text-eligible/metadata-only/
skipped-budget/missing disposition counts; acquisition-route attempted/
skipped/failed and persisted/reused paper counts; the draft/classified/
staged/grounded/promoted extraction funnel with a derived rejected-after-
classification count; re-retrieval attempted/succeeded status and
evidence-record count; and time-to-first-grounded-information/time-to-
final-report, both summed from BT-1's per-stage durations. Wired into
`run_research_question` as `ResearchQuestionResult.conversion_funnel_report`.
Web's own rendering of this contract is separate follow-up work.

### BT-3/BT-4 — remove dead ends

Complete production research-state behavior plus GQR-4/GQR-5 so a fresh topic can
actually cross the discovery-to-evidence boundary automatically.

**Status: GQR-4/GQR-5's executable bridge is implemented** (acquisition plan ->
bounded PMC/Europe PMC/CORE/Unpaywall execution -> persisted/reused Papers -> staged
extraction/classification -> Core LLM grounding -> automated review promotion ->
Core-validated durable EvidenceRecord append -> original-question re-retrieval,
wired into `run_research_question`'s own session/synthesis path); see issue #87's
first two comments for the live-verified measurement. Two follow-up gaps that
measurement surfaced are now also closed: the missed-qualifier release-gate
failure (`synthesis.py`'s `ensure_required_evidence_coverage` deterministically
appends any qualifying/contradicting record the model omitted, so
`verify_synthesis`'s `missed_qualifiers` check cannot be left non-empty by a small
model ignoring the prompt), and the "cold runs starve synthesis of time" gap
(`run_research_question`'s opt-in `min_synthesis_seconds` parameter, backed by
`ExecutionBudget.with_reserved_tail()`, lets a caller guarantee synthesis a time
floor even when discovery/acquisition/extraction would otherwise consume the
entire shared deadline; omitting it preserves the prior single-shared-budget
behavior). Remaining BT-4 work: improve pre-grounding extraction conversion for
papers the deterministic M52 classifier cannot initially structure (issue #87's
first comment), and decide/wire a production caller that actually opts into
`min_synthesis_seconds` with a real reservation value. BT-3's production
Research-mode wiring remains knowledge-engine-web's own follow-up (issue #86).

### BT-5 — measured latency optimization

Only after BT-1/BT-2 provide evidence, compare before/after traces for caching,
warming, persistent Core hosting, provider concurrency, acquisition batching, and
search-run reuse. BT-5a (indexed retrieval cache, `docs/roadmap/bt5a_indexed_retrieval_cache.md`)
and the batched grounded-review perf slice (`docs/roadmap/bt5_batch_grounded_review.md`)
are implemented.

### BT-7 — early stop on adequacy

`complete_discovered_research` now extracts/promotes already-indexed candidates
first, before any network acquisition, and skips every configured acquisition
route once that alone meets the adequacy threshold. See
`docs/roadmap/bt7_early_stop_on_adequacy.md`.

### BT-6 — progressive Web report

Web should show stage + elapsed time + bounded counts/reason for waiting. Avoid fake
percent-complete bars. A provider failure degrades coverage; it should not blank an
otherwise grounded answer.

**Status: AI-side contract implemented.** `run_research_question` now returns a
`ResearchProgressReport` (`knowledge_engine_ai.copilot.progress_report`, issue #90)
carrying current stage, overlap-adjusted elapsed time, indexed-vs-newly-acquired
EvidenceRecord IDs, provider coverage/degradation, an explicit wait reason,
citations/limitations, and a `final` gate mapped onto `knowledge-engine-web#93`'s
8 named progress states -- see `docs/roadmap/bt6_progressive_report_contract.md`.
Web's own rendering of this contract remains tracked in
`jweter/knowledge-engine-web#93` and is separate follow-up work; a later durable/
polling caller is still needed before the mid-flight states
(`discovering_sources`, `acquiring_sources`, `validating_extracting_evidence`,
`reretrieving`) can actually be emitted rather than reserved.

## Definition of streamlined v1

A previously unseen research question can be entered in Web and:

1. receive an immediate honest progress state;
2. use indexed evidence first;
3. automatically broaden when indexed evidence is inadequate;
4. acquire and validate eligible literature under bounded budgets;
5. promote grounded Evidence Records;
6. re-retrieve the original question;
7. release partial grounded information when legitimately available;
8. return a final source-linked report or a *post-research* insufficient-evidence
   result;
9. expose where time was spent and what degraded/failed;
10. reuse the validated work on a repeated/related question.

That is the performance/product definition. A fast `no papers found` response after
only local retrieval does not satisfy it.
