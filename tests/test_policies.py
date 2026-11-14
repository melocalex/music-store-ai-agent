"""The curated manual covers each section of the policy PDF and agrees with the constants."""

from music_store_agent.constants import (
    ANIVERSARIO_MAX_PERCENT,
    ANIVERSARIO_MIN_PERCENT,
    BLACK_FRIDAY_MAX_PERCENT,
    BLACK_FRIDAY_MIN_PERCENT,
    CG_DELIVERY_MAX_BUSINESS_DAYS,
    CG_DELIVERY_MIN_BUSINESS_DAYS,
    DEFECT_EXCHANGE_DAYS,
    FACTORY_WARRANTY,
    FIXED_HOLIDAYS,
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    LANDLINE_PHONE,
    LEGAL_WARRANTY_DAYS,
    MIN_PARCEL_2_TO_3,
    MIN_PARCEL_4_TO_6,
    MIN_PARCEL_7_TO_12,
    PIX_PERCENT,
    PREFERENCE_DAYS,
    REGRET_DAYS,
    SPLIT_PAYMENT_ABOVE,
    STORE_ADDRESS,
    STORE_EMAIL,
    TEAM_REPLY_BUSINESS_HOURS,
    WHATSAPP_PHONE,
)
from music_store_agent.policies import PolicySection, load_manual, section_text
from music_store_agent.textutil import format_brl

# Facts from data/store_policies.pdf, one list per section.
SOURCE_FACTS = {
    "sobre": [
        "fundada em 2008",
        "12.345.678/0001-90",
        STORE_ADDRESS,
        LANDLINE_PHONE,
        STORE_EMAIL,
        "Não vende acessórios como cordas, palhetas, cabos, cases, pedais ou amplificadores",
    ],
    "horario": [
        "09:00 às 18:00",
        "09:00 às 13:00",
        "Domingo e feriados | Fechado",
        "respostas automáticas fora do expediente",
        "pode ser estendido",
    ],
    "pagamento": [
        f"{PIX_PERCENT}% de desconto sobre o preço de tabela",
        "Todas as bandeiras",
        "Até 12x sem juros",
        "3 dias úteis",
        format_brl(MIN_PARCEL_2_TO_3),
        format_brl(MIN_PARCEL_4_TO_6),
        format_brl(MIN_PARCEL_7_TO_12),
        f"acima de {format_brl(SPLIT_PAYMENT_ABOVE)}",
    ],
    "trocas": [
        f"{REGRET_DAYS} dias corridos após o recebimento",
        f"{DEFECT_EXCHANGE_DAYS} dias corridos após a compra",
        f"em até {PREFERENCE_DAYS} dias",
        "10 dias úteis",
        "frete da devolução é da loja",
        "embalagem original",
        "venda final",
        "boquilha",
        "Diferença de valor",
        "8.078/90",
    ],
    "frete": [
        f"acima de {format_brl(FREIGHT_FREE_FROM)}",
        format_brl(FREIGHT_FLAT),
        f"{CG_DELIVERY_MIN_BUSINESS_DAYS} a {CG_DELIVERY_MAX_BUSINESS_DAYS} dias úteis",
        "motoboy",
        "PAC (Correios) | 5 a 12 dias úteis",
        "SEDEX (Correios) | 2 a 5 dias úteis",
        "Jadlog (.package) | 3 a 8 dias úteis",
        "seguro contra extravio",
        "recusar o recebimento",
        "site dos Correios ou da Jadlog",
        "cotação individual",
    ],
    "promocoes": [
        f"de {ANIVERSARIO_MIN_PERCENT}% a {ANIVERSARIO_MAX_PERCENT}%",
        f"de {BLACK_FRIDAY_MIN_PERCENT}% a {BLACK_FRIDAY_MAX_PERCENT}%",
        "Volta às Aulas",
        "Queima de Estoque",
        "22 de novembro",
        "não se somam",
        "rain check",
        "preço original e do percentual",
    ],
    "atendimento": [
        WHATSAPP_PHONE,
        "5 minutos",
        f"{TEAM_REPLY_BUSINESS_HOURS} horas úteis",
        "temporariamente indisponível",
        "preço atual",
    ],
    "garantia": [
        f"{LEGAL_WARRANTY_DAYS} dias",
        "do recebimento",
        FACTORY_WARRANTY.split(",")[0],
        "trastes",
        "terceiro não autorizado",
        "Dano estético",
    ],
    "privacidade": ["13.709/2018", "consentimento explícito", "exclusão", "marketing"],
    "disposicoes": ["assistente virtual", "gerência", "Versão 2.1"],
}
DIRECTIVES = ("Não aprove", "Peça a data", "Não invente", "Encaminhe", "Não prometa")
ADDED_RULES = (
    "cancelado não entra em troca",
    "preferência: 7 dias corridos a partir do recebimento",
)


def test_every_section_loads() -> None:
    manual = load_manual()
    assert set(manual) == {section.value for section in PolicySection}
    for section in PolicySection:
        assert section_text(section, manual).startswith(f"# {section.value}")


def test_each_section_carries_the_source_facts() -> None:
    manual = load_manual()
    assert set(SOURCE_FACTS) == set(manual)
    for section, facts in SOURCE_FACTS.items():
        for fact in facts:
            assert fact in manual[section], (section, fact)


def test_every_fixed_holiday_is_listed() -> None:
    hours = load_manual()["horario"]
    for month, day, name, _scope in FIXED_HOLIDAYS:
        assert f"{day:02d}/{month:02d} {name}" in hours


def test_conduct_lives_in_the_prompt_and_no_rule_is_added() -> None:
    text = "\n".join(load_manual().values())
    for directive in DIRECTIVES:
        assert directive not in text, directive
    for rule in ADDED_RULES:
        assert rule not in text, rule
