"""A local, offline LLM for grounded synthesis -- no API key, no network call.

The owner's explicit decision for this project's first LLM integration
(`docs/ai_design.md`'s "Decision: local LLM" section): a quantized GGUF
model run entirely on-machine via `llama-cpp-python`, not a hosted API.
No `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`-style secret exists anywhere in
this project as a result.

`LocalLLM` is a narrow `Protocol` -- one method, `generate` -- so
`knowledge_engine_ai.synthesis` and `cli.py` can depend on it without
importing `llama_cpp` directly, and so tests can substitute a fake
implementation instead of loading a real multi-gigabyte model file (the
same fake-transport pattern `core` uses for its live network lookups,
e.g. `knowledge_engine.rxnorm_http`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class LocalLLMError(RuntimeError):
    """The local model could not be loaded or could not generate a response."""


class LocalLLM(Protocol):
    def generate(self, prompt: str, *, max_tokens: int = 400) -> str:
        """Return the model's completion for `prompt`, run entirely locally."""
        ...


class LlamaCppLLM:
    """Loads a GGUF model file via `llama-cpp-python` and runs CPU inference."""

    def __init__(self, model_path: Path, *, n_ctx: int = 4096, n_threads: int | None = None):
        if not model_path.is_file():
            raise LocalLLMError(
                f"No model file at {model_path}. Download a small instruction-tuned GGUF model "
                "first, e.g.:\n"
                "  curl -L -o qwen2.5-1.5b-instruct-q4_k_m.gguf \\\n"
                "    https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
                "qwen2.5-1.5b-instruct-q4_k_m.gguf\n"
                "then point --llm-model (or KE_AI_LLM_MODEL_PATH) at the downloaded file."
            )

        try:
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - dependency is declared, not optional
            raise LocalLLMError("llama-cpp-python is not installed. Run `poetry install`.") from exc

        try:
            self._llama = Llama(
                model_path=str(model_path),
                n_ctx=n_ctx,
                n_threads=n_threads,
                verbose=False,
            )
        except Exception as exc:
            raise LocalLLMError(f"Could not load model at {model_path}: {exc}") from exc

    def generate(self, prompt: str, *, max_tokens: int = 400) -> str:
        try:
            # `stream` defaults to False, so this is always the single
            # dict response, never the streaming iterator -- the return
            # type is a union only because the same method also handles
            # `stream=True`, which this project never passes.
            completion = self._llama.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            assert isinstance(completion, dict)
        except Exception as exc:
            raise LocalLLMError(f"Local model inference failed: {exc}") from exc

        try:
            content = completion["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LocalLLMError(
                f"Local model returned an unexpected response shape: {exc}"
            ) from exc

        if content is None:
            raise LocalLLMError("Local model returned an empty response.")

        return content.strip()
