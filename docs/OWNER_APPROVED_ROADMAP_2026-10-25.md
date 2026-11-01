# Owner-approved roadmap direction — 2026-10-25

Status: OWNER-APPROVED — standing development direction and implementation authorization, reaffirmed 2026-11-01.

This document records the owner's accepted product objectives and constitutes standing authorization to plan, implement, test, review, and deliver development work that advances those objectives during an owner-authorized Iron God session. The owner has already specified **what to achieve**. Iron God and its qualified builders are responsible for deciding **how to achieve it**. Ordinary roadmap-derived development does not require a second, per-slice owner approval, a manually maintained approved-item list, or a fresh permission request whenever the backlog is exhausted.

## Standing development authorization and autonomous continuation (owner decision 2026-11-01)

- **Scope comes from this roadmap.** Treat the outcomes, constraints, and acceptance criteria below as approved development direction. The "Next slices" are starting points, not an exhaustive ceiling or an approval queue. Continue deriving dependency-ready slices until the outcomes are demonstrably achieved, or a genuine blocker requires guidance.
- **Plan from evidence, not guesses.** Reconcile this document with the project's authoritative local roadmap, AGENTS.md, current source, GitHub issues and reviews, verified acceptance evidence, existing PRs and file ownership, and the shared engineering, working, and development memory layers. Do not treat GitHub main as newer than an authoritative local version merely because it is remote; preserve dirty worktrees and reconcile conflicting changes.
- **Reuse existing implementations.** Before proposing a new feature or helper, search code, preserved branches, verified history, and shared memory for reusable work. Decompose larger outcomes into bounded, testable slices with explicit dependencies, allowed paths, baseline identity, verification steps, and traceability to the roadmap. Avoid duplicate, disconnected, or repeatedly failed work.
- **Proceed without routine reapproval.** The autonomous planner may generate, prioritize, and execute roadmap-derived slices without separately asking the owner to approve each slice. Use an available, capability-appropriate builder; a local worker's measured Level 1–2 limits do not limit the owner's roadmap authorization or justify silently skipping complex work. If a qualified implementer or necessary test environment is unavailable, record the blocker and keep other eligible repositories progressing.
- **Ask only when actual direction is missing.** Investigate unresolved details first using project context and verified evidence. If materially conflicting objectives, missing requirements, or choices with significant consequences remain, ask one focused clarification instead of inventing owner intent. Preserve all unaffected authorized work in the meantime.
- **Preserve engineering and product gates.** Maintain exact-head verification, native tests, canonical preflight, required GitHub CI/reviews, branch protection, provenance, product-reality checks, file-ownership reservations, resource limits, and safe publication/merge rules. Failed gates require repair, retry within bounded policy, or a recorded blocker—not a bypass. Never count an unmerged PR or synthetic-only result as a completed product outcome.
- **Separate scope authorization from runtime control.** This roadmap is ongoing authorization for development objectives; it is not itself a Take the Wheel execution grant. Iron God must still obey the existing authenticated owner-controller session, Give Me Control revocation, release pinning, and worker/lease fences. Shared memory provides context and verified lessons, never execution authority.
- **Respect scope and stop conditions.** Do not silently expand into unrelated products, alter owner-control safeguards, expose secrets, spend money, destroy user data, or install/deploy an unapproved engine release. If an unavoidable action falls outside the roadmap's authorization, ask first. Record progress, failures, merged deliverables, and remaining roadmap gaps in shared memory so subsequent cycles continue from verified evidence rather than start over.

The product-specific objectives, owner decisions, and acceptance criteria that follow remain in force. This authorization clarification does not replace or weaken them.

## Research Report v1
- One user request orchestrates online source discovery, retrieval, evidence analysis, citation verification, and a structured Research Report.
- Research computation runs locally; sources are online and fetched on demand. Local Ollama may be optional, not a mandatory research prerequisite.
- Avoid permanent bulk document storage. Require source-grounded claims, explicit uncertainty, verifiable citations, bounded intermediate artifacts, and cleanup.

## Next slices
1. Identify local-corpus and Ollama hard dependencies in the existing orchestration.
2. Implement an online-evidence adapter and report orchestration behind existing contracts.
3. Test a single-request report end to end, including missing/contradictory sources and citation validation.
