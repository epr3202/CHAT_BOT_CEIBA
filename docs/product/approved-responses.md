# Aprobación de disponibilidad y hospedaje — 2026-10-29

Textos exactos aprobados por Leandro y autorizados por Emerson en la adenda G3
del 29-oct. Se publican como APPROVED v1 en este PR. El catálogo cargado por
`data/knowledge_seed.py` está en `docs/conversation/approved-responses.md`; este
archivo conserva el registro de la autorización. Un test comprueba su igualdad.

## RESP-ACCOMMODATION-ROMANTIC-001 — Experiencia romántica con alojamiento

Estado: **APPROVED**, versión v1. Variables: `plan_name`.

> No somos hotel, pero tenemos una experiencia romántica que incluye alojamiento para la pareja: {plan_name}. Te comparto el catálogo con todos nuestros planes; cuéntame cuál te gusta y qué fecha tienes en mente, y reviso la disponibilidad. Las experiencias se reservan con mínimo un día de anticipación.

## RESP-AVAILABILITY-AVAILABLE-001 — Consulta de disponibilidad favorable

Estado: **APPROVED**, versión v1. Variables: `plan_name`, `date`, `time`.
Presenters de `date`/`time`: los de `booking_date`/`booking_time` de
RESP-BOOKING-CONFIRM-001.

> ¡Buenas noticias! {plan_name} está disponible el {date} a las {time}. Si quieres asegurarla, escríbeme "sí" y te explico cómo separar la fecha; si prefieres otra fecha u hora, dímelo.

## RESP-BOOKING-AGENDA-ERROR-001 — Consulta de agenda fallida

Estado: **APPROVED**, versión v1. Variables: `plan_name`, `date`, `time`.
Presenters de `date`/`time`: los de `booking_date`/`booking_time` de
RESP-BOOKING-CONFIRM-001.

> En este momento no pude consultar la agenda. Ya dejé registrada tu solicitud de {plan_name} para el {date} a las {time} y un asesor te confirma la disponibilidad lo antes posible dentro de nuestro horario de atención.
