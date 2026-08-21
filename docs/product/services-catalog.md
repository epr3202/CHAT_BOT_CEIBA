# Catálogo canónico de servicios — CHAT_BOT_CEIBA

**Estado:** APROBADO v1.0 — Emerson, 2026-08-21. Cambio editorial aplicado en aprobación: "bebidas" a secas excluido del match determinista (decisión b).
**Ubicación propuesta:** `docs/product/services-catalog.md` (o §13.2-bis de `entities.md`, a decidir en G1).
**Fuente de códigos:** `entities.md` §13.2 (36 códigos, sin cambios). Este documento NO crea códigos nuevos; añade la capa de labels, presentación, aliases y descripciones.

Este documento es la fuente única de verdad para:

1. La tabla código→label del presentador de `service_name` y `requested_services_summary` (decisión 5 de G1 del slice de la frontera, ahora resuelta como módulo de código con test de paridad contra este doc).
2. El vocabulario de match determinista A7-bis para respuestas a preguntas directas de servicios.
3. Las descripciones del prompt de la tarea `SERVICES_CLASSIFICATION` en OpenRouter.
4. El ejemplo interpolado en la plantilla de repregunta (RESP-SERVICES-RETRY-001).
5. La suite adversarial derivada (TC-SVC).

---

## 1. Estructura por servicio

Cada código tiene cuatro campos:

* **Label:** nombre canónico en español, forma nominal. Uso: panel admin, resúmenes internos.
* **Presentación:** forma con artículo para interpolar en texto a cliente ("con interés en {…}"). Es la forma que consume el presentador.
* **Aliases:** expresiones coloquiales que el match determinista reconoce por palabra completa (case-insensitive, sin tildes). También alimentan el prompt como ejemplos.
* **Descripción:** una línea para el prompt del clasificador. No llega nunca a cliente.

---

## 2. Catálogo

### Espacio y montaje

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `VENUE` | Espacio | el espacio | espacio, lugar, sede, solo espacio, solo el espacio, alquiler | Alquiler del lugar físico para el evento, sin servicios adicionales. |
| `FURNITURE` | Mobiliario | el mobiliario | mobiliario, mesas, sillas, muebles | Mesas, sillas y mobiliario estándar del montaje. |
| `ADDITIONAL_FURNITURE` | Mobiliario adicional | el mobiliario adicional | mobiliario adicional, muebles extra, salas lounge, mobiliario especial | Mobiliario más allá del montaje estándar (lounge, mesas auxiliares, etc.). |
| `TABLEWARE` | Vajilla | la vajilla | vajilla, platos, cubiertos | Vajilla y cubertería para el servicio de mesa. |
| `GLASSWARE` | Cristalería | la cristalería | cristaleria, copas, vasos | Copas y vasos para el servicio de bebidas. |

### Alimentos y bebidas

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `FOOD` | Gastronomía | la gastronomía | gastronomia, comida, catering, menu, alimentacion, banquete | Servicio de alimentación general del evento. |
| `BRUNCH` | Brunch | el brunch | brunch, desayuno | Servicio de brunch o desayuno. |
| `DINNER` | Cena | la cena | cena, cena formal | Servicio de cena servida. |
| `SNACKS` | Pasabocas | los pasabocas | pasabocas, pasapalos, picada, bocaditos, aperitivos | Pasabocas o aperitivos para los invitados. |
| `NON_ALCOHOLIC_BEVERAGES` | Bebidas sin alcohol | las bebidas sin alcohol | jugos, gaseosas, refrescos, bebidas sin alcohol | Bebidas no alcohólicas (jugos, gaseosas, agua). NOTA: "bebidas" a secas es ambiguo (puede incluir licor) y NUNCA es alias determinista; siempre resuelve vía clasificador LLM con contexto. |
| `COCKTAILS` | Coctelería | la coctelería | cocteleria, cocteles, bar, barra de cocteles | Servicio de coctelería con bartender. |
| `ALCOHOL_SERVICE` | Servicio de licor | el servicio de licor | licor, alcohol, servicio de licor, trago | Servicio y atención de bebidas alcohólicas (el licor puede ser externo; ver RESP-BEVERAGES-002). |
| `CAKE` | Torta | la torta | torta, pastel, ponque | Torta o pastel del evento. |
| `DESSERT_TABLE` | Mesa de postres | la mesa de postres | postres, mesa de postres, mesa dulce, dulces | Mesa o estación de postres. |
| `SHOT_CART` | Carrito de shots | el carrito de shots | carrito de shots, shots | Carrito móvil de shots para la fiesta. |

### Personal

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `WAITSTAFF` | Atención de meseros | la atención de meseros | meseros, meseras, atencion, servicio de meseros | Personal de servicio a la mesa durante el evento. |
| `SECURITY` | Seguridad | el servicio de seguridad | seguridad, vigilancia | Personal de seguridad para el evento. |
| `CHILDREN_ENTERTAINMENT` | Entretenimiento infantil | el entretenimiento infantil | recreacion, recreacionistas, entretenimiento infantil, ninos, payasos, inflables | Recreación y entretenimiento para niños. |

### Decoración y ambientación

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `DECORATION` | Decoración | la decoración | decoracion, decorado, ambientacion, adornos | Decoración general del espacio. |
| `FLORAL_DESIGN` | Floristería | la floristería | floristeria, flores, arreglos florales, ramos | Diseño y arreglos florales. |
| `LIGHTING` | Iluminación especial | la iluminación especial | iluminacion, luces | Iluminación decorativa o especial más allá de la básica. |
| `GIANT_LETTERS` | Letras gigantes | las letras gigantes | letras gigantes, letras luminosas, letras | Letras decorativas de gran formato (nombres, iniciales, "LOVE"). |
| `WELCOME_MIRROR` | Espejo de bienvenida | el espejo de bienvenida | espejo, espejo de bienvenida | Espejo decorativo de bienvenida con mensaje. |

### Música y audiovisual

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `DJ` | DJ | el DJ | dj, discjockey, musica cruzada | DJ para la música del evento. |
| `LIVE_MUSIC` | Música en vivo | la música en vivo | musica en vivo, banda, grupo musical, mariachi, trio, parranda | Agrupación o artista en vivo (banda, mariachi, trío, etc.). |
| `VIOLINIST` | Violinista | el violinista | violinista, violin | Violinista para momentos especiales. |
| `SAXOPHONIST` | Saxofonista | el saxofonista | saxofonista, saxo, saxofon | Saxofonista para ambientación. |
| `SOUND` | Sonido | el sonido | sonido, equipo de sonido, parlantes, amplificacion | Equipo y refuerzo de sonido. |
| `MICROPHONE` | Micrófono | el micrófono | microfono, micrófonos | Micrófono(s) para discursos o ceremonia. |
| `SCREEN` | Pantalla | la pantalla | pantalla, pantallas, proyector, video beam | Pantalla o proyección para el evento. |

### Registro y belleza

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `PHOTOGRAPHY` | Fotografía | la fotografía | fotografia, fotografo, fotos | Fotografía profesional del evento. |
| `VIDEO` | Video | el video | video, filmacion, videografo | Video profesional del evento. |
| `MAKEUP` | Maquillaje | el maquillaje | maquillaje, makeup | Maquillaje profesional. |
| `HAIR_STYLING` | Peinado | el peinado | peinado, peluqueria | Peinado profesional. |

### Experiencia La Ceiba

| Código | Label | Presentación | Aliases | Descripción (prompt) |
| --- | --- | --- | --- | --- |
| `POOL` | Piscina | la piscina | piscina | Uso de la piscina dentro del evento. |
| `ACCOMMODATION` | Alojamiento | el alojamiento | alojamiento, hospedaje, habitacion, suite | Alojamiento asociado al evento (p. ej. Suite Oasis; sujeto a confirmación, RESP-ACCOMMODATION-003). |
| `OTHER` | Otro servicio | (no interpolable) | — | Cualquier servicio no cubierto por los códigos anteriores. |

---

## 3. Reglas del conjunto

1. **Conjunto cerrado.** El clasificador solo puede devolver códigos de esta tabla. Cualquier código fuera → `INVALID_SCHEMA`, se descarta, se persiste en `ai_execution`.
2. **`OTHER` nunca se interpola.** Si el cliente pide un servicio no catalogado, se captura como `OTHER` + `notes` con el texto del cliente, y la respuesta usa RESP-SERVICES-003 con el texto del cliente **solo si pasa por presentador estricto**; si no, escala a RESP-SUPPLIERS-005 (consulta registrada). `OTHER` jamás aparece en `requested_services_summary`.
3. **Composición de `requested_services_summary`:** determinista, desde las formas de Presentación: 1 servicio → "el espacio"; 2 → "el espacio y la decoración"; 3+ → "el espacio, la decoración y el DJ". Serialización con coma y "y" final, sin coma de Oxford.
4. **Paridad doc↔código obligatoria:** test que compara los códigos de esta tabla contra el enum/dict del módulo. Divergencia = rojo.
5. **Aliases sin tildes y case-insensitive.** La normalización quita tildes antes del match; los aliases se escriben ya normalizados.

## 4. Reglas del match determinista (extensión A7-bis)

Aplica **solo** cuando hay pregunta directa de servicios pendiente en el estado conversacional:

1. Normalizar entrada (lowercase, sin tildes, sin puntuación terminal).
2. Match por palabra completa contra aliases, **longest-match-first** (evita que "mobiliario" capture dentro de "mobiliario adicional", o "musica" dentro de "musica en vivo").
3. Cada alias resuelve a exactamente un código; múltiples servicios en una respuesta son válidos ("espacio y decoracion" → `[VENUE, DECORATION]`).
4. **Negación detectada** ("no", "sin", "excepto", "menos" adyacente a un alias) → NO resolver determinista; pasa al clasificador LLM con el contexto completo.
5. Texto sin ningún match → clasificador LLM (tarea `SERVICES_CLASSIFICATION`).
6. LLM devuelve vacío o `INVALID_SCHEMA` → repregunta con ejemplo (RESP-SERVICES-RETRY-001). Segunda repregunta fallida → registrar `OTHER`/escalar según flujo vigente, nunca bucle.

## 5. Plantilla de repregunta (propuesta para approved-responses.md)

**RESP-SERVICES-RETRY-001 — Respuesta de servicios no entendida**

> No logré identificar los servicios que te interesan. ¿Me lo confirmas de nuevo? Por ejemplo: "el espacio y la decoración" o "solo el espacio".

Variables: ninguna (el ejemplo es fijo y deriva de las formas de Presentación de esta tabla). Nota UX: acusa el no-entendimiento explícitamente, resolviendo el ítem del backlog de repregunta idéntica sin acuse.
