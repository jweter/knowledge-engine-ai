# AI corpus and Ollama dependency audit (characterization)

Status: baseline audit at `8e8df4c0f9fb0c69bb6e3d43360ed99f9f37d424` (2026-11-02). This document describes existing behavior; it does **not** authorize removing a dependency or change any runtime path.

## Mandatory local-corpus inputs

| Existing path | Current requirement | Evidence |
| --- | --- | --- |
| `ke-ai ask` | `--sources` and `--evidence` are required existing filesystem paths, even when synthesis is disabled | `knowledge_engine_ai/cli.py`, `SourcesOption`/`EvidenceOption` and `ask` |
| `ke-ai research` | The same two required CLI options are passed to the research runner | `knowledge_engine_ai/cli.py`, `research` |
| `run_research_question` | Required `sources: Path` and `evidence: Path` are passed to the fixed-evidence workflow and optional grounded completion | `knowledge_engine_ai/copilot/run_research_question.py`, `run_research_question` |
| Fixed workflow and retrieval | `run_fixed_evidence_workflow` and `run_parallel_retrieval` require the two paths; the primary and contradiction-oriented retrieval branches use the indexed-evidence route | `knowledge_engine_ai/orchestrator/workflow.py`, `knowledge_engine_ai/orchestrator/parallel_retrieval.py` |
| Core CLI boundary | `evidence_report` unconditionally invokes `ke evidence-report ... --sources PATH --evidence PATH --format json`; `enriched_evidence_report` uses the same local-input boundary | `knowledge_engine_ai/ke_client.py` |
| Follow-on retrieval and benchmarks | The optional grounded-completion/re-retrieval path and corpus retrieval benchmark also accept explicit local source/evidence paths | `knowledge_engine_ai/copilot/grounded_completion.py`, `knowledge_engine_ai/copilot/research_freshness.py`, `knowledge_engine_ai/retrieval_benchmark_runner.py` |

These are **hard requirements of the current entrypoints**, not evidence that online-only research is impossible elsewhere in Core. Core now has the separate corpus-free `ke online-research` / `ke online-evidence-validate` CLI contract. This audit does not claim that the existing AI `evidence_report` wrapper already consumes that contract.

## Model dependencies and distinctions

| Existing path | Current requirement | Evidence |
| --- | --- | --- |
| `ke-ai ask` without `--synthesize` | **No Ollama requirement**: deterministic retrieval remains available with local corpus inputs | `knowledge_engine_ai/cli.py`, `ask` |
| `ke-ai ask --synthesize` | Requires a model name (`--llm-model` or `KE_AI_LLM_MODEL`) and constructs `OllamaLLM` | `knowledge_engine_ai/cli.py`, `ask` |
| `ke-ai research` | **Hard CLI model requirement**: without a model name it exits before invoking the research runner; when supplied it constructs `OllamaLLM` | `knowledge_engine_ai/cli.py`, `research` |
| `run_research_question` and downstream planner/report synthesis | Require an injected `LocalLLM` interface; **not** inherently a hard Ollama dependency because test or alternate implementations can satisfy the protocol | `knowledge_engine_ai/copilot/run_research_question.py`, `copilot/planner.py`, `copilot/research_report.py` |
| Research benchmark CLI | Requires a model name and constructs `OllamaLLM` for the benchmark, independently of the user-facing report entrypoint | `knowledge_engine_ai/research_benchmark_cli.py` |

Online federated discovery is currently opt-in (`--broaden-search-on-gap`), and it does not replace the mandatory local source/evidence arguments in `ke-ai research`. See `knowledge_engine_ai/cli.py` and `copilot/discovery_policy.py`.

## Characterization and next implementation boundary

`tests/test_corpus_ollama_dependency_audit.py` pins the current CLI rejection behavior and required Python call signatures without contacting Core, Ollama, or providers. These tests are deliberately expected to change when the next authorized `ai-online-evidence-orchestration` slice removes the old hard prerequisites.

Next slice: add an explicit opt-in AI adapter consuming Core's versioned online evidence bundle through the supported CLI boundary, then route the one-request report workflow through it without making Ollama or a pre-ingested corpus mandatory. Preserve existing `ask`/`research` behavior until compatibility tests and Core/Web consumer checks justify a migration. Keep intermediate evidence bounded, verifiable, and cleaned up; reject ungrounded claims and unavailable-source citations.
