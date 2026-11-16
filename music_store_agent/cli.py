"""Terminal chat. The phone flag is the WhatsApp sender, an extra way to confirm an order."""

import argparse
import asyncio
import os
import sys
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


NO_KEY_MESSAGE = (
    "Defina GOOGLE_API_KEY para conversar com o modelo, "
    "ou rode python -m music_store_agent --stub para testar sem chave."
)
EXIT_NO_KEY = 2
EXIT_BAD_SETTING = 3


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.stub and not (os.environ.get("GOOGLE_API_KEY") or "").strip():
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return EXIT_NO_KEY
    try:
        asyncio.run(_chat(args))
    except ValueError as error:
        # A model id, timeout, breaker window, or --today the app cannot use.
        print(error, file=sys.stderr)
        return EXIT_BAD_SETTING
    return 0


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
    if args.once is not None:
        await _print_turn(agent, deps, args.once, history)
        return
    while True:
        try:
            text = input("Você: ").strip()
        except EOFError:
            return
        if not text or text.casefold() in {"sair", "exit", "quit"}:
            return
        history = await _print_turn(agent, deps, text, history)


async def _print_turn(
    agent,
    deps,
    text: str,
    history: list[ModelMessage],
) -> list[ModelMessage]:
    turn = await run_turn(agent, deps, text, history)
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
