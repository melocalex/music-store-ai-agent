"""The primary and the fallback: a hard deadline on every request, a breaker on the primary."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
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

# Provider outages and a request past its deadline move that request to the fallback and open
# the primary's breaker. A rate limit, a quota, or a rejected request (bad key, unknown model)
# does neither: the fallback would fail the same way or hide the cause.
PROVIDER_OUTAGES = (
    ModelUnavailableError,
    ModelServerError,
    ModelConnectionError,
    ModelRequestTimeout,
)

_log = logging.getLogger(__name__)


class PrimaryBreakerOpen(ModelUnavailableError):
    """Raised instead of calling a primary whose breaker is open. The fallback answers at once."""


@dataclass
class CircuitBreaker:
    """In-memory record of the primary's last outage in this process.

    For `window` seconds after an outage, requests skip the primary. The first request after the
    window tries it again: a success closes the breaker, another outage starts a new window.
    A window of zero never skips.
    """

    window: float
    clock: Callable[[], float] = time.monotonic
    opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def remaining(self) -> float:
        """Seconds the primary stays skipped: zero once the window has passed or it is closed."""
        with self._lock:
            if self.opened_at is None:
                return 0.0
            return max(0.0, self.opened_at + self.window - self.clock())

    def record_outage(self) -> None:
        with self._lock:
            self.opened_at = self.clock()

    def record_success(self) -> bool:
        """Close the breaker. True when it had been opened."""
        with self._lock:
            was_open, self.opened_at = self.opened_at is not None, None
        return was_open


_SHARED: dict[tuple[str, float], CircuitBreaker] = {}
_SHARED_LOCK = threading.Lock()


def shared_breaker(primary_id: str, window: float) -> CircuitBreaker:
    """The breaker for one primary, shared by every agent this process builds."""
    with _SHARED_LOCK:
        return _SHARED.setdefault((primary_id, window), CircuitBreaker(window))


class GuardedModel(WrapperModel):
    """One model whose every request ends by its deadline, whatever the socket does.

    With a breaker, it is the primary: an outage opens the breaker, and while the breaker is open
    the request is refused at once so the fallback gets the whole budget.
    """

    def __init__(
        self, wrapped: Model | str, seconds: float, breaker: CircuitBreaker | None = None
    ) -> None:
        super().__init__(wrapped)
        self.seconds = seconds
        self.breaker = breaker

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        breaker = self.breaker
        if breaker is not None and (left := breaker.remaining()) > 0:
            _log.warning(
                "primary model %s skipped: breaker open for %.0f more seconds", self.model_id, left
            )
            raise PrimaryBreakerOpen(self.model_name, "breaker open after a recent outage")
        call = self.wrapped.request(messages, model_settings, model_request_parameters)
        try:
            response = await within_deadline(call, self.seconds, self.model_name)
        except PROVIDER_OUTAGES as error:
            if breaker is not None:
                breaker.record_outage()
                _log.warning(
                    "breaker opened: primary model %s skipped for %.0f seconds after %s",
                    self.model_id,
                    breaker.window,
                    type(error).__name__,
                )
            raise
        if breaker is not None and breaker.record_success():
            _log.info("breaker closed: primary model %s answered again", self.model_id)
        return response


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
    breaker: CircuitBreaker | None = None,
) -> FallbackModel:
    """The primary answers. An outage or a missed deadline moves that request to the fallback.

    With a breaker, a primary outage also sends the next requests straight to the fallback until
    the breaker's window passes.
    """
    return FallbackModel(
        GuardedModel(primary, seconds, breaker),
        GuardedModel(fallback, seconds),
        fallback_on=PROVIDER_OUTAGES,
    )
