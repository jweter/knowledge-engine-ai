## Repository Role

This repository is the AI/reasoning layer of the Knowledge Engine system.

Coordinate with:
- jweter/knowledge-engine-core
- jweter/knowledge-engine-web

Do not assume cross-repository compatibility. Verify shared contracts before changing them.

## Required Agent Context

Before selecting or implementing substantial work, read:

1. `AGENTS.md` — repository agent entry point.
2. `docs/agent-development-policy.md` — repository-specific autonomous workflow and shared Knowledge Engine family rules.
3. `docs/project-status.yaml` plus the active roadmap/design document it identifies.
4. `docs/INDUSTRY_REALITY_CHECK.md` — the current repo-specific gap analysis versus grounded-research/AI production expectations.

Treat `docs/INDUSTRY_REALITY_CHECK.md` as a durable quality-gap baseline, not as a replacement for verified repository state or the active roadmap. Prefer roadmap-compatible work that closes a documented quality gap when priorities are otherwise comparable. Do not declare a gap closed merely because orchestration code exists or CI passes when the report calls for end-to-end grounding, claim-level evaluation, adversarial robustness, observability, reuse, integration, performance, or Product Reality evidence. Update the assessment when major verified capability materially changes its conclusions.

## Engineering Priorities

Prefer, in order:

1. Fix failing existing PRs or tests.
2. Complete unfinished work.
3. Implement the highest-value authorized roadmap slice.
4. Refactor or clean up only when it supports current work.

Prefer small, coherent, reversible changes.

## Knowledge Engine Requirements

Preserve:
- evidence traceability
- provenance
- privacy
- deterministic/non-fabricated state
- documented architectural boundaries
- backward compatibility where practical

Before changing shared APIs, schemas, models, serialized structures, retrieval contracts, or integration boundaries:

1. Identify affected Knowledge Engine repositories.
2. Determine compatibility impact.
3. Coordinate dependent changes when necessary.
4. Test compatibility.
5. Avoid leaving the Knowledge Engine system in a knowingly broken state.

## Verification

Never claim a test, fix, PR, merge, or behavior succeeded unless verified.

Do not merge failed, pending, conflicted, blocked, or materially uncertain work.

Run targeted tests appropriate to the change.

## Scope

Work only on files relevant to the selected task.

Do not perform unrelated cleanup.

Read only the documentation and code needed for the current task.

Follow the repository's current roadmap, architecture, tests, issues, PRs, and documented policies.

## Human Decisions

Make routine engineering decisions autonomously.

Ask Jeremy only when work requires:
- fundamental product-direction changes
- major architecture changes not already authorized
- paid services
- license changes
- destructive migrations
- security/privacy boundary changes
- credentials
- publishing/release authorization
- irreversible actions
- materially ambiguous product outcomes
