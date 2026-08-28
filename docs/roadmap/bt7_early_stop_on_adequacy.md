# BT-7 — early stop on adequacy

Status: implemented (first slice)
Parent: #84
Issue: #92
Refs: #87, #89

## Purpose

Before this change, `complete_discovered_research` (GQR-4/GQR-5) always acquired
from every configured federated-discovery route up to
`policy.max_acquisition_routes`, then extracted/grounded/promoted everything it
had acquired in one combined batch, regardless of whether the papers already in
the local corpus were already enough to answer the question. That wasted
acquisition latency and provider cost on optional breadth even when the bounded
research path was already adequate -- exactly the gap #92 (BT-7), #87 (BT-4),
and #89 (BT-5) each call out: "avoid searching/acquiring beyond the point where
sufficient grounded evidence exists" and "stop the blocking critical path early
when adequacy is reached."

## What changed

`complete_discovered_research` now runs in two possible bounded phases:

1. **Already-indexed phase.** Candidates the acquisition plan already resolved
   to an existing paper (`disposition == "already_indexed"`) cost no network
   acquisition at all, so they are extracted/grounded/promoted first.
2. **Adequacy check.** If that phase alone promotes at least
   `policy.min_promoted_records_for_early_stop` grounded EvidenceRecords
   (default `3`, matching `discovery_policy.DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE`
   so "adequate coverage" means the same thing before and after discovery),
   every configured acquisition route is skipped. Each skipped route is still
   recorded as an explicit `AcquisitionRouteResult(attempted=False,
   skipped_reason=...)` -- never silently omitted -- so funnel/bottleneck
   reporting can distinguish "skipped because adequate" from "not attempted for
   an unknown reason."
3. **Acquisition phase (only when still inadequate).** Acquisition proceeds
   across every configured route exactly as before, and the newly acquired
   papers are extracted/grounded/promoted in one additional bounded batch. This
   preserves BT-5's recent batched-extraction latency win (one
   `evidence-review-automate` invocation per batch, not per record) for the
   still-common case where indexed coverage alone is not enough.

A single final re-retrieval still runs once, after whichever phases actually
executed, using the combined set of promoted records from both phases.

## What did not change

- No discovery candidate bypasses `EvidenceRecord` validation. Skipping
  acquisition only ever happens *after* real grounded evidence has already been
  durably promoted from already-indexed sources -- adequacy is judged on
  promoted `EvidenceRecord` counts, never on candidate/provider metadata.
- Extraction failure still stops that batch's new-evidence path before
  re-retrieval. A failure in the acquired-papers batch no longer discards
  grounded records the already-indexed batch already promoted durably --
  `GroundedCompletionResult.extraction_error` is surfaced alongside whatever
  was already promoted, rather than the whole result being thrown away.
- `GroundedCompletionPolicy` and `GroundedCompletionResult` gained new fields
  with safe defaults (`min_promoted_records_for_early_stop`,
  `acquisition_skipped_for_adequacy`, `AcquisitionRouteResult.skipped_reason`);
  no existing field was renamed or removed, so every current caller (including
  `knowledge-engine-web`, which pins this package by git revision) is
  unaffected until it opts into a newer revision.

## Follow-on work

This slice only short-circuits *before* acquisition begins. A finer-grained
version could re-check adequacy between individual acquisition routes (not
just before vs. after all routes), trading a proportional increase in local
extraction subprocess calls for earlier acquisition-network savings. That is
deliberately deferred: the BT-5/BT-5a batched-extraction work optimized for
exactly the "acquire everything, then batch-extract once" shape, and
per-route interleaving should be justified with its own before/after trace
evidence (per #89's acceptance rule) rather than assumed.
