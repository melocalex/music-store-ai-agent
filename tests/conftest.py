"""Offline tests never call a model provider."""

import os

import pydantic_ai.models as models
import pytest

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    """A key in the developer's shell must not put OpenRouter into the offline tests."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
