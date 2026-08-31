# Knowledge Engine AI — Agent Entry Point

All coding, Codex, scheduled, and autonomous agents working in this repository must load current repository evidence before making changes.

## Required reading

Before selecting or implementing substantial work, read:

1. `docs/agent-development-policy.md` — repository-specific autonomous development rules and the shared Knowledge Engine family policy it references.
2. `docs/project-status.yaml` — continuity snapshot; reconcile it with live PR, CI, issue, and code state before trusting it.
3. The active roadmap/design document named by `docs/project-status.yaml`.
4. `docs/roadmap/research_report_v1.md` — adopted product acceptance contract for report quality, evidence boundaries, and the Monster golden case.
5. `docs/INDUSTRY_REALITY_CHECK.md` — the current repo-specific gap analysis versus grounded-research/AI production expectations.

## Research Report v1 priority

Until the Monster Energy / one-year blood-pressure acceptance case passes end to end, treat Research Report v1 as a standing product constraint. Prefer work that directly improves the structured report contract, claim/evidence linkage, dimension-specific conclusions, certainty rationale, counter-evidence handling, missing-evidence disclosure, or the deployed end-to-end acceptance path over additional non-blocking orchestration abstractions.

Do not trade away grounding, provenance, contradiction review, coverage disclosure, or deterministic release gates to make the report look more polished.

## How to use the reality check

`docs/INDUSTRY_REALITY_CHECK.md` is a durable quality-gap baseline, not a replacement for verified repository state or the active product roadmap.

Use it when selecting, designing, reviewing, and validating work:

- prefer roadmap-compatible work that closes a documented industry-quality gap when priorities are otherwise comparable;
- treat grounding, claim-level evaluation, no-dead-end research behavior, adversarial robustness, observability, reuse, and production integration findings as acceptance concerns, not optional polish;
- do not declare a gap closed merely because orchestration code exists or unit tests pass when the report calls for end-to-end, grounded-generation, adversarial, performance, or Product Reality evidence;
- when a major capability materially changes the assessment, update the reality check or explicitly record why the prior finding still applies;
- never let an old score override newer verified evidence.

## Knowledge Engine family coordination

This repository is the AI/judgment/orchestration layer of one coordinated three-repository system. Coordinate shared contracts with:

- `jweter/knowledge-engine-core`
- `jweter/knowledge-engine-web`

Do not assume cross-repository compatibility. Verify CLI/output contracts, schemas, evidence semantics, progressive-answer state, Research Report v1 semantics, and Web consumption before changing shared boundaries.

## Execution rule

Existing broken, pending, or merge-ready work takes priority over new roadmap work. Never fabricate repository state, and never merge failed, pending, conflicted, blocked, or materially uncertain work.
