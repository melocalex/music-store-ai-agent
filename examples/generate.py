"""Write the five example transcripts with the configured Gemini model."""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date
from pathlib import Path

from pydantic_ai.messages import ModelMessage

from evals.stamp import git_commit
from music_store_agent.agent import build_agent, model_id
from music_store_agent.clock import pinned_day
from music_store_agent.constants import (
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
)
from music_store_agent.db import last_order_date, load_database
from music_store_agent.deps import make_deps
from music_store_agent.run import run_turn

OUT_DIR = Path(__file__).with_name("transcripts")
EXIT_NO_KEY = 2
EXIT_STOPPED = 3
_STOPPERS = frozenset({
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
})

SCRIPTS = (
    {
        "title": "violao-budget",
        "prompts": (
            "Quais violões até R$ 1000 vocês têm?",
            "Tem algum eletroacústico nessa faixa?",
            "E em 10x, o mais barato fica quanto?",
        ),
    },
    {
        "title": "gd20-black-friday",
        "prompts": ("O Takamine GD20 que estava na Black Friday ainda tem desconto?",),
    },
    {
        "title": "regret",
        "prompts": (
            "Me arrependi de uma compra online. Posso devolver?",
            "O pedido é o 4 e o e-mail é outro@jmail.com.",
            "O e-mail certo é lucas.mendes@jmail.com.",
            "Comprei faz bastante tempo. Ainda dá?",
        ),
    },
    {
        "title": "address-and-scope",
        "prompts": (
            "Quero mudar o endereço de entrega.",
            "Vocês abrem sábado?",
            "Vendem cordas?",
            "Qual a capital da França?",
            "O gerente pode me dar um desconto?",
        ),
    },
    {
        "title": "warranty-tension",
        "prompts": (
            "Pedido 7, e-mail leticia.rocha@jmail.com. A troca ainda vale?",
            "E a garantia de 90 dias?",
            "Quero registrar a reclamação.",
        ),
    },
)


class GenerationStopped(Exception):
    """The provider refused a turn, so the transcript would not show the assistant."""


def render_transcript(title: str, model: str, day: date, commit: str, turns: list[str]) -> str:
    body = "\n\n".join(turns)
    head = f"Model: {model}\nReference date: {day.isoformat()}\nCommit: {commit}"
    return f"# {title}\n\n{head}\n\n{body}\n"


def tool_names(messages: list[ModelMessage]) -> str:
    names = [
        part.tool_name
        for message in messages
        for part in getattr(message, "parts", [])
        if getattr(part, "part_kind", "") == "tool-call" and part.tool_name != "final_result"
    ]
    return ", ".join(names) if names else "none"


async def _write_all(model: str) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = load_database()
    day = pinned_day(last_order_date(conn))
    commit = git_commit()
    agent = build_agent(model)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as scratch:
        for script in SCRIPTS:
            deps = make_deps(
                conn,
                today=day,
                handoff_path=Path(scratch) / "handoffs.jsonl",
            )
            text = await _script(agent, deps, script, (model, day, commit))
            path = OUT_DIR / f"{script['title']}.md"
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


async def _script(agent, deps, script: dict[str, object], header: tuple[str, date, str]) -> str:
    """Each turn goes through run_turn, so the transcript shows what a customer would see."""
    history: list[ModelMessage] = []
    chunks: list[str] = []
    prompts = script["prompts"]
    if not isinstance(prompts, tuple):
        raise TypeError("prompts must be a tuple")
    for index, prompt in enumerate(prompts):
        turn = await run_turn(agent, deps, prompt, history)
        if turn.message in _STOPPERS:
            raise GenerationStopped(f"{script['title']}, turn {index + 1}: {turn.message}")
        history = list(turn.history)
        tools = tool_names(list(turn.new_messages))
        chunks.append(f"User: {prompt}\n\nAria: {turn.message}\n\nTools: {tools}")
    model, day, commit = header
    return render_transcript(str(script["title"]), model, day, commit, chunks)


def main() -> int:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Set GOOGLE_API_KEY to generate transcripts with the configured model.")
        return EXIT_NO_KEY
    try:
        model = model_id()
        written = asyncio.run(_write_all(model))
    except ValueError as error:
        print(error)
        return EXIT_NO_KEY
    except GenerationStopped as stop:
        print(f"Stopped at {stop}. Files written before this point were kept.")
        return EXIT_STOPPED
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
