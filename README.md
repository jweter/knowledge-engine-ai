# Knowledge Engine AI

The judgment layer for the [Knowledge Engine](https://github.com/jweter/knowledge-engine-core)
project: one Research Copilot orchestrating Retrieval, Evidence,
Analytical, and Discovery intelligences over `core`'s validated evidence
graph. See `knowledge-engine-core`'s `docs/ai_layer_architecture.md` for
the full architecture, and this repository's own `docs/ai_design.md` for
what this first milestone actually builds.

## Status

Early. One real capability exists: `ke-ai ask`, Retrieval Intelligence
over `core`'s corpus via `ke evidence-report --format json`. No LLM
integration yet -- see `docs/ai_design.md`'s "no LLM integration yet"
decision.

## The Seam

`core` locates, validates, and persists evidence. It never decides what
that evidence means for a person's actual question -- see
`knowledge-engine-core/docs/core_interface_contract.md`'s "The seam"
section. This project holds the exact same boundary, restated for a
judgment layer: the LLM (once one is wired in) explains, it never
judges. Any confidence number this project ever presents must decompose
into named, independently-inspectable components computed by this
project's own deterministic code -- never a bare model-generated
percentage. See `knowledge-engine-core`'s `docs/ai_layer_architecture.md`
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
- Citation-grounded chat with individual papers -- needs an explicit
  LLM-provider decision first; see `docs/ai_design.md`'s open questions.
- Evidence Intelligence, Analytical Intelligence, Discovery Intelligence
  -- later stages in `knowledge-engine-core`'s `docs/ai_layer_architecture.md`
  build sequence.

## Repository Family

- [`knowledge-engine-core`](https://github.com/jweter/knowledge-engine-core)
  -- offline scientific document ingestion, evidence validation, and the
  knowledge graph this project reads from.
- [`knowledge-engine-web`](https://github.com/jweter/knowledge-engine-web)
  -- read-only presentation of `core`'s graph and evidence.
- `knowledge-engine-ai` (this repository) -- the judgment layer.

## License

MIT. See `LICENSE`.
