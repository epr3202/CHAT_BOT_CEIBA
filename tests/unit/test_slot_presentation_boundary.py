from __future__ import annotations

import importlib
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import structlog

from app.conversation import knowledge
from app.conversation.presentation import (
    EVENT_TYPE_LABELS,
    format_date_natural,
    format_event_type,
    format_month_natural,
)
from app.event.models import EVENT_TYPES
from app.orchestrator import service as orchestrator_service


def presentation_api() -> tuple[Any, dict[str, Any], type[Exception]]:
    module = importlib.import_module("app.conversation.presentation")
    return (
        module.present_variables,
        module.VARIABLE_PRESENTERS,
        module.VariablePresentationError,
    )


def approved_template_variables() -> set[str]:
    approved_responses = (
        Path(__file__).parents[2] / "docs" / "conversation" / "approved-responses.md"
    )
    variables: set[str] = set()
    for line in approved_responses.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            variables.update(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", line))
    return variables


def test_tc_display_001_template_value_uses_natural_spanish_display_name() -> None:
    rendered = "Te comparto nuestro catálogo para {event_type}.".format(
        event_type=format_event_type("ROMANTIC_DINNER")
    )

    assert "cena romántica" in rendered
    assert "ROMANTIC_DINNER" not in rendered


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda value: f"TC-DISPLAY-002-{value}")
def test_every_official_event_type_has_a_non_enum_display_name(event_type: str) -> None:
    assert set(EVENT_TYPE_LABELS) == set(EVENT_TYPES)
    assert format_event_type(event_type) == EVENT_TYPE_LABELS[event_type]
    assert EVENT_TYPE_LABELS[event_type] != event_type


@pytest.mark.parametrize("event_type", EVENT_TYPES, ids=lambda value: f"TC-DISPLAY-003-{value}")
def test_composed_message_never_exposes_raw_event_type_identifier(event_type: str) -> None:
    rendered = f"Para {format_event_type(event_type)}, revisaremos el espacio."
    raw_enum = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")

    assert raw_enum.search(rendered) is None


def test_tc_display_004_verbatim_user_text_is_not_reused_as_template_value() -> None:
    user_text = "CENA ROMÁNTICA!!!"
    rendered = "Te comparto nuestro catálogo para {event_type}.".format(
        event_type=format_event_type("ROMANTIC_DINNER")
    )

    assert user_text not in rendered
    assert "cena romántica" in rendered


def test_every_approved_template_variable_has_a_registered_presenter() -> None:
    _, presenters, _ = presentation_api()

    assert approved_template_variables() <= set(presenters)


def test_unregistered_variable_fails_explicitly() -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({"invented_slot": "INTERNAL_SLOT"})


def test_registered_core_formatters_preserve_their_contracts() -> None:
    present_variables, presenters, _ = presentation_api()

    assert {"event_type", "event_date", "event_month"} <= set(presenters)
    assert format_event_type("WEDDING") == "una boda"
    assert format_date_natural(date(2026, 8, 19)) == "19 de agosto de 2026"
    assert format_month_natural("2026-08") == "agosto de 2026"
    assert present_variables(
        {
            "event_type": "WEDDING",
            "event_date": date(2026, 8, 19),
            "event_month": "2026-08",
        }
    ) == {
        "event_type": "una boda",
        "event_date": "19 de agosto de 2026",
        "event_month": "agosto de 2026",
    }


def test_visit_confirmation_uses_canonical_label_for_literal_incident() -> None:
    present_variables, _, _ = presentation_api()

    variables = present_variables({"event_type": "Una boda"})
    rendered = "para conocer el espacio pensando en {event_type}".format(**variables)

    assert rendered == "para conocer el espacio pensando en una boda"
    assert "Una boda" not in rendered


def test_unresolved_free_text_event_type_degrades_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    present_variables, _, _ = presentation_api()
    raw_value = "una boda para mi hija"

    with caplog.at_level("WARNING"):
        variables = present_variables({"event_type": raw_value})
    rendered = "pensando en {event_type}".format(**variables)

    assert rendered == "pensando en tu celebración"
    assert raw_value not in rendered
    assert "event_type_presentation_fallback" in caplog.text
    assert raw_value in caplog.text


def test_quote_summary_normalizes_literal_requested_services_incident() -> None:
    present_variables, _, _ = presentation_api()

    variables = present_variables({"requested_services_summary": "Solo el espacio"})
    rendered = "con interés en {requested_services_summary}".format(**variables)

    assert rendered == "con interés en el espacio"
    assert "Solo el espacio" not in rendered


@pytest.mark.parametrize(
    "variable",
    ["visit_date", "event_date", "resolved_date", "new_visit_date"],
)
def test_date_presenters_reject_non_formatter_text(variable: str) -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({variable: "el 4 de septiembre"})


@pytest.mark.parametrize(
    "variable",
    ["visit_date", "event_date", "resolved_date", "new_visit_date"],
)
def test_date_presenters_accept_exact_formatter_text_and_date(variable: str) -> None:
    present_variables, _, _ = presentation_api()

    assert present_variables({variable: "19 de agosto de 2026"}) == {
        variable: "19 de agosto de 2026"
    }
    assert present_variables({variable: date(2026, 8, 19)}) == {
        variable: "19 de agosto de 2026"
    }


def test_month_presenter_requires_exact_formatter_text() -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({"event_month": "septiembre"})
    assert present_variables({"event_month": "septiembre de 2026"}) == {
        "event_month": "septiembre de 2026"
    }


@pytest.mark.parametrize("variable", ["visit_time", "new_visit_time"])
def test_time_presenters_require_exact_formatter_text(variable: str) -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({variable: "a las 8"})
    assert present_variables({variable: "08:00"}) == {variable: "08:00"}


def test_appointment_options_require_exact_formatter_text() -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({"appointment_options": "varias horas disponibles"})
    assert present_variables({"appointment_options": "08:00, 09:00 y 11:00"}) == {
        "appointment_options": "08:00, 09:00 y 11:00"
    }


def test_guest_count_range_requires_exact_formatter_text() -> None:
    present_variables, _, presentation_error = presentation_api()

    with pytest.raises(presentation_error):
        present_variables({"guest_count_range": "más o menos cuarenta"})
    assert present_variables({"guest_count_range": "entre 40 y 50"}) == {
        "guest_count_range": "entre 40 y 50"
    }


@pytest.mark.parametrize(
    ("variable", "raw_value", "expected"),
    [
        ("missing_field", "event_type", "el tipo de evento"),
        ("missing_field", "guest_count", "la cantidad de invitados"),
        ("missing_field", "event_date", "la fecha del evento"),
        ("missing_field", "requested_services", "los servicios que deseas incluir"),
        (
            "missing_field",
            "la confirmación de la solicitud",
            "la confirmación de la solicitud",
        ),
        ("pending_topic", "requested_services", "los servicios"),
        ("pending_topic", "COLLECT_SERVICES", "los servicios"),
    ],
)
def test_internal_slot_labels_use_approved_customer_text(
    variable: str,
    raw_value: str,
    expected: str,
) -> None:
    present_variables, _, _ = presentation_api()

    assert present_variables({variable: raw_value}) == {variable: expected}


@pytest.mark.asyncio
async def test_unregistered_variable_uses_controlled_render_failure_path(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entries = {
        "RESP-TEST-PRESENTATION": SimpleNamespace(
            status="APPROVED",
            answer_template="Texto parcial {invented_slot}",
            allowed_variables=["invented_slot"],
        ),
        "RESP-AI-ERROR-001": SimpleNamespace(
            status="APPROVED",
            answer_template="Respuesta aprobada de respaldo.",
            allowed_variables=[],
        ),
    }

    async def fake_get_latest_response(_sessionmaker: object, code: str) -> Any:
        return entries.get(code)

    monkeypatch.setattr(knowledge, "get_latest_response", fake_get_latest_response)
    session = Mock()
    conversation = SimpleNamespace(id=101, last_question_code=None)
    customer = SimpleNamespace(phone_number="+573001112233")
    inbound_message = SimpleNamespace(id=202)

    previous_structlog_config = structlog.get_config()
    structlog.configure(
        processors=[structlog.stdlib.render_to_log_kwargs],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    try:
        with caplog.at_level("ERROR", logger="app.orchestrator.service"):
            await orchestrator_service.enqueue_template(
                session,
                object(),
                conversation,
                customer,
                inbound_message,
                "RESP-TEST-PRESENTATION",
                {"invented_slot": "INTERNAL_SLOT"},
            )
    finally:
        structlog.configure(
            **previous_structlog_config,
        )

    outbox = session.add.call_args.args[0]
    body = outbox.payload["text"]["body"]
    assert body == "Respuesta aprobada de respaldo."
    assert "Texto parcial" not in body
    assert "INTERNAL_SLOT" not in body
    assert any(
        (
            getattr(record, "event", None) == "approved_response_render_failed"
            or "approved_response_render_failed" in record.getMessage()
        )
        and (
            getattr(record, "response_code", None) == "RESP-TEST-PRESENTATION"
            or (
                isinstance(record.msg, dict)
                and record.msg.get("response_code") == "RESP-TEST-PRESENTATION"
            )
        )
        for record in caplog.records
    )
