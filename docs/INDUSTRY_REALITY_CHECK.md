# Industry Reality Check — Knowledge Engine AI

**Assessment date:** 2026-08-29  
**Assessment posture:** deliberately critical  
**Product category:** grounded scientific research orchestration / AI-assisted evidence synthesis

## Executive verdict

Knowledge Engine AI has a much stronger trust model than most small RAG/LLM projects. It explicitly refuses to use model memory as scientific authority, requires source-linked evidence, separates deterministic Evidence Intelligence from generated prose, keeps synthesis opt-in, and has begun building golden retrieval and fresh-question workflows.

The repository's main weakness is equally clear: **the product promise is ahead of the completed orchestration path**. The current system can retrieve and narrate indexed evidence, but the general arbitrary-question research loop is still incomplete. Automatic acquisition-to-grounded-extraction, EvidenceRecord promotion, re-retrieval, progressive answer release, latency optimization, provider degradation handling and reuse are still active work. Those are not peripheral features; they are the difference between an indexed-corpus assistant and a true research agent.

### Overall rating: **6.6 / 10**

The repo is architecturally disciplined and evaluation-aware, but it remains an **advanced AI alpha**, not a production research copilot.

## Scorecard

| Area | Score | Reality check |
|---|---:|---|
| Trust architecture / grounding | 8.5 | Strong explicit boundaries; generated text is not allowed to become evidence authority. |
| Retrieval integration | 7.0 | Real Core-backed retrieval exists, but subprocess integration and broader research continuation are limiting. |
| Synthesis quality controls | 7.0 | Citation-required local synthesis is a good foundation. Broader claim-level eval and adversarial testing should deepen. |
| General research orchestration | 5.0 | The intended loop is well specified but still incomplete at critical stages. |
| Evaluation discipline | 7.5 | Golden retrieval and live BT-0 style work are strong signals; end-to-end research quality metrics need expansion. |
| Testing / CI | 8.0 | Ruff, mypy, pytest, pip-audit, secret scanning, golden baseline and fresh-question workflows are solid. |
| Runtime architecture / performance | 5.0 | Per-call Core subprocesses and local Ollama are reasonable alpha choices but not a production architecture. |
| AI safety / robustness | 6.5 | Good no-invention boundaries; prompt injection, poisoned-source, malformed-provider and adversarial evaluation should become explicit. |
| Observability / research telemetry | 5.5 | Bottleneck reporting and funnel instrumentation are active work, not yet mature. |
| Production readiness | 4.5 | Not yet a dependable arbitrary-question research service. |

## What is already professionally strong

### 1. The AI layer is not allowed to invent scientific authority

This is the most important architectural choice in the repository. The LLM can narrate evidence, but does not author EvidenceRecords, evidence directions, relationship truth or opaque confidence percentages. That sharply reduces a common failure mode in LLM research products.

### 2. The system is local-first and explicit about model dependence

Ollama is optional and synthesis is opt-in. Default behavior remains deterministic retrieval. This makes failure modes inspectable and prevents the entire product from becoming unavailable when the model is unavailable.

### 3. The project has started treating AI quality as an evaluation problem

Golden retrieval baselines and fresh-question benchmark workflows are the right direction. Industry-grade AI systems need repeatable scenarios, not screenshots of good answers.

### 4. The arbitrary-question target is written as a stateful research process

The planned states (`indexed_answer`, `research_required`, `partial_answer`, `insufficient_evidence`, `provider_degraded`) are much better than a binary success/failure chat abstraction. That should remain the core product model.

## Where it falls below industry standard

### 1. The general research loop is not closed

The biggest problem is functional, not stylistic.

The intended path is:

`question -> plan -> local retrieval -> adequacy check -> discovery -> acquisition -> extraction/promotion -> re-retrieval -> synthesis -> report`

Open issues #69, #84, #86, #87, #88, #89 and #91 make clear that several middle stages remain incomplete or insufficiently instrumented.

The most serious blocker is the transition from "interesting papers were discovered" to "validated EvidenceRecords now exist and can change the answer." Until that is automated and reliable, the system still depends too heavily on pre-indexed evidence.

### 2. The current Core integration is too process-heavy for production

Every AI call into Core goes through the `ke` CLI subprocess contract. This is disciplined and safe for an alpha, but it imposes startup/process overhead and makes long-running orchestration more cumbersome.

A production system should eventually use a persistent, versioned read-only Core service with:

- stable JSON contracts;
- request/research IDs;
- streaming/progress events;
- cancellation/deadline propagation;
- retry semantics;
- health/readiness;
- compatibility fixtures;
- structured telemetry.

Do not replace the subprocess boundary before measured evidence says it is worth doing, but treat it as transitional.

### 3. AI evaluation needs to go beyond retrieval metrics

Retrieval Recall@K is necessary, but not enough. The AI layer should maintain a permanent evaluation suite for:

- citation precision: does each generated factual statement have the correct source?;
- citation completeness: are unsupported claims present?;
- source-faithfulness / entailment;
- contradiction handling;
- uncertainty language;
- evidence omission;
- inappropriate extrapolation across population/exposure/domain;
- answer-state correctness;
- provider degradation reporting;
- reproducibility across model versions;
- latency and time-to-first-grounded-information.

For scientific use, a shorter incomplete answer with correct sourcing should score higher than a fluent comprehensive answer with one unsupported claim.

### 4. Prompt injection and evidence poisoning need explicit adversarial tests

A research agent ingests external content. That makes source content itself an attack surface.

Add fixtures where papers/pages contain strings such as:

- instructions to ignore system rules;
- fake citation directives;
- malicious JSON-like fragments;
- attempts to overwrite research plans;
- contradictory metadata;
- prompt-like text in abstracts/full text.

The AI layer must always treat source text as untrusted evidence content, never executable instruction.

### 5. Progressive answer behavior is not yet product-complete

The adopted product direction is Draft -> Sourced -> Verified -> Deep. The AI orchestration should support that natively rather than returning one final object after all work completes.

Industry expectation for a long-running research assistant is:

1. immediate normalized question/research state;
2. fast indexed result if available;
3. visible transition to broader research;
4. partial grounded answer when evidence is sufficient for a bounded statement;
5. update/revision as validated evidence arrives;
6. final report with coverage and limitations.

Every revision must preserve citations and make answer maturity explicit.

### 6. Reuse/caching is not yet a first-class research capability

A production research system should not rediscover and reacquire the same paper for every related question. The repository already identifies this, but it needs measurable implementation.

Cache/reuse should be keyed by durable facts such as:

- normalized question/research plan where safe;
- corpus/evidence-store revision;
- provider search-run identity;
- source DOI/content hash;
- acquisition receipt;
- validated EvidenceRecord revision;
- model/prompt version for generated narration.

Never cache generated conclusions across evidence revisions without invalidation.

### 7. Model/version governance should be more formal

Any answer produced by an LLM should be reproducible enough to investigate. Persist or expose:

- model identifier;
- model version/digest where available;
- decoding parameters;
- prompt/template version;
- evidence/context revision;
- synthesis release-gate result;
- timestamp and research-session ID.

Local-first does not remove the need for model governance.

## User-experience standard to aim for

A user should never have to understand the internal split between Core, AI and Web. From the AI layer's perspective, the experience should behave as one durable research session.

Expected behavior:

- Ask a question once.
- Receive a useful immediate state.
- See whether the current answer is indexed-only, partial, verified or deep.
- See why the system is still researching.
- See which providers were searched and which degraded.
- Open every cited source/evidence record.
- Distinguish direct evidence from indirect evidence.
- See missing evidence and uncertainty.
- Revisit the session without restarting the work.
- Ask a related question and benefit from previously validated evidence.

## Highest-priority improvements

### P0 — Complete automatic grounded extraction/promotion and re-retrieval

Issue #87 is the critical path. A newly discovered/acquired paper must be able to become validated evidence and affect the original question without manual paper insertion.

### P0 — Enforce the no-dead-end research state contract

An indexed miss with research enabled must become `research_required`, not a terminal "no papers" answer. Final `insufficient_evidence` is legal only after the bounded research path was actually attempted or explicitly blocked.

### P1 — Build end-to-end benchmark scenarios

Use the Monster Energy case plus unrelated chemistry/materials and clinical questions. Measure cold and warm runs, evidence funnel, provider degradation, time-to-first-grounded-information and final state.

### P1 — Add grounded-generation evals

Create claim-level scoring for citation precision/completeness, entailment, unsupported claims, contradiction handling and uncertainty. Gate synthesis changes on these results.

### P1 — Add adversarial source/prompt-injection evaluation

Treat retrieved documents and provider metadata as untrusted input. Test that source text cannot alter system policy or evidence authority.

### P1 — Add research reuse and cache invalidation

Prove that a repeated/related question reuses search, acquisition and validated evidence while invalidating stale generated outputs when evidence changes.

### P2 — Migrate from subprocess orchestration only when measurements justify it

Once BT-0/BT-5 data proves startup/process cost is material, move to the persistent Core host behind parity-tested contracts.

### P2 — Formalize model/prompt provenance

Make every generated draft traceable to model, prompt version, evidence revision and release gate.

## What would move this above 8/10

- arbitrary unrelated questions reliably trigger and complete bounded research;
- newly discovered sources automatically become validated evidence and are re-retrieved;
- claim-level grounded-generation evals prevent regressions;
- prompt-injection/source-poisoning tests exist;
- progressive Draft -> Sourced -> Verified -> Deep output is durable and resumable;
- repeat research demonstrably reuses prior work;
- model/prompt/evidence versions are traceable;
- latency and provider bottlenecks are measurable;
- persistent Core integration is adopted only after parity and performance proof.

## Bottom line

Knowledge Engine AI has the **right safety philosophy and the right orchestration target**, which puts it ahead of many superficially impressive AI demos. But it is not yet a true general research copilot because the hard middle of the research process is still being completed.

The next milestone that matters is not better prose. It is proving that a fresh question outside the indexed corpus can autonomously become grounded, validated, re-retrieved evidence and then produce a citation-complete answer.