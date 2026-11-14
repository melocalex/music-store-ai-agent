"""The curated manual is what the agent reads."""

from music_store_agent.constants import LANDLINE_PHONE, STORE_EMAIL, WHATSAPP_PHONE
from music_store_agent.policies import PolicySection, load_manual, section_text


def test_every_section_loads() -> None:
    manual = load_manual()
    assert set(manual) == {section.value for section in PolicySection}
    for section in PolicySection:
        assert section_text(section, manual).startswith(f"# {section.value}")


def test_hours_phones_and_email_are_pinned() -> None:
    manual = load_manual()
    hours = manual["horario"]
    assert "09:00 às 18:00" in hours
    assert "09:00 às 13:00" in hours
    assert "Domingo e feriados" in hours
    assert "13/06 Santo Antônio" in hours
    assert LANDLINE_PHONE in manual["sobre"]
    assert STORE_EMAIL in manual["sobre"]
    assert WHATSAPP_PHONE in manual["atendimento"]
    assert "telefone fixo" in manual["atendimento"].casefold() or "Telefone fixo" in manual["sobre"]
