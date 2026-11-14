"""Offline tests never call a model provider."""

import os

import pydantic_ai.models as models

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
models.ALLOW_MODEL_REQUESTS = False
