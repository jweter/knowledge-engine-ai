# GQR-2 General Query-Plan Compiler

## Status

GQR-2 now has both halves required before provider execution:

1. a validated arbitrary-question decomposition producer; and
2. a deterministic, bounded provider-neutral query compiler.

Issue #79 remains the first golden research-case fixture.

## Purpose

The GQR-2 path turns arbitrary user text into a bounded, inspectable literature-search
plan without allowing model output to become evidence.

```text
user question
  -> local-model search decomposition proposal
  -> strict structural validation
  -> GQR-2 deterministic query-plan compiler
  -> bounded provider-neutral query variants
  -> later discovery adapter / Core federated discovery
```

This layer does **not** execute provider calls, acquire papers, extract Evidence
Records, or decide scientific truth.

## Arbitrary-question decomposition producer

`knowledge_engine_ai.copilot.query_decomposition.query_plan_from_question()` is the
validated producer in front of the deterministic compiler.

The local model may propose only:

- a domain hint;
- generic vs explicit PICO framing;
- answer dimensions;
- canonical search concepts;
- bounded aliases/synonyms;
- search tracks;
- the evidence-scope label for each track.

The model may **not** provide source identities. `seed_source_ids` is deliberately
absent from the model-owned JSON schema. Known PMIDs/DOIs can be supplied only by
the caller after the proposal validates. Unknown top-level fields are rejected, so a
model cannot smuggle a fabricated PMID/DOI into a privileged planning field.

The producer performs no retries or autonomous repairs. Malformed JSON, invalid
evidence scopes, unknown concept references, incompatible PICO framing, excessive
synonyms, excessive variants, or other compiler-bound violations fail closed with
the raw local-model output retained in the error for debugging.

The original user question is also caller-owned. It is never taken back from model
output and remains the text attached to the resulting `GeneralQueryPlan`.

## Contracts

The final plan records:

- original question;
- optional domain hint;
- explicit framing type (`generic` by default, `pico` only when requested);
- answer dimensions that later synthesis must keep distinct;
- caller-owned known source/PMID seeds that should be inspected;
- canonical concepts and bounded synonym sets;
- search tracks with a declared evidence scope;
- compiled provider-neutral query variants;
- the global variant budget.

Evidence scopes are explicit:

- `direct`;
- `class_level`;
- `indirect_context`;
- `guidance`;
- `counterevidence`.

This is especially important for issue #79, where direct Monster evidence,
energy-drink class evidence, chronic caffeine evidence, sugar-sweetened beverage
evidence, artificial-sweetener observational context, measurement guidance, and
null/tolerance evidence must not be silently collapsed into one evidence class.

## Bounded expansion

The compiler has hard ceilings for concepts, synonyms, search tracks, variants
per track, total variants, and query length.

Within the caller's total variant budget it always keeps the canonical query for
**every** search track first. Additional variants are allocated round-robin
across tracks.

Within a track, synonym expansion is also diversity-first: after the canonical
query, the compiler substitutes one concept at a time before falling back to
multi-concept Cartesian combinations. A small per-track budget therefore samples
aliases across the exposure, outcome, and time/duration concepts instead of
letting the product order repeatedly vary only one concept.

Together these rules prevent one synonym-rich track or concept from consuming
the search budget and silently dropping later research objectives or important
aliases.

## PICO is opt-in

The default frame is `generic`.

Both the producer prompt and deterministic compiler require PICO to be explicit.
The compiler rejects a PICO frame attached to a generic plan and rejects PICO mode
without an explicit `PicoFrame`.

Regression tests cover chemistry/materials, physics/astronomy, machine learning,
and general biology questions as generic plans. A clinical comparison test proves
that PICO remains available when it is actually appropriate.

## Issue #79 golden fixture

`knowledge_engine_ai.research_case_query_plan.monster_energy_bp_query_plan()`
compiles the Monster Energy / one-year blood-pressure benchmark through the same
generic compiler.

The fixture currently contains eleven explicit search tracks:

1. direct Monster/commercial energy-drink trials;
2. direct Monster Zero Ultra / White Monster blood-pressure evidence;
3. direct Monster Original / Original Green blood-pressure evidence;
4. randomized/meta-analytic energy-drink evidence;
5. repeated/chronic energy-drink exposure;
6. chronic caffeine evidence as bounded indirect context;
7. sugar-sweetened beverage incident-hypertension evidence;
8. artificially sweetened beverage context;
9. blood-pressure measurement guidance;
10. explicit 6-12 month / one-year longitudinal energy-drink search;
11. null, nonsignificant, and tolerance counter-evidence.

The explicit product tracks guarantee that Zero Ultra and Original cannot be
lost merely because the broader brand concept has more aliases than the current
query budget can expand.

The plan preserves the benchmark's answer dimensions and all seeded PMID
identities. Those PMIDs remain **discovery/validation targets only**. A query
plan or provider result is not an Evidence Record.

## Current boundary

GQR-2 question interpretation and bounded query compilation are now implemented.
The compiled variants still do not execute automatically.

The next integration slice is a bounded discovery adapter that maps
`GeneralQueryPlan.query_variants` into Core federated-discovery calls while retaining
`variant_id`, `track_id`, evidence scope, provider outcomes, and `search_run_id`
provenance. That adapter must prevent a large plan from multiplying provider calls
without an explicit execution budget.

Newly discovered papers still cannot affect synthesis until GQR-4/GQR-5 grounded
extraction, validation/promotion, and re-retrieval are complete.
