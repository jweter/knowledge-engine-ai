# BT-0 — end-to-end research benchmark

Status: implemented on the BT-0 branch  
Parent: #84  
Benchmark tracking: #91

## Purpose

The General Question Research Loop now has an executable path from an indexed miss through discovery, acquisition, grounded EvidenceRecord promotion, original-question re-retrieval, synthesis, verification, and session close. The next engineering question is no longer "is the bridge wired?" but "what actually happens on a fresh question, where does time go, and does the second run reuse work?"

`knowledge_engine_ai.research_pipeline_benchmark` projects the normal `ResearchQuestionResult` into a stable engineering benchmark document. It does not change evidence adequacy or scientific interpretation.

## Stable output

Each benchmark run records:

- question and normalized fingerprint;
- cold vs warm run marker;
- session identity;
- evidence-store revision before the run;
- wall-clock question-to-report duration;
- known time to first grounded information when every required trace stage is timed;
- deterministic AI research state;
- whether the narrative passed release gates;
- whether post-promotion re-retrieval actually supplied synthesis evidence;
- provider attempts/outcomes and degradation count;
- discovery candidate count;
- acquisition-plan dispositions;
- acquisition attempts, persisted papers, and reuse;
- extraction/classification/grounding/promotion counts;
- re-retrieval attempt count;
- the existing deterministic stage bottleneck report;
- cold-to-warm speedup and whether warm-run reuse was observed.

Unknown timing remains `null`; the benchmark does not turn an untimed stage into zero milliseconds.

## CLI

```bash
ke-ai-research-benchmark run \
  "In healthy adults, does listening to music during exercise improve endurance performance compared with exercising without music?" \
  --sources /absolute/path/to/sources.csv \
  --evidence /absolute/path/to/evidence.jsonl \
  --session-db /absolute/path/to/benchmark-sessions.sqlite3 \
  --ledger-root /absolute/path/to/federated-ledger \
  --papers-dir /absolute/path/to/research-papers \
  --llm-model qwen2.5:1.5b \
  --ke-executable ke \
  --repeats 2 \
  --scenario-id fresh-music-endurance \
  --output benchmark.json
```

The same mutable evidence store and acquisition directories are retained across repetitions. Run 1 is labeled `cold`; later runs are labeled `warm`. This is intentional: the benchmark is specifically checking whether a repeated/related research request benefits from already indexed or previously acquired material.

## Fresh-question acceptance case

The first non-project question selected for this benchmark is:

> In healthy adults, does listening to music during exercise improve endurance performance compared with exercising without music?

Before the benchmark branch was created, repository code and issue searches across AI/Core/Web returned no match for this question/topic phrase. It is therefore a fresh General Question Research Loop exercise rather than another GLP-1, Monster Energy, creatine, or existing fixture replay.

## Interpretation

A benchmark run can end successfully, partially, provider-degraded, insufficient-evidence, or blocked. Those outcomes are measurements. A run that reaches discovery but cannot acquire eligible full text is still useful because the funnel identifies the drop-off. Likewise, an untimed acquisition/extraction stage is reported as an instrumentation bottleneck rather than hidden.

The benchmark is the baseline for BT-5 latency work. Optimization should follow measured stage/funnel evidence instead of guessing whether subprocess startup, provider latency, acquisition, grounding, or synthesis is dominant.
