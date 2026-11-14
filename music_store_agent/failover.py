"""The primary and the fallback model, each under a hard deadline for every request."""

import asyncio
from collections.abc import Coroutine
from typing import Any

from pydantic_ai.exceptions import (
    ModelConnectionError,
    ModelRequestTimeout,
    ModelServerError,
    ModelUnavailableError,
)
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from music_store_agent.constants import DEFAULT_REQUEST_TIMEOUT_SECONDS, PROVIDER_SDK_RETRIES

# Provider outages and a request past its deadline move that request to the fallback. A rate
# limit, a quota, or a rejected request (bad key, unknown model) does not: the fallback would
# fail the same way or hide the cause.
PROVIDER_OUTAGES = (
    ModelUnavailableError,
    ModelServerError,
    ModelConnectionError,
    ModelRequestTimeout,
)


class DeadlineModel(WrapperModel):
    """One model whose every request ends by its deadline, whatever the socket does."""

    def __init__(self, wrapped: Model | str, seconds: float) -> None:
        super().__init__(wrapped)
        self.seconds = seconds

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        call = self.wrapped.request(messages, model_settings, model_request_parameters)
        return await within_deadline(call, self.seconds, self.model_name)


async def within_deadline(
    call: Coroutine[Any, Any, ModelResponse], seconds: float, model_name: str
) -> ModelResponse:
    """Run the call in its own task and stop waiting for it once `seconds` pass.

    At the deadline the task is cancelled and left behind, never awaited, so a socket that
    ignores the cancel cannot hold the turn. The miss raises ModelRequestTimeout, an outage the
    fallback already handles.
    """
    task = asyncio.ensure_future(call)
    try:
        done, _pending = await asyncio.wait({task}, timeout=seconds)
    finally:
        if not task.done():
            task.cancel()
            task.add_done_callback(_settle)
    if task not in done:
        raise ModelRequestTimeout(model_name, seconds)
    return task.result()


def _settle(task: asyncio.Future[ModelResponse]) -> None:
    """Read what the abandoned call ended with, so asyncio does not report it as unread."""
    if not task.cancelled():
        task.exception()


def request_settings(seconds: float) -> ModelSettings:
    """The HTTP client timeout for each attempt, and no SDK retry: the fallback is the only one."""
    return ModelSettings(timeout=seconds, max_retries=PROVIDER_SDK_RETRIES)


def model_chain(
    primary: Model | str,
    fallback: Model | str,
    seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> FallbackModel:
    """The primary answers. An outage or a missed deadline moves that request to the fallback."""
    return FallbackModel(
        DeadlineModel(primary, seconds),
        DeadlineModel(fallback, seconds),
        fallback_on=PROVIDER_OUTAGES,
    )
