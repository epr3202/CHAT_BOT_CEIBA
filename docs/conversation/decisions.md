# Decisiones de disponibilidad y hospedaje — 2026-10-29

Mandato de Emerson del 28-oct y adenda de Leandro del 29-oct. Las decisiones
generales anteriores permanecen en `docs/decisions.md`.

* La disponibilidad directa corresponde exclusivamente a planes de precio fijo
  ROMANTIC_DINNER/PROPOSAL. Es una lectura del backend, sin reservar, cobrar ni
  crear eventos en Calendar. Bodas y eventos grandes siguen fuera del alcance:
  faltan recursos y franjas de montaje, según `scope.md` §13.9 y §29.
* El modelo de recursos suite/terraza/mesa queda en backlog §29. La regla mínima
  bloquea un plan exclusivo o con pernoctación frente a una reserva RESERVED
  con pernoctación solapada (`RESERVED_OVERNIGHT`). Un plan compartido conserva
  su convivencia salvo otros bloqueos ya existentes, como exclusividad.
* REFUGIO_DOS es el plan del catálogo productivo que incluye pernoctación. La
  migración conserva duration_minutes y fija entrada/salida iniciales desde
  LODGING_CHECKIN_FROM/LODGING_CHECKOUT_TIME (15:00/11:00). Luego manda la fila
  editable del plan: volver a cargar el catálogo no sobrescribe esas horas.
* La entrada respeta checkin_from y BOOKING_LATEST_START; el final es el checkout
  del día siguiente en America/Bogota. Los demás planes mantienen su ventana
  diaria y el rechazo de cruces de medianoche. weekend_only exige sábado/domingo.
* Todas las lecturas externas de agenda, incluidas las conversiones de consulta,
  pasan por defer_agenda_service. El inbox revierte el intento local antes de
  consultar Calendar y reejecuta con el resultado. No se hace HTTP con una
  transacción de base de datos abierta.
* Los errores de agenda son valores tipados. La auditoría guarda razón y clase
  de excepción; los logs no contienen mensajes de excepción ni texto del cliente.
  SYSTEM_ERROR conserva el borrador; los demás handoffs lo eliminan.
* El renderer rechaza variables no permitidas. Las plantillas aprobadas de
  confirmación y reserva confirmada permanecen intactas: checkout se conserva
  en booking_draft y auditoría. Un texto de confirmación que muestre la salida
  requerirá otra aprobación. date/time reutilizan los presenters de booking_date/
  booking_time para las tres respuestas nuevas aprobadas v1 por Leandro.
* 0037 es la única migración: añade columnas del plan y amplía el CHECK de
  pending_action. El downgrade rechaza deliberadamente filas que usen
  CONFIRM_AVAILABILITY_BOOKING; no borra ni cambia confirmaciones pendientes.
* Aclaración de Emerson, 2026-10-29: se conserva el vencimiento del saldo antes
  de la entrada (`starts_at − 1 día`), no desde el checkout. Los recordatorios
  auditan starts_at/ends_at reales, incluido el checkout en planes con
  pernoctación, sin recalcular el final a partir de duration_minutes.
