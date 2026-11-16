"""Pick Portuguese or English for the fixed messages, from the customer's own words.

A model writes its replies in the customer's language. The fixed messages, such as the price
check handoff or a provider error, are code, so they need the same choice. Portuguese is the
default, and English wins only when the message clearly reads as English.
"""

import re

from music_store_agent.constants import (
    INPUT_TOO_LONG_MESSAGE,
    MAX_INPUT_CHARS,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    SAFE_PRICE_MESSAGE,
    TURN_ERROR_MESSAGE,
    WHATSAPP_PHONE,
)
from music_store_agent.textutil import fold

# Words that belong to one language only. "a", "do", "no", "me" and "as" are in both, so they
# vote for neither.
_ENGLISH = frozenset(
    """the you your have has any is are am was how much what which where when who why can could
    would should will please under below over above about with without for and or of to in on it
    its this that these those there here do does did i my mine we our they them he she hello hi
    hey thanks thank yes not want need looking show tell price prices cost costs cheap cheapest
    guitar guitars acoustic electric bass drum drums violin piano keyboard order delivery shipping
    store open hours
    """.split()
)
_PORTUGUESE = frozenset(
    """o os um uma uns umas de da dos das em na nas nos que qual quais quanto quanta quando onde
    quem como porque por pra para pelo pela com sem sobre voce voces vc tem tenho temos ter quero
    queria preciso posso pode podem gostaria oi ola bom boa dia tarde noite obrigado obrigada sim
    nao ate abaixo acima menos mais preco precos custa custam violao violoes guitarra guitarras
    baixo bateria teclado pedido entrega frete loja aberta horario e eu meu minha meus minhas
    seu sua seus suas esse essa isso isto aqui ai ali tambem ainda ja so
    """.split()
)
_ACCENTED = re.compile(r"[ãõçáéíóúâêô]", re.IGNORECASE)

ENGLISH_MESSAGES = {
    SAFE_PRICE_MESSAGE: (
        "I couldn't confirm a price with certainty. I'll bring in someone from the team to "
        "follow up with you."
    ),
    RATE_LIMIT_MESSAGE: (
        "The service that writes my answers is getting too many requests this minute. "
        f"Try again shortly or message us on WhatsApp {WHATSAPP_PHONE}."
    ),
    QUOTA_DAY_MESSAGE: (
        "The service that writes my answers has reached today's quota. "
        f"Come back tomorrow or message us on WhatsApp {WHATSAPP_PHONE}."
    ),
    PROVIDER_ERROR_MESSAGE: (
        "The service that writes my answers failed just now. "
        f"Try again shortly or message us on WhatsApp {WHATSAPP_PHONE}."
    ),
    TURN_ERROR_MESSAGE: "I couldn't put that answer together. Could you rephrase the question?",
    INPUT_TOO_LONG_MESSAGE: (
        f"The message is over {MAX_INPUT_CHARS} characters. Could you sum it up in one question?"
    ),
}


def is_english(text: str) -> bool:
    """True when the words clearly read as English. Empty, short, or mixed text is Portuguese."""
    words = re.findall(r"[a-z]+", fold(text))
    english = sum(word in _ENGLISH for word in words)
    portuguese = sum(word in _PORTUGUESE for word in words) + 2 * len(_ACCENTED.findall(text))
    return english > portuguese


def say(portuguese: str, customer_message: str) -> str:
    """The fixed message in the language of the customer's message."""
    if is_english(customer_message):
        return ENGLISH_MESSAGES.get(portuguese, portuguese)
    return portuguese


def is_safe_price_reply(reply: str) -> bool:
    """True for the price-check handoff in either language."""
    return reply.startswith((SAFE_PRICE_MESSAGE, ENGLISH_MESSAGES[SAFE_PRICE_MESSAGE]))
