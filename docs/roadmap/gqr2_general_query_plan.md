# GQR-2 General Query-Plan Compiler

## Status

First deterministic compiler slice implemented for General Question Research Loop v1
(issue #69), with issue #79 as the first golden research-case fixture.

## Purpose

`knowledge_engine_ai.general_query_plan` turns a structured question decomposition
into a bounded, provider-neutral, inspectable set of search queries.

It sits between high-level research planning and Core's federated discovery layer.

```text
user question
  -> structured concepts / synonyms / search tracks
  -> GQR-2 deterministic query-plan compiler
  -> bounded provider-neutral query variants
  -> later discovery executor / Core federated discovery
```

This module does **not** execute provider calls, acquire papers, extract Evidence
Records, or decide scientific truth.

## Contracts

The plan records:

- original question;
- optional domain hint;
- explicit framing type (`generic` by default, `pico` only when requested);
- answer dimensions that later synthesis must keep distinct;
- known source/PMID seeds that should be inspected;
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

A caller may supply an explicit `PicoFrame` and request `frame_type="pico"` when
PICO is appropriate. The compiler rejects a PICO frame attached to a generic
plan and rejects PICO mode without an explicit PICO frame.

Tests exercise chemistry/materials, physics/astronomy, machine learning, and
general biology questions to ensure they remain generic by default.

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

This slice closes the deterministic query-contract/compiler part of GQR-2. It
does not yet produce the structured decomposition from arbitrary free text on
its own and it does not execute the compiled variants.

The next integration step should connect a validated question-decomposition
producer to this compiler, then map the resulting variants into bounded Core
federated-discovery runs while preserving track identity and provider coverage.

Newly discovered papers still cannot affect synthesis until GQR-4/GQR-5
grounded extraction, validation/promotion, and re-retrieval are complete.
