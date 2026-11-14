"""Load the curated manual by section. The PDF is not parsed at runtime."""

from enum import StrEnum
from pathlib import Path

MANUAL_PATH = Path(__file__).with_name("manual.md")


class PolicySection(StrEnum):
    SOBRE = "sobre"
    HORARIO = "horario"
    PAGAMENTO = "pagamento"
    TROCAS = "trocas"
    FRETE = "frete"
    PROMOCOES = "promocoes"
    ATENDIMENTO = "atendimento"
    GARANTIA = "garantia"
    PRIVACIDADE = "privacidade"
    DISPOSICOES = "disposicoes"


def load_manual(path: Path | None = None) -> dict[str, str]:
    raw = (path or MANUAL_PATH).read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("# "):
            current = line[2:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def section_text(name: PolicySection, manual: dict[str, str] | None = None) -> str:
    source = manual if manual is not None else load_manual()
    body = source.get(name.value, "")
    return f"# {name.value}\n{body}".strip()


def sections_text(names: list[PolicySection], manual: dict[str, str] | None = None) -> str:
    source = manual if manual is not None else load_manual()
    return "\n\n".join(section_text(name, source) for name in names)
