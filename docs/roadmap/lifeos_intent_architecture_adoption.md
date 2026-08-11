# LifeOS Intent Architecture Adoption for Knowledge Engine AI

**Status:** accepted architecture direction  
**Scope:** `knowledge-engine-ai`  
**Source:** *LifeOS Engineering Teardown for an Ollama and Knowledge Engine Stack* (August 2026)

## Decision

Knowledge Engine will **borrow LifeOS architectural primitives, not depend on the LifeOS runtime**.

The AI repository remains provider-neutral and Knowledge Engine-native. LifeOS, ChatGPT, Claude, Codex, a local UI, or another harness may eventually call Knowledge Engine, but none owns Knowledge Engine's research state, evidence store, model routing, or verification policy.

The dependency direction is:

```text
Optional assistant / harness
        |
        v
Knowledge Engine API / CLI
        |
        v
Knowledge Engine AI orchestration
        |
        +--> deterministic tools
        +--> local model providers
        +--> policy-approved cloud providers
```

Never invert this so that Knowledge Engine requires LifeOS internals or Claude-specific lifecycle hooks.

## The primitives we are adopting

### 1. Intent hierarchy: Global intent -> Project intent -> Research ISA

Long-lived research doctrine should not be repeated in every prompt.

- **Global intent** defines Knowledge Engine's stable epistemic principles.
- **Project intent** defines the objective, constraints, and accepted data policy for one research project.
- **Research ISA** (Ideal State Artifact) defines what must be true before one research run may be considered complete.

The initial global principles are:

- separate evidence from inference;
- prefer primary scientific sources when evaluating scientific claims;
- preserve contradictory and qualifying evidence;
- never fabricate citations;
- distinguish absence of evidence from evidence of absence;
- preserve raw provenance;
- expose uncertainty and unresolved questions;
- prefer deterministic computation where it can answer the question reliably.

### 2. Verification is part of intent

A research task is not complete because a model says it is complete.

Each Research ISA contains falsifiable completion criteria and named probes. Examples:

```yaml
criteria:
  - id: ISC-01
    claim: every material scientific assertion is linked to evidence
    probe: orphan_claim_count == 0

  - id: ISC-02
    claim: contradictory evidence was reviewed
    probe: contradiction_review_complete

  - id: ISC-03
    claim: every citation resolves to an immutable evidence record
    probe: citation_integrity_check

  - id: ISC-04
    claim: uncertainty and known evidence gaps are disclosed
    probe: uncertainty_schema_check
```

This extends the existing `ResearchPlan` and verification architecture rather than replacing it.

### 3. Research hill-climbing loop

The orchestrator should converge on a verified state instead of following a brittle prompt script:

```text
current state
    -> explicit ideal state
    -> choose highest-value next action
    -> select typed capability
    -> route by capability + privacy
    -> execute deterministic tools / bounded model work
    -> journal evidence
    -> verify ISA criteria
    -> identify remaining gap or finish
    -> persist learning
```

The model may choose *how* to make progress inside allowed capabilities. Code decides whether completion criteria actually hold.

### 4. Journal before grade

External evidence must be captured before an LLM classifies, ranks, summarizes, or rejects it.

```text
source -> immutable capture -> parse -> normalize -> classify -> relate -> synthesize
```

A parser failure, model failure, or relevance decision must never erase the original capture. Reprocessing with a different extractor or model must remain possible.

### 5. Typed capabilities instead of fuzzy agent skills

Knowledge Engine keeps the useful LifeOS skill pattern but makes it machine-readable.

Each capability should declare:

- intent names;
- version;
- validated input/output schema;
- required capabilities;
- allowed and denied tools;
- data-access permissions;
- consequence level;
- produced artifacts;
- verification probes.

An LLM may infer that a user request maps to `literature_search` or `evidence_synthesis`, but execution occurs only through a registered, validated capability.

### 6. Provider roles, not provider names

No research workflow should require a specific model brand.

Workflows request roles such as:

- `local_fast`
- `local_reasoner`
- `high_reasoning`
- `independent_verifier`
- `embedding`

A policy router maps those roles to an actual provider/model based on measured capability, privacy class, availability, and configured cost policy.

### 7. Local-first, not local-only

Routine, structured, repetitive, and privacy-sensitive work should remain local whenever the configured local model is capable enough.

Potential cloud escalation is allowed only when:

1. task complexity or uncertainty justifies it;
2. project policy allows cloud use;
3. the data classification allows egress;
4. the policy broker approves the exact context sent;
5. provider/model provenance is recorded.

Sensitive or secret material must never be silently routed to cloud models.

### 8. Capability Doctor

Configured capability is not assumed capability.

Knowledge Engine should probe and record whether important runtime features are:

- `verified`
- `degraded`
- `unavailable`
- `disabled`

Initial probes should cover local inference, structured output, tool calling, embeddings, core API access, evidence store, database access, Python/statistics worker, external discovery providers, and optional cloud reasoning.

The distinction between **broken** and **intentionally disabled** is required.

### 9. Hot state plus durable typed memory

The AI layer should keep a small active research-state artifact for the current session, while durable scientific state remains structured and provenance-bearing.

- hot research state: active question, plan, ISA, unresolved gaps, current evidence bundle;
- durable research session: append-only/versioned workflow events;
- scientific evidence and relationships: owned by core;
- reusable decisions/lessons: curated, versioned research memory;
- vector/FTS indexes: rebuildable derivatives, never the source of truth.

### 10. External scientific content is untrusted data

Papers, PDFs, webpages, metadata, supplementary files, repository text, and tool outputs may contain adversarial instructions.

They never acquire instruction authority.

Enforce in code:

- tool allowlists;
- no unrestricted shell for evidence-reading workers;
- no credentials in model-visible context;
- URL/path/domain validation;
- egress policy;
- structured tool parameters;
- output schema validation;
- provenance for every tool-triggering inference;
- human authorization for consequential external actions.

## What we are explicitly not adopting

- LifeOS as a foundational runtime dependency;
- Claude-specific hooks or model routing;
- LifeOS directory conventions;
- natural-language skill routing as the sole execution gate;
- personal-assistant identity/personality machinery;
- Pulse as a near-term priority;
- filesystem-only durable scientific memory;
- a vector database as authoritative state;
- autonomous agent-to-agent debate without evaluation evidence that it improves results.

## Mapping to the existing AI repository

| LifeOS idea | Knowledge Engine AI location | Action |
|---|---|---|
| TELOS-lite | `copilot/intent.py` | add typed global/project intent contracts |
| ISA | `copilot/intent.py` + verification | add falsifiable run completion contract |
| Algorithm | orchestrator workflow | converge on ISA instead of model-declared done |
| Skills | capability registry | future typed registry over existing workers |
| Hooks | verification/policy gates | deterministic pre/post execution gates |
| Cortex hot memory | sessions | active research-state projection |
| Synapse | core evidence ingestion | journal-before-grade invariant |
| Ledger | session events + core provenance | append-only/versioned execution history |
| Doctor | runtime diagnostics | add capability probes |
| model roles | provider router | provider-neutral policy routing |

## Implementation sequence

1. **Intent + ISA contracts** in `copilot/intent.py` with validation tests.
2. Attach a Research ISA to planned research sessions without changing core evidence ownership.
3. Extend verification so an orchestration run can close only when required ISA probes pass or explicitly report an unresolved criterion.
4. Add provider-role and privacy policy contracts.
5. Add capability Doctor probes for Ollama and required KE services.
6. Introduce a typed capability registry around existing retrieval, discovery, statistics, skeptic, and synthesis operations.
7. Add curated learning/decision records after the execution loop is stable and measurable.

## Architectural invariant

> The LLM proposes progress. Deterministic policy controls authority. Evidence records what happened. Verification decides whether the task is done.
