from __future__ import annotations

import json

import pytest

import knowledge_engine_ai.llm as llm_module
from knowledge_engine_ai.llm import (
    DEFAULT_OLLAMA_HOST,
    LocalLLMError,
    OllamaLLM,
    UrllibOllamaTransport,
)


class _FakeResponse:
    def __init__(self, *, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class _FakeTransport:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, *, url: str, payload: bytes, timeout_seconds: float) -> _FakeResponse:
        self.calls.append({"url": url, "payload": payload, "timeout_seconds": timeout_seconds})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _chat_response_body(content: str) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": content}}).encode("utf-8")


def test_generate_posts_to_the_chat_endpoint_and_returns_the_content() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=200, body=_chat_response_body("Answer.")))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    result = llm.generate("Does X reduce Y?", max_tokens=200)

    assert result == "Answer."
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == f"{DEFAULT_OLLAMA_HOST}/api/chat"
    payload = call["payload"]
    assert isinstance(payload, bytes)
    body = json.loads(payload)
    assert body["model"] == "qwen2.5:1.5b"
    assert body["messages"] == [{"role": "user", "content": "Does X reduce Y?"}]
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 200


def test_generate_uses_the_given_host() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=200, body=_chat_response_body("Answer.")))
    llm = OllamaLLM(model="qwen2.5:1.5b", host="http://192.168.1.50:11434/", transport=transport)

    llm.generate("question")

    assert transport.calls[0]["url"] == "http://192.168.1.50:11434/api/chat"


def test_generate_strips_a_hybrid_reasoning_models_inline_think_block() -> None:
    content = "Some internal reasoning about the question.</think>\n\nThe actual answer [ev-1]."
    transport = _FakeTransport(_FakeResponse(status_code=200, body=_chat_response_body(content)))
    llm = OllamaLLM(model="qwen3:4b", transport=transport)

    result = llm.generate("question")

    assert result == "The actual answer [ev-1]."


def test_generate_raises_a_clear_error_for_a_missing_model() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=404, body=b"model not found"))
    llm = OllamaLLM(model="does-not-exist:1b", transport=transport)

    with pytest.raises(LocalLLMError) as excinfo:
        llm.generate("question")

    message = str(excinfo.value)
    assert "does-not-exist:1b" in message
    assert "ollama pull" in message


def test_generate_raises_for_a_non_200_non_404_status() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=500, body=b"internal error"))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    with pytest.raises(LocalLLMError) as excinfo:
        llm.generate("question")

    assert "500" in str(excinfo.value)


def test_generate_raises_for_a_connection_failure() -> None:
    transport = _FakeTransport(LocalLLMError("Could not reach Ollama at http://x: refused."))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    with pytest.raises(LocalLLMError):
        llm.generate("question")


def test_generate_raises_for_malformed_json() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=200, body=b"not json"))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    with pytest.raises(LocalLLMError):
        llm.generate("question")


def test_generate_raises_for_a_response_missing_the_content_field() -> None:
    body = json.dumps({"message": {"role": "assistant"}}).encode("utf-8")
    transport = _FakeTransport(_FakeResponse(status_code=200, body=body))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    with pytest.raises(LocalLLMError):
        llm.generate("question")


def test_generate_raises_for_an_empty_content_field() -> None:
    transport = _FakeTransport(_FakeResponse(status_code=200, body=_chat_response_body("   ")))
    llm = OllamaLLM(model="qwen2.5:1.5b", transport=transport)

    with pytest.raises(LocalLLMError):
        llm.generate("question")


def test_urllib_transport_wraps_a_slow_response_timeout_as_local_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `urlopen`'s `timeout=` bounds every socket read, not just the
    # connect -- a slow generation raises a bare `TimeoutError`, not a
    # `URLError`, that must be caught separately or it escapes `post`
    # unwrapped and crashes the caller (found live against `qwen3:4b`).
    def _raise_timeout(*args: object, **kwargs: object) -> object:
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_module, "urlopen", _raise_timeout)
    transport = UrllibOllamaTransport()

    with pytest.raises(LocalLLMError) as excinfo:
        transport.post(url="http://127.0.0.1:11434/api/chat", payload=b"{}", timeout_seconds=120.0)

    assert "did not respond within 120s" in str(excinfo.value)
