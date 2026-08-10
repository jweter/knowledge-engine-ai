# AI-O4 — Local Query Planner

**Status:** Implemented and live-verified against a real, running Ollama
server (2026-08-10).
**Depends on:** AI-O1 (`docs/ai_o1_design.md`, the `ResearchPlan` schema
and validator this milestone generates plans *behind*).

## What AI-O4 is

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O4 milestone:

> Add LLM plan generation behind schema validation.
>
> **Success criterion:** natural-language questions reliably map to
> bounded workflow plans.

`knowledge_engine_ai/copilot/planner.py`'s `plan_from_question` is that
generation step. It is the first place in the AI-O1-through-O11 build
order a model decides *which* capabilities a question needs -- AI-O3's
`run_fixed_evidence_workflow` never inspected the question's content,
only what curated data existed for a given corpus. The seam AI-O1 built
holds here: the model never executes a tool, retrieves real evidence, or
decides a scientific answer. It proposes a `ResearchPlan`;
`validate_research_plan` (already built, already tested, unmodified by
this milestone) is the only authority on whether that plan is
well-formed enough to hand to a future orchestrator.

## Why parse-then-force-fields, not trust-the-model

`plan_from_question` asks the model to echo back a fixed `plan_id` and
`created_at` it is given in the prompt (predictable IDs and valid
timestamps have nothing to do with the model's actual planning
judgment, so asking the model to *invent* them would just add a new way
for this call to fail for no useful reason). The first implementation of
this function only *asked* -- it trusted the model's echoed values
outright. Code review caught that a model which paraphrased or dropped
those fields would silently produce a plan carrying whatever `plan_id`/
`created_at` it happened to write, defeating the whole point of fixing
them in the prompt. The fix: after the model's JSON payload parses,
`plan_from_question` overwrites `payload["plan_id"]` and
`payload["created_at"]` with the values it actually generated,
unconditionally, before handing the payload to `parse_research_plan`.
The model's own values for those two fields are now advisory only --
correctness for them no longer depends on the model following
instructions.

## JSON extraction, not a raw-JSON assumption

`_extract_json_object` looks for the first `{`, then brace-depth-tracks
forward until the matching `}` closes -- not a naive
`find("{")..rfind("}")` scan, because the target JSON itself contains
nested objects (`required_capabilities`, each task object) that a naive
scan would still get right by luck, but a model that appends trailing
prose after the closing brace would break. It also survives a model
wrapping its answer in a markdown code fence, since the fence characters
just become text ignored by the brace scan.

## Failure handling: raise with the raw output attached, never repair

`plan_from_question` does not retry, coerce, or "fix up" a malformed
response. A model that returns non-JSON, JSON missing a required field,
an unrecognized `task_type`, or a structurally invalid plan (duplicate
task IDs, an unresolved dependency, a consequence level below its task
type's floor, `required_capabilities` disagreeing with `tasks`) causes
`plan_from_question` to raise `PlannerError` with the model's full raw
output attached. A caller that wants a bounded retry loop (e.g. feeding
the validation error back to the model as a correction prompt) builds
that explicitly, as its own deliberate policy choice; guessing a repair
here would be exactly the kind of autonomous "fix it and move on"
behavior the design doc's staged-consequence-level principle warns
against building before it's designed on purpose.

## Live verification

Run against a real, locally-running Ollama server (`ollama serve`, not
mocked, not a fake transport) in this session's own execution
environment -- CPU-only, 4 cores, no GPU.

**Model choice, decided from a real measurement, not a preference.**
Two models were pulled and available: `qwen3:4b` (has a hybrid-reasoning
"thinking" mode) and `qwen2.5:1.5b` (does not). `qwen3:4b` was tried
first, since it is the larger of the two. A single 50-token probe
request (`num_predict: 50`, no planning prompt, just "say hello in one
word") came back with an **empty response body** -- `_strip_thinking`
correctly stripped its `<think>...</think>` block, but the model had
spent the entire 50-token budget still inside that block with no
`</think>` closing tag reached, so there was no answer left to strip
*to*. At the planner's real `max_tokens=1200` budget, a full run against
`qwen3:4b` measured at roughly 9 tokens/second on this container and
hit `OllamaLLM`'s 120-second default timeout before finishing a single
question -- the crash was a real `TimeoutError` from the transport, not
a hang this document is guessing at. `qwen2.5:1.5b`, once warm,
generated at roughly 24 tokens/second with no thinking-token overhead.
The planner switched to `qwen2.5:1.5b` for this verification on that
basis: on CPU-only hardware, "does the model have spare token budget
left to answer" turned out to matter more than raw parameter count.
This is a live data point for the future AI-O8 ("Model Router") milestone,
not a permanent recommendation -- `OllamaLLM`'s `model` parameter stays
fully caller-configurable; this project still hardcodes no default
model anywhere.

**Three real questions, one per domain this project's corpora cover,
run back to back against the warm `qwen2.5:1.5b` model:**

| Question | Result | Latency | `domain` | Task types produced |
|---|---|---|---|---|
| Does semaglutide reduce body weight more than placebo in adults with obesity? | SUCCESS | 48.9s | `obesity_metabolic_disease` | `corpus_retrieval`, `pico_comparison`, `statistics` |
| What is the evidence for checkpoint inhibitors improving overall survival in NSCLC? | SUCCESS | 41.6s | `cancer_treatment` | `corpus_retrieval`, `pico_comparison`, `statistics` |
| Are SSRIs more effective than SNRIs for major depressive disorder? | SUCCESS | 39.2s | `mental_health` | `corpus_retrieval`, `pico_comparison`, `statistics` |

3 of 3 real questions produced a plan that parsed and passed every
`validate_research_plan` invariant on the first attempt, with no retry.
Each plan's `domain` field correctly tracked the question's actual
subject rather than reusing the worked example's
`obesity_metabolic_disease` value verbatim, and each plan's
`required_capabilities` agreed exactly with its `tasks`' task types (the
cross-field check most likely to trip a small model up, since it
requires the model to keep two separate parts of a long JSON object in
sync). This is a small sample -- three questions, one session, one
model, one machine -- and this document does not claim a rate beyond
what was actually measured; "reliably" here means "3/3 in this specific
live run," not a statistically powered claim.

**What this does not verify:** adversarial or malformed questions (an
empty string, a non-medical question, a question this project's corpora
cannot possibly answer), the model's behavior across many repeated runs
of the *same* question (temperature is fixed at 0.1 in `OllamaLLM`, but
this was not re-run to measure variance), or `qwen3:4b`'s actual planning
quality under a timeout generous enough to let its thinking block
finish -- only that its *default*-configuration behavior in this
environment was unusable for this call. A future AI-O8 pass is the right
place to make that a controlled, side-by-side benchmark instead of an
incidental finding from this milestone.

## What this does not do

- No orchestrator consumption of the plan yet. AI-O3's
  `run_fixed_evidence_workflow` still runs its own hardcoded sequence,
  unaware this module exists. Wiring a `ResearchPlan`'s `tasks` to
  actually drive which of AI-O3's (or a generalized future orchestrator's)
  steps run is explicitly out of scope for AI-O4, per the roadmap's own
  framing of AI-O4 as sitting *above* AI-O3, not replacing it yet.
- No retry, repair, or multi-turn correction loop. See "Failure
  handling" above.
- No consequence-level enforcement beyond what `validate_research_plan`
  already checks (a task's declared level meets its type's floor). Which
  execution decision (`autonomous`, `human_authorization_required`, etc.)
  a produced plan's tasks actually receive is `execution_decision_for`'s
  job (AI-O1, unmodified) and a future orchestrator's job to obey -- this
  module only produces the plan.
- No model download, pull, or lifecycle management. `OllamaLLM` assumes
  the caller already ran `ollama pull <model>`; this milestone did not
  change that.

## Tests

`tests/copilot/test_planner.py` (16 tests, alongside `test_contracts.py`
and `test_validation.py` in the same `tests/copilot/` package, matching
`planner.py`'s home in `knowledge_engine_ai/copilot/`) uses a fake
`LocalLLM` (the same `_FakeLLM` shape as `tests/test_synthesis.py`'s,
which records every prompt/`max_tokens` it was called with and returns a
fixed canned response) so the suite runs deterministically and does not
require a real `ollama serve` process. Covers: a well-formed response
producing a valid plan; that the model's own `plan_id`/`created_at`
values are overridden by the resolved ones (both when an explicit
`plan_id` is given and when one is generated); `max_tokens` being passed
through to the LLM call; JSON wrapped in a markdown code fence being
extracted correctly; `PlannerError` on no JSON object present, malformed
JSON, a missing required field, an unrecognized `task_type`, a
`required_capabilities`/`tasks` mismatch, and a consequence level below
its task type's floor; that a `PlannerError`'s message includes the raw
model output for debugging; the prompt-building function including the
question and the fixed IDs; and the brace-balanced JSON extractor's
three cases (prose-wrapped object, no brace present, unbalanced braces).
