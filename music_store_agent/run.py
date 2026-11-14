"""One customer turn: caps, the model, then a safe fallback if the price check fails."""

from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelRateLimitError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage

from music_store_agent.clock import real_clock
from music_store_agent.constants import (
    DAILY_CAP_MESSAGE,
    DAILY_TURN_CAP,
    RATE_LIMIT_MESSAGE,
    SAFE_PRICE_MESSAGE,
    SESSION_CAP_MESSAGE,
    SESSION_TURN_CAP,
)
from music_store_agent.deps import Deps
from music_store_agent.guard import AgentReply, PriceQuote
from music_store_agent.handoff import write_handoff
from music_store_agent.usage import reserve


@dataclass(frozen=True)
class Turn:
    message: str
    quotes: tuple[PriceQuote, ...]
    history: tuple[ModelMessage, ...]
    limited: bool = False


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
    if not reserve(deps.paths.usage, real_clock().today(), daily_limit):
        return Turn(DAILY_CAP_MESSAGE, (), tuple(history), limited=True)
    try:
        result = await agent.run(message, deps=deps, message_history=history)
    except (ModelRateLimitError, ModelAPIError) as error:
        if _rate_limited(error):
            return Turn(RATE_LIMIT_MESSAGE, (), tuple(history), limited=True)
        raise
    except UnexpectedModelBehavior:
        return _safe_price(deps, history)
    reply = result.output
    return Turn(reply.message, tuple(reply.quotes), tuple(result.all_messages()))


def _rate_limited(error: ModelAPIError) -> bool:
    if isinstance(error, ModelRateLimitError):
        return True
    return getattr(error, "status_code", None) == 429


def _safe_price(deps: Deps, history: list[ModelMessage]) -> Turn:
    write_handoff(
        deps.paths.handoff,
        deps.clock.now(),
        "price_check",
        "A resposta citou um valor que nenhuma ferramenta devolveu.",
        deps.identity.verified_customer_id,
    )
    return Turn(SAFE_PRICE_MESSAGE, (), tuple(history), limited=True)
