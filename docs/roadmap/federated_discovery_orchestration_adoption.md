# Federated Discovery Orchestration Adoption

Status: adopted AI-layer guidance, 2026-08-15.

This document records the AI-layer lessons taken from the review of
`surendranb/find-research-papers-mcp`. The useful behavior is translated into
Knowledge Engine's own orchestration model. The external MCP server is not a
required dependency, does not define our research method, and does not own our
provider choices.

The matching Core plan is
`knowledge-engine-core/docs/roadmap/federated_research_discovery_adoption.md`.

**2026-08-19: `FederatedDiscoveryResult.search_run_created_at` added, parsing
Core's `coverage.created_at` (half of `knowledge-engine-web`'s WEB-FRD-2
gap).** `knowledge-engine-core`'s `docs/core_interface_contract.md` already
documents `coverage.created_at` as part of `ke federated-discover --output`'s
public shape; this repository's parser simply never read it.
`parse_federated_discovery_result()` now carries it through as
`FederatedDiscoveryResult.search_run_created_at: str | None`, `None` when a
payload predates or omits the `coverage` block, never a guessed value.
Purely additive -- `knowledge-engine-web`'s current pinned revision is
unaffected. See `CHANGELOG.md`'s matching entry. A future
`knowledge-engine-web` PR still needs to bump its pinned `knowledge-engine-ai`
revision and render the field in `discover.html`'s "Run timestamp" row to
close WEB-FRD-2 fully -- out of this repository's own scope, the same
two-step pattern already used for WEB-FRD-3/WEB-FRD-4.

**2026-08-19: `ke_client.citation_snowball()` added, AI-FRD-4's first client
wrapper for Core's FRD-7 `ke citation-snowball` command.** See AI-FRD-4's
section below for the exit-criteria status; a no-caller, no-seed-selection
gap remains this milestone's own next continuation.

**2026-08-19: `FederatedCandidateSummary` now surfaces per-provider
`retracted`/`preprint` observations, unblocking `knowledge-engine-web`'s
WEB-FRD-4.** `knowledge-engine-web`'s
`docs/federated_discovery_transparency_roadmap.md` (WEB-FRD-2/WEB-FRD-4,
merged in Web's PR #64) recorded a concrete cross-repo gap: `/discover`
could not show visitors per-provider `retracted`/`preprint` observations
because this repository's typed `FederatedCandidateSummary` -- the only
value Web's route receives from this repo -- discarded everything from
Core's `ProviderObservation` except the provider name, even though Core's
`ke federated-discover --output` JSON already includes `retracted`,
`preprint`, and `preprint_version` per provider observation. This repository
now parses those fields into a new `FederatedCandidateSummary.observation_flags`
field (`FederatedProviderObservationFlags`, one entry per provider
observation, additive and unmerged across providers). Purely additive --
`providers` and every other existing field/JSON key are unchanged, so Web's
current `/discover` integration remains compatible without modification. A
future `knowledge-engine-web` PR still needs to update its own route/UI to
read `observation_flags` and close WEB-FRD-4 on Web's side; this repository
change was this run's full, authorized scope (Web/Core changes were
explicitly out of bounds for this run). See `CHANGELOG.md`'s matching entry
for live-verification detail (arXiv observations reporting real
`preprint`/`preprint_version`, OpenAlex reporting real `retracted`).

**2026-08-18: `ke_client.federated_discover()` gained its first in-repository
caller, `ke-ai discover`.** The client wrapper existed, was unit-tested, and
was live-verified against the real `ke` binary, but had no caller inside this
repository -- only `knowledge-engine-web`'s `/discover` route used it. The new
CLI command is a direct, bounded way to run one federated discovery search and
inspect Core's recorded coverage/disagreement facts from this repository
without a full Research Copilot session. It is deliberately a standalone
command, not a step inside `run_research_question`'s own planning -- deciding
*when* a research task needs broader provider coverage is AI-FRD-3's
(Discovery-plan compiler) job below, which remains not started pending its own
capability-registry/execution-budget design. This closes the immediate
"built but unreachable" gap without prematurely committing to that larger,
not-yet-authorized design.

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

**Status: compiler/executor foundation implemented; not yet wired into
Research Copilot's own planning.** `discovery_plan.py`'s `DiscoveryPlan` /
`compile_discovery_plan()` / `execute_discovery_plan()` give this milestone
its typed plan and bounded execution primitive: `DiscoveryPlan` validates
provider names against `KNOWN_DISCOVERY_PROVIDERS` (mirrors Core's own
`_federated_discovery_registry` set), a limit/year/execution-budget bound
that fails closed in `__post_init__` before any subprocess call ever runs,
and `execute_discovery_plan()` runs the plan through the same
`ke_client.federated_discover()` boundary every other caller uses,
returning Core's own `search_run_id` (replayable through Core's ledger, not
a second local record of what ran). What is *not* yet built: nothing calls
this compiler except tests -- `run_research_question` still only searches
the local corpus, and no policy exists yet for deciding when a Research
Session should compile and execute a discovery plan instead. That remains
this milestone's own next continuation.

Exit criteria:

- provider/tool names validate against capability registry; **met** --
  `DiscoveryPlan.__post_init__` against `KNOWN_DISCOVERY_PROVIDERS`
- execution budget/depth is explicit; **met** -- `max_execution_seconds`
  and `limit_per_provider` are required, bounded `DiscoveryPlan` fields;
  `execute_discovery_plan()` always builds its `ExecutionBudget` from the
  plan's own bound
- unknown tool/provider requests fail closed; **met** -- raises
  `DiscoveryPlanError` at plan construction, before any `ke` subprocess call
- plan execution remains replayable through Core run IDs. **met** --
  `execute_discovery_plan()` returns Core's own `search_run_id`
- not yet done: wiring a compiled plan into `run_research_question`'s own
  planning, and the policy for deciding *when* to compile/execute one --
  `ke-ai discover`'s docstring flagged this as this milestone's job and it
  remains open

### AI-FRD-4 -- Citation-snowball planner

Add a bounded strategy for reference/citation expansion from selected seed works.

**Status: `ke_client` wrapper added; no planner or caller yet.**
`ke_client.citation_snowball()` is the first in-repository way to invoke
Core's FRD-7 `ke citation-snowball` command -- it passes seeds, provider,
directions, depth, and per-traversal/candidate bounds straight through to
Core and returns a typed, parsed `CitationSnowballResult` (mirroring
`federated_discover()`'s own shape). What is *not* yet built: no CLI
command calls it (unlike `federated_discover`, which `ke-ai discover`
already exposes), no seed-selection strategy exists, and nothing decides
*when* a Research Session should run a citation snowball or wires this into
`run_research_question`'s own planning. That remains this milestone's own
next continuation.

Exit criteria:

- seed selection and depth are visible; **partial** -- depth is an explicit,
  bounded `citation_snowball()` argument; seed *selection* (which works a
  Research Session should snowball from) is not yet decided by any caller
- results enter normal Core provenance flow; **met** -- every run persists
  to Core's own citation-snowball ledger before `citation_snowball()`
  returns, replayable via Core's `ke citation-snowball-report`
- planner cannot bypass deduplication, acquisition, or evidence validation;
  **met by construction** -- `citation_snowball()` only reads Core's
  discovery/traversal output, the same read-only boundary
  `federated_discover()` uses, and does not touch acquisition
- not yet done: a CLI or `run_research_question` caller, and a seed-selection
  policy

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
