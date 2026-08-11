# AI-O8 — Model Router

**Status:** Implemented and live-verified (2026-08-11) -- see "Live
verification" below.
**Depends on:** `llm.py` (`LocalLLM`, `OllamaLLM`), `routing.py`
(`ModelRole`, `ProviderSpec`, `select_provider` -- merged just ahead of
this milestone), AI-O4's `planner.py` (`plan_from_question` +
AI-O1's `validate_research_plan`), and AI-O6/AI-O7's
`verify_synthesis`/`build_session_report`.

## What AI-O8 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O8 milestone:

> Benchmark local models on planning, extraction, evidence comparison,
> synthesis, and citation compliance.
>
> **Success criterion:** use the smallest model meeting task-quality
> thresholds.

Today, every LLM call in this project (`plan_from_question`,
`synthesize_answer`) is constructed against one hardcoded model tag
chosen once, by hand, during development (`qwen2.5:1.5b`, found usable
in this CPU-only environment; `qwen3:4b`, found unusable by AI-O4's own
live check because its "thinking" tokens consumed the entire response
budget). Nothing in the codebase measures that judgment against real
task output, and nothing revisits it if a new model is pulled. AI-O8 is
that measurement: a deterministic benchmark harness that runs each
candidate model against the same task probes this project already has
graders for, and recommends the *smallest* model that clears the
quality bar for each `ModelRole` -- not the most capable one, the
cheapest one that still works.

## Architecture: reuse existing graders, don't invent new ones

New module `knowledge_engine_ai/model_benchmark.py`. Two entry points:

```python
def run_model_benchmark(
    candidates: tuple[ModelCandidate, ...],
    tasks: tuple[BenchmarkTask, ...],
    llm_factory: Callable[[str], LocalLLM],
) -> tuple[ModelBenchmarkResult, ...]

def recommend_models_by_role(
    candidates: tuple[ModelCandidate, ...],
    results: tuple[ModelBenchmarkResult, ...],
) -> dict[ModelRole, str]
```

A `BenchmarkTask` is a named, role-tagged probe that takes an `LocalLLM`
and returns a pass/fail `BenchmarkOutcome` -- deliberately not a new
grading method. Each task in this first slice wraps an **existing**,
already-tested deterministic check:

- **Planning task** (`role=ModelRole.REASONER`): calls AI-O4's
  `plan_from_question(question, llm)` against a fixed real question.
  Passes if a valid `ResearchPlan` comes back; a caught `PlannerError`
  (malformed JSON, schema violation, or a validation failure any of
  AI-O1's `validate_research_plan` checks already enforce) is a fail,
  not a crash -- this is exactly what "task-quality threshold" means
  for planning: did the model produce a plan AI-O1's own contract
  accepts, on a real question, unassisted.
- **Synthesis + citation-compliance task** (`role=ModelRole.SYNTHESIS`):
  calls `synthesize_answer(report, llm)` against a fixed real
  `EvidenceReport`, then runs AI-O6's `verify_synthesis` on the result.
  Passes only if a narrative came back **and**
  `not (verification.hallucinated_citations or
  verification.ungrounded_numbers)` -- the two checks AI-O6 built
  specifically to catch a model stating something its evidence does not
  support. `missed_qualifiers` is deliberately excluded from this
  pass/fail gate: it is a completeness signal (AI-O6's own design doc
  already treats it as a distinct failure class from unsupported-claim
  fidelity), not a citation-compliance failure, and folding it in here
  would benchmark something this task is not named for.

```python
@dataclass(frozen=True)
class ModelCandidate:
    tag: str
    approx_parameter_count_billions: float

@dataclass(frozen=True)
class BenchmarkOutcome:
    passed: bool
    detail: str

@dataclass(frozen=True)
class BenchmarkTask:
    name: str
    role: ModelRole
    run: Callable[[LocalLLM], BenchmarkOutcome]

@dataclass(frozen=True)
class ModelBenchmarkResult:
    model_tag: str
    task_name: str
    role: ModelRole
    outcome: BenchmarkOutcome
```

`run_model_benchmark` never lets one candidate's crash (a model that is
not pulled, an Ollama timeout, an unexpected exception inside a task's
`run`) stop the rest of the sweep -- each task invocation is wrapped and
turned into a failed `BenchmarkOutcome` with the exception's message as
`detail`, the same "one step's failure does not stop the rest"
discipline AI-O3/AI-O5 already established for a workflow, applied here
to a benchmark sweep instead.

`approx_parameter_count_billions` is supplied by the caller, not
auto-detected. This project cannot reliably introspect a pulled model's
true parameter count from Ollama's API without adding a new dependency
on tag-name parsing conventions that are not guaranteed stable across
model families -- the same "don't invent a capability this project
cannot verify" discipline every prior milestone has followed. A caller
who wants live-verified numbers types them in from `ollama list`'s own
output (e.g. `qwen2.5:1.5b` -> `1.5`, `qwen3:4b` -> `4.0`), the same way
a human would when reading a model card.

## `recommend_models_by_role`: smallest model that clears the bar

For each `ModelRole` that has at least one task in the sweep,
`recommend_models_by_role` finds every candidate whose **every** task
for that role passed, and returns the smallest one by
`approx_parameter_count_billions` (ties broken by `tag`, for
reproducibility -- the same tie-break `routing.select_provider` already
uses). A role with no candidate clearing every task for it is simply
omitted from the returned mapping rather than raising -- an empty
recommendation for a role is itself a meaningful, reportable result
("nothing pulled locally clears this bar yet"), not an error condition
a caller must catch.

## Closing the loop: feeding a recommendation into `routing.py`

A benchmark result that never reaches `select_provider` is just a
report. New helper in the same module:

```python
def provider_specs_from_benchmark(
    recommendation: dict[ModelRole, str],
    *,
    max_privacy: PrivacyClass = PrivacyClass.SENSITIVE,
) -> tuple[ProviderSpec, ...]
```

Turns each `{role: model_tag}` entry into one local, `roles={role}`
`ProviderSpec` (`local=True`, since every benchmarked candidate in this
project is an Ollama model run on this machine) that `routing.py`'s
already-merged `select_provider` can rank and choose exactly as it does
today for any other `ProviderSpec` -- AI-O8 does not add a second
routing mechanism, it supplies better-informed input to the one PR #16
already built. `max_privacy` defaults to `SENSITIVE` (not `SECRET`,
matching `routing.py`'s own invariant that SECRET-class data must never
reach model context at all -- no `ProviderSpec` should ever claim it can
serve a SECRET request, benchmarked or not).

## What this does not do

- Does not benchmark "extraction" or "evidence comparison" tasks. The
  roadmap names both, but neither has an LLM-based worker in this
  project yet to benchmark: PICO/evidence-map comparison
  (`evidence_map_report`/`statistical_verify` in `workflow.py`) is
  `core`'s deterministic Markdown output consumed verbatim, and
  per-candidate LLM extraction (`extraction_tier="llm_grounded"`) lives
  in `core`'s own pipeline, never imported into `ai` (the
  `ke_client.py` subprocess boundary this project has held since AI-O0).
  Benchmarking a capability that does not exist here would mean
  building a second, throwaway implementation just to measure it --
  named here as follow-up work once (if) either capability moves into
  this project directly, not attempted now.
- Does not run the benchmark automatically, on a schedule, or as part of
  any CLI command yet. This slice is the harness and the two task
  probes it can honestly support today; wiring it into `ke-ai`'s CLI or
  a scheduled job is future work, the same "no orchestrator wiring yet"
  boundary AI-O5/AI-O6 drew for their own first slices.
- Does not persist benchmark results anywhere (no `ResearchSession`
  event, no file). A caller who wants a durable record writes one; this
  module returns an in-memory `tuple[ModelBenchmarkResult, ...]` and
  leaves storage to the caller, matching AI-O2's own boundary that a
  session's event log is opt-in, not implicit.
- Does not attempt true task-quality *scoring* (a 0-100 grade). Every
  probe in this slice is pass/fail against an existing deterministic
  contract (`validate_research_plan`, `verify_synthesis`'s two grounding
  checks) -- a graded score would need a labeled benchmark dataset this
  project does not have, the same gap AI-O5's and AI-O6's design docs
  already named for their own would-be benchmarks.

## Testing strategy

Unit tests with fake `LocalLLM`s (mirroring `tests/copilot/test_planner.py`'s
and `tests/test_verification.py`'s fixture styles, not a real Ollama
call): a task that passes is recorded as passed; a task whose probe
raises is recorded as a failed outcome, not an uncaught exception; given
two candidates where only the larger one passes every task for a role,
`recommend_models_by_role` returns the larger one (there is no smaller
qualifying alternative); given two candidates that both pass, the
smaller one is recommended; a role with zero passing candidates is
omitted from the recommendation, not an error;
`provider_specs_from_benchmark` produces one `ProviderSpec` per
recommended role with `local=True` and the given `max_privacy`.

## Live verification

Ran the real benchmark against both models actually pulled in this
environment (`qwen2.5:1.5b`, `qwen3:4b`) with a real running
`ollama serve`: the planning task against a real question ("Does
semaglutide reduce body weight more than placebo in adults with
obesity?"), and the synthesis task against the same real GLP-1
`EvidenceReport` AI-O6/AI-O7 already live-verified against.

First run used `OllamaLLM`'s 120s default per-call timeout and both
models timed out on the planning task -- but a follow-up isolated retry
of `qwen2.5:1.5b`'s planning probe alone, with a 480s timeout, completed
in **36.2 seconds**. The 120s default was too tight for this
environment's first (cold-loaded) call, not evidence the model cannot
plan -- re-running the full sweep with `timeout_seconds=300.0` gives an
honest read instead of an artifact of an under-tuned timeout:

| model | planning (`REASONER`) | synthesis + citation compliance (`SYNTHESIS`) |
|---|---|---|
| `qwen2.5:1.5b` | **passed** -- produced a schema-valid `ResearchPlan` | **passed** -- `hallucinated_citations=()`, `ungrounded_numbers=()` |
| `qwen3:4b` | **failed** -- timed out at 300s | **failed** -- `synthesize_answer` returned an empty response (Ollama's `content` field was empty after `_strip_thinking` removed the `<think>...</think>` block, i.e. the "thinking" tokens consumed the entire response budget) |

`recommend_models_by_role` -> `{ModelRole.REASONER: "qwen2.5:1.5b",
ModelRole.SYNTHESIS: "qwen2.5:1.5b"}`. `provider_specs_from_benchmark`
turned that into two local `ProviderSpec`s, `max_privacy=SENSITIVE`,
ready for `routing.select_provider` to rank.

This is a genuine, not contrived, result: with only two models pulled
in this environment, "smallest model meeting the bar" trivially
resolves to the one model that clears both bars, but the benchmark
independently *confirmed* AI-O4's prior anecdotal finding about
`qwen3:4b`'s CPU-only unusability as a reproducible, automated result
rather than a one-off observation -- and the timeout-tuning episode
above is itself a real, worth-keeping finding: a benchmark harness on
CPU-only hardware needs a materially longer per-call timeout than a
single interactive request would, because cold model load time can
exceed a "generous-looking" 120s budget even when actual inference
takes under a minute once warm.
