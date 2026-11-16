"""One customer turn: caps, the model, then a fixed message for each kind of failure."""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import Agent, AgentRunResult
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    RunTimedOut,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.fallback import FallbackModel

from music_store_agent.constants import (
    INPUT_TOO_LONG_MESSAGE,
    MAX_INPUT_CHARS,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    SAFE_PRICE_MESSAGE,
    TURN_ERROR_MESSAGE,
    TURN_TIMEOUT_SECONDS,
)
from music_store_agent.deps import Deps
from music_store_agent.failover import (
    PrimaryBreakerOpen,
    is_daily_quota,
    is_quota_error,
)
from music_store_agent.guard import AgentReply, PriceQuote
from music_store_agent.handoff import HandoffCase, follow_up, write_handoff

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    message: str
    quotes: tuple[PriceQuote, ...]
    history: tuple[ModelMessage, ...]
    limited: bool = False
    new_messages: tuple[ModelMessage, ...] = ()


async def run_agent(
    agent: Agent[Deps, AgentReply],
    deps: Deps,
    message: str,
    history: list[ModelMessage],
) -> AgentRunResult[AgentReply]:
    """Run the agent once, and once more if the model's own output made it give up.

    `UnexpectedModelBehavior` is a model that answered in a way the run could not use: text where
    a reply was due, or tool arguments that stayed invalid. A second attempt usually fixes it. A
    turn the price check already gave up on is not retried, and the retry only gets what is left
    of the turn budget, so a customer never waits longer than `TURN_TIMEOUT_SECONDS`.
    """
    started = time.monotonic()
    firings = deps.counters.validator_firings
    try:
        return await agent.run(
            message, deps=deps, message_history=history, timeout=TURN_TIMEOUT_SECONDS
        )
    except UnexpectedModelBehavior as error:
        left = TURN_TIMEOUT_SECONDS - (time.monotonic() - started)
        if deps.counters.validator_firings > firings or left <= 0:
            raise
        _log.warning("turn retried once: %s", error_label(error))
        return await agent.run(message, deps=deps, message_history=history, timeout=left)


async def run_turn(
    agent: Agent[Deps, AgentReply],
    deps: Deps,
    message: str,
    history: list[ModelMessage],
) -> Turn:
    if len(message) > MAX_INPUT_CHARS:
        return Turn(INPUT_TOO_LONG_MESSAGE, (), tuple(history), limited=True)
    firings = deps.counters.validator_firings
    try:
        result = await run_agent(agent, deps, message, history)
    except ModelAPIError as error:
        _log.warning("provider error: %s", error_label(error))
        return _unanswered(history, provider_message(error))
    except (FallbackExceptionGroup, RunTimedOut) as error:
        # Every model failed, or the turn ran past its budget.
        _log.warning("no model answered: %s", error_label(error))
        return _unanswered(history, group_message(error))
    except UnexpectedModelBehavior as error:
        if deps.counters.validator_firings > firings:
            _log.warning("price check gave up: %s", error_label(error))
            return _safe_price(deps, history)
        _log.warning("turn failed: %s", error_label(error))
        return _unanswered(history, TURN_ERROR_MESSAGE)
    except Exception as error:
        _log.warning("turn crashed: %s", error_label(error))
        return _unanswered(history, TURN_ERROR_MESSAGE)
    reply = result.output
    fresh = tuple(result.new_messages())
    log_answering_model(agent, fresh)
    return Turn(reply.message, tuple(reply.quotes), tuple(result.all_messages()), False, fresh)


def log_answering_model(
    agent: Agent[Deps, AgentReply], messages: Sequence[ModelMessage]
) -> list[str]:
    """Name the model behind each response of the turn, and return those ids in order.

    A fallback answer is a warning. Only model ids and error types are logged: an error message
    can carry the provider's body.
    """
    chain = agent.model
    names: list[str] = []
    if not isinstance(chain, FallbackModel):
        return names
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        failed = message.failed_attempts or []
        answered = chain.models[min(len(failed), len(chain.models) - 1)].model_id
        names.append(answered)
        if not failed:
            _log.info("primary model %s answered", answered)
            continue
        causes = ", ".join(_attempt_text(attempt.model_name, attempt.error) for attempt in failed)
        _log.warning("fallback model %s answered after %s", answered, causes)
    return names


def _attempt_text(model_name: str, error: str | None) -> str:
    error_type = (error or "rejected").split(":", 1)[0]
    if error_type == PrimaryBreakerOpen.__name__:
        return f"{model_name} was skipped by the open breaker"
    return f"{model_name} failed with {error_type}"


def _unanswered(history: list[ModelMessage], message: str) -> Turn:
    """The visitor always gets a fixed message when no model answered."""
    return Turn(message, (), tuple(history), limited=True)


def provider_message(error: ModelAPIError) -> str:
    """A 429 is a limit. Its body says whether it is the day's quota. Anything else is generic."""
    if not is_quota_error(error):
        return PROVIDER_ERROR_MESSAGE
    return QUOTA_DAY_MESSAGE if is_daily_quota(error) else RATE_LIMIT_MESSAGE


def group_message(error: BaseException) -> str:
    """The message for a turn where every model failed.

    Only when every model hit a limit is the limit the reason: the day's quota if all of them
    spent it, otherwise the per-minute message. Any outage among them is a plain provider failure.
    """
    causes = _leaves(error)
    if not causes or not all(_is_limit(cause) for cause in causes):
        return PROVIDER_ERROR_MESSAGE
    return (
        QUOTA_DAY_MESSAGE if all(_is_day_limit(cause) for cause in causes) else RATE_LIMIT_MESSAGE
    )


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


def _is_limit(error: BaseException) -> bool:
    if isinstance(error, PrimaryBreakerOpen):
        return bool(error.quota)
    return is_quota_error(error)


def _is_day_limit(error: BaseException) -> bool:
    if isinstance(error, PrimaryBreakerOpen):
        return error.quota == "day"
    return is_daily_quota(error)


def error_label(error: BaseException) -> str:
    """The error type, its HTTP status, and its model. Never its message, body, or headers.

    A provider message can repeat the request, and a bad-key body can quote the key.
    """
    if isinstance(error, BaseExceptionGroup):
        return ", ".join(error_label(inner) for inner in error.exceptions)
    parts = [type(error).__name__]
    status = getattr(error, "status_code", None)
    if status is not None:
        parts.append(f"status={status}")
    model = getattr(error, "model_name", None)
    if model:
        parts.append(f"model={model}")
    return " ".join(parts)


def _safe_price(deps: Deps, history: list[ModelMessage]) -> Turn:
    identity = deps.identity
    case = HandoffCase(
        "price_check",
        "A resposta citou um valor que nenhuma ferramenta devolveu.",
        deps.protocol,
        identity.verified_customer_id,
        identity.verified_order_id,
    )
    write_handoff(deps.paths.handoff, deps.clock.now(), case)
    message = f"{SAFE_PRICE_MESSAGE} {follow_up(identity.verified_order_id, deps.protocol)}"
    return Turn(message, (), tuple(history), limited=True)
