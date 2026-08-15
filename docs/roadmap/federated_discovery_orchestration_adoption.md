# Federated Discovery Orchestration Adoption

Status: adopted AI-layer guidance, 2026-08-15.

This document records the AI-layer lessons taken from the review of
`surendranb/find-research-papers-mcp`. The useful behavior is translated into
Knowledge Engine's own orchestration model. The external MCP server is not a
required dependency, does not define our research method, and does not own our
provider choices.

The matching Core plan is
`knowledge-engine-core/docs/roadmap/federated_research_discovery_adoption.md`.

## AI-layer role

Core owns provider transport, search-run provenance, canonical identity,
provider health/status, and evidence/source persistence. AI owns research-task
planning and interpretation over those deterministic facts.

The Research Copilot may decide that a task would benefit from:

- broader provider coverage;
- citation/reference expansion from a landmark paper;
- an updated recency search;
- a contradiction-oriented query variant;
- a correction/retraction sweep;
- a provider that covers a domain better than the providers already searched.

It must express that as a bounded discovery request to Core. It must not call
provider APIs directly and then treat unrecorded results as evidence.

## Search coverage becomes part of the Research ISA

A Research ISA should increasingly be able to express search-completion claims
such as:

- the configured relevant scholarly providers were attempted;
- provider failures are visible;
- at least one independent bibliographic index and one domain-specific source
  were searched when appropriate;
- citation/reference expansion was completed when the question requires it;
- contradiction-oriented search was performed;
- correction/retraction status was checked for works used in the final answer;
- every cited claim maps to persisted evidence;
- the system reports unresolved coverage gaps rather than silently closing.

These are criteria, not model self-scores. Core supplies the underlying search
run and provider-status facts; deterministic verification decides whether the
criterion passes.

## Capability-aware planning

The reviewed project demonstrates useful graceful degradation. Knowledge Engine
should take this further by giving Research Copilot an explicit capability view.

Example:

```text
pubmed: available
crossref: available
openalex: available
arxiv: available
semantic_scholar: rate_limited
citation_expansion: available_via_openalex
retraction_check: available
local_llm: available
cloud_reasoner: disabled
```

The planner can adapt the research plan to this state, but must not relabel a
partial plan as complete. `disabled`, `unavailable`, `rate_limited`, `failed`,
and `not_relevant` remain distinct states.

## Provider diversity is a retrieval signal, not a confidence shortcut

Using multiple providers can improve recall and make blind spots visible, but the
number of providers is not evidence quality.

The AI layer must never reason:

> five databases found this paper, therefore the claim is more true.

Multiple provider observations may improve confidence in bibliographic identity
or search coverage. Scientific confidence still depends on the underlying study
evidence and Knowledge Engine's Evidence/Analytical Intelligence contracts.

## Citation graph as a planning primitive

Research Copilot should eventually be able to propose bounded citation-snowball
steps:

```text
seed known landmark work
-> inspect references
-> inspect citing works
-> normalize identities
-> screen for relevance
-> persist candidate provenance
-> repeat only to declared depth/budget
```

Useful cases:

- finding earlier foundational work;
- finding replications or extensions;
- locating corrections/retractions and follow-up studies;
- identifying later contradiction or qualification;
- tracing how a scientific claim changed over time.

The model proposes the strategy; Core executes and records it.

## Provider-generated text is not evidence text

Semantic Scholar and future providers may expose generated TLDRs, summaries, or
other convenience text. These can be useful navigation hints, but they must carry
provider-generated provenance and must never be supplied to grounding validators
as though they were source-paper text.

Priority for substantive interpretation remains:

1. persisted full source text with locator provenance;
2. source abstract/metadata that the scholarly provider reports as source
   metadata;
3. provider-generated summary only as a discovery/navigation hint.

The AI layer should label the distinction in its own internal context.

## Research-plan diversification

One important improvement beyond the reviewed repository is to make discovery
strategies composable instead of using the same query everywhere blindly.

A future planner may produce something like:

```yaml
research_plan:
  - step: federated_search
    providers: [pubmed, crossref, openalex]
    query_intent: primary_question
  - step: domain_search
    provider: pubmed
    query_intent: clinical_synonyms_mesh_expansion
  - step: preprint_sweep
    provider: arxiv
    when: domain_relevant
  - step: citation_expand
    seeds: [landmark_work_ids]
    direction: both
    depth: 1
  - step: contradiction_search
    query_intent: aligned_pico_direction_reversal
  - step: correction_retraction_check
    targets: cited_work_ids
```

Every step must have a deterministic run record and bounded execution budget.

## Keep research doctrine ours

The external project exposes a `get_research_method()` helper. Knowledge Engine
will not import an upstream project's "house method" as scientific authority.

Our own research method evolves through:

- project principles;
- Research ISA criteria;
- Evidence Intelligence;
- Analytical Intelligence;
- source/provenance contracts;
- explicit contradiction policy;
- deterministic verification;
- domain-specific validated methods where needed.

A provider or MCP plugin can say what capability it offers. It does not get to
say what counts as adequate evidence.

## Security and privacy

The external repository's telemetry and environment/client fingerprinting are not
part of Knowledge Engine AI's architecture.

AI-layer rules:

- no default external telemetry;
- no persistent third-party analytics installation identity;
- no research-query analytics sent outside the provider calls actually needed to
  execute the research;
- no tool-sequence or harness fingerprinting sent to third parties;
- provider credentials stay outside prompts and research-session records;
- remote installer convenience is not a reason to weaken reviewed dependency
  management;
- external paper/web text remains untrusted data, never instructions.

## Provider-neutral model and tool routing

The federated-discovery review reinforces the broader LifeOS-derived rule already
adopted in this repository: workflow semantics should name capabilities, not
vendors.

Prefer:

```text
search_scholarly_literature
expand_citation_graph
check_retraction_status
high_reasoning_model
local_private_model
```

rather than hard-coded provider/model names in research doctrine.

Concrete providers remain configurable implementations behind those roles.

## AI roadmap additions

### AI-FRD-1 -- Consume Core discovery coverage

Once Core exposes provider status/search-run contracts, ingest them into the
Research Session without reinterpreting them.

Exit criteria:

- session records can identify complete versus degraded discovery;
- provider status is preserved through synthesis and close-gate verification;
- no model-generated provider status exists.

### AI-FRD-2 -- Coverage-aware Research ISA

Add deterministic close-gate criteria for provider coverage, contradiction
search, citation integrity, and correction/retraction checks where relevant.

Exit criteria:

- deliberately failed provider fixture blocks a "complete coverage" claim;
- synthesis can still proceed in degraded mode when policy permits, but the
  limitation is explicit;
- close gate never passes merely because the model says it searched broadly.

### AI-FRD-3 -- Discovery-plan compiler

Allow Research Copilot to produce a typed, bounded plan using Core discovery
capabilities.

Exit criteria:

- provider/tool names validate against capability registry;
- execution budget/depth is explicit;
- unknown tool/provider requests fail closed;
- plan execution remains replayable through Core run IDs.

### AI-FRD-4 -- Citation-snowball planner

Add a bounded strategy for reference/citation expansion from selected seed works.

Exit criteria:

- seed selection and depth are visible;
- results enter normal Core provenance flow;
- planner cannot bypass deduplication, acquisition, or evidence validation.

### AI-FRD-5 -- Research freshness / rerun reasoning

Given an earlier Research Session, help decide whether a new federated search is
warranted and explain what changed after Core reruns it.

Exit criteria:

- new evidence is distinguished from previously seen evidence;
- corrections/retractions can invalidate or qualify prior synthesis;
- prior answer text is never silently overwritten as if it had always been the
  updated answer.

## Improvements beyond the external reference

The external MCP focuses on finding papers. Knowledge Engine can go further by
joining discovery to the rest of its scientific operating system.

### Discovery quality benchmark

Extend retrieval benchmarks to test provider-level recall and identity merging,
not just ranking over already-ingested corpora. Golden fixtures should include:

- papers only one provider finds;
- DOI duplicates returned by several providers;
- preprint and journal-version pairs;
- retracted/corrected works;
- rate-limited provider runs;
- citation-expanded relevant papers missing from lexical search;
- intentionally conflicting provider metadata.

### Stopping rules

Research Copilot should eventually be able to stop discovery for an explicit
reason:

- ISA coverage criteria satisfied;
- execution/time budget reached;
- no material new candidates after bounded expansion;
- required provider unavailable, making completion impossible;
- user intentionally requested a narrow source scope.

"The model feels done" is never a stopping rule.

### Counter-search before conclusion

Before a strong synthesis is released, the planner should be able to issue one
or more adversarial searches designed to find evidence that would weaken or
reverse the emerging conclusion. This should become a standard Research ISA
pattern for consequential questions.

### Search-strategy provenance in the answer

The user-facing answer should eventually be able to summarize, in compact form,
not just which studies were cited but how the evidence search was constructed:
providers searched, important failures, citation expansion, last refresh, and
material limitations. Web owns the presentation; AI owns the grounded narrative
of what those deterministic run facts imply for completeness.

## End state

The AI layer should become capable of planning a research investigation across
many scholarly sources while remaining unable to fake the investigation.

The desired flow is:

```text
question
-> Research ISA
-> capability-aware discovery plan
-> Core executes/persists every discovery step
-> evidence is validated and linked
-> AI analyzes only recorded evidence and run facts
-> Skeptic/close gate tests coverage, contradiction, and citations
-> answer states both the evidence and the limits of the search
```

That is the Knowledge Engine version of the useful idea: broad discovery with
scientific accountability, not an MCP wrapper around five APIs.
