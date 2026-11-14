"""One assistant, with an explicit tool list."""

import os
from decimal import Decimal

from pydantic_ai import Agent, ModelRetry, RunContext

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
    OUTPUT_RETRIES,
    RETRY_PRICE,
    TOOL_RETRIES,
)
from music_store_agent.deps import Deps
from music_store_agent.guard import AgentReply, grounding_gap
from music_store_agent.handoff import write_handoff
from music_store_agent.hours import hours_answer, parse_asked_day
from music_store_agent.orders import explain_after_sales, load_orders, read_order, verify
from music_store_agent.policies import PolicySection, load_manual, sections_text
from music_store_agent.prompts import INSTRUCTIONS
from music_store_agent.quotes import quote_text
from music_store_agent.textutil import amounts_in_text, parse_amount

_MANUAL = load_manual()


def build_agent(model: str | object | None = None) -> Agent[Deps, AgentReply]:
    chosen = model if model is not None else os.environ.get(MODEL_ENV, DEFAULT_MODEL)
    agent: Agent[Deps, AgentReply] = Agent(
        chosen,  # type: ignore[arg-type]
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
    gap = grounding_gap(reply.message, reply.quotes, ctx.deps.ledger)
    if gap.ok:
        return reply
    ctx.deps.counters.validator_firings += 1
    ctx.deps.counters.validator_catches += 1
    raise ModelRetry(RETRY_PRICE)


def search_products(
    ctx: RunContext[Deps],
    query: str = "",
    category: str | None = None,
    max_price: str | None = None,
    sort_by: str = "price_asc",
    offset: int = 0,
) -> str:
    """Search sellable instruments. Category uses the Portuguese catalog name."""
    ceiling = _money(max_price)
    request = CatalogQuery(query, category, ceiling, sort_by, offset)
    return search_catalog(load_catalog(ctx.deps.conn), request, ctx.deps.ledger)


def get_product(ctx: RunContext[Deps], query: str) -> str:
    """Look up one model. Returns out of stock, discontinued, coming soon, or several matches."""
    products = load_catalog(ctx.deps.conn)
    return describe_matches(products, find_products(products, query), ctx.deps.ledger)


def quote_offer(
    ctx: RunContext[Deps],
    query: str,
    quantity: int = 1,
    payment: str = "pix",
    installments: int = 1,
    destination: str = DESTINATION_CITY,
) -> str:
    """Price one sellable product. Refuses a price for anything not for sale."""
    products = load_catalog(ctx.deps.conn)
    found = find_products(products, query)
    if len(found) != 1:
        return describe_matches(products, found, ctx.deps.ledger)
    product = found[0]
    if not is_sellable(product):
        return describe_matches(products, found, ctx.deps.ledger)
    in_city = destination == DESTINATION_CITY
    return quote_text(product, quantity, payment, installments, in_city, ctx.deps.ledger)


def list_active_promotions(ctx: RunContext[Deps]) -> str:
    """List promotions that are active now. Inactive campaigns are not prices."""
    return active_promotion_text(load_catalog(ctx.deps.conn), ctx.deps.ledger)


def consult_policy(ctx: RunContext[Deps], sections: list[PolicySection]) -> str:
    """Return whole policy sections. Use the section name, not a search query."""
    text = sections_text(list(sections), _MANUAL)
    for amount in amounts_in_text(text):
        ctx.deps.ledger.add_policy(amount)
    return text


def verify_customer(
    ctx: RunContext[Deps],
    order_id: int,
    email: str | None = None,
    phone: str | None = None,
) -> str:
    """Confirm an order with the full email or full phone of that order's owner."""
    identity = ctx.deps.identity
    was_locked = identity.locked
    text = verify(identity, load_orders(ctx.deps.conn), order_id, email, phone)
    if identity.locked and not was_locked:
        _handoff(ctx, "verification_failed", "Confirmação falhou após as tentativas permitidas.")
    return text


def get_order(ctx: RunContext[Deps], order_id: int) -> str:
    """Read one order that belongs to the confirmed customer. Uses the stored total."""
    return read_order(ctx.deps.identity,
        load_orders(ctx.deps.conn),
        order_id,
        ctx.deps.clock.today(),
        ctx.deps.ledger)


def explain_order_policy(ctx: RunContext[Deps], order_id: int) -> str:
    """State return and warranty rules for one confirmed order, then hand off. Does not approve."""
    text = explain_after_sales(ctx.deps.identity,
        load_orders(ctx.deps.conn),
        order_id,
        ctx.deps.clock.today())
    if "A equipe confirma" in text:
        _handoff(ctx, "return_request", f"Pedido {order_id}: regra explicada, sem aprovação.")
    return text


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


def _money(raw: str | None) -> Decimal | None:
    if raw is None or not str(raw).strip():
        return None
    return parse_amount(raw)
