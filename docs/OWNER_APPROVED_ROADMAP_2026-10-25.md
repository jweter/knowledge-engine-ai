# Owner-approved roadmap direction — 2026-10-25

Status: proposed roadmap addendum for review, not an accepted implementation or permission to execute.

This records explicit owner decisions. Reconcile with the authoritative local roadmap, AGENTS.md, active claims, dirty worktrees, and newer accepted work before implementation. Existing safety, provenance, testing, product-reality, controller authorization, and worker lease gates remain mandatory. Do not treat GitHub main as newer than the authoritative local version.

## Research Report v1
- One user request orchestrates online source discovery, retrieval, evidence analysis, citation verification, and a structured Research Report.
- Research computation runs locally; sources are online and fetched on demand. Local Ollama may be optional, not a mandatory research prerequisite.
- Avoid permanent bulk document storage. Require source-grounded claims, explicit uncertainty, verifiable citations, bounded intermediate artifacts, and cleanup.

## Next slices
1. Identify local-corpus and Ollama hard dependencies in the existing orchestration.
2. Implement an online-evidence adapter and report orchestration behind existing contracts.
3. Test a single-request report end to end, including missing/contradictory sources and citation validation.
