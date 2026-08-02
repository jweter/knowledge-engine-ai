from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.llm import LlamaCppLLM, LocalLLMError


def test_llamacpp_llm_raises_a_clear_error_for_a_missing_model_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.gguf"

    with pytest.raises(LocalLLMError) as excinfo:
        LlamaCppLLM(missing)

    message = str(excinfo.value)
    assert str(missing) in message
    assert "huggingface.co" in message
