# Knowledge Engine AI

The judgment layer for the [Knowledge Engine](https://github.com/jweter/knowledge-engine-core)
project: one Research Copilot orchestrating Retrieval, Evidence,
Analytical, and Discovery intelligences over `core`'s validated evidence
graph. See `knowledge-engine-core`'s `docs/ai_layer_architecture.md` for
the full architecture, and this repository's own `docs/ai_design.md` for
what this first milestone actually builds.

## Status

Early. `ke-ai ask` is Retrieval Intelligence over `core`'s corpus via
`ke evidence-report --format json`, attaching each matched claim's
Evidence Intelligence (Evidence Quality/Consensus/Claim Confidence/
Coverage) via `ke evidence-intelligence --format json` where a graph
claim exists. `--synthesize` (opt-in) has a local, offline LLM served by
[Ollama](https://ollama.com) (no API key, no cloud call) narrate that
same evidence into one grounded paragraph, citing an
`evidence_record_id` for every claim it states -- see
`docs/ai_design.md`'s "Decision: local LLM".

## The Seam

`core` locates, validates, and persists evidence. It never decides what
that evidence means for a person's actual question -- see
`knowledge-engine-core/docs/core_interface_contract.md`'s "The seam"
section. This project holds the exact same boundary, restated for a
judgment layer: the LLM explains, it never judges. Any confidence number
this project ever presents must decompose into named,
independently-inspectable components computed by this project's own
deterministic code -- never a bare model-generated percentage.
`--synthesize`'s local LLM is held to this directly: it is given only
already-computed fields (`claim_text`, `result_summary`, Evidence
Quality/Consensus/Claim Confidence) and told to cite an
`evidence_record_id` for every claim, never to introduce a new fact or
score. See `knowledge-engine-core`'s `docs/ai_layer_architecture.md`
before adding anything that might blur this line.

## Requirements

- Python 3.12+
- [Poetry](https://python-poetry.org/)
- `knowledge-engine-core`'s `ke` CLI, installed and on `PATH`
- A `knowledge-engine-core` SQLite database and corpus (`sources.csv`,
  `evidence_records.jsonl`) to point at
- [Ollama](https://ollama.com), installed and running (`ollama serve`),
  only if using `--synthesize`

## Installation

```bash
poetry install
```

## Quick Start

```bash
export KE_DATABASE_URL="sqlite:///path/to/knowledge_engine.sqlite3"
poetry run ke-ai ask "does semaglutide reduce lean mass" \
  --sources /path/to/sources.csv \
  --evidence /path/to/evidence_records.jsonl
```

Every paper and evidence record printed traces back to a real `ke
evidence-report` field. Default retrieval performs no synthesis. The command
may display core's deterministic Evidence Intelligence values, but this
repository does not compute them; `--synthesize` is the explicit opt-in path
described below.

Public entry points:

- [Project showcase](https://knowledge-engine.steelzombie9999.chatgpt.site/)
- [Working web alpha](https://knowledge-engine-web-alpha.onrender.com/)

This repository is an implementation layer behind that experience. Its job is
to improve traceable retrieval and carefully bounded narration, not to market
model output as scientific judgment.

To also have a local LLM narrate that same evidence into one grounded,
citation-required paragraph, install [Ollama](https://ollama.com), start
it, and pull a model once:

```bash
ollama serve &          # if not already running as a service
ollama pull qwen2.5:1.5b
export KE_AI_LLM_MODEL="qwen2.5:1.5b"
poetry run ke-ai ask "does semaglutide reduce lean mass" \
  --sources /path/to/sources.csv \
  --evidence /path/to/evidence_records.jsonl \
  --synthesize
```

No API key, no cloud call at inference time -- everything runs on the
local machine (`KE_AI_OLLAMA_HOST`/`--ollama-host` default to
`http://127.0.0.1:11434`, Ollama's own default). Any Ollama chat model
works via `--llm-model`/`KE_AI_LLM_MODEL`; see `docs/ai_design.md`'s
"Decision: local LLM" for model-choice guidance on real hardware.

## Architecture

This project never imports `knowledge_engine` as a Python package --
`core_interface_contract.md` is explicit that "there is no HTTP API, no
RPC layer, no Python package published for import today -- `ke
<command>` is the interface." Every call into `core` runs `ke` as a
subprocess with an explicit argument list (never `shell=True`, never
string-interpolated arguments) and parses its documented JSON contract.
See `docs/ai_design.md` for the full reasoning and this milestone's
scope.

## Federated discovery direction

A review of `surendranb/find-research-papers-mcp` identified useful patterns for
future Discovery Intelligence: common scholarly-provider contracts, OpenAlex,
Semantic Scholar, and arXiv as additional discovery sources, citation/reference
expansion, explicit provider degradation, and search-coverage provenance. We are
adopting those ideas in Knowledge Engine-native form rather than adding the
external MCP server as a foundational dependency.

Core will own provider transport, normalized candidates, search-run state,
identity, and provenance. This AI layer will eventually use those deterministic
facts to compile bounded research plans and Research ISA coverage criteria. It
must never invent provider coverage, treat citation count as evidence quality,
or let a provider/plugin define the project's research method. See
[`docs/roadmap/federated_discovery_orchestration_adoption.md`](docs/roadmap/federated_discovery_orchestration_adoption.md).

`ke-ai discover "<query>" --ledger-root <dir>` runs one federated discovery
search through Core's `ke federated-discover` and prints its recorded
per-provider coverage and (when Core's snapshot includes it)
provider-metadata-disagreement summary -- a direct, bounded way to exercise
`ke_client.federated_discover()` from this repository, standalone from a full
Research Copilot session. It is not yet part of `run_research_question`'s own
planning; deciding when a research task needs broader provider coverage is
AI-FRD-3's (Discovery-plan compiler) job.

## Roadmap

The repository family now follows one ordered project path: unify the public
showcase and live alpha; benchmark and improve Ask retrieval; complete one
defensible GLP-1/body-weight evidence map; begin structured Evidence and
Analytical Intelligence only over that evaluated foundation; then replace this
client's per-call core subprocesses with the read-only persistent host when its
deployment trigger is met. Core's `docs/roadmap.md` is canonical.

The first three shared tasks are:

1. Make the showcase, alpha, and repository documentation one coherent public
   journey with explicit trust boundaries.
2. Create a golden-question benchmark and improve retrieval ranking before
   expanding synthesis behavior.
3. Complete the GLP-1/body-weight evidence map that later Evidence and
   Analytical Intelligence can be evaluated against.

- `ke-ai ask` -- Retrieval Intelligence: natural-language question to
  ranked, source-linked evidence (done).
- `ke-ai ask` enriched with per-claim Evidence Intelligence and
  `--format json` (done) -- unblocked `knowledge-engine-web`'s
  question-first "Ask" page.
- `ke-ai ask --synthesize` -- a local, offline LLM narrates the
  retrieved evidence into one grounded, citation-required paragraph
  (done; see `docs/ai_design.md`'s "Decision: local LLM"). One-question-
  in, one-answer-out -- not multi-turn chat.
- Golden-question retrieval evaluation and structured multi-record Evidence
  Intelligence -- next, coordinated with the core and web roadmaps.
- Federated Discovery Intelligence -- after Core's provider-neutral Discovery
  Broker/search-run contracts are stable, consume explicit provider coverage,
  compile bounded search/citation-expansion plans, add coverage-aware Research
  ISA gates, and support repeatable freshness/counter-search workflows. See
  `docs/roadmap/federated_discovery_orchestration_adoption.md`.
- Analytical Intelligence -- begins only after the golden evidence map can
  exercise real agreement, disagreement, population differences, and missing
  evidence. Deterministic statistical checks precede broader narration.
- Discovery Intelligence -- later, after Analytical Intelligence and adequate
  relationship coverage; federated provider orchestration is one foundational
  capability for that stage, not permission to skip the evidence-quality gates.

## Repository Family

- [`knowledge-engine-core`](https://github.com/jweter/knowledge-engine-core)
  -- offline scientific document ingestion, evidence validation, and the
  knowledge graph this project reads from.
- [`knowledge-engine-web`](https://github.com/jweter/knowledge-engine-web)
  -- read-only presentation of `core`'s graph and evidence.
- `knowledge-engine-ai` (this repository) -- the judgment layer.

## License

MIT. See `LICENSE`.
