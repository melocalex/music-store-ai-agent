"""One customer turn: caps, the model, then a fixed message for each kind of failure."""

from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelRateLimitError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage

from music_store_agent.clock import real_clock
from music_store_agent.constants import (
    DAILY_CAP_MESSAGE,
    DAILY_TURN_CAP,
    INPUT_TOO_LONG_MESSAGE,
    MAX_INPUT_CHARS,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    SAFE_PRICE_MESSAGE,
    SESSION_CAP_MESSAGE,
    SESSION_TURN_CAP,
    TURN_ERROR_MESSAGE,
)
from music_store_agent.deps import Deps
from music_store_agent.guard import AgentReply, PriceQuote
from music_store_agent.handoff import write_handoff
from music_store_agent.usage import reserve

_HTTP_TOO_MANY = 429
_DAILY_QUOTA_HINTS = ("perday", "per day", "per_day", "daily")


@dataclass(frozen=True)
class Turn:
    message: str
    quotes: tuple[PriceQuote, ...]
    history: tuple[ModelMessage, ...]
    limited: bool = False
    new_messages: tuple[ModelMessage, ...] = ()


async def run_turn(
    agent: Agent[Deps, AgentReply],
    deps: Deps,
    message: str,
    history: list[ModelMessage],
    session_turns: int,
    daily_limit: int = DAILY_TURN_CAP,
) -> Turn:
    if session_turns >= SESSION_TURN_CAP:
        return Turn(SESSION_CAP_MESSAGE, (), tuple(history), limited=True)
    if len(message) > MAX_INPUT_CHARS:
        return Turn(INPUT_TOO_LONG_MESSAGE, (), tuple(history), limited=True)
    if not reserve(deps.paths.usage, real_clock().today(), daily_limit):
        return Turn(DAILY_CAP_MESSAGE, (), tuple(history), limited=True)
    firings = deps.counters.validator_firings
    try:
        result = await agent.run(message, deps=deps, message_history=history)
    except ModelAPIError as error:
        return Turn(provider_message(error), (), tuple(history), limited=True)
    except UnexpectedModelBehavior:
        if deps.counters.validator_firings > firings:
            return _safe_price(deps, history)
        return Turn(TURN_ERROR_MESSAGE, (), tuple(history), limited=True)
    reply = result.output
    fresh = tuple(result.new_messages())
    return Turn(reply.message, tuple(reply.quotes), tuple(result.all_messages()), False, fresh)


def provider_message(error: ModelAPIError) -> str:
    """A 429 is a quota. Its body says whether it is the daily one. Anything else is generic."""
    limited = isinstance(error, ModelRateLimitError)
    limited = limited or getattr(error, "status_code", None) == _HTTP_TOO_MANY
    if not limited:
        return PROVIDER_ERROR_MESSAGE
    body = f"{getattr(error, 'body', '')} {error}".casefold()
    if any(hint in body for hint in _DAILY_QUOTA_HINTS):
        return QUOTA_DAY_MESSAGE
    return RATE_LIMIT_MESSAGE


def _safe_price(deps: Deps, history: list[ModelMessage]) -> Turn:
    write_handoff(
        deps.paths.handoff,
        deps.clock.now(),
        "price_check",
        "A resposta citou um valor que nenhuma ferramenta devolveu.",
        deps.identity.verified_customer_id,
    )
    return Turn(SAFE_PRICE_MESSAGE, (), tuple(history), limited=True)
