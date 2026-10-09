from __future__ import annotations

import pytest

from kci.models import LlamaCppCliProvider, LlamaCppCliProviderError


def test_llama_cpp_cli_provider_requires_explicit_local_artifacts(tmp_path) -> None:
    missing_executable = tmp_path / "missing-llama-completion"
    missing_model = tmp_path / "missing-model.gguf"

    with pytest.raises(LlamaCppCliProviderError) as exc_info:
        LlamaCppCliProvider(missing_executable, missing_model, timeout_s=1)

    assert exc_info.value.category == "configuration"
