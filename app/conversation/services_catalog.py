from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceCatalogEntry:
    code: str
    label: str
    presentation: str | None
    aliases: tuple[str, ...]
    description: str


SERVICE_CATALOG: tuple[ServiceCatalogEntry, ...] = (
    ServiceCatalogEntry(
        "VENUE",
        "Espacio",
        "el espacio",
        ("espacio", "lugar", "sede", "solo espacio", "solo el espacio", "alquiler"),
        "Alquiler del lugar físico para el evento, sin servicios adicionales.",
    ),
    ServiceCatalogEntry(
        "FURNITURE",
        "Mobiliario",
        "el mobiliario",
        ("mobiliario", "mesas", "sillas", "muebles"),
        "Mesas, sillas y mobiliario estándar del montaje.",
    ),
    ServiceCatalogEntry(
        "ADDITIONAL_FURNITURE",
        "Mobiliario adicional",
        "el mobiliario adicional",
        ("mobiliario adicional", "muebles extra", "salas lounge", "mobiliario especial"),
        "Mobiliario más allá del montaje estándar.",
    ),
    ServiceCatalogEntry(
        "TABLEWARE",
        "Vajilla",
        "la vajilla",
        ("vajilla", "platos", "cubiertos"),
        "Vajilla y cubertería para el servicio de mesa.",
    ),
    ServiceCatalogEntry(
        "GLASSWARE",
        "Cristalería",
        "la cristalería",
        ("cristaleria", "copas", "vasos"),
        "Copas y vasos para el servicio de bebidas.",
    ),
    ServiceCatalogEntry(
        "FOOD",
        "Gastronomía",
        "la gastronomía",
        ("gastronomia", "comida", "catering", "menu", "alimentacion", "banquete"),
        "Servicio de alimentación general del evento.",
    ),
    ServiceCatalogEntry(
        "BRUNCH", "Brunch", "el brunch", ("brunch", "desayuno"), "Servicio de brunch o desayuno."
    ),
    ServiceCatalogEntry(
        "DINNER", "Cena", "la cena", ("cena", "cena formal"), "Servicio de cena servida."
    ),
    ServiceCatalogEntry(
        "SNACKS",
        "Pasabocas",
        "los pasabocas",
        ("pasabocas", "pasapalos", "picada", "bocaditos", "aperitivos"),
        "Pasabocas o aperitivos para los invitados.",
    ),
    ServiceCatalogEntry(
        "NON_ALCOHOLIC_BEVERAGES",
        "Bebidas sin alcohol",
        "las bebidas sin alcohol",
        ("jugos", "gaseosas", "refrescos", "bebidas sin alcohol"),
        "Bebidas no alcohólicas; ‘bebidas’ a secas es ambiguo.",
    ),
    ServiceCatalogEntry(
        "COCKTAILS",
        "Coctelería",
        "la coctelería",
        ("cocteleria", "cocteles", "bar", "barra de cocteles"),
        "Servicio de coctelería con bartender.",
    ),
    ServiceCatalogEntry(
        "ALCOHOL_SERVICE",
        "Servicio de licor",
        "el servicio de licor",
        ("licor", "alcohol", "servicio de licor", "trago"),
        "Servicio y atención de bebidas alcohólicas.",
    ),
    ServiceCatalogEntry(
        "CAKE", "Torta", "la torta", ("torta", "pastel", "ponque"), "Torta o pastel del evento."
    ),
    ServiceCatalogEntry(
        "DESSERT_TABLE",
        "Mesa de postres",
        "la mesa de postres",
        ("postres", "mesa de postres", "mesa dulce", "dulces"),
        "Mesa o estación de postres.",
    ),
    ServiceCatalogEntry(
        "SHOT_CART",
        "Carrito de shots",
        "el carrito de shots",
        ("carrito de shots", "shots"),
        "Carrito móvil de shots para la fiesta.",
    ),
    ServiceCatalogEntry(
        "WAITSTAFF",
        "Atención de meseros",
        "la atención de meseros",
        ("meseros", "meseras", "atencion", "servicio de meseros"),
        "Personal de servicio a la mesa durante el evento.",
    ),
    ServiceCatalogEntry(
        "SECURITY",
        "Seguridad",
        "el servicio de seguridad",
        ("seguridad", "vigilancia"),
        "Personal de seguridad para el evento.",
    ),
    ServiceCatalogEntry(
        "CHILDREN_ENTERTAINMENT",
        "Entretenimiento infantil",
        "el entretenimiento infantil",
        (
            "recreacion",
            "recreacionistas",
            "entretenimiento infantil",
            "ninos",
            "payasos",
            "inflables",
        ),
        "Recreación y entretenimiento para niños.",
    ),
    ServiceCatalogEntry(
        "DECORATION",
        "Decoración",
        "la decoración",
        ("decoracion", "decorado", "ambientacion", "adornos"),
        "Decoración general del espacio.",
    ),
    ServiceCatalogEntry(
        "FLORAL_DESIGN",
        "Floristería",
        "la floristería",
        ("floristeria", "flores", "arreglos florales", "ramos"),
        "Diseño y arreglos florales.",
    ),
    ServiceCatalogEntry(
        "LIGHTING",
        "Iluminación especial",
        "la iluminación especial",
        ("iluminacion", "luces"),
        "Iluminación decorativa o especial más allá de la básica.",
    ),
    ServiceCatalogEntry(
        "GIANT_LETTERS",
        "Letras gigantes",
        "las letras gigantes",
        ("letras gigantes", "letras luminosas", "letras"),
        "Letras decorativas de gran formato.",
    ),
    ServiceCatalogEntry(
        "WELCOME_MIRROR",
        "Espejo de bienvenida",
        "el espejo de bienvenida",
        ("espejo", "espejo de bienvenida"),
        "Espejo decorativo de bienvenida con mensaje.",
    ),
    ServiceCatalogEntry(
        "DJ", "DJ", "el DJ", ("dj", "discjockey", "musica cruzada"), "DJ para la música del evento."
    ),
    ServiceCatalogEntry(
        "LIVE_MUSIC",
        "Música en vivo",
        "la música en vivo",
        ("musica en vivo", "banda", "grupo musical", "mariachi", "trio", "parranda"),
        "Agrupación o artista en vivo.",
    ),
    ServiceCatalogEntry(
        "VIOLINIST",
        "Violinista",
        "el violinista",
        ("violinista", "violin"),
        "Violinista para momentos especiales.",
    ),
    ServiceCatalogEntry(
        "SAXOPHONIST",
        "Saxofonista",
        "el saxofonista",
        ("saxofonista", "saxo", "saxofon"),
        "Saxofonista para ambientación.",
    ),
    ServiceCatalogEntry(
        "SOUND",
        "Sonido",
        "el sonido",
        ("sonido", "equipo de sonido", "parlantes", "amplificacion"),
        "Equipo y refuerzo de sonido.",
    ),
    ServiceCatalogEntry(
        "MICROPHONE",
        "Micrófono",
        "el micrófono",
        ("microfono", "microfonos"),
        "Micrófonos para discursos o ceremonia.",
    ),
    ServiceCatalogEntry(
        "SCREEN",
        "Pantalla",
        "la pantalla",
        ("pantalla", "pantallas", "proyector", "video beam"),
        "Pantalla o proyección para el evento.",
    ),
    ServiceCatalogEntry(
        "PHOTOGRAPHY",
        "Fotografía",
        "la fotografía",
        ("fotografia", "fotografo", "fotos"),
        "Fotografía profesional del evento.",
    ),
    ServiceCatalogEntry(
        "VIDEO",
        "Video",
        "el video",
        ("video", "filmacion", "videografo"),
        "Video profesional del evento.",
    ),
    ServiceCatalogEntry(
        "MAKEUP", "Maquillaje", "el maquillaje", ("maquillaje", "makeup"), "Maquillaje profesional."
    ),
    ServiceCatalogEntry(
        "HAIR_STYLING", "Peinado", "el peinado", ("peinado", "peluqueria"), "Peinado profesional."
    ),
    ServiceCatalogEntry(
        "POOL", "Piscina", "la piscina", ("piscina",), "Uso de la piscina dentro del evento."
    ),
    ServiceCatalogEntry(
        "ACCOMMODATION",
        "Alojamiento",
        "el alojamiento",
        ("alojamiento", "hospedaje", "habitacion", "suite"),
        "Alojamiento asociado al evento, sujeto a confirmación.",
    ),
    ServiceCatalogEntry(
        "OTHER",
        "Otro servicio",
        None,
        (),
        "Cualquier servicio no cubierto por los códigos anteriores.",
    ),
)

_BY_CODE = {entry.code: entry for entry in SERVICE_CATALOG}
_NEGATIONS = frozenset({"no", "sin", "excepto", "menos"})


def service_catalog_codes() -> tuple[str, ...]:
    return tuple(entry.code for entry in SERVICE_CATALOG)


def service_aliases(service_code: str) -> tuple[str, ...]:
    entry = _BY_CODE.get(service_code)
    return entry.aliases if entry is not None else ()


def service_catalog_entries() -> tuple[ServiceCatalogEntry, ...]:
    return SERVICE_CATALOG


def match_requested_services(message_text: str) -> list[str] | None:
    tokens = _normalized_tokens(message_text)
    if not tokens:
        return None

    candidates: list[tuple[int, int, str]] = []
    for entry in SERVICE_CATALOG:
        for alias in entry.aliases:
            alias_tokens = tuple(alias.split())
            for start in _matching_starts(tokens, alias_tokens):
                end = start + len(alias_tokens)
                if _is_negated(tokens, start, end):
                    return None
                candidates.append((start, end, entry.code))

    occupied: set[int] = set()
    selected: list[tuple[int, str]] = []
    for start, end, code in sorted(
        candidates,
        key=lambda candidate: (-(candidate[1] - candidate[0]), candidate[0]),
    ):
        span = set(range(start, end))
        if span & occupied:
            continue
        occupied.update(span)
        selected.append((start, code))

    if not selected:
        return None
    result: list[str] = []
    for _, code in sorted(selected):
        if code not in result:
            result.append(code)
    return result


def compose_requested_services_summary(service_values: Sequence[str]) -> str:
    raise NotImplementedError


def _normalized_tokens(value: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return tuple(re.findall(r"[a-z0-9]+", without_accents))


def _matching_starts(tokens: tuple[str, ...], alias_tokens: tuple[str, ...]) -> tuple[int, ...]:
    width = len(alias_tokens)
    return tuple(
        start
        for start in range(len(tokens) - width + 1)
        if tokens[start : start + width] == alias_tokens
    )


def _is_negated(tokens: tuple[str, ...], start: int, end: int) -> bool:
    before = tokens[start - 1] if start > 0 else None
    after = tokens[end] if end < len(tokens) else None
    return before in _NEGATIONS or after in _NEGATIONS
