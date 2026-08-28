# GQR Research State v2

`ResearchStateResult` now distinguishes an answer produced from the indexed corpus from an answer produced after the bounded research loop acquired, grounded, promoted, and re-retrieved new evidence.

## New terminal state

`researched_answer` means all of the following are true:

1. indexed coverage was insufficient and discovery was triggered;
2. grounded completion produced newly promoted EvidenceRecords;
3. the original question was re-run after promotion;
4. that reretrieved grounded report was the report actually used for synthesis; and
5. deterministic verification and the Research ISA close gate released the narrative.

`partial_answer` retains its previous meaning: the indexed answer is releaseable, but newly discovered leads have not become the grounded evidence used for that answer.

`provider_degraded` remains the higher-priority state when a releaseable answer exists but attempted provider coverage was incomplete. The v2 facts show whether that answer nevertheless used grounded reretrieved evidence.

## No-dead-end terminal semantics

When discovery triggered and a `GroundedCompletionResult` exists, a completed session with no releaseable grounded answer is now `insufficient_evidence`, not `research_required`. This is safe because the bounded research path has actually been evaluated. Before grounded completion is evaluated, the same initial corpus miss remains `research_required`.

## Added deterministic facts

Schema version 2 adds:

- `grounded_completion_attempted`
- `grounded_completion_completed`
- `used_reretrieved_evidence`
- `promoted_evidence_record_count`

These are workflow facts, not scientific confidence scores.

Refs #69
Refs #84
