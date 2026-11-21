from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.conversation.prefilled_form import parse_prefilled_form
from app.customer.models import Customer
from app.notifications.staff_texts import build_params
from app.plan.models import Plan

VISIT_FORM = (
    "Hola, equipo de La Ceiba! 💍 Quisiera solicitar una visita para conocer el lugar y "
    "conversar sobre nuestra boda. Nombre: Luna Ejemplo Correo: luna@example.org "
    "Visita solicitada: jueves, 29 de octubre de 2026 Hora: 3:13 p. m. (Colombia) "
    "Fecha estimada de la boda: no se Invitados: Menos de 50 Inversión contemplada (COP): "
    "Entre $15 y $20 millones Nos gustaría conocer o resolver: Lo conversaremos durante la "
    "visita. ¿Nos confirman si este horario está disponible? ¡Muchas gracias!"
)
EXPERIENCE_FORM = (
    "Hola, La Ceiba. Soy luna y quiero consultar disponibilidad para esta experiencia: "
    "Romance entre Copas · 2 personas Plan base: $400.000 COP Detalles adicionales: "
    "• Violín en vivo: $300.000 COP Subtotal definido: $700.000 COP Fecha deseada: "
    "31 de octubre de 2026 Horario preferido: Noche (por confirmar) Ocasión: Aniversario "
    "¿Me confirman disponibilidad, horario, valor final y condiciones para reservar?"
)


def with_line_breaks(text: str) -> str:
    for label in (
        "Nombre:",
        "Correo:",
        "Visita solicitada:",
        "Hora:",
        "Fecha estimada",
        "Invitados:",
        "Inversión contemplada",
        "Nos gustaría",
        "Plan base:",
        "Detalles adicionales:",
        "• ",
        "Subtotal definido:",
        "Fecha deseada:",
        "Horario preferido:",
        "Ocasión:",
        "¿",
    ):
        text = text.replace(f" {label}", f"\n{label}")
    return text


@pytest.mark.parametrize("message", [VISIT_FORM, with_line_breaks(VISIT_FORM)])
def test_visit_form_fields_are_read_from_their_labels(message: str) -> None:
    form = parse_prefilled_form(message)
    assert form.full_name == "Luna Ejemplo"
    assert form.email == "luna@example.org"
    assert form.guest_count_range == (1, 49)
    assert form.estimated_budget == Decimal("15000000")
    assert form.visit_reason == "Boda. Lo conversaremos durante la visita."
    assert form.requested_services == ()
    assert form.extras == ()
    assert "Fecha estimada de la boda: no se" in form.details
    assert "Invitados: Menos de 50" in form.details
    assert "Inversión contemplada (COP): Entre $15 y $20 millones" in form.details
    assert not any("luna@example.org" in line or "Luna" in line for line in form.details)


@pytest.mark.parametrize("message", [EXPERIENCE_FORM, with_line_breaks(EXPERIENCE_FORM)])
def test_experience_form_keeps_unpriced_extras_and_details(message: str) -> None:
    form = parse_prefilled_form(message)
    assert form.full_name == "Luna"
    assert form.email is None
    assert form.requested_services == ("VIOLINIST",)
    assert form.extras == ("Violín en vivo",)
    assert "Adicional por cotizar: Violín en vivo: $300.000 COP" in form.details
    assert "Subtotal definido: $700.000 COP" in form.details
    assert "Horario preferido: Noche (por confirmar)" in form.details
    assert "Ocasión: Aniversario" in form.details
    assert not any(line.startswith("¿") or "Me confirman" in line for line in form.details)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Invitados: Entre 80 y 120", (80, 120)),
        ("Invitados: 60", (60, 60)),
        ("Invitados: muchos", None),
    ],
)
def test_guest_count_label_variants(message: str, expected: tuple[int, int] | None) -> None:
    assert parse_prefilled_form(message).guest_count_range == expected


def test_free_text_without_labels_is_not_a_form() -> None:
    form = parse_prefilled_form("Hola, quiero información de bodas para 80 personas")
    assert form.is_empty
    assert form.full_name is None and form.details == ()


@pytest.mark.parametrize(
    "message,name",
    [
        ("Nombre: https://x.co Correo: no-es-un-correo", None),
        ("Nombre: 3001234567 Correo: a@b", None),
        ("Nombre: Ana Correo: " + "a" * 250 + "@x.co", "Ana"),
    ],
)
def test_invalid_name_and_email_are_discarded(message: str, name: str | None) -> None:
    form = parse_prefilled_form(message)
    assert form.email is None
    assert form.full_name == name


def test_extra_previews_are_bounded_and_the_advisor_keeps_all_originals() -> None:
    message = "Detalles adicionales: " + " ".join(f"• Extra {i}: {'x' * 400}" for i in range(40))
    form = parse_prefilled_form(message)
    assert len(form.details) == 40
    assert all(line.endswith("x" * 400) for line in form.details)
    assert len(form.extras) == 10 and all(len(name) <= 200 for name in form.extras)


def test_staff_request_notice_lists_extras_to_quote() -> None:
    params = build_params(
        customer=Customer(phone_number="+573001112233", full_name="Luna"),
        plan=Plan(name="Romance entre Copas"),
        starts_at=datetime(2026, 10, 8, 0, tzinfo=UTC),
        deposit_cop=200000,
        extras=("Violín en vivo",),
    )
    assert params[1] == "Romance entre Copas (adicionales por cotizar: Violín en vivo)"
    assert len(params) == 4 and all(len(p) <= 120 for p in params)


def test_staff_request_notice_without_extras_is_unchanged() -> None:
    params = build_params(
        customer=Customer(phone_number="+573001112233", full_name="Luna"),
        plan=Plan(name="Romance entre Copas"),
        starts_at=datetime(2026, 10, 8, 0, tzinfo=UTC),
        deposit_cop=200000,
    )
    assert params[1] == "Romance entre Copas"
