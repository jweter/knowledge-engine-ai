# Agent Development Policy

This document governs scheduled and autonomous engineering work on
`knowledge-engine-ai`. It exists so a fresh, isolated agent run — with no
memory of any prior conversation — can pick this repository up cold and work
it correctly.

`knowledge-engine-core`'s `docs/agent-development-policy.md` defines the
shared foundation for the whole Knowledge Engine family (project isolation,
source-of-truth order, the PR state machine, priority order, trust
boundaries, human escalation boundaries, and truthfulness rules). Read it
first. This document only states what is specific to this repository.

## 1. This repository's place in the family

`knowledge-engine-ai` is the judgment/orchestration layer, and it owns the
**one** supported process boundary for invoking Core's `ke` CLI as a
subprocess: `knowledge_engine_ai/ke_client.py`. Every wrapper function in
that module follows the same shape:

- never `shell=True`, never a string-interpolated command;
- structured parsing of `ke`'s `--output`/`--format json` machine-readable
  shape, not stdout scraping;
- every failure normalized into `KeCommandError` with a sanitized message —
  no raw path, stacktrace, or provider-side error body ever reaches a caller;
- an optional shared `ExecutionBudget` (from `knowledge_engine_ai/execution.py`)
  threaded through so composed calls share one wall-clock deadline.

`knowledge-engine-web` depends on this repository specifically so it never
needs its own raw-subprocess logic — if a new Core CLI command needs a web
surface, the wrapper belongs here first, in `ke_client.py`, following the
existing pattern (see `evidence_report`, `evidence_map_report`,
`federated_discover` for reference shapes), before Web calls it.

**Known gap, currently true:** `ke_client.federated_discover()` exists and
is tested, but has no caller anywhere in this repository (not
`run_research_question`, not a `ke-ai` CLI command). See
`docs/project-status.yaml`'s `next_continuation` for the concrete next step.

## 2. Cost-consciousness

Every capability that calls a local LLM or a real external provider API has a
real cost/latency profile. Do not fold a new such call into `run_research_question`'s
default path without explicit confirmation this is authorized product
direction — this repository's history shows federated discovery was
deliberately kept out of `/ask`'s always-on path for exactly this reason.
New optional capability should be reachable through its own explicit
opt-in surface (a new function other repos call only when they choose to,
or a new CLI subcommand), not silently added cost to an existing default.

## 3. Required CI

For the exact current head SHA to count as GREEN:

- `Quality` (`.github/workflows/quality.yml`, job `checks`) —
  `ruff format --check .`, `ruff check .`, `mypy .`, `pytest`.

`Golden Retrieval Baseline` (`.github/workflows/golden-retrieval-baseline.yml`)
is `workflow_dispatch`-only — it never runs automatically on a PR and is not
a required check.

Merge with squash. Never opt for a draft PR — inherited convention across the
whole Knowledge Engine family.

## 4. Development workflow specifics

- Run the full local gate before opening a PR: `ruff format --check .`,
  `ruff check .`, `mypy .`, `pytest` (Poetry-managed).
- A new `ke_client.py` wrapper function must be live-verified against the
  real `ke` binary before the PR is opened, not just tested against a fake
  `subprocess.run`. Locate the real binary in the active Core Poetry
  virtualenv, invoke the new function directly (a short script is fine), and
  read the full real result before trusting it.
- Update `docs/roadmap/future_ai_orchestration_plan.md` and the relevant
  `docs/ai_o*.md` or `docs/roadmap/*.md` design document in the same PR when
  a milestone's status changes. Update `CHANGELOG.md` under
  `## [Unreleased]`.

## 5. Continuity record

`docs/project-status.yaml` is this repository's continuity cache — same
contract as Core's: verify it against real repository state at the start of
every scheduled run, update it whenever durable project reality changes.

## 6. Truthfulness and safety

Never fabricate repository access, files, tests, CI results, PR numbers,
merge results, or project progress. Never expose or commit secrets. Never
merge red, pending, missing-required-check, conflicted, or materially
uncertain code. Prefer small, reversible, testable changes.
