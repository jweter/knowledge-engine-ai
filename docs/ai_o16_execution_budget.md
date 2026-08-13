# AI-O16 Execution Budget Foundation

## Status

Implemented as the AI-side prerequisite for Web's public-endpoint guardrails.
This change does not expose Research Copilot publicly or add request admission
controls by itself.

## Problem

`knowledge-engine-web` needs an honest wall-clock limit around
`run_research_question`. A web-only thread timeout is insufficient: the timed-out
thread could leave `ke` subprocesses or an Ollama request consuming resources in
the background.

## Decision

`run_research_question(..., timeout_seconds=...)` creates one monotonic
`ExecutionBudget`. Every core subprocess in both retrieval branches and every
subsequent Evidence Intelligence lookup receives the budget's remaining time.
The synthesis call receives the same remaining time as a per-call Ollama
timeout.

The budget is optional. Existing CLI and library callers that omit it retain
their prior behavior. Web must supply it when it enables the compute-bearing
Research Copilot path.

## Failure Behavior

- A `ke` command that outlives the budget is terminated by
  `subprocess.run(..., timeout=...)` and becomes a sanitized `KeCommandError`.
- A budget exhausted before another command starts fails before spawning it.
- An Ollama call uses only the remaining budget and keeps the existing
  `LocalLLMError` timeout behavior.
- Retrieval branch failures remain durable workflow events under the existing
  "record failure, continue honestly" contract.
- No exception message includes command arguments, corpus paths, prompts, or
  model output.

## Boundary

This budget covers the concrete `ke` and Ollama operations used by Web's
`run_research_question` composition. The optional caller-supplied external
discovery hook is not used by Web and is not made cancellable here. A future
external-discovery implementation must accept the same budget before it can be
enabled on the public path.

## Web Handoff

Web AI-O16 can now:

1. configure one request deadline;
2. pass it into `run_research_question`;
3. cap concurrent admitted runs;
4. apply a small per-client rate limit;
5. show an immediate in-progress state; and
6. render timeout, busy, and rate-limit failures without hiding deterministic
   retrieval.

The web layer must remain fail closed and must not claim that a timeout cancels
work outside the bounded core/Ollama interfaces described above.
