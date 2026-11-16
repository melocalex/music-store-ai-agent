"""A customer turn that runs off the page's script, so a rerun or a dropped tab cannot kill it."""

import asyncio
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from music_store_agent.constants import (
    PROVIDER_ERROR_MESSAGE,
    TURN_ERROR_MESSAGE,
    TURN_TIMEOUT_SECONDS,
)
from music_store_agent.deps import Deps
from music_store_agent.guard import AgentReply
from music_store_agent.language import say
from music_store_agent.run import Turn, error_label, run_turn

# The turn has its own budget. This one only catches a worker that never came back.
JOB_DEADLINE_SECONDS = TURN_TIMEOUT_SECONDS + 30.0
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="turn")
_log = logging.getLogger(__name__)


@dataclass
class TurnJob:
    """One turn in flight. It lives in the visitor's session until its answer is shown."""

    prompt: str
    history: tuple[ModelMessage, ...]
    future: Future[Turn]
    started: float = field(default_factory=time.monotonic)

    def finished(self) -> bool:
        return self.future.done() or self.overdue()

    def overdue(self) -> bool:
        return not self.future.done() and time.monotonic() - self.started > JOB_DEADLINE_SECONDS

    def result(self) -> Turn:
        """The turn, or a fixed message in the customer's language if the worker failed."""
        if not self.future.done():
            _log.warning("turn worker did not answer in %.0f seconds", JOB_DEADLINE_SECONDS)
            return Turn(say(PROVIDER_ERROR_MESSAGE, self.prompt), (), self.history, limited=True)
        error = self.future.exception()
        if error is not None:
            _log.warning("turn worker failed: %s", error_label(error))
            return Turn(say(TURN_ERROR_MESSAGE, self.prompt), (), self.history, limited=True)
        return self.future.result()


def start_turn(
    agent: Agent[Deps, AgentReply],
    deps: Deps,
    prompt: str,
    history: list[ModelMessage],
) -> TurnJob:
    kept = tuple(history)
    future = _POOL.submit(_work, agent, deps, prompt, list(kept))
    return TurnJob(prompt, kept, future)


def _work(
    agent: Agent[Deps, AgentReply],
    deps: Deps,
    prompt: str,
    history: list[ModelMessage],
) -> Turn:
    """Never raises: any failure is logged by type and becomes a fixed message."""
    try:
        return asyncio.run(run_turn(agent, deps, prompt, history))
    except Exception as error:
        _log.warning("turn crashed: %s", error_label(error))
        return Turn(say(TURN_ERROR_MESSAGE, prompt), (), tuple(history), limited=True)
