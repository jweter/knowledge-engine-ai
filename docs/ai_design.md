# AI Design: First Slice (Retrieval Intelligence)

Status: implementation-ready design for this repository's first
milestone, the same role `knowledge-engine-web`'s `docs/web_design.md`
played for its own first slice. The full architecture this milestone is
one piece of -- one Research Copilot orchestrating Retrieval/Evidence/
Analytical/Discovery intelligences, the three-way confidence split,
domain-specific profiles -- is designed in `knowledge-engine-core`'s
`docs/ai_layer_architecture.md` and `docs/ai_interface_layer_scoping.md`.
This document does not repeat that; it scopes down to what this
milestone actually builds and why, the same "smallest honest version
first" discipline `web_design.md` followed for its own bootstrap.

## Mission

Turn a natural-language research question into ranked, source-linked
evidence from `core`'s corpus -- Retrieval Intelligence, Phase 1 of the
five-stage build sequence `ai_layer_architecture.md` lays out. No
synthesis, no confidence scoring, no LLM call yet. Those are named,
sequenced, and deliberately deferred, not omitted by oversight.

## The seam (restated, inherited without exception)

Same boundary every `core` and `knowledge-engine-web` milestone has
held: this project never sets or infers `research_question`/
`evidence_direction` on a stored record, never invents a confidence
number not traceable to a real signal, and never presents this
milestone's output as more than what it is -- retrieval results, not a
judged answer. `ai_layer_architecture.md`'s "seam applies to all three
[now four] engines, without exception" section is the concrete
statement of this; nothing here loosens it.

## Decision: shell out to `ke`, never import `knowledge_engine`

Same reasoning `knowledge-engine-web`'s `web_design.md` already worked
through and confirmed by direct testing: `core_interface_contract.md`
is explicit that "there is no HTTP API, no RPC layer, no Python package
published for import today -- `ke <command>` is the interface."
Importing `knowledge_engine` would pull in its full dependency set
(`torch`, `sentence-transformers`, `faiss-cpu`) for a project that only
needs to invoke one CLI command and parse its JSON output. Every call
into `core` goes through `subprocess.run([...])` with an explicit
argument list -- never `shell=True`, never string-interpolated
arguments -- and parses the documented, versioned JSON contract
(`schema_version` in `ke evidence-report --format json`'s output),
not scraped console text.

## What this milestone builds

One real capability: given a natural-language question, run `ke
evidence-report <question> --sources <path> --evidence <path> --format
json`, parse the result, and return it as a structured Python object
(and a CLI command, `ke-ai ask`, that prints a compact summary of it).
That command was itself added to `core` (`docs/roadmap.md`'s
Unreleased `--format json` entry) specifically to unblock this
milestone with a real, structured, documented contract instead of
scraped prose.

```
$ ke-ai ask "does semaglutide reduce lean mass" \
    --sources /path/to/sources.csv \
    --evidence /path/to/evidence_records.jsonl

Question: does semaglutide reduce lean mass
Evidence summary: 156 records (156 draft, 0 reviewed)

1. Personalized Combination of a Ketogenic Diet and Low-Dose Semaglutide...
   DOI: 10.3390/jpm16060313 -- 2026
   Matched: semaglutide OR reduce OR lean OR mass
   Evidence records: 0

2. GLP-1 Receptor Agonists for Obesity Management in Older Adults...
   ...

This is retrieval plus recorded evidence only. No scientific synthesis
has been performed.
```

Every line traces back to a real `ke evidence-report` field -- nothing
here is generated, summarized, or reworded by a model.

## Architecture

```
knowledge_engine_ai/
    ke_client.py   -- subprocess wrapper: runs `ke evidence-report
                       --format json`, parses and validates the JSON
                       contract, raises a typed error on a schema
                       mismatch or non-zero exit rather than silently
                       returning partial data.
    models.py       -- frozen dataclasses mirroring the JSON contract
                       (EvidenceReport, RetrievedPaper, EvidenceRecord)
                       -- typed, not a raw dict, so callers get
                       autocomplete and mypy coverage instead of
                       string-keyed lookups.
    cli.py          -- `ke-ai ask QUESTION --sources ... --evidence ...`,
                       a typer app printing a compact, readable summary.
```

## Decision: no LLM integration yet

`ai_layer_architecture.md`'s five-stage sequence puts "citation-grounded
chat with individual papers" inside Stage 1, but that specific piece
needs a real LLM-provider decision (which API, how keys are managed,
cost implications) this document does not make unilaterally -- a
product/infrastructure choice for the project owner, not something to
guess at. This milestone builds everything in Stage 1 that does *not*
require that decision: natural-language search and structured,
source-linked results. Conversational chat over individual papers is
the next real slice once that decision is made.

## Out of scope (this milestone)

- **Any LLM call, of any kind.** No synthesis, no chat, no summarization.
- **PICO-shaped query decomposition.** `ai_layer_architecture.md`'s
  Phase 1 names this; it is closer to a judgment call (parsing informal
  free text into P/I/C/O) than the parts already deterministic in
  `core`'s own `evidence-report`. Left for a follow-up slice once real
  usage shows what decomposition would actually help with.
  `evidence-report`'s own FTS5-based natural-language retrieval already
  handles free-text questions reasonably without it.
- **Semantic/vector search.** `ke fused-search`/`ke vector-search`
  require a prebuilt local FAISS index and an embedding-generator
  choice -- real setup this milestone does not assume exists. FTS5
  lexical retrieval (what `evidence-report` already uses) needs no such
  setup and is a real, working starting point.
- **Evidence Quality/Consensus/Claim Confidence scoring**, Statistics
  Auditor, Discovery Intelligence, domain profiles -- all later stages
  in `ai_layer_architecture.md`'s sequence, not this one.

## Open questions (owner decisions, not resolved here)

- **LLM provider and key management**, once Stage 1's conversational
  piece is actually built.
- **Package structure once a second capability exists** (Evidence
  Intelligence, Analytical Intelligence) -- not designed against one
  capability, revisit at the second real slice, the same discipline
  `web_design.md` applied to its own second-page question.
