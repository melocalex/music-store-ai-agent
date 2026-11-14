"""One assistant, with an explicit tool list."""

import os
from decimal import Decimal

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model, parse_model_id
from pydantic_ai.providers import infer_provider_class

from music_store_agent.catalog import (
    CatalogQuery,
    active_promotion_text,
    describe_matches,
    find_products,
    is_sellable,
    load_catalog,
    search_catalog,
)
from music_store_agent.constants import (
    DEFAULT_MODEL,
    DESTINATION_CITY,
    MODEL_ENV,
    MODEL_PROVIDER,
    OUTPUT_RETRIES,
    PAYMENT_PIX,
    RETRY_PRICE,
    SORT_PRICE_ASC,
    TOOL_RETRIES,
    Destination,
    PaymentMethod,
    SortOrder,
)
from music_store_agent.deps import Deps
from music_store_agent.guard import AgentReply, grounding_gap
from music_store_agent.handoff import write_handoff
from music_store_agent.hours import hours_answer, parse_asked_day
from music_store_agent.orders import explain_after_sales, read_order, verify
from music_store_agent.policies import PolicySection, load_manual, sections_text
from music_store_agent.prompts import INSTRUCTIONS
from music_store_agent.quotes import quote_text
from music_store_agent.textutil import amounts_in_text, parse_amount, percents_in_text

_MANUAL = load_manual()


def model_id(raw: str | None = None) -> str:
    """Return a Gemini id the installed Pydantic AI can resolve, or raise at startup."""
    chosen = (raw if raw is not None else os.environ.get(MODEL_ENV, "")).strip() or DEFAULT_MODEL
    provider, _name = parse_model_id(chosen)
    if provider != MODEL_PROVIDER:
        raise ValueError(f"MODEL={chosen!r} is not a Gemini API id. Use {DEFAULT_MODEL!r}.")
    infer_provider_class(provider)
    return chosen


def build_agent(model: Model | str | None = None) -> Agent[Deps, AgentReply]:
    chosen = model if isinstance(model, Model) else model_id(model)
    agent: Agent[Deps, AgentReply] = Agent(
        chosen,
        deps_type=Deps,
        output_type=AgentReply,
        instructions=INSTRUCTIONS,
        name="aria",
        retries={"output": OUTPUT_RETRIES, "tools": TOOL_RETRIES},
        defer_model_check=True,
    )
    _register(agent)
    return agent


def _register(agent: Agent[Deps, AgentReply]) -> None:
    agent.tool(name="search_catalog")(search_products)
    agent.tool(get_product)
    agent.tool(quote_offer)
    agent.tool(list_active_promotions)
    agent.tool(consult_policy)
    agent.tool(verify_customer)
    agent.tool(get_order)
    agent.tool(name="explain_after_sales")(explain_order_policy)
    agent.tool(check_hours)
    agent.tool(handoff_to_human)
    agent.instructions(reference_day)
    agent.output_validator(validate_reply)


def reference_day(ctx: RunContext[Deps]) -> str:
    """Reference date injected on every turn."""
    clock = ctx.deps.clock
    kind = "fixo, um dia após o último pedido" if clock.pinned else "relógio real"
    return f"Data de referência: {clock.today().isoformat()} ({kind}). Use só esta data."


def validate_reply(ctx: RunContext[Deps], reply: AgentReply) -> AgentReply:
    names = {product.product_id: product.name for product in load_catalog(ctx.deps.conn)}
    gap = grounding_gap(reply.message, reply.quotes, ctx.deps.ledger, names)
    if gap.ok:
        return reply
    ctx.deps.counters.validator_firings += 1
    if gap.unknown:
        ctx.deps.counters.validator_catches += 1
    raise ModelRetry(RETRY_PRICE)


def search_products(
    ctx: RunContext[Deps],
    query: str = "",
    category: str | None = None,
    max_price: str | None = None,
    sort_by: SortOrder = SORT_PRICE_ASC,
    offset: int = 0,
) -> str:
    """Search instruments that are for sale, five rows at a time.

    Args:
        query: Customer words such as "violão eletroacústico" or "ukulele concert".
            Words outside the catalog vocabulary are ignored.
        category: Family in any spelling, for example "violões", "Violão", or "Guitarras".
        max_price: Budget in reais, for example "1000" or "1.000,00".
        sort_by: price_asc for the cheapest first, price_desc for the most expensive first.
        offset: Row to start from, to see the next block.
    """
    ceiling = _money(max_price)
    request = CatalogQuery(query, category, ceiling, sort_by, offset)
    return _shown(ctx, search_catalog(load_catalog(ctx.deps.conn), request, ctx.deps.ledger))


def get_product(ctx: RunContext[Deps], query: str = "", product_id: int | None = None) -> str:
    """Look up one model: state, price, PIX, promotion, specs, or several matches.

    Args:
        query: Model code or name, for example "C40", "GD-20", or "Takamine".
        product_id: The id a previous tool printed. Use it instead of the query when known.
    """
    if not query.strip() and product_id is None:
        return "Diga o modelo, o código ou o id do produto."
    products = load_catalog(ctx.deps.conn)
    found = find_products(products, query, product_id)
    return _shown(ctx, describe_matches(products, found, ctx.deps.ledger))


def quote_offer(
    ctx: RunContext[Deps],
    query: str,
    quantity: int = 1,
    payment: PaymentMethod = PAYMENT_PIX,
    installments: int = 1,
    destination: Destination = DESTINATION_CITY,
) -> str:
    """Price one sellable product with payment, installments, and freight.

    Refuses a price for anything not for sale.

    Args:
        query: Model code, name, or the product id a tool printed, for example "C40" or "81".
        quantity: Units, limited by the stock.
        payment: pix, debit, credit, boleto, or pix_and_card.
        installments: Number of credit card parcels, from 1 to 12.
        destination: campo_grande for the city, other for any other city.
    """
    if not query.strip():
        return "Diga o modelo, o código ou o id do produto."
    products = load_catalog(ctx.deps.conn)
    found = find_products(products, query)
    if len(found) != 1 or not is_sellable(found[0]):
        return _shown(ctx, describe_matches(products, found, ctx.deps.ledger))
    in_city = destination == DESTINATION_CITY
    text = quote_text(found[0], quantity, payment, installments, in_city, ctx.deps.ledger)
    return _shown(ctx, text)


def list_active_promotions(ctx: RunContext[Deps]) -> str:
    """List promotions that are active now. Inactive campaigns are not prices."""
    return _shown(ctx, active_promotion_text(load_catalog(ctx.deps.conn), ctx.deps.ledger))


def consult_policy(ctx: RunContext[Deps], sections: list[PolicySection]) -> str:
    """Return whole policy sections. Use the section name, not a search query."""
    text = sections_text(list(sections), _MANUAL)
    for amount in amounts_in_text(text):
        ctx.deps.ledger.add_policy(amount)
    return _shown(ctx, text)


def verify_customer(
    ctx: RunContext[Deps],
    order_id: int,
    email: str | None = None,
    phone: str | None = None,
) -> str:
    """Confirm an order with the full email or full phone of that order's owner.

    Args:
        order_id: The order number the customer gave.
        email: The full email the customer typed, if any.
        phone: The full phone with area code the customer typed, if any.
    """
    identity = ctx.deps.identity
    was_locked = identity.locked
    text = verify(identity, ctx.deps.conn, order_id, email, phone)
    if identity.locked and not was_locked:
        _handoff(ctx, "verification_failed", "Confirmação falhou após as tentativas permitidas.")
    return text


def get_order(ctx: RunContext[Deps], order_id: int) -> str:
    """Read one order that belongs to the confirmed customer. Uses the stored total."""
    deps = ctx.deps
    return read_order(deps.identity, deps.conn, order_id, deps.clock.today(), deps.ledger)


def explain_order_policy(ctx: RunContext[Deps], order_id: int) -> str:
    """State return and warranty rules for one confirmed order, then hand off. Does not approve."""
    deps = ctx.deps
    result = explain_after_sales(deps.identity, deps.conn, order_id, deps.clock.today())
    if result.open_to_request:
        _handoff(ctx, "return_request", f"Pedido {order_id}: regra explicada, sem aprovação.")
    return result.text


def check_hours(ctx: RunContext[Deps], day: str | None = None) -> str:
    """Say if the store is open. Pass YYYY-MM-DD or DD/MM for a specific day, including holidays."""
    asked = parse_asked_day(day, ctx.deps.clock.today())
    if day and asked is None:
        return "Não entendi a data. Use AAAA-MM-DD."
    return hours_answer(ctx.deps.clock.now(), asked)


def handoff_to_human(ctx: RunContext[Deps], reason: str, summary: str) -> str:
    """Record a handoff when the store would have to commit to an order or exception."""
    _handoff(ctx, reason, summary)
    return "Registrei o encaminhamento para a equipe. Alguém retoma o contato."


def _handoff(ctx: RunContext[Deps], reason: str, summary: str) -> None:
    write_handoff(
        ctx.deps.paths.handoff,
        ctx.deps.clock.now(),
        reason,
        summary,
        ctx.deps.identity.verified_customer_id,
    )


def _shown(ctx: RunContext[Deps], text: str) -> str:
    """Percents in tool text are the only ones the reply may repeat."""
    ctx.deps.ledger.add_percents(percents_in_text(text))
    return text


def _money(raw: str | None) -> Decimal | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return parse_amount(raw)
    except ValueError as error:
        raise ModelRetry("max_price precisa ser um valor em reais, por exemplo 1000.") from error
