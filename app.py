"""Hosted chat. Visitors never paste a key. The host sets GOOGLE_API_KEY."""

import asyncio
import os

import streamlit as st
from pydantic_ai.messages import ModelMessage

from music_store_agent.agent import build_agent
from music_store_agent.clock import weekday_name
from music_store_agent.constants import (
    ASSISTANT_NAME,
    MAX_INPUT_CHARS,
    SAMPLE_QUESTIONS,
    STORE_NAME,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.run import run_turn
from music_store_agent.textutil import mask_pii

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

LIVE_NOTE = "A cópia hospedada dorme depois de um tempo sem uso e acorda na próxima visita."
DISCLAIMER = "Protótipo. Catálogo, clientes e pedidos são fictícios."
WORKING = "Consultando catálogo, pedidos e regras..."
_HIDDEN_TOOLS = frozenset({"final_result"})


def host_key() -> str | None:
    secret = ""
    try:
        secret = str(st.secrets.get("GOOGLE_API_KEY", "") or "")
    except (FileNotFoundError, AttributeError, KeyError):
        secret = ""
    return secret or os.environ.get("GOOGLE_API_KEY") or None


def safe_markdown(text: str) -> str:
    """Mask email and phone, and escape $ so a pair of R$ values is not read as LaTeX."""
    return mask_pii(text).replace("$", "\\$")


def tool_lines(messages: list[ModelMessage]) -> list[str]:
    lines: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            if getattr(part, "part_kind", "") != "tool-call":
                continue
            name = getattr(part, "tool_name", "tool")
            if name in _HIDDEN_TOOLS:
                continue
            args = mask_pii(str(getattr(part, "args", "")))
            lines.append(f"{name}: {args}")
    return lines


def main() -> None:
    st.set_page_config(page_title=STORE_NAME, page_icon="🎸")
    try:
        _ensure_session()
    except ValueError as error:
        st.error(str(error))
        return
    now = st.session_state.deps.clock.now()
    label = st.session_state.deps.clock.label
    st.info(f"Data de referência: {weekday_name(now.date())}, {now.date().isoformat()} ({label}).")
    st.title(ASSISTANT_NAME)
    st.caption(f"Assistente virtual da {STORE_NAME}. {DISCLAIMER}")
    _sidebar()
    if not host_key():
        st.warning("O responsável pelo site ainda não configurou a chave do modelo.")
        return
    _history()
    typed = st.chat_input("Escreva sua pergunta", max_chars=MAX_INPUT_CHARS)
    prompt = typed or st.session_state.pop("pending", None)
    if prompt:
        _ask(prompt)
    st.caption(LIVE_NOTE)


def _ensure_session() -> None:
    if "deps" in st.session_state:
        return
    os.environ.setdefault("GOOGLE_API_KEY", host_key() or "")
    st.session_state.agent = build_agent()
    st.session_state.deps = make_deps(load_database())
    st.session_state.history = []
    st.session_state.turns = 0
    st.session_state.chat = []


def _sidebar() -> None:
    st.sidebar.header("Exemplos")
    for question in SAMPLE_QUESTIONS:
        if st.sidebar.button(question, key=f"sample-{question}"):
            st.session_state.pending = question


def _history() -> None:
    for item in st.session_state.chat:
        with st.chat_message(item["role"]):
            st.markdown(safe_markdown(item["text"]))
            if item["role"] == "assistant":
                _tools(item)


def _tools(item: dict[str, object]) -> None:
    with st.expander("Chamadas de ferramenta desta resposta"):
        for line in item.get("tools", []):
            st.text(line)
        for quote in item.get("quotes", []):
            st.text(quote)


def _ask(prompt: str) -> None:
    with st.chat_message("user"):
        st.markdown(safe_markdown(prompt))
    with st.chat_message("assistant"), st.spinner(WORKING):
        turn = asyncio.run(
            run_turn(
                st.session_state.agent,
                st.session_state.deps,
                prompt,
                list(st.session_state.history),
                st.session_state.turns,
            )
        )
    st.session_state.history = list(turn.history)
    st.session_state.turns += 1
    quotes = [f"valor {quote.product_id} {quote.amount}" for quote in turn.quotes]
    st.session_state.chat.append({"role": "user", "text": prompt})
    st.session_state.chat.append(
        {
            "role": "assistant",
            "text": turn.message,
            "tools": tool_lines(list(turn.new_messages)),
            "quotes": quotes,
        }
    )
    st.rerun()


if __name__ == "__main__":
    main()
