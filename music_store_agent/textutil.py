"""Text helpers: folding, money parsing, contact comparison, masking."""

import re
import unicodedata
from decimal import Decimal

from music_store_agent.constants import (
    CENT,
    COUNTRY_CODE,
    PHONE_MIN_DIGITS,
    PHONE_NATIONAL_MAX_DIGITS,
)

_UNITS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
_TENS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
_HUNDREDS = {
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
_SCALES = {"mil": 1000, "milhao": 1_000_000, "milhoes": 1_000_000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_HUNDREDS) | set(_SCALES) | {"e"}
# One shape for pt-BR (1.749,50) and English (1,749.50) money. A final separator with one or
# two digits is the decimal point. A separator before three digits groups thousands.
_NUMBER = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CURRENCY = r"R\$|BRL|US\$|\$"
_MONEY = re.compile(
    rf"(?:{_CURRENCY})\s*(?P<pre>{_NUMBER})(?![\d.,]*\d)"
    rf"|(?<![\d.,])(?P<suf>{_NUMBER})\s*(?:reais|real|BRL)\b"
    rf"|(?<![\d.,])(?P<bare>\d{{1,3}}(?:[.,]\d{{3}})+[.,]\d{{2}}|\d+[.,]\d{{2}})(?![\d.,]*\d)",
    re.IGNORECASE,
)
_AMOUNT_TEXT = re.compile(rf"(?:{_CURRENCY})?\s*({_NUMBER})\s*(?:reais|real|BRL)?", re.IGNORECASE)
_PERCENT = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:%|por\s*cento\b|percent\b)", re.IGNORECASE
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_CANDIDATE = re.compile(r"\+?\d[\d\s().-]{8,}\d")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.casefold()


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def emails_match(stored: str, given: str) -> bool:
    return stored.strip().casefold() == given.strip().casefold()


def phones_match(stored: str, given: str) -> bool:
    left = national_phone(stored)
    right = national_phone(given)
    if len(left) < PHONE_MIN_DIGITS or len(right) < PHONE_MIN_DIGITS:
        return False
    return left == right


def national_phone(text: str) -> str:
    """DDD plus number. Drops a trunk 0 and the 55 country code, so DDD 55 still works."""
    number = digits(text).lstrip("0")
    if len(number) > PHONE_NATIONAL_MAX_DIGITS and number.startswith(COUNTRY_CODE):
        return number[len(COUNTRY_CODE) :]
    return number


def format_brl(amount: Decimal) -> str:
    quantized = amount.quantize(CENT)
    sign = "-" if quantized < 0 else ""
    cents_total = abs(int(quantized * 100))
    whole, cents = divmod(cents_total, 100)
    whole_text = f"{whole:,}".replace(",", ".")
    return f"R$ {sign}{whole_text},{cents:02d}"


def format_amount(amount: Decimal) -> str:
    return f"{amount.quantize(CENT):.2f}"


def parse_amount(value: object) -> Decimal:
    """Read 1000, 1.000, 1.000,00, 1,000.00, R$ 1000, or 1000 reais. Raise ValueError otherwise."""
    if isinstance(value, Decimal):
        return value.quantize(CENT)
    if isinstance(value, int | float):
        return Decimal(str(value)).quantize(CENT)
    match = _AMOUNT_TEXT.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"not an amount: {value!r}")
    return _number_value(match.group(1))


def parse_money_token(token: str) -> Decimal | None:
    try:
        return parse_amount(token)
    except ValueError:
        return None


def _number_value(token: str) -> Decimal:
    head, separator, tail = _split_decimal(token)
    whole = re.sub(r"[.,]", "", head)
    text = f"{whole}.{tail}" if separator else whole
    return Decimal(text).quantize(CENT)


def _split_decimal(token: str) -> tuple[str, str, str]:
    cut = max(token.rfind(","), token.rfind("."))
    if cut < 0 or len(token) - cut - 1 == len("000"):
        return token, "", ""
    return token[:cut], token[cut], token[cut + 1 :]


def amounts_in_text(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for match in _MONEY.finditer(text):
        token = match.group("pre") or match.group("suf") or match.group("bare")
        found.add(_number_value(token))
    found.update(_word_amounts(text))
    return found


def percents_in_text(text: str) -> set[Decimal]:
    return {_number_value(match.group(1)) for match in _PERCENT.finditer(text)}


def _word_amounts(text: str) -> set[Decimal]:
    tokens = re.findall(r"[a-z]+|\d+", fold(text))
    found: set[Decimal] = set()
    for index, token in enumerate(tokens):
        if token not in {"real", "reais"}:
            continue
        whole = _whole_before(tokens, index)
        if whole is None:
            continue
        cents = _cents_after(tokens, index)
        if cents is None:
            continue
        found.add((Decimal(whole) + (Decimal(cents) / Decimal(100))).quantize(CENT))
    return found


def _whole_before(tokens: list[str], index: int) -> int | None:
    if index > 0 and tokens[index - 1].isdigit():
        return None  # digits before "reais" are read by _MONEY, with their decimals
    words = _walk_back(tokens, index)
    if not words:
        return None
    return parse_pt_number(words)


def _cents_after(tokens: list[str], index: int) -> int | None:
    if index + 1 >= len(tokens) or tokens[index + 1] != "e":
        return 0
    words: list[str] = []
    cursor = index + 2
    while cursor < len(tokens) and tokens[cursor] in _NUMBER_WORDS:
        words.append(tokens[cursor])
        cursor += 1
    if cursor >= len(tokens) or tokens[cursor] != "centavos":
        return 0
    while words and words[-1] == "e":
        words.pop()
    parsed = parse_pt_number(words)
    if parsed is None or parsed > 99:
        return None
    return parsed


BRANDS = (
    "music man",
    "takamine",
    "giannini",
    "yamaha",
    "tagima",
    "crafter",
    "martin",
    "taylor",
    "shelby",
    "rozini",
    "kalani",
    "gibson",
    "fender",
    "ibanez",
    "roland",
    "pearl",
    "ohana",
    "tama",
    "kala",
    "korg",
    "nord",
    "prs",
)


def brands_in(text: str) -> set[str]:
    folded = fold(text)
    found: set[str] = set()
    for brand in BRANDS:
        if re.search(rf"(?<![a-z]){re.escape(brand)}(?![a-z])", folded):
            found.add(brand)
    return found


def description_conflicts(name: str, description: str) -> bool:
    named = brands_in(name)
    described = brands_in(description)
    if not named or not described:
        return False
    return named.isdisjoint(described)


def _walk_back(tokens: list[str], index: int) -> list[str]:
    cursor = index - 1
    picked: list[str] = []
    while cursor >= 0 and tokens[cursor] in _NUMBER_WORDS:
        picked.append(tokens[cursor])
        cursor -= 1
    picked.reverse()
    while picked and picked[0] == "e":
        picked.pop(0)
    while picked and picked[-1] == "e":
        picked.pop()
    return picked


def parse_pt_number(words: list[str]) -> int | None:
    total = 0
    current = 0
    seen = False
    for word in words:
        if word == "e":
            continue
        seen = True
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word in _HUNDREDS:
            current += _HUNDREDS[word]
        elif word in _SCALES:
            factor = current or 1
            total += factor * _SCALES[word]
            current = 0
        else:
            return None
    if not seen:
        return None
    return total + current


def mask_pii(text: str) -> str:
    masked = _EMAIL.sub("[email]", text)

    def _phone(match: re.Match[str]) -> str:
        if len(digits(match.group(0))) >= PHONE_MIN_DIGITS:
            return "[phone]"
        return match.group(0)

    return _PHONE_CANDIDATE.sub(_phone, masked)


def code_tokens(text: str) -> set[str]:
    folded = fold(text)
    found: set[str] = set()
    for token in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", folded):
        compact = token.replace("-", "")
        if re.search(r"[a-z]", compact) and re.search(r"\d", compact):
            found.add(compact)
    parts = re.findall(r"[a-z0-9]+", folded)
    for left, right in zip(parts, parts[1:], strict=False):
        if re.fullmatch(r"[a-z]+", left) and right.isdigit():
            found.add(left + right)
        if left.isdigit() and re.fullmatch(r"[a-z]+", right):
            found.add(left + right)
    return found
