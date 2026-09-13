# Unattended Verification Policy

Routine engineering verification is machine-owned. Jeremy is not a recurring test executor and must not be placed inside ordinary implementation, regression, environment, Product Reality, or promotion loops when objective evidence can be automated or collected by an unattended worker.

## Default verification path

`change -> FAST_GATE -> exact-head preflight -> CI -> unattended environment-specific verification -> structured evidence -> automated diagnosis/repair -> re-verification -> promotion -> optional Jeremy milestone acceptance`

Environment dependence is not automatically human dependence. Tests requiring local Ollama, persistent Core services, acquisition/retrieval integration, long-running research benchmarks, or another non-CI environment should first be scheduled to an approved unattended worker.

## Evidence classification

Use this order:

1. Repository-native deterministic test.
2. Unattended environment test.
3. Automatable Product Reality probe using logs, metrics, traces, artifacts, timing, source/provenance evidence, or machine-readable observations.
4. Human judgment only when genuinely subjective, ambiguous, irreversible, safety-sensitive, or product-direction dependent.

`Jeremy must run this manually` is a workflow deficiency unless category 4 actually applies.

## Worker contract

An unattended worker must identify repository, branch, exact SHA, request, environment, model/runtime configuration, and timestamp; record bounded commands/actions and evidence; return `PASS`, `FAIL`, `REVIEW_REQUIRED`, `PRODUCT_REALITY_REQUIRED`, or `ENVIRONMENT_FAILURE`; write permitted results back to the issue/PR/evidence ledger; fail closed on missing evidence; preserve secrets/privacy/provenance; and leave the machine safe. It must not require Jeremy to watch, click ordinary steps, copy logs, or manually relay completion.

Pending worker verification blocks only the dependent lane. Parallel-safe work continues.

## Knowledge Engine AI application

Local Ollama synthesis, cold/warm research benchmarks, acquisition/promotion/re-retrieval paths, grounded-answer generation, provenance validation, report instrumentation, and other objective environment-specific acceptance should be automated through CI or an unattended local worker. Exact commit plus model/runtime configuration must accompany evidence so conclusions are reproducible and never fabricated.

Jeremy may test milestones whenever useful, but repeated model startup, benchmark execution, result copying, log collection, and regression verification should be engineered out of his workflow.

Every recurring manual test is therefore a candidate automation defect: prefer deterministic assertions, synthetic fixtures, benchmark harnesses, CI jobs, unattended worker tasks, machine-readable evidence, and durable regression guards over another manual request.
