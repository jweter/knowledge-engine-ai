# Cross-Domain Golden-Question Retrieval Benchmark

## Purpose

The next shared project milestone after AI-O17 is to measure retrieval quality
before expanding synthesis behavior. This benchmark creates a deterministic,
reviewable baseline across the three currently reviewed domains: GLP-1/body
weight, NSCLC checkpoint inhibitors, and adult MDD antidepressants.

The benchmark does not ask an LLM whether a retrieved result is relevant. Its
expectations are anchored to already-reviewed golden Evidence Maps in
`knowledge-engine-core` and scored only by Evidence Record identity.

## Initial question bank

1. **GLP-1/body weight** — Do GLP-1 receptor agonists reduce body weight in
   adults with overweight or obesity?
2. **Oncology/NSCLC** — Do immune checkpoint inhibitors improve overall
   survival in adults with advanced non-small-cell lung cancer?
3. **Mental health/MDD** — Do SSRIs and SNRIs reduce depressive symptom
   severity in adults with major depressive disorder?

Each question has a deliberately small set of high-value required records.
Qualifier records are a subset of that required set and test whether retrieval
surfaces evidence that narrows, limits, or complicates a favorable headline
answer rather than only retrieving supporting evidence.

## Metrics

`evaluate_retrieval()` reports:

- required Evidence Records found and missing;
- qualifier Evidence Records found and missing;
- required-record recall at the requested rank cutoff;
- qualifier recall at the requested rank cutoff;
- a conservative pass verdict that requires both required and qualifier recall
  to be complete.

This first slice intentionally does not define precision, NDCG, semantic
relevance labels, or a single project-wide score. Those require reviewed labels
for non-golden candidates and should be added only when there is enough evidence
to make them meaningful.

## Trust and architecture boundaries

- Core remains the authority for Evidence Records and reviewed golden maps.
- AI owns evaluation of Retrieval Intelligence against those fixed expectations.
- No benchmark result changes Core evidence, source files, relationships, or
  confidence values.
- Citation count is never used as a relevance or quality label.
- Model output is not used to grade model or retrieval output.
- Missing qualifier recall is visible rather than hidden behind fluent
  synthesis.

## Next slice

Wire the benchmark runner to the real `ke-ai ask` retrieval path and record the
measured cross-domain baseline at fixed cutoffs. Ranking changes should then be
made only against observed failures, with before/after benchmark results kept in
reviewable project history.
