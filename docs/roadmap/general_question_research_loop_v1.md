# General Question Research Loop v1

Status: **active cross-repository build plan**  
Owner repository: `knowledge-engine-ai`  
Tracking issue: #69  
Companion issues: `knowledge-engine-core` #402, `knowledge-engine-web` #86

## Product decision

The Knowledge Engine is a general-purpose research system. The GLP-1/body-weight corpus is a golden validation corpus and regression benchmark, not the product boundary. The interactive Research Copilot must accept an arbitrary scientific question, use the current evidence store when it is sufficient, and broaden research when it is not.

The target behavior is:

```text
question
  -> interpret and normalize
  -> search indexed evidence first
  -> deterministic adequacy check
  -> bounded federated discovery when coverage is thin
  -> bounded acquisition/ingestion of eligible sources
  -> grounded evidence extraction
  -> re-run retrieval
  -> verify and synthesize
  -> answer with citations, provenance, coverage, and limitations
  -> retain validated evidence for later related questions
```

The model may plan and explain. It is not the factual authority. New factual claims become answerable only after they are grounded in evidence that Core can identify and validate.

## Why this change is required

The current system has strong components but the composed experience is still effectively corpus-bound. `run_research_question` can trigger federated discovery through `FederatedDiscoveryPolicy`, but discovered papers remain leads. They are not automatically acquired, validated, promoted to Evidence Records, re-retrieved, or included in the answer. The Web integration also historically omitted the discovery policy, leaving the deployed Ask path corpus-only even though the AI layer had the trigger machinery.

This produced the wrong product behavior: a new question outside the indexed corpus looked like an unsupported question instead of a research task.

## Invariants

1. **Indexed evidence first.** Every question first searches the current validated evidence store.
2. **No model-memory authority.** The LLM may generate search terms, query decompositions, explanations, and candidate summaries, but no uncited model-memory fact is treated as evidence.
3. **Discovery is not evidence.** A provider candidate cannot be cited as an Evidence Record until Core has acquired and validated the source.
4. **Assessment depth is independent of retrieval breadth.** The system may retrieve and synthesize across domains even when a domain-specific confidence profile does not yet exist. Unsupported scoring must be labeled unavailable rather than blocking retrieval.
5. **Deterministic adequacy.** The decision to broaden the search is based on inspectable retrieval/coverage signals, not an opaque LLM judgment.
6. **Bounded autonomy.** Provider count, candidate count, acquisition count, elapsed time, and retries are capped.
7. **Durable provenance.** Every provider run, candidate, acquisition attempt, source, evidence record, and answer session must remain traceable.
8. **Reuse.** Once evidence has been acquired and validated, later related questions should benefit from it.

## Research states

The composed pipeline must expose one of these stable states to callers and Web:

| State | Meaning |
|---|---|
| `indexed_answer` | Existing validated evidence was sufficient; no external research required. |
| `research_required` | Indexed coverage was insufficient and bounded discovery/acquisition began. |
| `researching` | External discovery/acquisition/extraction is still in progress. |
| `partial_answer` | Some grounded evidence supports an answer, but coverage or provider execution is incomplete. |
| `insufficient_evidence` | Bounded research completed without enough grounded evidence for a supported answer. |
| `provider_degraded` | A research run is usable but one or more configured providers failed or were rate-limited. |
| `blocked` | Core retrieval/validation failed in a way that broader discovery cannot repair safely. |

A state is descriptive workflow metadata, not an evidence-quality score.

## General Question Research Loop

### Stage 0 - normalize the question

Inputs:
- original user text
- optional stable `research_question_id`

Outputs:
- normalized question text
- high-level domain hint
- concepts/entities
- synonyms and query variants
- optional structured framing where appropriate (PICO for clinical questions, but not forced onto unrelated fields)

Rules:
- keep the original text unchanged in the durable session;
- any LLM-generated term is a search-plan artifact, not evidence;
- query expansion is bounded and inspectable.

### Stage 1 - indexed retrieval

Run the existing primary and contradiction-oriented retrieval branches over Core's validated evidence store.

Capture:
- retrieved evidence record IDs
- DOI/source identity
- retrieval scores/ranks
- contradiction-only recall gain
- domain-specific intelligence fields when available

### Stage 2 - retrieval adequacy

V1 adequacy remains conservative and deterministic. The existing AI-FRD trigger uses deduplicated Evidence Record coverage. General Question v1 extends the contract so adequacy can later include:
- number of distinct Evidence Records;
- number of distinct sources;
- retrieval score distribution;
- agreement/contradiction coverage;
- age/freshness when relevant;
- whether the question's major concepts are represented.

Provider count must never be used as a proxy for evidence quality.

### Stage 3 - bounded federated discovery

When indexed evidence is inadequate, compile and execute a bounded provider-neutral plan through Core.

Current provider set:
- PubMed
- Crossref
- OpenAlex
- Semantic Scholar
- arXiv

Future providers remain Core-owned and must be added through the same provider contract.

Record:
- `search_run_id`
- query variants
- attempted providers
- provider outcomes
- candidate identities
- deduplication observations
- completeness/degradation
- elapsed time and truncation

### Stage 4 - candidate triage and acquisition

This is the critical missing bridge for a real general-question engine.

Core must convert eligible discovery leads into a bounded acquisition queue. Candidate selection may use deterministic metadata plus AI-assisted relevance triage, but final source eligibility remains governed by explicit rules: stable identity, accessible/licensed source path, deduplication, provenance, and acquisition budget.

V1 acquisition result statuses:
- `already_indexed`
- `acquired_full_text`
- `metadata_only`
- `license_or_access_unavailable`
- `duplicate`
- `failed`
- `skipped_budget`

No acquisition status implies that the source supports the user's claim.

### Stage 5 - ingestion and evidence extraction

For newly acquired full text:
- persist source/paper identity;
- parse pages;
- run the domain-general grounded extraction path;
- verify every proposed extracted field against source text;
- validate Evidence Record schema/provenance;
- reject unsupported proposed fields rather than guessing.

The hand-tuned GLP-1 regex extractor must not become the cross-domain fallback. The grounded local-LLM extraction path is the default for unfamiliar domains where deterministic rules have not been validated.

### Stage 6 - re-retrieval

After successful acquisition/extraction, rerun the original indexed retrieval against the enlarged evidence store.

This is mandatory. Discovery results themselves never go directly to synthesis.

The session records which Evidence Records existed before the research cycle and which became available during it.

### Stage 7 - verification and synthesis

Synthesis uses only validated retrieved evidence.

Output must include:
- direct answer or explicit inability to answer;
- citations/evidence record IDs;
- previously indexed vs newly acquired evidence distinction;
- provider/search coverage;
- degraded-provider warnings;
- evidence limitations and contradictions;
- confidence/quality metrics only when a validated domain profile exists.

If no domain-specific assessment profile exists, state that the score is unavailable. Do not block the answer solely for that reason.

### Stage 8 - durable reuse and freshness

Validated new evidence becomes part of the reusable Knowledge Engine corpus/library. Later questions can retrieve it immediately.

The existing `research_question_id`, answer version, federated search history, and freshness machinery remain the foundation for reruns when literature changes.

## Cross-repository contract

### AI owns
- question interpretation and bounded query planning;
- adequacy policy configuration;
- orchestration order;
- research-state derivation;
- synthesis and explanation;
- never factual persistence authority.

### Core owns
- provider integrations;
- provider/search-run ledgers;
- candidate normalization and deduplication;
- legal/access-aware acquisition;
- paper/source persistence;
- parsing and grounding verification;
- Evidence Record validation and storage;
- reusable corpus state.

### Web owns
- user-visible research progress;
- safe invocation of the AI orchestration path;
- presentation of indexed/newly acquired evidence distinction;
- coverage/degradation/limitations display;
- no hidden provider/model claims.

## Build slices

### GQR-0 - Web discovery wiring
**Goal:** stop leaving the existing AI-FRD policy disconnected from the Research Copilot Web path.

- [ ] Web passes a bounded `FederatedDiscoveryPolicy` to `run_research_question`.
- [ ] Tests prove an arbitrary non-GLP-1 question is eligible for the same path.
- [ ] Existing local retrieval remains first.

### GQR-1 - Research state contract
- [ ] Add stable state enum/result metadata.
- [ ] Derive state deterministically from retrieval/discovery/acquisition outcomes.
- [ ] Add JSON serialization contract.
- [ ] Web renders it.

### GQR-2 - General query-plan compiler
- [ ] bounded synonyms/query variants;
- [ ] optional domain hint;
- [ ] no forced PICO outside suitable domains;
- [ ] inspectable plan JSON;
- [ ] tests with clinical, chemistry, physics, ML, and general-biology questions.

### GQR-3 - Core acquisition bridge
- [x] Core command/API contract accepts one persisted search run and bounded
  selected candidates -- `ke general-question-acquisition-plan` (Core's
  CORE-GQR-1/GQR-2, `docs/core_interface_contract.md`) shipped this on
  Core's `main`, and this repository's `ke_client.py` has
  `general_question_acquisition_plan()`, the AI-side wrapper that reaches
  it. `copilot/discovery_policy.py`'s `FederatedDiscoveryPolicy` now also
  has an opt-in `enable_acquisition_plan` toggle (default `False`) that
  decides *when* to call it (right after a triggered federated-discovery
  run returns its own candidates) and *which* candidates to call it with
  (that run's own deduplicated candidate IDs, capped and bounded by
  policy). This closes the "nothing decides when/which candidates" gap
  this section previously named. Still not wired: no caller has opted a
  real session into `enable_acquisition_plan=True` yet, and there is
  nothing downstream that acts on an `eligible_full_text` disposition --
  see the two items below, both still Core's own future work.
- [x] resolve candidate identity and existing-paper reuse -- Core's
  planner reports `already_indexed` (with the matching `Paper.id`) via
  DOI/PMID/arXiv identity before any budget logic runs; the wrapper above
  parses that disposition and identity verbatim.
- [ ] use existing PMC/Europe PMC/Unpaywall/CORE acquisition capabilities
  where applicable -- Core's own CORE-GQR-3 (acquisition routing),
  not started.
- [ ] persist structured acquisition receipts -- Core's own CORE-GQR-4
  (persist and parse), not started.
- [ ] no silent download of non-permitted full text -- not yet
  meaningfully testable end-to-end: no code path downloads anything yet
  (the plan command never fetches full text itself), so this remains
  open until CORE-GQR-3/GQR-4 exist to violate or honor it.

### GQR-4 - Automatic grounded extraction
- [ ] parse newly acquired paper;
- [ ] invoke grounded domain-general extraction;
- [ ] validate and append Evidence Records;
- [ ] record rejection reasons;
- [ ] enforce per-run record budget.

### GQR-5 - Re-retrieval and answer completion
- [ ] rerun original question after successful promotion;
- [ ] distinguish old/new evidence IDs;
- [ ] synthesize only after re-retrieval;
- [ ] final state is `indexed_answer`, `partial_answer`, `insufficient_evidence`, `provider_degraded`, or `blocked`.

### GQR-6 - Web research UX
- [ ] searching indexed evidence;
- [ ] broadening literature search;
- [ ] acquiring/validating sources;
- [ ] re-running evidence retrieval;
- [ ] final answer provenance and coverage panel.

### GQR-7 - Cross-domain golden benchmark
Minimum v1 benchmark set:
- clinical medicine: GLP-1/body weight;
- oncology;
- mental health;
- chemistry/materials question;
- biology question;
- physics/astronomy question;
- machine-learning methods question.

Each benchmark question records expected relevant source IDs where known, expected behavior when evidence is absent, and whether domain-specific scoring should be available.

### GQR-8 - Reliability hardening
- [ ] provider failure drills;
- [ ] duplicate acquisition tests;
- [ ] timeout/budget exhaustion tests;
- [ ] malformed provider payload tests;
- [ ] Ollama-unavailable behavior;
- [ ] no-grounded-evidence behavior;
- [ ] repeat-question reuse test;
- [ ] deterministic replay of provenance.

## V1 acceptance test

Given a fresh installation whose indexed evidence does not contain a creatine/strength corpus:

1. User asks: `Does creatine supplementation improve maximal strength?`
2. Local retrieval runs and reports inadequate coverage.
3. Federated discovery automatically runs within configured bounds.
4. Provider outcomes and candidates are persisted.
5. Eligible sources are acquired under the acquisition budget.
6. Grounded extraction promotes valid Evidence Records.
7. Original retrieval runs again.
8. Final synthesis cites only promoted Evidence Records.
9. The answer identifies newly acquired evidence and any incomplete coverage.
10. A second related creatine question can reuse that evidence without reacquiring identical sources.

The same control flow must work for a chemistry or physics question even when no domain-specific confidence profile exists.

## Definition of done

General Question Research Loop v1 is done only when a previously unseen research topic can travel from arbitrary natural-language question to newly acquired, validated, citable evidence in one bounded Research Copilot session, with durable provenance and later reuse. Federated discovery alone does not satisfy this definition because leads are not evidence.
