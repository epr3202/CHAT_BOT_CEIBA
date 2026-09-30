"""B1a acceptance contracts; missing features fail assertions during test execution.

No fallback implementation or import-time skips: these tests must remain executable
on the G2 baseline and exercise the real models/services once G3 supplies them.
"""

from importlib import import_module
from types import ModuleType
from typing import Any

STATUSES = ("PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED", "EXPIRED", "CANCELLED")
VALID_TRANSITIONS = {
    ("PAYMENT_PENDING", "PAYMENT_REVIEW"),
    ("PAYMENT_PENDING", "EXPIRED"),
    ("PAYMENT_PENDING", "CANCELLED"),
    ("PAYMENT_REVIEW", "RESERVED"),
    ("PAYMENT_REVIEW", "CANCELLED"),
    ("RESERVED", "CANCELLED"),
}
# name -> (event_type, price_cop, duration_minutes, exclusive, weekend_only)
EXPECTED_PLANS = {
    "Ritual del Corazón": ("ROMANTIC_DINNER", 250000, 180, False, False),
    "Romance entre Copas": ("ROMANTIC_DINNER", 400000, 180, False, False),
    "Mañanas de Encanto": ("ROMANTIC_DINNER", 450000, 180, False, True),
    "Cinema y Amor": ("ROMANTIC_DINNER", 700000, 180, False, False),
    "Refugio para Dos": ("ROMANTIC_DINNER", 1000000, 180, False, False),
    "Entre Pétalos y Estrellas": ("PROPOSAL", 450000, 180, False, False),
    "Confesión bajo la Luna": ("PROPOSAL", 900000, 180, False, False),
    "Noche Inolvidable": ("PROPOSAL", 2500000, 180, True, False),
}


def require_module(name: str) -> ModuleType:
    try:
        return import_module(name)
    except ModuleNotFoundError as error:
        # Do not disguise missing third-party dependencies or broken internal imports.
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        raise AssertionError(f"B1a: falta implementar el módulo {name}") from error


def require_symbol(module_name: str, name: str) -> Any:
    module = require_module(module_name)
    value = getattr(module, name, None)
    assert value is not None, f"B1a: falta el contrato {module_name}.{name}"
    return value
