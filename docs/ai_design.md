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

**Revised (M2 slice):** `ke-ai ask` now also attaches each matched
evidence record's Evidence Intelligence (Evidence Quality/Consensus/
Claim Confidence/Coverage) via `core`'s new `ke evidence-intelligence
--format json` (`core`'s M63). This does **not** loosen the "no
Evidence Quality/Consensus/Claim Confidence scoring" boundary below --
this project still never *computes* any of those numbers; it only
*displays* numbers `core` already computed and stood behind elsewhere
(the same numbers `knowledge-engine-web`'s claim pages already show).
No new judgment, no cross-claim synthesis, still zero LLM calls. Built
to unblock the project owner's next priority: a question-first "Ask"
experience in `knowledge-engine-web`, which will shell out to `ke-ai
ask --format json` the same way this repository shells out to `ke`.

**Revised (M3 slice):** the project owner made the LLM-provider call
this document's original "Decision: no LLM integration yet" section
left open -- a local, offline model, not a hosted API (see "Decision:
local LLM" below, which replaces that section). `ke-ai ask --synthesize`
now has an LLM narrate the same evidence `--format json` already
exposes into one grounded paragraph, strictly constrained to cite an
`evidence_record_id` for every claim it states. This is the one place
in this project a model-generated string is allowed to appear -- see
`knowledge_engine_ai/synthesis.py`'s module docstring for exactly how
the seam still holds.

## Mission

Turn a natural-language research question into ranked, source-linked
evidence from `core`'s corpus -- Retrieval Intelligence, Phase 1 of the
five-stage build sequence `ai_layer_architecture.md` lays out. No
confidence *scoring* by this project (M1/M2's boundary, still held).
M3 adds one opt-in exception to "no LLM call": `--synthesize`, a local
model narrating that same retrieval into a grounded paragraph -- see
"Decision: local LLM" below.

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
    ke_client.py   -- subprocess wrapper: `evidence_report()` runs `ke
                       evidence-report --format json`; `evidence_intelligence()`
                       runs `ke evidence-intelligence --format json` for one
                       claim, returning `None` (not an error) when the
                       claim has no graph entry yet; `enriched_evidence_report()`
                       combines both -- retrieval, then a best-effort
                       Evidence Intelligence lookup per matched record.
                       Parses and validates each JSON contract, raises a
                       typed error on a schema mismatch or non-zero exit
                       (the "no graph claim" case excepted) rather than
                       silently returning partial data.
    models.py       -- frozen dataclasses mirroring both JSON contracts
                       (EvidenceReport, RetrievedPaper, EvidenceRecord,
                       EvidenceIntelligence and its four nested scores) --
                       typed, not a raw dict, so callers get autocomplete
                       and mypy coverage instead of string-keyed lookups.
    llm.py          -- `LocalLLM`, a one-method `Protocol` (`generate`),
                       and `OllamaLLM`, its only real implementation: a
                       bounded HTTP client (`urllib` only, no SDK) for a
                       running Ollama server's `/api/chat` endpoint. No
                       API key. Tests substitute a fake `OllamaTransport`
                       instead of requiring a real `ollama serve`
                       process and a downloaded model.
    synthesis.py    -- `build_synthesis_prompt`/`synthesize_answer`:
                       assembles a strict, evidence-only prompt from an
                       `EvidenceReport` (every `claim_text`/
                       `result_summary`/Evidence Intelligence number
                       already in it, nothing else) and calls a
                       `LocalLLM` to narrate it. Returns `None` without
                       calling the model at all when there is no
                       evidence to ground on.
    cli.py          -- `ke-ai ask QUESTION --sources ... --evidence ...
                       [--format text|json] [--synthesize] [--llm-model
                       NAME] [--ollama-host URL]`, a typer app printing
                       a compact, readable summary (or the full
                       structured result as JSON for a downstream
                       consumer like `knowledge-engine-web`).
                       `--synthesize` is opt-in and additive -- the
                       retrieval/Evidence Intelligence output is
                       unchanged either way.
```

## Decision: local LLM

**Owner decision (M3, revised):** local, offline inference served by
[Ollama](https://ollama.com) -- an open-weight model (e.g. Qwen, Gemma)
running on-machine via Ollama's own long-lived process (`ollama serve`),
not a hosted API. No `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`-style secret
anywhere in this project as a result. This resolves the original "no LLM
integration yet" open question below in favor of the option that needs
no key management at all: `ollama pull <model>` once, point
`--llm-model`/`KE_AI_LLM_MODEL` at that model's name, and it just runs
-- the same "download once, run offline" shape M31's local
`sentence-transformers` embedding generator already established in
`core`.

An earlier draft of this milestone loaded a GGUF model file directly
in-process via `llama-cpp-python`. The project owner's team recommended
Ollama instead, and this document agrees: Ollama's own long-running
process handles model download/management, quantization, GPU
acceleration, and memory across requests, so it doesn't reload a
multi-gigabyte model on every single `ke-ai ask` invocation the way an
in-process library would -- a real difference once this moves toward
serving more than one CLI call at a time. `LocalLLM`'s one-method
`Protocol` shape meant swapping the implementation touched only
`llm.py`; `synthesis.py` and `cli.py`'s public contract were unaffected.

Live-verified against the real GLP-1 corpus with `qwen2.5:1.5b` (a
small, non-reasoning instruction-tuned model, ~1GB, CPU-only, a few
seconds per question after Ollama's first load). Model choice is a
runtime/deployment decision, not hardcoded -- any Ollama chat model
works via `--llm-model`. The project owner's team specifically suggested
benchmarking `qwen3:8b` and `gemma3:4b`/`gemma3:12b` on real tasks once
running on real hardware; `--llm-model` supports switching without a
code change. Note: Qwen3's hybrid-reasoning models interleave a
`<think>...</think>` block into the same response field rather than a
separate one -- `llm.py` strips it before returning, so `synthesis.py`
never sees the model's internal reasoning as part of its answer.

`knowledge_engine_ai/llm.py` defines `LocalLLM` as a one-method
`Protocol` (`generate(prompt) -> str`), so `synthesis.py` and `cli.py`
never depend on Ollama's wire format directly and tests substitute a
fake `OllamaTransport` instead of requiring a real `ollama serve`
process and a downloaded model -- the same fake-transport pattern
`core` uses for its own live network lookups (e.g.
`knowledge_engine.rxnorm_http`).

`--synthesize` is opt-in, off by default: real local inference costs
real CPU time and requires Ollama running with a model already pulled,
unlike this command's default retrieval-only path. `ollama serve` itself
is a separate process this project does not manage or start -- see the
Out of scope section for the production-deployment implications of that
(a laptop cannot durably serve the AI layer to the public web; this
document scopes exactly the same "development is free, public
deployment needs its own architecture" split the project owner's team
raised).

## Historical: why this was deferred past M1/M2

`ai_layer_architecture.md`'s five-stage sequence puts "citation-grounded
chat with individual papers" inside Stage 1, but that specific piece
needed a real LLM-provider decision (which API, how keys are managed,
cost implications) this document did not make unilaterally -- a
product/infrastructure choice for the project owner, not something to
guess at. M1/M2 built everything in Stage 1 that did *not* require that
decision: natural-language search and structured, source-linked results.
M3 (above) is that next slice, now that the decision has been made.

## Out of scope (this milestone)

- **Conversational, multi-turn chat.** `--synthesize` (M3) is one
  question in, one grounded paragraph out -- no session state, no
  follow-up questions, no memory of a prior answer. Still Retrieval
  Intelligence's shape, not a chat product.
- **Any LLM call that is not `--synthesize`'s grounded narration.** No
  summarization of a whole paper, no cross-question reasoning, no
  freeform chat.
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
- **Computing Evidence Quality/Consensus/Claim Confidence** (as opposed
  to displaying `core`'s already-computed numbers, added in the M2
  revision above), Statistics Auditor, Discovery Intelligence, domain
  profiles -- all later stages in `ai_layer_architecture.md`'s
  sequence, not this one.
- **Running `ollama serve` for the user, or managing it as a service.**
  This project only ever calls the API a running Ollama process already
  exposes; it never starts, stops, or supervises that process itself.
- **A public-facing deployment of the LLM layer.** A laptop (or any
  single machine) running `ollama serve` is a real, working development
  setup, not a durable public architecture -- it disappears on sleep,
  reboot, or a lost connection, and Ollama's raw port should never be
  exposed directly to the Internet. Moving `--ollama-host` to point at a
  dedicated always-on machine (a home server, a rented GPU, a cloud
  instance) is future infrastructure work, not a code change here.

## Open questions (owner decisions, not resolved here)

- **Conversational, multi-turn chat**, if ever wanted -- `--synthesize`
  (M3) deliberately stays one-question-in, one-answer-out.
- **Model choice for `--synthesize`** beyond the live-verified default
  (`qwen2.5:1.5b`) -- a deployment/quality tradeoff for whoever runs
  this, not fixed by this document. Any Ollama chat model works via
  `--llm-model`; the project owner's team suggested benchmarking
  `qwen3:8b` and `gemma3:4b`/`gemma3:12b` against real extraction/
  synthesis tasks once running on real hardware.
- **Where Ollama itself runs in a public deployment** -- see the Out of
  scope bullet above. Not this document's call.
- **Package structure once a second capability exists** (Evidence
  Intelligence, Analytical Intelligence) -- not designed against one
  capability, revisit at the second real slice, the same discipline
  `web_design.md` applied to its own second-page question.
