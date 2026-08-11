from __future__ import annotations

NO_APPROVED_ANSWER = "NO_APPROVED_ANSWER"

CATEGORY_RESPONSE_CODES: dict[str, str] = {
    "identidad": "RESP-DISCOVERY-002",
    "ubicacion": "RESP-LOCATION-001",
    "ubicación": "RESP-LOCATION-001",
    "mapa": "RESP-LOCATION-002",
    "enlace de google maps": "RESP-LOCATION-002",
    "parqueadero": "RESP-PARKING-001",
    "capacidad": "RESP-CAPACITY-001",
    "capacidades": "RESP-CAPACITY-001",
    "espacios": "RESP-SPACES-001",
    "tipos de eventos": "RESP-EVENTS-001",
    "piscina": "RESP-POOL-001",
    "mascotas": "RESP-PETS-001",
    "proveedores": "RESP-SUPPLIERS-001",
    "proveedores externos": "RESP-SUPPLIERS-001",
    "alimentos": "RESP-FOOD-001",
    "alimentos externos": "RESP-FOOD-001",
    "bebidas externas": "RESP-BEVERAGES-001",
    "licor": "RESP-BEVERAGES-002",
    "descorche": "RESP-BEVERAGES-003",
    "alojamiento": "RESP-ACCOMMODATION-001",
    "horarios": "RESP-EVENT-HOURS-001",
    "horario de eventos": "RESP-EVENT-HOURS-001",
    "horarios de eventos": "RESP-EVENT-HOURS-001",
    "horario humano": "RESP-HANDOFF-002",
    "visitas": "RESP-VISIT-001",
    "horarios de visitas": "RESP-VISIT-001",
    "proceso para cotizar": "RESP-PRICE-001",
    "separacion": "RESP-RESERVATION-001",
    "separación": "RESP-RESERVATION-001",
    "proceso para separar una fecha": "RESP-RESERVATION-001",
    "pagos": "RESP-PAYMENT-METHODS-001",
    "medios de pago": "RESP-PAYMENT-METHODS-001",
    "servicios": "RESP-SERVICES-001",
    "servicios generales": "RESP-SERVICES-001",
    "tiempos de respuesta": "RESP-QUOTE-004",
    "cancelacion": "RESP-CANCEL-EVENT-002",
    "cancelación": "RESP-CANCEL-EVENT-002",
    "politica general de cancelacion": "RESP-CANCEL-EVENT-002",
    "política general de cancelación": "RESP-CANCEL-EVENT-002",
    "fallos tecnicos": "RESP-AI-ERROR-001",
    "fallos técnicos": "RESP-AI-ERROR-001",
    "seguridad": "RESP-SECURITY-001",
}

FAQ_CATEGORY_VALUES = tuple(CATEGORY_RESPONSE_CODES.keys())

FAQ_CATEGORY_PROMPT_BLOCK = "\n".join(f"- {category}" for category in FAQ_CATEGORY_VALUES)


def response_code_for_category(category: str) -> str:
    normalized = " ".join(category.strip().lower().split())
    return CATEGORY_RESPONSE_CODES.get(normalized, NO_APPROVED_ANSWER)
