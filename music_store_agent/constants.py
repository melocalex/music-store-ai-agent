"""Named money, policy, and limit values. Do not scatter literals."""

from datetime import time
from decimal import Decimal
from typing import Literal

STORE_NAME = "Empório da Música"
ASSISTANT_NAME = "Aria"
STORE_TIMEZONE = "America/Campo_Grande"
STORE_CITY = "Campo Grande"

WHATSAPP_PHONE = "(67) 3321-4500"
LANDLINE_PHONE = "(67) 3341-4444"
STORE_EMAIL = "contato@emporiodamusica.com.br"
ACCENTED_EMAIL = "contato@empóriodamusica.com.br"
STORE_ADDRESS = "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, 79202-333"

MODEL_PROVIDER = "google"
DEFAULT_MODEL = f"{MODEL_PROVIDER}:gemini-3.8-flash"
MODEL_ENV = "MODEL"
CLOCK_ENV = "MUSIC_STORE_CLOCK"
TODAY_ENV = "MUSIC_STORE_TODAY"
REAL_CLOCK_VALUE = "real"

CENT = Decimal("0.01")
PIX_PERCENT = Decimal("5")
INSTALLMENT_MAX = 12
TIER_LOW_MAX = 3
TIER_MID_MAX = 6
CASH_INSTALLMENTS = 1
MIN_PARCEL_2_TO_3 = Decimal("50.00")
MIN_PARCEL_4_TO_6 = Decimal("80.00")
MIN_PARCEL_7_TO_12 = Decimal("100.00")
SPLIT_PAYMENT_ABOVE = Decimal("2000.00")
FREIGHT_FREE_FROM = Decimal("500.00")
FREIGHT_FLAT = Decimal("35.00")
QUANTITY_MAX = 10
QUANTITY_MIN = 1

REGRET_DAYS = 7
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90
PREFERENCE_DAYS = 7
FACTORY_WARRANTY = "de 6 meses a 2 anos, conforme o certificado que acompanha o produto"
TEAM_REPLY_BUSINESS_HOURS = 24

MAX_VERIFICATION_ATTEMPTS = 3
SEARCH_ROW_CAP = 5
SIMILAR_CAP = 3
CATALOG_FETCH_LIMIT = 500
ORDER_ITEMS_LIMIT = 50
EMPTY_CATEGORY_IDS = (6, 7, 8)
SESSION_TURN_CAP = 30
DAILY_TURN_CAP = 80
HANDOFF_SUMMARY_CAP = 400
OUTPUT_RETRIES = 1
TOOL_RETRIES = 1
PINNED_DAY_OFFSET = 1
HOLIDAY_LOOKAHEAD_DAYS = 21
PHONE_MIN_DIGITS = 10
PHONE_NATIONAL_MAX_DIGITS = 11
COUNTRY_CODE = "55"
OFFSET_MAX = 200

WEEKDAY_OPEN = time(9, 0)
WEEKDAY_CLOSE = time(18, 0)
SATURDAY_OPEN = time(9, 0)
SATURDAY_CLOSE = time(13, 0)
REFERENCE_TIME = time(10, 0)
SUNDAY = 6
SATURDAY = 5

ANIVERSARIO_MIN_PERCENT = Decimal("10")
ANIVERSARIO_MAX_PERCENT = Decimal("25")
BLACK_FRIDAY_MIN_PERCENT = Decimal("15")
BLACK_FRIDAY_MAX_PERCENT = Decimal("30")
CG_DELIVERY_MIN_BUSINESS_DAYS = 1
CG_DELIVERY_MAX_BUSINESS_DAYS = 3

STATUS_ACTIVE = "active"
STATUS_DISCONTINUED = "discontinued"
STATUS_COMING_SOON = "coming_soon"
STATE_AVAILABLE = "available"
STATE_OUT_OF_STOCK = "out_of_stock"
STATE_DISCONTINUED = "discontinued"
STATE_COMING_SOON = "coming_soon"
STATE_UNKNOWN = "unknown"
BLACK_FRIDAY = "Black Friday"

SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_NAME = "name"

ORDER_CANCELLED = "cancelled"
ORDER_DELIVERED = "delivered"
OPEN_DELIVERY_STATUSES = frozenset({"shipped", "confirmed", "pending"})
PAYMENT_PIX = "pix"
PAYMENT_DEBIT = "debit"
PAYMENT_CREDIT = "credit"
PAYMENT_BOLETO = "boleto"
PAYMENT_SPLIT = "pix_and_card"
CASH_PAYMENTS = frozenset({PAYMENT_PIX, PAYMENT_DEBIT, PAYMENT_BOLETO})
DESTINATION_CITY = "campo_grande"
DESTINATION_OTHER = "other"

# Tool arguments the model must pick from. Pydantic turns these into enums in the schema.
SortOrder = Literal[SORT_PRICE_ASC, SORT_PRICE_DESC, SORT_NAME]
PaymentMethod = Literal[PAYMENT_PIX, PAYMENT_DEBIT, PAYMENT_CREDIT, PAYMENT_BOLETO, PAYMENT_SPLIT]
Destination = Literal[DESTINATION_CITY, DESTINATION_OTHER]
HandoffReason = Literal[
    "purchase",
    "cancel",
    "address_change",
    "return_request",
    "complaint",
    "out_of_city_freight",
    "discount_request",
    "other",
]
HANDOFF_REASON_CAP = 40

VERIFICATION_FAILED = "Não encontrei um pedido com esses dados."
VERIFICATION_LOCKED = "Não consegui confirmar o pedido. Vou chamar alguém da equipe."
ASK_CONTACT = "Preciso do e-mail completo ou do telefone completo usados nesse pedido."
ASK_PHONE = "Para confirmar esse pedido, preciso também do telefone completo usado na compra."
NOT_VERIFIED = "Preciso confirmar o pedido antes de consultar o status."
NOT_YOUR_ORDER = "Esse pedido não está vinculado à confirmação atual."
SAFE_PRICE_MESSAGE = (
    "Não consegui confirmar um valor com segurança. "
    "Vou chamar alguém da equipe para seguir com você."
)
RATE_LIMIT_MESSAGE = "Estou recebendo muitas perguntas agora. Espere um minuto e tente de novo."
SESSION_CAP_MESSAGE = "Cheguei ao limite de mensagens desta conversa. Abra uma conversa nova."
DAILY_CAP_MESSAGE = (
    "O limite de atendimento de hoje foi atingido. "
    f"Volte amanhã ou fale no WhatsApp {WHATSAPP_PHONE}."
)
RETRY_PRICE = (
    "Há valor sem fonte ou ligado ao produto errado. "
    "Responda de novo só com pares de produto e valor que uma ferramenta devolveu."
)

# Fixed dates only. Carnival, Good Friday, and Corpus Christi move and are not listed.
FIXED_HOLIDAYS = (
    (1, 1, "Confraternização Universal", "national"),
    (4, 21, "Tiradentes", "national"),
    (5, 1, "Dia do Trabalho", "national"),
    (6, 13, "Santo Antônio", "campo_grande"),
    (8, 26, "Aniversário de Campo Grande", "campo_grande"),
    (9, 7, "Independência do Brasil", "national"),
    (10, 11, "Criação do estado de Mato Grosso do Sul", "campo_grande"),
    (10, 12, "Nossa Senhora Aparecida", "national"),
    (11, 2, "Finados", "national"),
    (11, 15, "Proclamação da República", "national"),
    (12, 25, "Natal", "national"),
)

SAMPLE_QUESTIONS = (
    "Quais violões até R$ 1000 vocês têm?",
    "Quanto custa o Takamine?",
    "O Takamine GD-20 da Black Friday ainda tem desconto?",
    "Qual o preço do Crafter HT-100 no PIX?",
    "Vocês abrem no sábado e no dia 13 de junho?",
    "Qual o frete do Yamaha C40 para São Paulo?",
    "Me arrependi de uma compra. Posso devolver?",
    "Quero saber o status de um pedido.",
)
