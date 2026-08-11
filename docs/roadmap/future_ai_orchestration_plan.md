# Knowledge Engine — Future AI Orchestration and Multi-Agent Architecture Plan

**Status:** Future architecture and roadmap guidance  
**Date:** 2026-08-08  
**Primary target:** `knowledge-engine-ai`  
**Depends on:** `knowledge-engine-core`, the Evidence Graph, Evidence Intelligence, deterministic statistical verification, and evaluated retrieval

## Purpose

This document defines the long-term AI orchestration layer for Knowledge Engine. The objective is not to create a swarm of autonomous chatbots. The objective is one researcher-facing **Research Copilot** that decomposes a research problem into bounded tasks, delegates those tasks to specialized reasoning or deterministic workers, verifies their outputs, preserves provenance, and returns source-linked synthesis with visible uncertainty.

The mature system should help a researcher search broadly across scientific domains, turn an imprecise question into an explicit research plan, retrieve evidence, identify support/contradiction/qualification/context, compare PICO and methods, perform deterministic statistical checks, identify unknowns, explain disagreement, preserve durable investigations across sessions, incorporate new evidence without rewriting history, distinguish evidence from reference knowledge, cite every material scientific claim, disclose coverage limits, and eventually suggest testable hypotheses without presenting speculation as fact.

> **Knowledge Engine does not decide scientific truth. It organizes, evaluates, compares, and explains evidence while preserving disagreement, uncertainty, provenance, and unknowns.**

## Architectural Decision — One Copilot, Many Internal Capabilities

The user interacts with one **Research Copilot**. Specialized agents are internal implementation components, not separate personalities.

```text
Researcher
    |
    v
Research Copilot
    |
    +---- Search
    +---- Analyze
    +---- Compare
    +---- Statistics
    +---- Evidence
    +---- Discover
    +---- Teach
```

Internal architecture:

```text
                           USER QUESTION
                                 |
                                 v
                        RESEARCH COPILOT
                    Intent + scope + planning
                                 |
                         RESEARCH PLAN
                                 |
        +------------------------+------------------------+
        |                        |                        |
        v                        v                        v
   RETRIEVAL                DISCOVERY               REFERENCE
   WORKERS                  WORKERS                 WORKERS
        |                        |                        |
        +------------------------+------------------------+
                                 |
                          EVIDENCE BUNDLE
                                 |
            +--------------------+--------------------+
            |                    |                    |
            v                    v                    v
      EVIDENCE ANALYST     STATISTICS AUDITOR   SKEPTIC WORKER
            |                    |                    |
            +--------------------+--------------------+
                                 |
                       VERIFICATION / AUDIT
                                 |
                        SYNTHESIS COMPOSER
                                 |
                       CITATION / CLAIM AUDIT
                                 |
                                 v
                         USER-FACING REPORT
```

The workflow is typed and inspectable. Agent prose is never authoritative state.

## Core Design Rule — Workflow First, Agents Second

Knowledge Engine should define research operations as typed workflows. An LLM worker is only one possible executor for a workflow node.

| Workflow task | Preferred executor |
|---|---|
| DOI validation | deterministic code |
| arithmetic verification | deterministic code |
| database lookup | deterministic code |
| citation graph traversal | deterministic code |
| PICO grounding verification | deterministic code |
| query interpretation | local LLM |
| research-plan generation | local LLM + schema validation |
| disagreement explanation | LLM over structured evidence |
| synthesis narration | LLM over verified evidence |
| source citation audit | deterministic first, optional LLM second |
| hypothesis generation | LLM, strongly gated and explicitly speculative |

> **Never use an agent where deterministic code can provide the same result more reliably.**

## Durable Research Workflow State

The central orchestration object should be a durable `ResearchSession`.

```text
ResearchSession
├── session_id
├── created_at
├── updated_at
├── user_question_original
├── normalized_question
├── scope
├── domain_hints
├── research_plan_version
├── evidence_cutoff_time
├── corpus_snapshot_id
├── retrieval_runs[]
├── discovery_runs[]
├── reference_lookups[]
├── evidence_sets[]
├── analyses[]
├── statistical_checks[]
├── contradiction_checks[]
├── gap_assessments[]
├── verification_results[]
├── syntheses[]
├── user_decisions[]
├── unresolved_questions[]
├── workflow_events[]
└── final_status
```

Every important action becomes an append-only or versioned event.

```text
ResearchEvent
├── event_id
├── session_id
├── timestamp
├── workflow_node
├── executor_type
├── model_name
├── model_version
├── prompt_template_version
├── tool_name
├── tool_version
├── inputs_hash
├── source_ids[]
├── output_schema_version
├── output_hash
├── validation_status
├── retry_of
├── parent_event_ids[]
└── notes
```

This becomes the basis for reproducibility, debugging, auditability, and research continuation.

## Research Plan Contract

The Orchestrator should produce a typed `ResearchPlan`, not free-form instructions passed between agents.

```json
{
  "question": "Does semaglutide produce clinically meaningful long-term weight loss?",
  "intent": "evidence_synthesis",
  "domain": "clinical_medicine",
  "subquestions": [
    "What randomized evidence measures long-term body-weight change?",
    "How durable is weight loss during continued treatment?",
    "What happens after discontinuation?",
    "What important safety or tolerability qualifiers exist?"
  ],
  "required_capabilities": {
    "corpus_retrieval": true,
    "external_discovery": true,
    "pico_comparison": true,
    "contradiction_search": true,
    "statistics": true,
    "lifecycle_check": true,
    "reference_context": false
  }
}
```

The schema is validated before execution. The Copilot proposes the plan; deterministic policy controls what actually runs.

## Internal Capabilities

### Orchestrator / Research Planner

Converts the question into intent, scope, subquestions, search strategy, required capabilities, dependencies, budgets, and stop conditions.

It may create/revise a `ResearchPlan`, choose registered capabilities, and request bounded jobs. It may not alter canonical Evidence Records, invent scientific results, compute confidence directly, bypass validation, execute arbitrary shell commands, or decide scientific truth.

First implementation: local LLM -> strict schema -> validator -> execution policy.

### Retrieval Intelligence Worker

Searches the existing Knowledge Engine evidence pool through FTS, semantic/vector retrieval, citation graph, Evidence Records, relationship graph, and lifecycle metadata.

```text
RetrievalResultSet
├── query
├── retrieval_method
├── corpus_snapshot
├── records[]
├── rank_features
├── retrieved_at
└── retrieval_trace
```

Retrieval quality must be evaluated independently from synthesis quality. A beautiful answer over bad retrieval is a system failure.

### External Discovery Worker

Searches scientific providers for evidence absent from the current corpus. Existing or likely providers include PubMed/PMC, Europe PMC, CORE, Unpaywall, and future domain-specific indexes.

Discovery does not silently promote records:

```text
discovered
 -> identity-resolved
 -> license-evaluated
 -> acquisition-approved / held / rejected
 -> acquired
 -> validated
 -> corpus-eligible
```

Agent judgment never bypasses identity, legal/reuse, or validation checks.

### Reference Knowledge Worker

Retrieves background terminology or mechanisms from sources such as MeSH, RxNorm, PubChem, Wikipedia, and future open-license textbooks.

Reference material may explain terminology, normalize entities, expand queries, or support teaching. It must never be silently counted as evidence supporting a research claim.

Preserve source classes such as `reference`, `primary_evidence`, and `secondary_evidence`.

### Evidence Analyst

Compares structured evidence on PICO overlap, population, intervention, comparator, endpoint, follow-up duration, study design, direction, limitations, applicability, and methodology.

It should consume structured Evidence Records and source spans wherever possible rather than unrestricted raw internet text.

```text
EvidenceComparison
├── compared_records[]
├── shared_features
├── important_differences
├── supporting_patterns
├── qualifying_patterns
├── conflicting_patterns
├── missing_information
├── source_links
└── assessment_limitations
```

Natural-language explanation is generated only after the comparison object validates.

### Skeptic / Adversarial Evidence Worker

This capability should be first-class. It assumes the emerging interpretation may be incomplete or wrong and deliberately searches for the strongest evidence that would weaken, narrow, qualify, or contradict it.

Search for direction-reversing evidence, subgroup conflicts, alternate comparators/populations, withdrawal effects, duration effects, methodological disagreement, negative replication, corrections/retractions, changed standards, and evidence missed by the primary strategy.

Required behavior:

> Search for the strongest evidence that would weaken, narrow, qualify, or contradict the emerging interpretation. Do not manufacture disagreement. Return "no aligned contradictory evidence found within the searched scope" when appropriate.

Absence of discovered contradiction is not proof that none exists.

## Analytical Intelligence

### Statistics Auditor

The Statistics Auditor remains deterministic wherever possible.

Potential capabilities include arithmetic reproduction, mean differences, risk ratios, odds ratios, risk differences, confidence intervals, standardized mean differences, responder percentages, ARR/NNT where valid, consistency checks, unit normalization, and reported-versus-recomputed comparison.

```text
source-audited numeric inputs
            |
            v
    deterministic formula
            |
            v
    reproduced statistic
            |
            v
 comparison to reported result
            |
            v
       verification status
```

Suggested statuses: `exactly_verified`, `compatible_with_rounding`, `approximation_only`, `insufficient_inputs`, `non_equivalent_estimand`, `mismatch_detected`, `display_only`.

The LLM may explain these states. It does not calculate them.

### Cross-Study Analytical Worker

Future work after statistical readiness is adequate. Responsibilities include detecting compatible estimands, pooling compatibility, effect-magnitude comparison, scientifically justified unit normalization, sensitivity analysis, and eventually meta-analysis only when prespecified compatibility rules pass.

Meta-analysis is a deterministic analytical workflow with explicit protocol, assumptions, and provenance, never an automatic agent behavior.

## Evidence Intelligence and Confidence Framework

Keep these concepts distinct.

### Evidence Quality

How trustworthy is the individual evidence source or record? Inputs may include study design, extraction rigor, domain-appropriate sample size, limitations, risk-of-bias signals, statistical verification, source integrity, and replication context.

### Evidence Consensus

How consistently does relevant evidence agree? Consensus must account for study independence, duplicate reports, quality weights, PICO compatibility, direction, qualification, and contradiction. Ten weak duplicate analyses must not outweigh one strong independent study merely by count.

### Claim Confidence

Given quality, consensus, coverage, stability, recency, applicability, and uncertainty, how strongly does the available evidence support this specific claim?

This is an **Evidence Confidence score**, not a literal probability that a claim is true.

Correct:

```text
Evidence Confidence: 82/100
Assessment reliability: Moderate
```

Incorrect:

```text
82% chance the claim is true
```

### Evidence Coverage

Every synthesis should eventually disclose how much relevant evidence is held locally, whether external discovery was performed, estimated completeness where defensible, cutoff time, and known gaps.

The Knowledge Engine corpus is not identical to the scientific literature.

## Discovery Intelligence

Discovery Intelligence comes after reliable Retrieval, Evidence Intelligence, and Analytical Intelligence.

### Contradiction Explainer

Move beyond support/contradiction counts and investigate whether disagreement tracks population, dosage, duration, comparator, baseline disease state, endpoint definition, statistical methodology, experimental method, time period, or technology generation.

Characterize disagreement without pretending to resolve it automatically.

### Unknowns Engine

Unknowns should become first-class objects.

```text
KnowledgeGap
├── gap_id
├── research_question
├── gap_type
├── affected_claims[]
├── evidence_basis[]
├── why_gap_exists
├── what_evidence_would_reduce_it
├── priority
├── expected_information_gain
├── generated_at
└── provenance
```

Gap types may include no evidence, weak evidence, conflicting evidence, narrow-population evidence, missing replication, outdated evidence, missing long-term follow-up, missing mechanism, missing comparative evidence, or unresolved methodological disagreement.

### Hypothesis Generator

Late-stage only. Hypotheses must never enter the evidence graph as evidence.

```text
HypothesisCandidate
├── hypothesis
├── rationale
├── supporting_observations[]
├── contradicting_observations[]
├── missing_evidence[]
├── falsifiable_prediction
├── proposed_test
├── novelty_basis
├── uncertainty
└── status = speculative
```

The UI must visibly separate **Known evidence** from **Machine-generated hypothesis**.

## Education Intelligence

Education should reuse the same evidence infrastructure rather than build a second factual system. Future functions include "Teach me about X," adjustable explanation depth, prerequisite maps, glossary generation, evidence-linked examples, misconception identification, guided paper reading, and adaptive learning paths.

Simplify explanation without simplifying provenance away.

## Default Agent Execution Pattern

```text
PLAN
  |
  v
PARALLEL EVIDENCE GATHERING
  |
  +--> corpus retrieval
  +--> external discovery
  +--> contradiction search
  +--> reference lookup
  |
  v
MERGE STRUCTURED RESULTS
  |
  v
ANALYZE
  |
  +--> evidence comparison
  +--> statistics
  +--> lifecycle
  |
  v
SKEPTIC PASS
  |
  v
SOURCE / CLAIM AUDIT
  |
  v
SYNTHESIS
  |
  v
FINAL CITATION AUDIT
```

Do not default to endless agent-to-agent conversation. Debate or evaluator/optimizer loops should be used only when evaluation demonstrates measurable improvement.

## Local Model Router

Maintain a provider-neutral model interface.

```text
ModelRouter
├── classify(task)
├── estimate_required_capability(task)
├── choose_model(task, policy)
├── execute()
└── record_model_provenance()
```

Routing hierarchy:

```text
Can deterministic code do it?
        |
       yes -> deterministic execution
        |
       no
        v
Can the smallest local model do it reliably?
        |
       yes -> small local model
        |
       no
        v
Use stronger local model
        |
       insufficient
        v
Optional configured external provider
```

Record provider, model, model version/digest when available, generation settings, prompt-template version, input/output hashes, latency, and token counts where available.

This preserves a $0 local path while keeping future public inference replaceable.

## Durable Workflow Engine

A future multi-agent system must be resumable. Required characteristics include checkpoints, idempotency, retries, explicit task states, no duplicate side effects, crash/reboot continuation, parent/child linkage, bounded concurrency, bounded recursion, cancellation, failure propagation, and partial-result preservation.

Suggested states:

```text
pending
running
blocked
awaiting_input
awaiting_approval
completed
failed
cancelled
superseded
```

The first implementation does not require Kubernetes. Lightweight Python orchestration plus SQLite is sufficient until scale proves otherwise.

## Tool Permission Model

Every worker receives an allowlisted tool set.

```text
Retriever:
    READ corpus
    READ evidence
    READ graph
    NO WRITE

Discovery:
    READ external providers
    WRITE temporary candidate objects
    NO canonical evidence mutation

Statistics:
    READ verified numerical inputs
    EXECUTE allowlisted formulas
    WRITE verification records
    NO arbitrary code execution

Composer:
    READ validated analysis
    NO external network
    NO canonical writes
```

Consequence levels:

- Level 0 — pure computation
- Level 1 — read-only
- Level 2 — reversible bounded write
- Level 3 — canonical mutation
- Level 4 — external consequential action

Default policy: Level 0/1 autonomous; Level 2 autonomous only in bounded workspace; Level 3 schema/rule gated and provenance-preserving; Level 4 explicit human authorization.

## Prompt Injection and Untrusted Scientific Content

Scientific papers, websites, metadata, PDFs, supplemental files, and tool outputs are **untrusted data**.

Required controls:

1. structural separation between instructions and retrieved content;
2. tool allowlists;
3. no unrestricted shell/network tool for evidence-reading workers;
4. no credentials in model-visible context;
5. tool output treated as untrusted input;
6. validate all tool-call parameters;
7. domain/path allowlists for sensitive tools;
8. output schema validation;
9. red-team indirect prompt injection;
10. log the originating evidence/source for tool-triggering inference.

A scientific source can provide data to an agent but can never grant it new authority.

## Verification Pipeline

Every generated research answer should eventually pass layered verification.

### Layer A — Structural Validation

Validate schema, IDs, citations, source spans, numeric units, and enums.

### Layer B — Grounding Validation

For each material claim, identify supporting Evidence Record IDs, locate source spans, verify factual basis, and reject unsupported additions.

### Layer C — Contradiction Check

Check whether synthesis omitted material contradiction, lost qualifiers, erased population boundaries, or overstated confidence.

### Layer D — Citation Audit

Every material scientific assertion maps to one or more valid sources.

```text
claims_total: 14
claims_grounded: 14
claims_missing_citation: 0
unsupported_claims: 0
material_contradictions_omitted: 0
status: PASS
```

## Evaluation Framework

Evaluation is mandatory architecture, not optional QA.

### Retrieval

Measure Recall@K, Precision@K, nDCG, MRR, Evidence Record coverage, citation retrieval, and contradictory-evidence recall.

### Extraction

Measure PICO precision/recall, grounding rate, study-type classification, limitation extraction, and hallucinated-field rate.

### Synthesis

Measure claim grounding, citation correctness, citation completeness, contradiction preservation, qualifier preservation, unsupported assertion rate, and uncertainty calibration.

### Workflow

Measure task success, tool-choice correctness, unnecessary calls, loops/retries, latency, local compute, cloud fallback rate, recovery after failure, and reproducibility.

### Adversarial

Test prompt injection in PDFs, malicious metadata, contradictory source text, malformed provider responses, duplicate sources, retractions, citation mismatch, corrupt numerical values, and poisoned reference content.

No new agent capability becomes default until it passes a defined evaluation set.

## Observability

Every workflow should be traceable.

```text
research.session
research.plan
retrieval.query
discovery.query
evidence.compare
agent.run
model.generate
tool.call
guardrail.check
statistical.verify
grounding.verify
synthesis.generate
citation.audit
workflow.retry
```

Capture duration, status, model, tool, retries, source counts, token counts where available, context size, cache hit/miss, validation result, and errors. Prefer OpenTelemetry-compatible conventions where practical.

## Research Memory

Do not implement memory as a giant transcript pasted into prompts.

Separate session memory, user research preferences, scientific memory, and decision memory. Scientific facts remain in Evidence Records, graph relationships, verified analytics, and source documents. Model-generated summaries are regenerable views, not canonical facts.

## Caching

Candidate cache key:

```text
hash(
    task_type,
    model,
    model_version,
    prompt_template_version,
    normalized_inputs,
    evidence_snapshot
)
```

Cache query decomposition, embeddings, reference lookups, grounded extraction results, comparison objects, and other deterministic/reproducible intermediate results. Do not blindly reuse synthesis when the evidence snapshot changes.

## Public Deployment Architecture

Development:

```text
Laptop
 |
 +-- core
 +-- AI
 +-- web
 +-- Ollama
 +-- SQLite
```

Future durable deployment:

```text
Public Web
    |
    v
Application API
    |
    +---- read-only evidence service
    |
    +---- orchestration service
              |
              +---- local/private model endpoint
              +---- optional cloud model endpoint
              +---- worker queue
              +---- research-session store
```

The raw Ollama port should not be exposed directly to the public internet. The orchestration service owns authentication, rate limits, job limits, permissions, model routing, tracing, cancellation, and timeouts.

# Design Block Register

These are architectural constraints, not reasons to stop the project.

## BLOCK 1 — Multi-agent error compounding

**Problem:** one worker's subtle error can be amplified downstream.

**Wrong response:** add more agents and assume voting creates truth.

**Required design:** structured outputs, independent verifier source access, deterministic validators, skeptic pass, intermediate provenance, and no model prose treated as evidence.

**End-state rule:** scientific assertions remain traceable to evidence, never agent authority.

## BLOCK 2 — Prompt injection from scientific documents

**Problem:** retrieved content can contain model-directed malicious text.

**Required design:** data/instruction separation, least privilege, no unrestricted execution, parameter validation, audit logging, and adversarial tests.

**End-state rule:** a source can provide data but never new authority.

## BLOCK 3 — Local AI is not durable public infrastructure

**Problem:** Ollama on a laptop is excellent for development/private use but not reliable multi-user public serving.

**Required design:** keep a provider-neutral protocol such as `ModelProvider` / `LocalLLM`; later support local/private remote and optional cloud implementations.

**Trigger to revisit:** measured users, concurrency, latency target, operating cost, and privacy/security requirements.

## BLOCK 4 — Context-window growth

**Problem:** thousands of papers cannot be dumped into one prompt.

**Required design:** hierarchical reduction:

```text
sources -> Evidence Records -> comparison objects -> evidence clusters -> verified findings -> synthesis
```

Preserve identifiers and provenance at every stage.

## BLOCK 5 — Corpus coverage can masquerade as consensus

**Problem:** agreement inside the corpus may reflect missing contrary literature.

**Required design:** display Coverage separately from Consensus; optionally perform external discovery and contradiction-oriented retrieval; disclose cutoff and corpus snapshot.

## BLOCK 6 — One cross-domain evidence-quality rubric is invalid

**Problem:** clinical medicine, chemistry, physics, psychology, engineering, and ML do not share one defensible scoring formula.

**Required design:** common framework dimensions plus versioned domain-specific quality profiles based on field-native standards and validated against real corpus data.

## BLOCK 7 — Scientific relationship generation can become circular

**Problem:** AI-authored graph edges can become self-reinforcing if later treated as independent evidence.

**Required design:** every relationship stores generation method, endpoints, rationale, confirmation state, and model/tool provenance. Machine-generated relationships are never independent evidence votes.

## BLOCK 8 — Canonical evidence mutation

**Problem:** autonomous rewrites of Evidence Records threaten reproducibility.

**Required design:** append/version/promote workflows. AI proposes `CandidateEvidenceRevision`; grounding/schema gates control promotion; prior versions remain recoverable.

## BLOCK 9 — Evaluation drift

**Problem:** changing model, prompt, ranking, embedding, or tools can improve one task while degrading another.

**Required design:** versioned benchmark suites with before/after retrieval, grounding, citation, contradiction recall, latency, and resource metrics.

## BLOCK 10 — Non-deterministic research continuation

**Problem:** interrupted workflows may restart differently or duplicate work.

**Required design:** durable Research Sessions, checkpoints, task IDs, idempotency, and explicit retry lineage. Chat transcript alone is never execution state.

## BLOCK 11 — Cost explosion

**Problem:** agent fan-out can multiply model calls dramatically.

**Required design:** deterministic-first routing, smallest adequate local model, hard call budgets, bounded fan-out, caching, stop conditions, opt-in cloud fallback, and per-session resource accounting.

## BLOCK 12 — Autonomous hypothesis generation can outrun evidence quality

**Problem:** plausible hypotheses are easy to generate before the evidence graph is mature.

**Required design:** gate Discovery Intelligence on retrieval quality, corpus coverage, relationship coverage, Evidence Intelligence maturity, and Analytical Intelligence maturity. Hypotheses remain speculative.

## BLOCK 13 — Memory poisoning

**Problem:** bad interpretations saved as durable memory contaminate future sessions.

**Required design:** scientific memory resolves to sources, Evidence Records, verified graph objects, and analytical records. Model summaries are regenerable views.

## BLOCK 14 — Duplicate evidence and pseudo-replication

**Problem:** one study may appear as multiple papers, follow-ups, reviews, or analyses and be counted as independent support.

**Required design:** distinguish document identity, study identity, trial identity, dataset identity, and analysis identity where possible. Consensus counts independent evidence units, not raw documents.

## BLOCK 15 — Publication bias cannot be solved from papers alone

**Problem:** missing studies may be invisible.

**Required design:** report detectable indicators or registry/publication mismatch where available, but never conclude "no publication bias" merely because none was detected.

## BLOCK 16 — Framework lock-in

**Problem:** agent frameworks evolve rapidly.

**Required design:** Knowledge Engine owns its domain contracts: `ResearchPlan`, `ResearchTask`, `ResearchEvent`, `EvidenceBundle`, `VerificationResult`, and `SynthesisResult`. Framework adapters execute them. Do not let LangGraph, AutoGen, OpenAI Agents SDK, or any one orchestration package become Knowledge Engine's schema.

## Security Architecture

Adopt a threat model before allowing write-capable agents. Threat surfaces include user input, retrieved papers, PDFs, OCR, metadata, external results, MCP/tool servers, model providers, workflow state, agent memory, logs, credentials, and graph writes.

Controls include least privilege, explicit trust boundaries, sandboxing for code execution, secrets outside prompts, source validation, output schemas, approval for irreversible actions, audit logs, versioned workflow definitions where appropriate, dependency scanning, and a red-team corpus.

## Framework Strategy

Do not commit immediately to a large orchestration framework.

### Phase A — Native Python orchestration

Use dataclasses/Pydantic, `asyncio`, task groups, SQLite, and existing provider protocols to prove the Knowledge Engine-specific workflow.

### Phase B — Evaluate orchestration frameworks

Evaluate only after durable workflow requirements are concrete. Candidates may include LangGraph-style persistent state graphs, OpenAI Agents SDK-style handoffs/structured tools/guardrails/tracing, AutoGen-style event-driven workers, or a general durable workflow engine if execution becomes operationally complex.

Selection criteria: local/open-model support, provider neutrality, checkpointing, structured outputs, observability, human-in-the-loop, async/concurrency, recoverability, minimal lock-in, and security model.

## Suggested Future Package Layout

```text
knowledge_engine_ai/
├── copilot/
│   ├── orchestrator.py
│   ├── planner.py
│   └── policies.py
├── workflows/
│   ├── research.py
│   ├── compare.py
│   ├── analyze.py
│   ├── contradict.py
│   ├── discover.py
│   └── teach.py
├── workers/
│   ├── retrieval.py
│   ├── discovery.py
│   ├── evidence.py
│   ├── skeptic.py
│   ├── statistics.py
│   ├── verifier.py
│   └── composer.py
├── models/
│   ├── provider.py
│   ├── router.py
│   └── ollama.py
├── sessions/
│   ├── models.py
│   ├── repository.py
│   └── events.py
├── verification/
│   ├── grounding.py
│   ├── citations.py
│   └── claims.py
├── telemetry/
│   ├── tracing.py
│   └── metrics.py
├── security/
│   ├── permissions.py
│   ├── guardrails.py
│   └── trust.py
├── evals/
│   ├── retrieval.py
│   ├── synthesis.py
│   ├── agents.py
│   └── adversarial.py
└── cli.py
```

Do not scaffold all of this immediately. Create modules when the second real implementation requires them.

## Suggested Future CLI

```text
ke-ai ask QUESTION
ke-ai research QUESTION
ke-ai compare RECORD...
ke-ai contradict QUESTION
ke-ai analyze SESSION_ID
ke-ai verify SESSION_ID
ke-ai session show SESSION_ID
ke-ai session continue SESSION_ID
ke-ai session export SESSION_ID
ke-ai eval retrieval
ke-ai eval synthesis
ke-ai eval workflow
```

## Implementation Roadmap

### AI-O1 — Research Plan Contract

Build `ResearchPlan`, task types, execution policy, structured planner output, and schema validator. No autonomous tools yet.

**Success criterion:** a question is reliably converted into an inspectable bounded plan.

**Status (2026-08-09): contracts and validator built.** `ResearchPlan`/
`ResearchTask`, the `TaskType` enum, the `ConsequenceLevel`/
`ExecutionDecision` execution policy, and `validate_research_plan()`/
`parse_research_plan()` are implemented in `knowledge_engine_ai/copilot/`
-- see `docs/ai_o1_design.md`. What exists is the inspectable, validated
*shape* a plan must have, plus a test suite proving the validator
actually catches malformed plans (duplicate task IDs, unresolved/cyclic
dependencies, understated consequence levels, capability/task
mismatches) -- the prerequisite AI-O2/AI-O3/AI-O4 build on, not those
milestones themselves. AI-O4 (below) is what converts a real question
into a plan against this same validator.

### AI-O2 — Durable Research Session

Build session persistence, event log, checkpointing, and continuation.

**Success criterion:** a workflow can stop and resume without losing or duplicating state.

**Status (2026-08-09): success criterion met and verified.**
`ResearchSession`/`ResearchEvent` and a SQLite-backed
`SessionRepository` are implemented in `knowledge_engine_ai/sessions/`
-- see `docs/ai_o2_design.md`. `create_session`/`append_event` raise
typed errors (`DuplicateSessionError`/`DuplicateEventError`) on a
re-used ID instead of silently duplicating a row, and a test exercises
the actual success criterion end to end: create a session, append an
event, close the database connection entirely (simulating a crash),
open a fresh connection against the same file, check before
re-appending, append a new event, and confirm the final event log has
no duplicates and preserves append order. No orchestrator, no LLM
call, and no real workflow node connects to this yet -- that is AI-O3.

### AI-O3 — Deterministic Orchestrator

Connect existing core retrieval, Evidence Intelligence, evidence-map, and statistical-verification capabilities using fixed workflow rules.

**Success criterion:** one session can call multiple existing Knowledge Engine capabilities and assemble structured results without an LLM dynamically deciding execution.

**Status (2026-08-10): success criterion met and live-verified.**
`knowledge_engine_ai/orchestrator/workflow.py`'s `run_fixed_evidence_workflow`
runs a hardcoded step sequence (retrieval + Evidence Intelligence always;
evidence-map and statistical-verification only when the caller supplies
their required curated inputs) against an already-created AI-O2
`ResearchSession`, appending one `ResearchEvent` per step whether it
succeeds or fails. Two new `ke_client.py` wrappers
(`evidence_map_report`/`statistical_verify`) added for this -- neither
`ke evidence-map-report` nor `ke statistical-verify` has a `--format
json` mode, so both return their rendered Markdown verbatim. Live-verified
against the real GLP-1 corpus with `core`'s actual `ke` executable (not
mocked): all three steps succeeded end to end, each producing a real,
non-null `output_hash`. See `docs/ai_o3_design.md`. No LLM call, no
`ResearchPlan` consumption yet (that connection is AI-O4's job, sitting
above this module), no retry logic.

### AI-O4 — Local Query Planner

Add LLM plan generation behind schema validation.

**Success criterion:** natural-language questions reliably map to bounded workflow plans.

**Status (2026-08-10): success criterion live-verified against a real
Ollama server.** `knowledge_engine_ai/copilot/planner.py`'s
`plan_from_question` prompts a local model for a `ResearchPlan` JSON
object, extracts it with a brace-balanced scan (survives markdown-fence
wrapping and surrounding prose), force-overwrites `plan_id`/`created_at`
with the values it generated (never trusts the model's echo of those two
fields), and runs the result through AI-O1's unmodified
`parse_research_plan`/`validate_research_plan`. Raises `PlannerError`
with the raw model output attached on any parse or validation failure --
no retry, no repair. Live-verified with a real, running `ollama serve`
process (not mocked): 3 of 3 real questions, one per this project's
three corpus domains, each produced a schema-valid plan with a correctly
domain-matched `domain` field on the first attempt (39-49 seconds each
against `qwen2.5:1.5b` on CPU-only hardware). `qwen3:4b` was tried first
and found unusable in this environment at default settings -- its
hybrid-reasoning "thinking" tokens consumed the entire response budget
before producing an answer, and a full-length run exceeded `OllamaLLM`'s
120-second default timeout. See `docs/ai_o4_design.md` for the full
verification record, including what a 3-question sample does and does
not establish. No orchestrator wiring yet -- AI-O3's fixed workflow does
not consume a produced plan's `tasks`; that connection remains future
work.

### AI-O5 — Parallel Retrieval + Contradiction Search

Run primary retrieval, contradiction-oriented retrieval, and optional external discovery in parallel.

**Success criterion:** measured contradiction recall improves without materially reducing precision.

**Status (2026-08-11): mechanism implemented and live-verified; a real,
substantial recall gain measured at sufficient retrieval depth.**
`knowledge_engine_ai/orchestrator/parallel_retrieval.py`'s
`run_parallel_retrieval` widens AI-O3's single always-run retrieval step
into two, run concurrently via a thread pool: the unmodified question
(primary) and the same question with `core`'s own already-validated
same-PICO-contradiction-audit negative-signal phrase set appended
(contradiction-oriented) -- no new `core`-side capability, no LLM call,
matching AI-O3's "no LLM dynamically deciding execution" precedent.
Each branch's `KeCommandError` is caught independently, never aborting
its sibling; the concrete recall signal
(`contradiction_only_evidence_record_ids`, a real set difference) is
computed and exposed on the result. `run_fixed_evidence_workflow`
records both branches as separate `ResearchEvent`s. Live-verified
against `core`'s real GLP-1 and oncology corpora with the actual `ke`
executable, at two retrieval depths for the oncology check: the
mechanism runs correctly end to end throughout. GLP-1 (`--limit 5`) and
oncology at a shallow window (`--limit 8`) both found zero recall
gain -- the GLP-1 result matches `core`'s own GLP-1 same-PICO
contradiction audit finding no contradiction exists in that corpus (a
correct null result, not a mechanism failure), while the shallow
oncology check simply did not reach deep enough. Oncology at a deeper
window (`--limit 20`) told a materially different story: 63 primary IDs
vs. 145 contradiction IDs, with 121 contradiction-only (net-new) against
only 37 lost -- a real, substantial recall gain, roughly 3.3x net-new
records vs. lost. Retrieval depth, not just query wording, turned out to
materially change whether the gain is visible at all. Whether those 121
net-new records are disproportionately genuine contradiction candidates
(vs. simply more records from a less-selective query) was not manually
spot-checked and remains named, explicit follow-up work -- see
`docs/ai_o5_design.md`'s "what this does not establish" section. A real
recall/precision benchmark needs a labeled question/
known-contradiction dataset this project does not yet have; building
one is named as follow-up work, not attempted here. Optional external
discovery is an injectable callable, deliberately left unwired to any
concrete `core` capability -- `ke discovery-cycle-run`'s persisted
pagination-offset semantics do not fit a per-question, in-session call
(see the design doc). A real, narrow concurrency defect was found and
worked around during verification: two `ke` subprocesses racing to
apply the same pending schema migration to the same on-disk SQLite file
on first concurrent use (`database is locked`); resolved by warming the
database with one serial call first, documented rather than
silently patched with speculative retry logic.

### AI-O6 — Skeptic + Verifier

Add independent verification.

**Success criterion:** unsupported-claim and missed-qualifier rate is lower than direct synthesis baseline.

### AI-O7 — Research Session Synthesis

Generate a final report from validated structured objects.

**Success criterion:** every material scientific claim resolves to evidence IDs and source citations.

**Status (2026-08-11): implemented and live-verified.** New
`knowledge_engine_ai/orchestrator/session_report.py`: `build_session_report`
resolves each `[evidence_record_id]` citation a `synthesis.py` narrative
actually makes into a `SourcedClaim` carrying the containing paper's real
title, authors, year, DOI, citation string, and source URL -- a join from
evidence-record-level citation up to paper-level bibliography no earlier
module performed. Takes AI-O6's already-computed `VerificationResult` as
a parameter rather than recomputing it, so `unresolved_citations` is
exactly AI-O6's `hallucinated_citations`, and `is_fully_sourced` is a
simple derived fact. Live-verified by resolving the real narrative and
`EvidenceReport` AI-O6's own live check already captured: both of the
narrative's real citations resolved to their correct source papers (with
real DOIs), zero unresolved citations, `is_fully_sourced=True`. See
`docs/ai_o7_design.md`.

### AI-O8 — Model Router

Benchmark local models on planning, extraction, evidence comparison, synthesis, and citation compliance.

**Success criterion:** use the smallest model meeting task-quality thresholds.

**Status (2026-08-11): implemented and live-verified.** New
`knowledge_engine_ai/model_benchmark.py`: `run_model_benchmark` runs
role-tagged `BenchmarkTask` probes -- reusing AI-O1/AI-O4's
`validate_research_plan`/`plan_from_question` for planning and AI-O6's
`verify_synthesis` for synthesis/citation-compliance, not a new scoring
method -- against each candidate model; `recommend_models_by_role`
returns the smallest candidate that passed every task for a role.
`provider_specs_from_benchmark` feeds a recommendation into PR #16's
just-merged `routing.py` (`ProviderSpec`/`select_provider`) rather than
building a second routing mechanism. Extraction and evidence-comparison
benchmarking are out of scope for this slice -- neither has an
LLM-based worker in this project yet to benchmark. Live-verified against
both models pulled in this environment: `qwen2.5:1.5b` passed both
probes; `qwen3:4b` failed both (planning timed out at 300s; synthesis
returned empty because its "thinking" tokens consumed the response
budget), turning AI-O4's prior anecdotal finding into a reproducible
benchmark result. A real timeout-tuning artifact (a too-tight 120s
default made even the passing model appear to fail on a cold model
load) was found and corrected during verification. See
`docs/ai_o8_design.md`.

### AI-O9 — Observability + Budgeting

Add workflow tracing and resource metrics.

**Success criterion:** every session can answer what ran, why, what model/tool was used, where time was spent, what failed, and what evidence supported the output.

**Status (2026-08-11): implemented and live-verified.** Closed two real
gaps in AI-O2's `ResearchEvent` (no duration field; `source_ids` never
populated) additively, then added
`knowledge_engine_ai/orchestrator/observability.py`:
`build_session_trace`/`render_session_trace` project a session's
existing event log into an answer to all six success-criterion
questions -- a read-side reporting layer over AI-O2's store, not a new
one. "Why" is answered at the session level (the original question),
since no per-step reasoning data exists in this project yet.
Budgeting/cost metrics beyond wall-clock duration are named as explicit
follow-up, since nothing here tracks a cost unit today. Live-verified
against the real GLP-1 corpus with all four fixed workflow steps: all
six trace sections rendered with real data, including 4 real
evidence-record IDs surfaced via `source_ids` for the first time and a
real `total_duration_ms=120,058`. See `docs/ai_o9_design.md`.

### AI-O10 — Discovery Intelligence

Only after analytical and graph prerequisites are met. Build contradiction explanation, Unknowns Engine, and gap ranking.

### AI-O11 — Hypothesis / Experiment Assistance

Late-stage capability requiring explicit speculation labels, evidence provenance, and falsifiability. Follows this project's established grounding-verification pattern (`core`'s M52/M69, and M72's `relationship_classification.classify_relationship`): a proposed hypothesis is accepted by default only when its cited evidence passes a deterministic grounding check against the source records it claims to draw from, not on a human reviewer's say-so for every item. Human scientific review remains available on any hypothesis, and is the honest expectation before acting on one outside this system -- but it is oversight of a labeled, falsifiable, evidence-linked proposal, not a required gate this project blocks on for every record at scale, the same distinction `Relationship to the Existing Knowledge Engine` draws below.

## Release Gates

A workflow should not become default until explicit gates pass.

```text
Retrieval Recall@10 >= target
Citation correctness >= target
Citation completeness >= target
Unsupported factual assertion rate <= target
Grounding failure rate <= target
Contradictory evidence recall >= target
Workflow completion rate >= target
Runaway-loop rate = 0 in benchmark
Canonical unauthorized writes = 0
Prompt-injection critical failures = 0
```

Targets should come from measured baselines, not invented before evaluation exists.

## Relationship to the Existing Knowledge Engine

This plan extends, not replaces, the current architecture.

- `knowledge-engine-core` owns ingestion, provenance, Evidence Records, graph data, deterministic checks, and source-linked scientific structures.
- `knowledge-engine-ai` owns the Research Copilot and interpretation/orchestration layer.
- `knowledge-engine-web` remains the researcher-facing presentation layer.
- local Ollama inference remains a preferred low-cost/private execution path.
- Evidence Quality, Consensus, Claim Confidence, Coverage, Stability, and lifecycle concepts remain distinct.
- statistical calculations remain deterministic.
- grounding verification remains mandatory for LLM-assisted extraction.
- graph relationships and machine-generated interpretations retain provenance.
- uncertainty remains visible.
- human review remains possible even when not required for every record at scale.

The AI orchestration layer consumes these capabilities through documented interfaces rather than duplicating them.

## What Not to Build

Avoid:

- an autonomous swarm that talks to itself without structured state;
- Kubernetes solely because agents sound distributed;
- one enormous model prompt containing whole papers;
- automatic canonical evidence rewriting;
- LLM-generated confidence percentages;
- automatic meta-analysis without compatibility checks;
- one universal evidence-quality rubric;
- treating reference text as evidence;
- unrestricted shell access for research agents;
- unbounded recursion;
- agent votes as a substitute for evidence;
- cloud-only design that makes local/private use impossible;
- local-only design that makes future public deployment impossible.

## End-State Vision

The mature Knowledge Engine should operate more like a scientific research operating system than a chatbot.

A user asks:

> "What is the current evidence that intervention X improves outcome Y, where does the evidence disagree, how confident should we be, and what is still unknown?"

The system should return:

1. a structured interpretation of the question;
2. exact search/discovery scope;
3. relevant primary and secondary evidence;
4. PICO and methodological comparisons;
5. supporting, qualifying, and contradicting findings;
6. independently verified numerical checks where possible;
7. evidence-quality and consensus assessments;
8. corpus coverage and evidence cutoff;
9. lifecycle/stability context;
10. unresolved gaps;
11. candidate follow-up research questions;
12. concise human-readable synthesis;
13. citations for every material claim;
14. complete machine-readable audit trail;
15. a durable session that can be reopened when new evidence arrives.

When new evidence appears, the system should not merely answer the same question again. It should identify what changed, why the assessment changed, what did not change, and what remains unknown.

That is the target: not an AI oracle, not a search box, and not a swarm of bots, but a traceable, continuously revisable system for helping humans reason over scientific evidence.

## External Design References Reviewed

This architecture was cross-checked against contemporary agent-system guidance and standards including Anthropic guidance on effective agents and agent evaluations, OpenAI Agents SDK concepts for handoffs/tools/guardrails/tracing, Microsoft AutoGen multi-agent orchestration patterns, NIST AI RMF and Generative AI risk guidance, OWASP agentic AI security guidance, OpenTelemetry GenAI observability work, and Model Context Protocol authorization guidance.

Knowledge Engine should use these as engineering references, not dependencies or authorities on scientific truth.

## Recommended Immediate Decision

Do **not** implement a generalized multi-agent framework next.

The next planning action should be:

> **Formalize `ResearchPlan`, `ResearchSession`, `ResearchTask`, and `ResearchEvent` contracts first.**

Those four types establish the stable Knowledge Engine domain model that any future agent framework can execute.

Once they exist, implement one bounded orchestration workflow using existing Retrieval Intelligence, Evidence Intelligence, contradiction-oriented retrieval, statistical verification, and synthesis.

Only after that workflow is evaluated should the project decide whether a dedicated orchestration framework adds enough value to justify the dependency.

That path keeps the system aligned with the end vision while minimizing architectural rework.
