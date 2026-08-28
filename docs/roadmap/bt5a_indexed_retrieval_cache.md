# BT-5a — indexed retrieval cache

Status: implemented
Parent: #84
Benchmark tracking: #91
Issue: #114
Refs: #89

## Purpose

BT-0's measured fresh music/endurance run showed warm execution at ~60.5s, with
indexed retrieval alone at ~31.3s -- and `warm_run_reuse_observed=false`, because
the second run's indexed retrieval had no explicit cache/reuse layer even though
the corpus had not changed. BT-5a is the first BT-5 latency optimization: a
bounded in-process cache for successful indexed retrieval results.

## What the cache does

`knowledge_engine_ai.orchestrator.retrieval_cache` adds a process-local,
least-recently-used cache, bounded to 64 entries, keyed by:

- the normalized query (case/whitespace-collapsed);
- the retrieval `limit`;
- content-addressed (`sha256`) revisions of both the sources file and the
  evidence file;
- the resolved sources/evidence paths, working directory, and `ke` executable.

A cache hit returns a deep copy of a previously retrieved, already-enriched
`EvidenceReport` instead of re-running `ke evidence-report` +
`ke evidence-intelligence`. Only successful branches are ever stored --
`orchestrator.parallel_retrieval._run_branch` stores a result only after
`enriched_evidence_report` returns without raising `KeCommandError`, so a
failed retrieval attempt is retried on the next call rather than silently
cached. Any change to the sources or evidence file content changes the
content-addressed key automatically, so stale results are never served after a
corpus update.

Both the primary and the contradiction-oriented retrieval branches are cached
independently, and each has its own `cache_hit` flag on
`RetrievalBranchResult`. External discovery is unaffected: it keeps running
every call regardless of indexed-retrieval cache state, matching AI-O5's
"primary retrieval, contradiction-oriented retrieval, and optional external
discovery in parallel" milestone text.

## Observability

- `workflow.run_fixed_evidence_workflow` records each retrieval branch's cache
  status (`retrieval_cache_hit=true|false`) on that branch's `ResearchEvent.notes`
  when the branch succeeded, alongside the existing duration/source-id fields.
- `research_pipeline_benchmark.ResearchConversionFunnel` gained
  `primary_indexed_retrieval_cache_hit` and
  `contradiction_indexed_retrieval_cache_hit`, both included in the funnel's
  `to_dict()`/JSON output, and both feed into `reuse_hit` alongside the
  existing paper-reuse/already-indexed signals -- so a warm benchmark run whose
  only reuse was indexed-retrieval caching (no re-acquired papers) now correctly
  reports `reuse_hit=true` and `warm_run_reuse_observed=true`.

## What did not change

Retrieval semantics, evidence adequacy, and evidence-record identity are
unchanged: a cache hit returns the same enriched report a fresh call would have
produced against the same corpus snapshot. No evidence threshold, promotion
criterion, or verifier/release gate was touched.
