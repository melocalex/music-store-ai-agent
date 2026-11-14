"""Terminal chat. The phone flag is the WhatsApp sender, an extra way to confirm an order."""

import argparse
import asyncio
import os
from datetime import date

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.test import TestModel

from music_store_agent.agent import build_agent
from music_store_agent.constants import ASSISTANT_NAME, STORE_NAME
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.run import run_turn
from music_store_agent.textutil import mask_pii

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    asyncio.run(_chat(args))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{ASSISTANT_NAME}, assistente da {STORE_NAME}")
    parser.add_argument("--phone", default=None, help="Telefone de quem escreveu no WhatsApp")
    parser.add_argument("--today", default=None, help="Data AAAA-MM-DD no lugar do relógio fixo")
    parser.add_argument("--real-clock", action="store_true", help="Usa o relógio real")
    parser.add_argument("--once", default=None, help="Uma pergunta e encerra")
    parser.add_argument("--stub", action="store_true", help="Resposta local, sem modelo remoto")
    return parser


async def _chat(args: argparse.Namespace) -> None:
    deps = make_deps(
        load_database(),
        today=_day(args.today),
        real=args.real_clock,
        phone=args.phone,
    )
    print(f"Data de referência: {deps.clock.today().isoformat()} ({deps.clock.label})")
    agent = build_agent(_stub_model() if args.stub else None)
    history: list[ModelMessage] = []
    turns = 0
    if args.once is not None:
        await _print_turn(agent, deps, args.once, history, turns)
        return
    while True:
        try:
            text = input("Você: ").strip()
        except EOFError:
            return
        if not text or text.casefold() in {"sair", "exit", "quit"}:
            return
        history = await _print_turn(agent, deps, text, history, turns)
        turns += 1


async def _print_turn(
    agent,
    deps,
    text: str,
    history: list[ModelMessage],
    turns: int,
) -> list[ModelMessage]:
    turn = await run_turn(agent, deps, text, history, turns)
    print(f"{ASSISTANT_NAME}: {mask_pii(turn.message)}")
    for quote in turn.quotes:
        label = "regra" if quote.product_id is None else f"produto {quote.product_id}"
        print(f"Fonte: {label} {quote.amount}")
    return list(turn.history)


def _stub_model() -> TestModel:
    return TestModel(
        call_tools=[],
        custom_output_args={
            "message": (
                f"Olá, sou a {ASSISTANT_NAME}, assistente virtual da {STORE_NAME}. "
                "Como posso ajudar?"
            ),
            "quotes": [],
        },
    )


def _day(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)
