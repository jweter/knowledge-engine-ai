# Web Integration — Making the Orchestrator the Live Product

Status: design + step-wise execution plan, nothing implemented yet. This
document exists so anyone (including a future instance of the agent that
wrote it) can pick this up cold and know exactly what is built, what is
missing, and what the next concrete step is.

## The gap this closes

`docs/roadmap/long_term_vision.md` (in `knowledge-engine-core`) names the
actual finished product:

> The finished product is a live, AI-powered search and discovery engine.
> A person asks a real research question; the system searches and reasons
> across the evidence `core` has validated and the connections the
> Knowledge Graph has modeled, and returns a report scoped to that
> specific question — with an explicit confidence rating, not just a list
> of matching papers.

As of 2026-08-11, that experience does not exist anywhere a person can
actually reach it. This is not a capability gap — AI-O1 through AI-O9 are
built, tested, and merged in this repo. It is a **wiring** gap, and it is
worse than it first looks: there are three disconnected layers, not one
missing connection.

### Layer 1: the orchestrator is built but nothing calls it

`knowledge_engine_ai/orchestrator/` contains a complete pipeline:

- `parallel_retrieval.run_parallel_retrieval` — primary + contradiction-oriented
  retrieval, concurrent (AI-O5).
- `workflow.run_fixed_evidence_workflow` — composes retrieval + Evidence
  Intelligence + optional evidence-map/statistical-verification steps,
  recording every step as a durable `ResearchEvent` (AI-O3/AI-O5).
- `verification.verify_synthesis` — the Skeptic step: checks a synthesized
  narrative against the evidence it claims to summarize (AI-O6).
- `session_report.build_session_report` — assembles a final, source-linked
  report (AI-O7).
- `close_gate.attempt_session_close` — the ISA-gated close condition
  (AI-O2's Research ISA contract).
- `observability.build_session_trace` / `render_session_trace` — the full
  "what ran, why, what it cost" trace (AI-O9).

Grepping the whole repo for callers of these five functions outside
`tests/` and each other's own docstrings returns **nothing**. No CLI
command, no script, nothing in this repo actually runs the composed
pipeline end to end. `model_benchmark.py` mentions `verify_synthesis` and
`plan_from_question` in a comment, but doesn't call them either.

### Layer 2: this repo's own CLI bypasses its own orchestrator

`knowledge_engine_ai/cli.py`'s only command, `ke-ai ask`, calls
`ke_client.enriched_evidence_report` (one `ke evidence-report` +
`ke evidence-intelligence` shell-out) and, if `--synthesize` is passed,
`synthesis.synthesize_answer` directly. It never touches
`knowledge_engine_ai.orchestrator` or `knowledge_engine_ai.sessions` at
all. There is no session created, no plan, no parallel/contradiction
retrieval, no skeptic verification, no trace. `ke-ai ask` today is
strictly simpler than what AI-O1-O9 already built.

### Layer 3: `knowledge-engine-web`'s `/ask` doesn't call this repo at all

`knowledge_engine_web/main.py`'s `ask()` route calls `core`'s own
`retrieval.py` (`answer_retrieval`) directly and has its **own**,
independent `knowledge_engine_web/synthesis.py` +
`knowledge_engine_web/OllamaLLM` wrapper — a second, simpler
reimplementation of roughly what `ke-ai ask` already does, built without
ever importing `knowledge_engine_ai`. There is no `ai_client.py` or
equivalent anywhere in the web repo.

**Net effect:** three real things exist (the orchestrator, the simple ai
CLI, the simple web page), and none of them talk to each other. Fixing
this is not "add an API endpoint" — it's composing Layer 1 into something
callable for the first time, then routing Layer 3 through it instead of
its own reimplementation.

## Architecture decision: library integration, not a standalone service

`docs/roadmap/future_ai_orchestration_plan.md` (this repo) already names
a future direction: *"The raw Ollama port should not be exposed directly
to the public internet. The orchestration service owns authentication,
rate limits, job limits, permissions, model routing, tracing,
cancellation, and timeouts."* That describes a real deployed service with
its own API, auth, and independent scaling — appropriate once there is a
second consumer of the orchestrator, or real multi-tenant load to manage.

That is not this project's situation today. `knowledge-engine-web` is a
single Render service, low traffic, alpha-stage, basic-auth-gated. One
concrete fact makes a separate service the wrong choice **for this
phase**, and one earlier claim in this section needs a correction:

1. **`knowledge-engine-ai` has no web-framework dependency today**
   (`pyproject.toml`: `typer`, `click`, `rich` — nothing else). Building a
   real service means adding an HTTP framework, auth, a second Docker
   image, a second corpus-data copy baked into that image (the way
   `knowledge-engine-web`'s own `Dockerfile` already bundles a snapshot),
   a second Ollama reachability story, and a second deploy pipeline to
   operate — real, ongoing infrastructure cost for zero current
   multi-tenant need.
2. **Correction (found during AI-O13, not caught before this doc
   merged): `knowledge-engine-web` does *not* already import
   `knowledge-engine-core` as a Python package.** Verified directly
   against `knowledge-engine-web`'s own `pyproject.toml` (no `core`
   dependency listed) and `docs/web_design.md`'s own "Decision: read
   `core`'s SQLite database via SQLAlchemy reflection, not by
   redeclaring its schema" section, which explains that `web`
   deliberately reads `core`'s database via reflection *specifically to
   avoid* a Python-package dependency on `core`. `web` today has zero
   ML dependencies (no `torch`, `sentence-transformers`, `faiss-cpu`,
   `qdrant-client`) -- the earlier claim that adding `ai` "costs almost
   nothing next to" an existing `core` dependency was wrong; there is no
   existing `core` dependency to compare against.

   The real cost is materially different: `knowledge_engine_ai`'s
   retrieval shells out to the `ke` CLI (`ke_client.py`'s subprocess
   boundary, unchanged by this decision), so `run_research_question`
   only actually *works* in `web` -- not just imports cleanly -- once
   `ke` is on `PATH`, which means `web`'s deployment needs `core`'s full
   dependency stack, torch included, for the first time. `web`'s data
   snapshot also has no `sources.csv` today (only
   `evidence_records.jsonl` and a SQLite DB), another precondition `ke
   evidence-report` needs that this plan did not originally account
   for.

   This is a real, non-trivial deployment-weight question -- but it is
   the same shape of gap this plan already named and deferred rather
   than silently assumed away: the "no LLM inference in production
   today" precondition below. Both are scoped to AI-O16 (guardrails for
   a real, publicly-reachable endpoint) and AI-O17's public-alpha half,
   not a blocker for AI-O13/AI-O14's local/dev-scoped work. The decision
   below still stands on fact 1 alone -- avoiding a second service, a
   second auth story, and a second deploy pipeline for a consumer that
   does not yet exist -- it just no longer stands on a "this is nearly
   free" claim that was never true.

**Decision:** `knowledge-engine-web` adds `knowledge-engine-ai` as a
direct Python dependency and calls the orchestrator in-process, in the
same request/response cycle, the same way it already calls `core`.
`knowledge_engine_ai.orchestrator`'s subprocess boundary into `core`
(`ke_client.py`) stays exactly as it is — this decision only changes how
*web* reaches *ai*, not how *ai* reaches *core*.

**Deferred, not rejected:** extracting the orchestrator into a real
standalone service (auth, rate limits, its own deploy) is named as AI-O18+
below — the right move once there is a second consumer of the
orchestrator, or real production load that justifies independent
scaling/auth. Building that now, for one low-traffic consumer, would be
exactly the kind of premature infrastructure this project's own
engineering discipline (see `CLAUDE.md`-style guidance across every
design doc in this repo) argues against.

### This reopens a prior `knowledge-engine-web` decision — on purpose

`knowledge-engine-web/docs/web_design.md`'s existing "Decision: local
LLM" section already considered and explicitly rejected a
`knowledge-engine-ai` dependency — but for a much smaller case: reusing
`ai`'s ~150-line `llm.py`/`synthesis.py` pair, which `web` chose to
hand-duplicate instead ("its own CLI-only dependencies (`typer`,
`click`, `rich`), unused in a FastAPI server -- just to reuse ~150 lines
with no `knowledge_engine_web`-specific coupling to begin with"). That
reasoning was correct for that decision and remains correct for it —
this plan does not undo it by itself.

What changes the calculus here is the size and nature of what's being
reused: not ~150 lines of Ollama-calling boilerplate, but the entire
composed orchestrator — durable sessions, parallel/contradiction
retrieval, skeptic verification, session reporting, the ISA close gate,
observability tracing. Hand-duplicating that into `knowledge-engine-web`
would mean maintaining two copies of real, evolving decision logic in
permanent lockstep, not two copies of a stable wire-format client. AI-O13
should supersede the "Decision: local LLM" section's dependency
reasoning explicitly when it lands (update that section in
`knowledge-engine-web`'s own design doc rather than leaving two
contradictory rationales on record), while leaving its actual
`llm.py`/`synthesis.py` duplication as-is unless AI-O14's route change
happens to retire those modules by replacing what calls them.

### A precondition this plan does not solve: the deployed alpha has no LLM inference at all

`knowledge-engine-web/docs/web_design.md`'s same section states this
plainly: *"The hosted Render alpha deliberately presents retrieval-only
Ask until it gets a separately hosted, secured, and operationally
durable inference architecture -- not attempted here. Exposing a
laptop's Ollama listener to the public internet is not that
architecture."* That gap is still open today and this plan does not
close it. AI-O12 through AI-O14 are fully buildable, testable, and
live-verifiable in a local/dev environment exactly the way every AI-O
milestone in this repo already has been (a local `ollama serve` +
`qwen2.5:1.5b`/`qwen3:4b`, the same pattern used throughout this
project's history) — that is real, valid progress and should not wait on
the deployment question. But AI-O17's "live end-to-end verification
against the real deployed web page" cannot be fully honest about the
*public* alpha until a durably-hosted Ollama (or an equivalent local,
offline-inference-compliant architecture — this project's own "never a
hosted API" decision in `ai_design.md` still applies) exists somewhere
Render can reach. Treat that as a real, separate, not-yet-scoped
precondition for AI-O17's public-facing half, not something AI-O15/AI-O16
implicitly solve by naming session-persistence and rate-limit
guardrails. Whoever picks up AI-O17 should scope that hosting question
explicitly before claiming the vision-doc close, not discover it then.

## The step-wise plan: AI-O12 through AI-O17

Naming: this project's `AI-O#` sequence (Research Plan Contract through
Observability, AI-O1-O9 built, AI-O10/AI-O11 named and gated) is the
established, proven numbering for every milestone in this repo — this
initiative continues that same sequence as `AI-O12` through `AI-O17`
rather than inventing a separate prefix. `AI-O10` (Discovery
Intelligence) and `AI-O11` (Hypothesis Assistance) stay exactly where
they are, still gated on their own named prerequisites; `AI-O12` starting
before they're built is not a reordering or a skip, it's simply the next
increment of work this project chose to do next — the same way `core`'s
own `M#` sequence has never required strict in-order completion (see,
for example, `M71`/`M72`/`M73` landing independently of any gap elsewhere
in that sequence).

Each step below is meant to be independently buildable, tested, and
merged — matching this project's established per-milestone discipline
(design → implement → test → live-verify against real data → docs →
quality gate → PR → merge) used for every `M#`/`AI-O#` milestone so far.
Update this document's **Status** line for each step as it lands; do not
let it drift out of sync with reality the way task-tracking elsewhere in
this project's history sometimes has.

### AI-O12: Compose the orchestrator into one callable pipeline

**Status: done.** `knowledge_engine_ai/copilot/run_research_question.py`'s
`run_research_question` composes all seven steps below into one call, with
full unit-test coverage and a new `ke-ai research` CLI command that
exercises it live. Live-verified against the real GLP-1 corpus with real
Ollama models across three runs, each a different real outcome: a Skeptic
verification catching a small model's missing citations and correctly
blocking session close; a clean vacuous-pass completion when no evidence
had a stated claim to narrate; and a pre-existing `llm.py` bug (a slow
generation's response-read timeout escaping `LocalLLMError` unwrapped)
that this live run surfaced and that is now fixed with a regression test.
See `CHANGELOG.md` for the full account. AI-O13 is next.

**Problem:** Layer 1 above — nothing composes
`run_fixed_evidence_workflow` → `verify_synthesis` →
`build_session_report` → `attempt_session_close` →
`build_session_trace` into one call. This is the actual missing piece;
everything else in this plan depends on it existing.

**Deliverable:** a new function, `run_research_question` (proposed
location: `knowledge_engine_ai/copilot/run_research_question.py`, since
`knowledge_engine_ai/copilot/` already holds the Research Plan Contract
pieces this composes with), with a signature roughly:

```python
def run_research_question(
    question: str,
    *,
    session_repository: SessionRepository,
    sources: Path,
    evidence: Path,
    llm: LocalLLM,  # for synthesis + verification
    limit: int = 5,
    external_discovery: ExternalDiscoveryCallable | None = None,
    ke_executable: str = "ke",
) -> ResearchQuestionResult:
    """Create a session, run the fixed workflow, synthesize, verify, close, trace."""
```

Concretely, in order:

1. `session_repository.create_session(question)` (AI-O2).
2. `run_fixed_evidence_workflow(...)` (AI-O3/AI-O5) — retrieval +
   Evidence Intelligence, both branches.
3. `synthesize_answer(...)` (existing `synthesis.py`) over the primary
   branch's `EvidenceReport`.
4. `verify_synthesis(narrative, report)` (AI-O6) — the Skeptic check. If
   verification fails, the result must say so explicitly, not silently
   drop the failure — matching `run_fixed_evidence_workflow`'s own "record
   failure, don't stop" discipline.
5. `build_session_report(...)` (AI-O7) — the assembled, source-linked
   final report.
6. `attempt_session_close(...)` (AI-O2's ISA contract) — whether this
   session's own completion criteria are actually met.
7. `build_session_trace(...)` (AI-O9) — for the observability view.

**Definition of done:**
- New module with full unit test coverage (fake `SessionRepository`, fake
  `LocalLLM`, following the `_FakeLLM`/`FakeTransport` pattern already
  used throughout this repo's tests).
- `ke-ai` gets a new command (or a flag on the existing `ask`, decide
  during implementation which reads better) that calls
  `run_research_question` instead of the simple path, so the composed
  pipeline is exercisable and live-verifiable from the CLI *before* web
  ever touches it — dogfooding the same discipline `ke-ai ask
  --synthesize` already established.
- Live-verified against a real corpus with a real Ollama model: a real
  question produces a real session with a real trace, read in full (not
  just checked for a non-error exit code) — matching every prior AI-O
  milestone's own verification bar.
- Quality gate green (`ruff format --check .`, `ruff check .`, `mypy
  knowledge_engine_ai tests`, `pytest`), docs, `CHANGELOG.md`, PR, merge.

### AI-O13: Add `knowledge-engine-ai` as a `knowledge-engine-web` dependency

**Status: implemented in `knowledge-engine-web` PR
[#41](https://github.com/jweter/knowledge-engine-web/pull/41).**

**Corrected premise (see the Architecture decision section above for the
full account):** `knowledge-engine-web` has **no** existing
`knowledge-engine-core` dependency to match the shape of -- it reads
`core`'s SQLite database via reflection specifically to avoid one.
`knowledge-engine-ai`'s own dependencies (`typer`/`click`/`rich`) are
light, but `ai`'s retrieval shells out to the `ke` CLI, so making
`run_research_question` actually work (not just import) in `web`
requires `core`'s full dependency stack -- torch included -- on `web`'s
`PATH` too. This is a real Docker-image-weight change, not a
non-event; verify it live and record the actual before/after image
size rather than assume it is small.

**Deliverable:**
- `knowledge-engine-web`'s `pyproject.toml` gains a
  `knowledge-engine-ai` dependency (a git dependency pointing at this
  repo, since there is no shared package registry between these sibling
  repos and no existing `core`-dependency precedent to match).
- Document the Docker-image-weight finding above rather than assume
  it away; the actual `web` Docker build (pulling in `core` too, for
  `ke` on `PATH`) is deferred to AI-O16 territory, not required for
  this step's own definition of done below.
- Decide and document the config surface: session-database path
  (`KE_AI_SESSION_DB_PATH` or similar — new env var), which `KE_WEB_*`
  values (Ollama host/model) get reused vs. need `KE_AI_*` siblings, and
  the new `sources.csv` config `web` has never needed before today
  (its data snapshot currently ships `evidence_records.jsonl` and a
  SQLite DB, not a `sources.csv` -- `ke evidence-report` needs both).
  Prefer reusing web's existing settings where the meaning is identical
  (e.g. one Ollama host, one model) — don't invent a second config
  surface for the same value.

**Delivered behavior:** `knowledge-engine-web` imports the immutable
`knowledge-engine-ai` revision declared in its dependency metadata,
wires corpus and session settings through its real `Settings` object,
and proves `run_research_question` callability with a real subprocess
boundary and SQLite session persistence. Shipping the heavier core
runtime and a hosted model remains a deployment concern rather than an
assumption hidden inside this dependency milestone.

**Definition of done:** `knowledge_engine_ai.copilot.run_research_question`
is importable and callable from a `knowledge_engine_web` test, using
web's real settings wiring and real corpus data (proving genuine
callability, not just a clean import). No route changes yet, and no
requirement that `web`'s own Docker/deployment story handle this yet —
this step is purely "the dependency exists, is wired to config, and is
provably callable," so AI-O14 is a smaller, more reviewable diff and
AI-O16 is where the deployment-weight question gets solved for real.

### AI-O14: Route `/ask` through the orchestrator

**Status: implemented in `knowledge-engine-web` PR
[#49](https://github.com/jweter/knowledge-engine-web/pull/49).**

**Deliverable:** `knowledge_engine_web/main.py`'s `ask()` route calls
`run_research_question` instead of its own direct `answer_retrieval` +
`synthesize_answer` reimplementation. New template sections for:

- The plan/session identity (so a person can see this was a structured
  run, not a black box).
- Both retrieval branches' summary — primary and contradiction-oriented
  — including the real recall-gain signal
  (`contradiction_only_evidence_record_ids`) AI-O5 already computes, so
  "this system checks for contradicting evidence" becomes a real,
  visible claim instead of an internal implementation detail nobody
  outside this repo's tests ever sees.
- The Skeptic verification result (AI-O6) — shown honestly whether it
  passed or flagged something, not hidden on a pass and only shown on a
  failure.
- A link/expander to the full session trace (AI-O9's
  `render_session_trace`) for anyone who wants the "what ran, why, what
  it cost" detail.

**Trust-language discipline:** every existing label this project has
built (`docs/public_journey_design.md`'s Shared Trust Language,
`templates/ask.html`'s existing "AI-generated, not reviewed" framing)
must still be accurate after this change — a synthesized narrative that
now passed Skeptic verification is a *stronger* claim than before and
should say so, but "verified" here means "checked against the retrieved
evidence for internal consistency," not "confirmed true" — get this
distinction right in the copy, the same care `templates/relationship_candidates.html`'s
M72 rewrite (see `knowledge-engine-web`'s own recent history) already
modeled for a structurally similar claim.

**Delivered behavior:** `/ask` invokes `run_research_question` only when
the static capability gate confirms the model, corpus files, `ke`
executable, and writable session store are available. The page renders
the durable session ID, workflow health, close-gate and verification
state, AI-generated narrative, and resolved source citations.

Deterministic web retrieval deliberately remains the primary and
always-available path. This corrects the original definition-of-done
language above: the old direct *AI narration* path was retired, but
direct deterministic retrieval was not removed. If the composed AI
runtime is incomplete or fails, `/ask` fails closed to retrieval-only
output instead of making the scientific question unavailable.

The Render alpha remains retrieval-only. AI-O14 did not quietly add the
core runtime, corpus inputs, persistent storage, or hosted Ollama
service needed for a public Research Copilot run. Full implementation
and test details live in `knowledge-engine-web`'s
`docs/ai_o14_capability_gated_ask.md`.

### AI-O15: Session persistence in the deployed environment

**Status: implemented as a storage policy and deployment gate in
`knowledge-engine-web` PR
[#50](https://github.com/jweter/knowledge-engine-web/pull/50).**

**Problem:** `sessions/repository.py` is SQLite-backed. `core`'s own
working database already has a documented "no persistent host yet"
caveat (`docs/service_boundary_design.md`, referenced in
`knowledge-engine-web`'s own README) — Render's alpha deployment rebuilds
from a committed snapshot, so anything written at runtime (including a
new session-store SQLite file) does not survive a redeploy today.

**Decision:** ordinary local SQLite is acceptable for development and a
trusted single-machine deployment. A hosted or persistent deployment
must use `persistent` storage mode and place the session database
canonically inside an explicitly configured persistent mount. Ephemeral
public Research Sessions are rejected: showing a durable session ID
while silently losing its history on redeploy would violate the
project's traceability promise.

The capability gate rejects missing or unwritable mounts, relative
hosted paths, database paths outside the configured root, and symlink
escapes. It does not create directories, databases, disks, or billing
resources while checking capability. The Render blueprint declares the
intended `/var/data` contract but intentionally does not provision a
persistent disk; until an operator attaches and verifies that disk, the
alpha remains retrieval-only.

`SessionRepository` can reopen the same SQLite store and recover durable
session state, and the web integration tests exercise that boundary.
This is storage continuity, not a user-facing resume feature. The
current `run_research_question` composition does not yet define how a
browser continues an existing session, so authorization, terminal-state
handling, and idempotent continuation require a separate contract before
such a UI is claimed. Full implementation and operator details live in
`knowledge-engine-web`'s `docs/ai_o15_deployed_session_persistence.md`.

### AI-O16: Guardrails for a real, publicly-reachable, LLM-cost-bearing endpoint

**Status: next. Depends on the implemented AI-O14 route and AI-O15
storage boundary.**

`/ask` today already runs local inference on request (existing
`synthesize=1` path) behind only the alpha's basic-auth gate. Routing it
through the full composed pipeline means every question now triggers
*multiple* tool/LLM calls (parallel retrieval ×2, synthesis, skeptic
verification) instead of one — real latency and real compute cost per
request, from anyone who has the alpha credentials.

**Deliverable:**
- A visible "this may take a while" UX state (the parallel-retrieval +
  synthesis + verification chain is not instant) — don't leave a person
  looking at a blank/hung page.
- An explicit timeout with an honest failure message if the pipeline
  doesn't complete in a bounded time — never a partial, unlabeled result
  presented as complete.
- A minimal per-session or per-IP rate limit appropriate to a
  single-instance alpha (exact mechanism TBD at implementation time —
  don't over-build this; it needs to stop accidental hammering, not
  survive a real attack).

**Definition of done:** a deliberately slow/failing case (e.g. Ollama
unreachable, or a forced timeout in a test) is live-verified to fail
honestly rather than hang or silently degrade.

### AI-O17: Live verification and closing the vision-doc claim

**Status: not started. Depends on AI-O12-O16, and on the hosted-inference
precondition named above under "A precondition this plan does not
solve" — read that section before starting this step.**

**Deliverable, local/dev scope (buildable now, no precondition
blocking):** a real end-to-end run — a real question, through a local
dev instance of `knowledge-engine-web` with a local `ollama serve`,
against a real corpus (GLP-1, oncology, or mental-health), producing a
real composed result: plan/session, both retrieval branches, the
contradiction-recall signal, a skeptic-verified synthesis, a final
session report, and a viewable trace. Read the actual output in full,
the same "measured, not asserted" bar every AI-O milestone in this repo
has already held itself to — do not report this step done from a green
test suite alone.

**Deliverable, public-alpha scope (blocked on the hosted-inference
precondition):** the same run, but against the actual deployed Render
alpha a real person can reach. Do not claim this half is done until the
durably-hosted-Ollama (or equivalent) question above is actually
resolved — a local-only verification is real progress and should be
reported as exactly that, not conflated with the public claim.

Once verified, update `docs/roadmap/long_term_vision.md`'s "The Finished
Product Is Not an Offline PDF Archive" section (in `knowledge-engine-core`)
to say this is real and link the verification evidence, replacing its
current forward-looking framing.

### AI-O18+ (deferred): Extract the orchestrator into a real service

Not scoped, not started, not needed yet. Revisit when either becomes
true: (a) a second consumer of the orchestrator appears (a second web
frontend, a CLI product, an API for third parties), or (b) real
production load or multi-tenant need justifies independent auth, rate
limiting, and scaling this project doesn't need today. When that day
comes, this document's Architecture Decision section above is the
record of why library integration was chosen first — read it before
re-deciding, don't re-litigate from scratch.

## What this plan deliberately does not cover

- **AI-O10 (Discovery Intelligence) / AI-O11 (Hypothesis Assistance).**
  Separate, gated milestones per `docs/roadmap/future_ai_orchestration_plan.md`
  — not part of this wiring effort. AI-O12-O17 expose what O1-O9 already
  built; they do not add new analytical capability.
- **`knowledge-engine-ai`'s own `ke-ai ask` CLI's long-term shape.**
  AI-O12 gives it a second, fuller code path; whether the simple path
  should eventually be removed, kept as a lighter-weight option, or
  merged into one command with flags is an open question for whoever
  implements AI-O12 to resolve, not pre-decided here.
- **Multi-corpus question routing.** `run_research_question` takes one
  `--sources`/`--evidence` pair, matching every existing `ke-ai`/`ke`
  command's current scope. Which corpus a web question should search
  (today: presumably whichever one the deployed alpha snapshot bundles)
  is unchanged by this plan.
