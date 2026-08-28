# GQR-4 / GQR-5 Grounded Completion Bridge

## Status

First executable completion slice for issue #69 and bottleneck issue #87.

The purpose is to eliminate the most important dead zone in the arbitrary-question
research loop: Core could discover and persist papers, but the AI layer had no
bounded path that turned those papers into newly grounded, validated EvidenceRecords
and then reran the researcher's original question.

## Implemented control flow

`knowledge_engine_ai.copilot.grounded_completion.complete_discovered_research()`
implements this bounded path:

```text
Core acquisition plan
  -> reuse already-indexed Papers
  -> execute eligible PMC / Europe PMC / CORE / Unpaywall acquisition routes
  -> parse + persist Papers through Core
  -> bounded extraction-review batch
  -> deterministic automated classification
  -> promote into a private staged evidence file
  -> Core LLM-grounded PICO verification per staged record
  -> Core automated review promotion
  -> keep only llm_grounded + reviewed records
  -> Core validation/promotion into the durable evidence JSONL
  -> rerun the original question through `ke evidence-report`
```

Discovery candidates and merely acquired Papers never go directly to synthesis.

## Why staging exists

Core's existing `extraction-review-autoclassify` can create schema-shaped draft
records, but those records are still automated drafts. Writing them directly into
the reusable evidence store would make a later retrieval capable of seeing a record
that had not passed the grounding verifier.

The bridge therefore promotes automatic classifications into a temporary evidence
file first. Each staged record is sent through `evidence-review-automate`, which
uses Core's local-model proposal plus deterministic source-text grounding checks.
`evidence-record-review-promote` then marks only already-grounding-verified records
reviewed. The AI layer filters on those two recorded Core facts and submits that
subset back through `extraction-review-promote` for the final durable append.

The AI layer never writes a factual record directly into the evidence store.

## Bounded autonomy

`GroundedCompletionPolicy` caps:

- acquisition routes;
- candidates per route;
- full-text acquisitions per route;
- per-route elapsed-time request budget;
- promoted EvidenceRecords per completion pass;
- final re-retrieval result count.

Every external command also shares the caller's existing `ExecutionBudget`.

## Acquisition route behavior

Eligible candidates are grouped by Core's acquisition-plan route and kept in a
stable order:

1. `pmc_oa`;
2. `europe_pmc_oa`;
3. `core`;
4. `unpaywall`.

A route failure is retained as a degraded `AcquisitionRouteResult`; it does not
erase successfully persisted Papers from another route. `already_indexed`
candidates contribute their existing Core `paper_id` without re-acquisition.

## Current extraction limitation

This first slice intentionally composes the extraction capabilities Core already
ships. The deterministic extraction-review generator and M52 automatic classifier
must produce a promotable record before M69 grounding can strengthen it. A paper
whose initial draft lacks enough PICO structure can therefore still drop out before
the grounding pass.

That remaining conversion loss is now explicit and measurable through
`draft_item_count`, `classified_item_count`, staged/grounded/promoted IDs, and
`grounding_failures`. It is the next GQR-4 extraction-quality target, not a reason
to let ungrounded records into the answer.

## GQR-5 completion semantics

Re-retrieval occurs only when at least one newly grounded EvidenceRecord was durably
promoted. The returned `reretrieval_report` is the first result in this flow that is
eligible to replace the original corpus-miss report as a synthesis input.

The next orchestration slice is to make `run_research_question` consume this result
inside the same ResearchSession, record acquisition/extraction/re-retrieval events,
and synthesize from the reretrieved report. Web can then wire Research mode to that
single composed path and enforce the no-dead-end product rule.

Refs #69
Refs #79
Refs #84
Refs #87
