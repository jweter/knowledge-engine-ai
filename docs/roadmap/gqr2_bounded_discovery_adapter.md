# GQR-2 Bounded Discovery Adapter

## Status

Implemented as the provider-execution boundary immediately after the validated
GQR-2 query-plan compiler.

The adapter is intentionally narrow: it executes already-validated query variants
through Core federated discovery and records provenance. It does **not** acquire
full text, extract or promote Evidence Records, or allow discovery candidates to
influence synthesis.

## Flow

```text
user question
  -> validated query decomposition
  -> deterministic GeneralQueryPlan
  -> bounded discovery adapter
  -> Core `ke federated-discover`
  -> provenance-preserving discovery snapshot
  -> later GQR-4/GQR-5 acquisition, extraction, promotion, re-retrieval
```

## Contract

`knowledge_engine_ai.copilot.discovery_adapter.execute_general_query_plan_discovery()`
requires all of the following explicitly:

- a validated `GeneralQueryPlan`;
- a Core federated-discovery ledger root;
- an explicit, non-empty provider set;
- a `DiscoveryAdapterBudget` containing:
  - maximum query-variant calls;
  - maximum variant × provider attempts;
  - maximum candidates requested per variant;
- optional Core `project_id` and `research_question_id` provenance;
- the existing shared wall-clock `ExecutionBudget` when the caller is part of a
  composed Research Copilot run.

The adapter refuses to execute if the query-call budget cannot preserve at least
one variant for every search track. When the call budget is smaller than the full
compiled plan, it selects one variant per track first and then allocates remaining
capacity in original plan order. Omitted variant IDs are returned explicitly; no
truncation is hidden.

Before the first provider call, the adapter also checks the multiplicative cost:

```text
selected query variants × requested providers <= max_provider_attempts
```

This prevents a bounded query compiler from becoming an unbounded provider-call
fan-out at the execution layer.

## Preserved provenance

Every executed variant retains:

- `variant_id`;
- `track_id`;
- evidence scope (`direct`, `class_level`, `indirect_context`, `guidance`, or
  `counterevidence`);
- exact query text;
- Core-owned `search_run_id`;
- Core search-run timestamp when present;
- completeness state;
- per-provider attempted/outcome/result-count/reason fields;
- Core canonical candidate IDs and candidate provider provenance.

The adapter rejects a Core result whose returned query text does not match the
query variant that was executed. This is a provenance-integrity failure rather
than something the AI layer is allowed to repair or guess around.

## Issue #79 / Monster Energy benchmark

The Monster Energy blood-pressure golden case now has an executable path from its
11-track GQR-2 query plan into Core federated discovery. A caller can choose a
budget large enough to execute every compiled variant or a smaller bounded budget
that still guarantees at least one query for every research track.

This means the benchmark can now preserve distinctions such as:

- Monster Zero Ultra / White Monster direct searches;
- Monster Original / Original Green direct searches;
- acute energy-drink evidence;
- chronic/repeated exposure;
- chronic caffeine as indirect context;
- sugar-sweetened beverage hypertension evidence;
- artificial-sweetener context;
- BP-measurement guidance;
- explicit 6–12 month / one-year longitudinal searches;
- deliberate null/tolerance counter-evidence.

The resulting papers are still **discovery candidates only**. PMID seeds and
provider hits remain non-citable until Core acquisition, grounded extraction,
validation/promotion, and re-retrieval produce ordinary Evidence Records.

## Next boundary

The next General Question Research Loop integration is GQR-4/GQR-5: bounded
candidate acquisition followed by grounded extraction/promotion and re-retrieval.
That work must preserve the discovery provenance captured here and must not let a
provider candidate or model-generated summary bypass Core's Evidence Record trust
boundary.
