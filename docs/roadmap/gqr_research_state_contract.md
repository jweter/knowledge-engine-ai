# GQR Research State Contract v1

Tracking: General Question Research Loop v1, issue #69, GQR-1.

## Purpose

Expose one stable, deterministic workflow state to downstream callers without
asking Web to infer progress from answer prose and without using provider count
as an evidence-quality signal.

The contract lives in `knowledge_engine_ai.copilot.research_state` and has
`schema_version = 1`.

## States

| State | Current synchronous meaning |
|---|---|
| `indexed_answer` | Indexed evidence produced a releaseable answer and the coverage-gap trigger did not fire. |
| `research_required` | Indexed coverage was insufficient and bounded external research is required or has begun, but no releaseable grounded answer exists yet. |
| `researching` | Reserved in v1 for the later durable/asynchronous acquisition-extraction workflow while work is genuinely still in progress. The current synchronous derivation does not emit it. |
| `partial_answer` | A releaseable answer exists from grounded indexed evidence, but the adequacy trigger proved indexed coverage was thin and discovered leads are not yet validated evidence. |
| `insufficient_evidence` | No releaseable grounded indexed answer exists and bounded external research was not triggered. |
| `provider_degraded` | A releaseable partial answer exists, but Core recorded incomplete federated-provider execution or the federated call failed. |
| `blocked` | Primary Core retrieval failed or a required deterministic release gate blocked the session. |

## Serialized metadata

`ResearchStateResult.to_json()` emits stable, sorted JSON containing:

- `schema_version`;
- `state`;
- `reason`;
- `indexed_evidence_record_count`;
- `discovery_triggered`;
- `federated_discovery_attempted`;
- `acquisition_plan_attempted`;
- `provider_degraded`.

The evidence count is the deduplicated union of evidence-record IDs from the
primary and contradiction-oriented indexed retrieval branches. Provider count
is never used to derive state.

## Safety boundaries

- Discovery candidates remain leads, never Evidence Records.
- A triggered discovery run cannot be called `indexed_answer`; the deterministic
  adequacy rule has already established that indexed coverage is thin.
- Until Core GQR-5 grounds/promotes acquired papers and GQR-6 re-retrieves them,
  a releaseable narrative after discovery is at most `partial_answer` (or
  `provider_degraded`).
- State derivation never inspects narrative text and never calls an LLM.
- Acquisition-plan metadata describes workflow progress only. It never implies
  that a paper supports the user's claim.

## Next consumer

`knowledge-engine-web` WEB-GQR-1 should render this AI-owned contract directly
and map each state to visitor-facing messaging. Web must not recreate the
derivation from narrative text or provider result counts.
