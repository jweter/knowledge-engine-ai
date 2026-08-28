"""A local, offline LLM for grounded synthesis -- no API key, no cloud call.

The owner's explicit decision for this project's first LLM integration
(`docs/ai_design.md`'s "Decision: local LLM" section): a locally-run,
open-weight model served by Ollama (https://ollama.com), not a hosted
API. No `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`-style secret exists
anywhere in this project as a result. Ollama runs as its own long-lived
process (`ollama serve`) exposing an HTTP API on `localhost:11434` by
default -- this module is a thin, bounded HTTP client for that API, the
same "own dedicated transport, `urllib` only, no SDK" shape `core` uses
for its own live network lookups (e.g. `knowledge_engine.rxnorm_http`).

`LocalLLM` is a narrow `Protocol` -- one method, `generate` -- so
`knowledge_engine_ai.synthesis` and `cli.py` never depend on Ollama's
wire format directly, and so tests can substitute a fake transport
instead of requiring a real `ollama serve` process and a downloaded
model.
"""

from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 120.0
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class LocalLLMError(RuntimeError):
    """The local model could not be reached, or did not return a usable response."""


class LocalLLMTimeoutError(LocalLLMError):
    """The local model exceeded the caller's bounded generation window."""


class LocalLLM(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        """Return the model's completion for `prompt`, run entirely locally."""
        ...


class OllamaTransportResponse(Protocol):
    """Minimal response contract this module consumes."""

    status_code: int
    body: bytes


class OllamaTransport(Protocol):
    def post(self, *, url: str, payload: bytes, timeout_seconds: float) -> OllamaTransportResponse:
        """POST `payload` (already-encoded JSON) to `url` and return the response."""
        ...


class _Response:
    def __init__(self, *, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class UrllibOllamaTransport:
    """POSTs to a local (or LAN) Ollama server via the standard library only."""

    def post(self, *, url: str, payload: bytes, timeout_seconds: float) -> OllamaTransportResponse:
        request = Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                status_code = response.status
        except HTTPError as exc:
            return _Response(status_code=exc.code, body=exc.read())
        except URLError as exc:
            raise LocalLLMError(
                f"Could not reach Ollama at {url}: {exc.reason}. "
                "Is `ollama serve` running, and is the host/port correct?"
            ) from exc
        except TimeoutError as exc:
            # `urlopen`'s `timeout=` bounds every socket read, not just the
            # connect -- a slow generation (a larger or reasoning model,
            # e.g. Qwen3's "thinking" mode) can time out reading the
            # response body itself. Keep timeout distinct from other local
            # model failures so synthesis can safely fall back to a purely
            # deterministic evidence rendering without masking outages,
            # malformed responses, or missing-model errors.
            raise LocalLLMTimeoutError(
                f"Ollama at {url} did not respond within {timeout_seconds:.0f}s. "
                "The model may still be generating -- a larger or reasoning "
                "model can need more time than the default timeout."
            ) from exc

        if len(body) > _MAX_RESPONSE_BYTES:
            raise LocalLLMError(f"Ollama response from {url} exceeded {_MAX_RESPONSE_BYTES} bytes.")

        return _Response(status_code=status_code, body=body)


class OllamaLLM:
    """Calls a running Ollama server's `/api/chat` endpoint for one-shot completions."""

    def __init__(
        self,
        *,
        model: str,
        host: str = DEFAULT_OLLAMA_HOST,
        transport: OllamaTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self._transport = transport if transport is not None else UrllibOllamaTransport()
        self._timeout_seconds = timeout_seconds

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": max_tokens},
            }
        ).encode("utf-8")

        response = self._transport.post(
            url=f"{self._host}/api/chat",
            payload=payload,
            timeout_seconds=(self._timeout_seconds if timeout_seconds is None else timeout_seconds),
        )

        if response.status_code == 404:
            raise LocalLLMError(
                f"Ollama has no model {self._model!r} pulled. "
                f"Run `ollama pull {self._model}` first."
            )
        if response.status_code != 200:
            body_text = response.body.decode(errors="replace")
            raise LocalLLMError(f"Ollama returned HTTP {response.status_code}: {body_text}")

        try:
            parsed = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise LocalLLMError(f"Ollama did not return valid JSON: {exc}") from exc

        try:
            content = parsed["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LocalLLMError(f"Ollama returned an unexpected response shape: {exc}") from exc

        if not isinstance(content, str) or not content.strip():
            raise LocalLLMError("Ollama returned an empty response.")

        return _strip_thinking(content).strip()


def _strip_thinking(content: str) -> str:
    """Drop a hybrid-reasoning model's inline `<think>...</think>` block, if present.

    Some Ollama models (e.g. Qwen3) interleave their internal reasoning
    into the same `content` field rather than a separate one. Only the
    text after `</think>` is the actual answer; a response with no such
    tag is returned unchanged.
    """

    marker = "</think>"
    if marker in content:
        return content.rsplit(marker, 1)[1]
    return content
