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
claim exists. `--synthesize` (opt-in) has a local, offline LLM
(`llama-cpp-python`, no API key) narrate that same evidence into one
grounded paragraph, citing an `evidence_record_id` for every claim it
states -- see `docs/ai_design.md`'s "Decision: local LLM".

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
evidence-report` field. No synthesis, no confidence rating.

To also have a local LLM narrate that same evidence into one grounded,
citation-required paragraph, download a small instruction-tuned GGUF
model once:

```bash
curl -L -o qwen2.5-1.5b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
export KE_AI_LLM_MODEL_PATH="$(pwd)/qwen2.5-1.5b-instruct-q4_k_m.gguf"
poetry run ke-ai ask "does semaglutide reduce lean mass" \
  --sources /path/to/sources.csv \
  --evidence /path/to/evidence_records.jsonl \
  --synthesize
```

No API key, no network call at inference time -- everything runs on the
local machine.

## Architecture

This project never imports `knowledge_engine` as a Python package --
`core_interface_contract.md` is explicit that "there is no HTTP API, no
RPC layer, no Python package published for import today -- `ke
<command>` is the interface." Every call into `core` runs `ke` as a
subprocess with an explicit argument list (never `shell=True`, never
string-interpolated arguments) and parses its documented JSON contract.
See `docs/ai_design.md` for the full reasoning and this milestone's
scope.

## Roadmap

- `ke-ai ask` -- Retrieval Intelligence: natural-language question to
  ranked, source-linked evidence (done).
- `ke-ai ask` enriched with per-claim Evidence Intelligence and
  `--format json` (done) -- unblocked `knowledge-engine-web`'s
  question-first "Ask" page.
- `ke-ai ask --synthesize` -- a local, offline LLM narrates the
  retrieved evidence into one grounded, citation-required paragraph
  (done; see `docs/ai_design.md`'s "Decision: local LLM"). One-question-
  in, one-answer-out -- not multi-turn chat.
- Analytical Intelligence, Discovery Intelligence -- later stages in
  `knowledge-engine-core`'s `docs/ai_layer_architecture.md` build
  sequence.

## Repository Family

- [`knowledge-engine-core`](https://github.com/jweter/knowledge-engine-core)
  -- offline scientific document ingestion, evidence validation, and the
  knowledge graph this project reads from.
- [`knowledge-engine-web`](https://github.com/jweter/knowledge-engine-web)
  -- read-only presentation of `core`'s graph and evidence.
- `knowledge-engine-ai` (this repository) -- the judgment layer.

## License

MIT. See `LICENSE`.
