# GQR-5 Grounded Completion Inside a Research Session

## Status

Implemented on the GQR-5 session-integration branch after the standalone grounded-completion bridge landed.

This slice removes the orchestration gap between the GQR-4/GQR-5 completion bridge and the normal `run_research_question` pipeline. A Research Session can now continue from thin/empty local evidence through discovery, acquisition, grounded extraction, durable EvidenceRecord promotion, original-question re-retrieval, and synthesis without creating a second session or allowing discovery leads to bypass the evidence trust boundary.

## Composed control flow

When the caller supplies both a `FederatedDiscoveryPolicy` and a `GroundedCompletionPolicy`, `run_research_question` executes:

```text
create ResearchSession
  -> fixed local retrieval (primary + contradiction-oriented)
  -> coverage-gap decision
  -> federated discovery when needed
  -> bounded Core acquisition plan
  -> grounded completion
       -> acquire/reuse planned Papers
       -> extract draft evidence
       -> private-stage automated classification
       -> LLM proposal + deterministic source grounding
       -> automated review promotion
       -> Core-validated durable EvidenceRecord promotion
       -> rerun the researcher's original question
  -> choose synthesis input
       -> grounded re-retrieval report, when one exists
       -> otherwise original local retrieval report
  -> synthesize
  -> verify synthesis against the exact report used for synthesis
  -> build session report
  -> evaluate Research ISA
  -> close or block session
  -> build trace
```

The initial `WorkflowResult` is retained unchanged for provenance. Grounded re-retrieval does not overwrite or erase what the first retrieval found; it becomes the *effective synthesis report* only after the grounded-completion bridge has durably promoted at least one eligible EvidenceRecord and Core successfully answers the original question again.

## Explicit opt-in and configuration contract

Grounded completion remains opt-in because it can perform network acquisition, write Papers/EvidenceRecords through Core, and use a local grounding model.

Supplying `grounded_completion_policy` requires:

1. a `discovery_policy`;
2. `discovery_policy.enable_acquisition_plan=True`; and
3. the discovery and grounded-completion policies to use the same `ledger_root`.

The configuration is checked before a ResearchSession is created. This prevents a run from beginning with an impossible acquisition configuration and prevents a completion step from resolving candidates against a different federated-search ledger than the discovery step that produced them.

## Synthesis trust boundary

The rule remains strict:

- a federated-discovery candidate is not evidence;
- an acquisition-plan item is not evidence;
- an acquired or reused Paper is not evidence;
- an automatically classified draft is not evidence;
- a private staged record is not durable answer evidence;
- only a Core-grounded, reviewed, durably promoted EvidenceRecord can enter the re-retrieval report;
- only that re-retrieval report can replace the initial report as synthesis input.

Verification and `SessionReport` construction use the same effective EvidenceReport that synthesis used. The pipeline therefore cannot synthesize from one report and verify against another.

## Durable session events

The same ResearchSession now records three GQR completion-stage events before synthesis:

- `grounded_acquisition`
- `grounded_extraction`
- `grounded_reretrieval`

These events summarize the completion funnel and preserve failures/skips in the normal append-only `ResearchEvent` ledger.

`grounded_reretrieval` carries the EvidenceRecord IDs and paper DOIs from the report eligible for synthesis. The synthesis event also records the IDs/DOIs of the exact report it used. Consequently, the existing SessionTrace can answer which grounded EvidenceRecords supported the final narrative even when the initial local retrieval found none.

## Close-gate behavior

When grounded completion is requested, the Research ISA gains a required `grounded_completion_integrity` criterion.

It passes when:

- the initial corpus already had sufficient coverage, so completion was unnecessary;
- discovery/completion ran cleanly and produced a grounded re-retrieval report; or
- the bounded path ran cleanly but found no promotable evidence.

It fails on hard pipeline failures that would otherwise risk making a research run appear successfully complete despite a broken requested research path, including:

- federated-discovery failure;
- acquisition-plan failure;
- no completion result after completion was requested;
- grounded extraction failure;
- grounded re-retrieval failure; or
- every usable acquisition route failing before any Paper became available.

This is separate from the optional `discovery_coverage` criterion. Provider degradation remains an explicit coverage limitation, while a hard failure in the requested acquire/extract/re-retrieve path can block session completion.

## Compatibility

The new behavior is additive:

- no `discovery_policy` and no `grounded_completion_policy`: original corpus-only behavior;
- `discovery_policy` only: existing federated-discovery/citation-snowball behavior;
- both policies: the full GQR-4/GQR-5 continuation inside the same session.

`ResearchQuestionResult` adds `grounded_completion` plus two read-side helpers:

- `effective_evidence_report`
- `used_reretrieved_evidence`

Existing callers do not need to change until they opt into the completion policy.

## Tests

The integration regression tests cover:

1. a reretrieved grounded record replacing an older initial retrieval record for synthesis and verification;
2. the same session recording acquisition, extraction, re-retrieval, synthesis, and close-gate events in order;
3. re-retrieval and synthesis source IDs/DOIs reflecting the newly grounded evidence;
4. a grounded extraction failure being durable in the event trace and blocking the required completion-integrity criterion; and
5. fail-fast configuration when grounded completion is requested without acquisition-plan-enabled discovery.

## Next slice: Web Research mode

After this integration is green, the next product-facing step is to make the Web Research path invoke this composed mode with explicit bounded policies and surface the session's progress/events.

That Web slice should preserve the product's multi-speed answer model:

- an immediate response can still come from the fast/local path;
- Research mode can continue through discovery and grounded completion;
- once grounded re-retrieval succeeds, the answer can be upgraded from newly promoted evidence;
- a failure or no-evidence outcome must remain explicit rather than stalling indefinitely.

Refs #69
Refs #79
Refs #84
Refs #87
