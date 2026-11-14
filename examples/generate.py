"""Write five real transcripts. This module does not invent model output."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import date
from pathlib import Path

from music_store_agent.agent import build_agent
from music_store_agent.clock import pinned_day
from music_store_agent.constants import DEFAULT_MODEL
from music_store_agent.db import last_order_date, load_database
from music_store_agent.deps import make_deps
from pydantic_ai.messages import ModelMessage

OUT_DIR = Path(__file__).with_name("transcripts")

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


def render_transcript(title: str, model: str, day: date, commit: str, turns: list[str]) -> str:
    body = "\n\n".join(turns)
    return f"# {title}\n\nModel: {model}\nDate: {day.isoformat()}\nCommit: {commit}\n\n{body}\n"


def git_commit() -> str:
    try:
        output = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return output.strip() or "unknown"


def tool_names(messages: list[ModelMessage]) -> str:
    names = [
        part.tool_name
        for message in messages
        for part in getattr(message, "parts", [])
        if getattr(part, "part_kind", "") == "tool-call" and part.tool_name != "final_result"
    ]
    return ", ".join(names) if names else "none"


async def _write_all(model: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = load_database()
    day = pinned_day(last_order_date(conn))
    commit = git_commit()
    agent = build_agent(model)
    for script in SCRIPTS:
        deps = make_deps(
            conn,
            today=day,
            handoff_path=OUT_DIR / "handoffs.jsonl",
            usage_path=OUT_DIR / "turns.json",
        )
        text = await _script(agent, deps, script, model, day, commit)
        (OUT_DIR / f"{script['title']}.md").write_text(text, encoding="utf-8")


async def _script(
    agent,
    deps,
    script: dict[str, object],
    model: str,
    day: date,
    commit: str,
) -> str:
    history: list[ModelMessage] = []
    chunks: list[str] = []
    prompts = script["prompts"]
    assert isinstance(prompts, tuple)
    for prompt in prompts:
        result = await agent.run(prompt, deps=deps, message_history=history)
        history = list(result.all_messages())
        tools = tool_names(list(result.new_messages()))
        chunks.append(f"User: {prompt}\n\nAria: {result.output.message}\n\nTools: {tools}")
    title = str(script["title"])
    return render_transcript(title, model, day, commit, chunks)


def main() -> int:
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Set GOOGLE_API_KEY to generate transcripts. Nothing here is invented.")
        return 2
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    asyncio.run(_write_all(model))
    print(OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
