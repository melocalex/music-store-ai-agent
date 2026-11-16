"""The primary and the fallback: a hard deadline on every request, a breaker on the primary."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelRequestTimeout,
    ModelServerError,
    ModelUnavailableError,
)
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from music_store_agent.constants import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    PROVIDER_SDK_RETRIES,
    QUOTA_BREAKER_SECONDS,
    RATE_LIMIT_BREAKER_SECONDS,
)

# Provider outages and a request past its deadline move that request to the next model and open
# the breaker of the one that failed.
PROVIDER_OUTAGES = (
    ModelUnavailableError,
    ModelServerError,
    ModelConnectionError,
    ModelRequestTimeout,
)
# A rate limit or a quota belongs to one model, so the next model can still answer. The breaker
# then skips the limited model for a minute, or an hour for a daily quota. An HTTP 400 moves that
# request on without opening the breaker. A bad key or an unknown model (401, 403, 404) moves
# nothing: the next model would not fix a setup error.
QUOTA_ERRORS = (ModelRateLimitError, ModelQuotaExceededError)
FALLBACK_ON = PROVIDER_OUTAGES + QUOTA_ERRORS
_HTTP_TOO_MANY = 429
_HTTP_BAD_REQUEST = 400
_DAILY_QUOTA_HINTS = ("perday", "per day", "per_day", "daily")

_log = logging.getLogger(__name__)


def is_bad_request(error: BaseException) -> bool:
    """An HTTP 400 from one provider. Another model may accept the same turn.

    Anthropic refuses a request whose reasoning block does not match the conversation, for
    example. That says nothing about the next model, and nothing about this model for the next
    turn, so the request moves on and the breaker stays closed. A bad key or an unknown model
    (401, 403, 404) is a setup problem and still stops the turn.
    """
    return (
        isinstance(error, ModelAPIError)
        and getattr(error, "status_code", None) == _HTTP_BAD_REQUEST
    )


def moves_on(error: Exception) -> bool:
    """The `fallback_on` rule: an outage, a limit, a missed deadline, or a rejected request."""
    return isinstance(error, FALLBACK_ON) or is_bad_request(error)


def is_quota_error(error: BaseException) -> bool:
    """A 429, or the error classes pydantic-ai maps from one."""
    if isinstance(error, QUOTA_ERRORS):
        return True
    return (
        isinstance(error, ModelAPIError) and getattr(error, "status_code", None) == _HTTP_TOO_MANY
    )


def is_daily_quota(error: BaseException) -> bool:
    """True for a 429 that says the day's quota is spent, not the minute's."""
    if not is_quota_error(error):
        return False
    if isinstance(error, ModelQuotaExceededError):
        return True
    body = f"{getattr(error, 'body', '')} {error}".casefold()
    return any(hint in body for hint in _DAILY_QUOTA_HINTS)


def limit_window(error: BaseException) -> float | None:
    """How long a limited model is skipped. None keeps the breaker's own outage window."""
    if not is_quota_error(error):
        return None
    return QUOTA_BREAKER_SECONDS if is_daily_quota(error) else RATE_LIMIT_BREAKER_SECONDS


class PrimaryBreakerOpen(ModelUnavailableError):
    """Raised instead of calling a model whose breaker is open. The next model answers at once.

    `quota` is "day" or "minute" when the breaker opened on a limit, and empty after an outage.
    """

    quota: str = ""


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
    quota: str = ""
    _span: float | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def remaining(self) -> float:
        """Seconds the primary stays skipped: zero once the window has passed or it is closed."""
        with self._lock:
            if self.opened_at is None:
                return 0.0
            span = self.window if self._span is None else self._span
            return max(0.0, self.opened_at + span - self.clock())

    def record_outage(self, span: float | None = None, quota: str = "") -> None:
        """Open the breaker. A window of zero never skips, whatever the span."""
        with self._lock:
            self.opened_at = self.clock()
            self._span = None if self.window <= 0 else span
            self.quota = quota

    def record_success(self) -> bool:
        """Close the breaker. True when it had been opened."""
        with self._lock:
            was_open, self.opened_at = self.opened_at is not None, None
            self._span, self.quota = None, ""
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
                "model %s skipped: breaker open for %.0f more seconds", self.model_id, left
            )
            skipped = PrimaryBreakerOpen(self.model_name, "breaker open after a recent failure")
            skipped.quota = breaker.quota
            raise skipped
        call = self.wrapped.request(messages, model_settings, model_request_parameters)
        try:
            response = await within_deadline(call, self.seconds, self.model_name)
        except FALLBACK_ON as error:
            if breaker is not None:
                span = limit_window(error)
                quota = "" if span is None else ("day" if is_daily_quota(error) else "minute")
                breaker.record_outage(span, quota)
                _log.warning(
                    "breaker opened: model %s skipped for %.0f seconds after %s",
                    self.model_id,
                    breaker.remaining(),
                    type(error).__name__,
                )
            raise
        except ModelAPIError as error:
            if is_bad_request(error):
                _log.warning("model %s rejected the request (HTTP 400): moving on", self.model_id)
            raise
        if breaker is not None and breaker.record_success():
            _log.info("breaker closed: model %s answered again", self.model_id)
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


def model_stack(
    models: Sequence[Model | str],
    seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    breakers: Sequence[CircuitBreaker | None] = (),
) -> FallbackModel:
    """The first model answers. An outage, a missed deadline, or a limit moves that request on.

    `breakers` pair with the models in order. With one, a failure also sends the next requests
    straight past that model until its window passes. A model without one is tried every time.
    """
    kept = [*breakers, *[None] * (len(models) - len(breakers))]
    guarded = [
        GuardedModel(model, seconds, guard) for model, guard in zip(models, kept, strict=False)
    ]
    return FallbackModel(*guarded, fallback_on=moves_on)


def model_chain(
    primary: Model | str,
    fallback: Model | str,
    seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    breaker: CircuitBreaker | None = None,
    reserve: Model | str | None = None,
    later_breakers: tuple[CircuitBreaker | None, ...] = (),
) -> FallbackModel:
    """A primary, a fallback, and an optional reserve, with their breakers in that order."""
    models = [primary, fallback] if reserve is None else [primary, fallback, reserve]
    return model_stack(models, seconds, [breaker, *later_breakers])
