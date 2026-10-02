// Presentation only: keys remain the exact values used by the API.
export const labels = {
  conversationState: {
    NEW: "Nueva", BOT_ACTIVE: "Bot activo", ANSWERING_INFORMATION: "Respondiendo información",
    COLLECTING_EVENT_DATA: "Capturando datos del evento", QUOTE_REQUEST_READY: "Cotización lista para asesor",
    WAITING_FOR_APPOINTMENT_DATE: "Esperando fecha de visita",
    WAITING_FOR_APPOINTMENT_SELECTION: "Esperando selección de horario",
    APPOINTMENT_PENDING_CONFIRMATION: "Visita pendiente de confirmación",
    APPOINTMENT_CONFIRMED: "Visita confirmada", WAITING_FOR_HUMAN: "Esperando asesor",
    HUMAN_ACTIVE: "Atendida por asesor", RETURNED_TO_BOT: "Devuelta al bot",
    RESOLVED: "Resuelta", CLOSED: "Cerrada",
  },
  handoffStatus: { PENDING: "Pendiente", TAKEN: "Asignado", RETURNED: "Devuelto", RESOLVED: "Resuelto" },
  handoffReason: {
    PAYMENT_REVIEW: "Revisión de comprobante", QUOTE_PREPARATION: "Preparar cotización",
    CUSTOMER_REQUEST: "Cliente pidió asesor", LOW_CONFIDENCE: "Bot sin certeza",
    UNSUPPORTED_REQUEST: "Solicitud no soportada", CATALOG_NOT_AVAILABLE: "Catálogo no disponible",
    MANUAL_TAKEOVER: "Toma manual", TEMPLATE_UNAVAILABLE: "Sin respuesta aprobada",
    SYSTEM_ERROR: "Error del sistema", COMPLAINT: "Queja", CANCELLATION: "Cancelación",
    CAPACITY_REVIEW: "Revisión de capacidad", DISCOUNT_REQUEST: "Solicitud de descuento",
    PRICE_NEGOTIATION: "Negociación de precio", RESERVATION_CONFIRMATION: "Confirmación de reserva",
    SPECIAL_EVENT: "Evento especial", SUPPLIER_CONFIRMATION: "Confirmación de proveedor",
    REPEATED_NO_SHOW: "Inasistencias repetidas", URGENT_EVENT: "Evento urgente", OTHER: "Otro",
  },
  priority: { NORMAL: "Normal", URGENT: "Urgente", CRITICAL: "Crítica" },
  direction: { INBOUND: "Recibido", OUTBOUND: "Enviado" },
  role: { ADMIN: "Administrador", AGENT: "Asesor" },
  active: { true: "Activo", false: "Inactivo" },
  sendMode: { PROACTIVE: "Proactivo", ON_REQUEST: "A solicitud" },
  reviewStatus: { PENDING_REVIEW: "Pendiente de revisión", ACCEPTED: "Aceptado", REJECTED: "Rechazado" },
  reservationStatus: {
    PAYMENT_PENDING: "Pendiente de pago", PAYMENT_REVIEW: "En revisión de pago",
    RESERVED: "Reservada", EXPIRED: "Vencida", CANCELLED: "Cancelada",
  },
  paymentKind: { DEPOSIT: "Abono", FULL: "Pago total" },
  calendarStatus: { NONE: "Sin sincronizar", CONFIRMED: "Sincronizado" },
  staffNotificationStatus: {
    PENDING: "Pendiente", SENDING: "Enviando", SENT: "Enviado", DELIVERED: "Entregado",
    READ: "Leído", FAILED: "Fallido", DEFERRED: "En espera", EXPIRED: "Vencido",
  },
  staffMessageKind: { TEXT: "Texto", TEMPLATE: "Plantilla" },
  staffEventKind: {
    EVIDENCE_RECEIVED: "Comprobante recibido", PAYMENT_PENDING_CREATED: "Solicitud de reserva",
    TEST: "Prueba del panel",
  },
  bookingBlocker: {
    CALENDAR_EXCLUSIVE: "Evento exclusivo en calendario",
    RESERVED_EXCLUSIVE: "Reserva exclusiva confirmada", RESERVED_CONFLICT: "Reserva confirmada",
  },
  settlementResult: {
    RESERVED: "Reserva confirmada", PARTIAL: "Abono registrado",
    CONFLICT: "Franja ya reservada; reprograma o cancela",
    REJECTED: "Comprobante rechazado", NO_RESERVATION: "Comprobante aceptado",
    BALANCE_PAID: "Saldo pagado", BALANCE_PARTIAL: "Abono de saldo registrado",
  },
  bookingWindow: {
    TIMEZONE_REQUIRED: "La fecha debe incluir zona horaria.", INVALID_RANGE: "La hora final debe ser posterior al inicio.",
    CROSSES_MIDNIGHT: "La experiencia debe terminar a más tardar a medianoche.",
    OUTSIDE_HOURS: "La experiencia está fuera del horario permitido.",
    MIN_LEAD_DAYS: "La fecha no cumple la anticipación mínima.",
  },
  downloadStatus: {
    PENDING: "Pendiente", DOWNLOADED: "Descargado", FAILED_RETRYABLE: "Fallo temporal",
    FAILED_PERMANENT: "Fallo permanente",
  },
  // Source: app/conversation/catalog_event_type.py, CATALOG_EVENT_TYPE_LABELS.
  eventType: {
    WEDDING: "Boda", CIVIL_WEDDING: "Boda civil", PROPOSAL: "Pedida de mano",
    BIRTHDAY: "Cumpleaños", GRADUATION: "Graduación", ANNIVERSARY: "Aniversario",
    ROMANTIC_DINNER: "Cena romántica", CORPORATE_EVENT: "Evento corporativo", FAMILY_EVENT: "Evento familiar",
    BAPTISM: "Bautizo", FIRST_COMMUNION: "Primera comunión", BABY_SHOWER: "Baby shower",
    WORKSHOP: "Taller", POOL_DAY: "Día de piscina", PRIVATE_DINNER: "Cena privada",
    GENDER_REVEAL: "Revelación de género", OTHER: "Otro tipo de evento",
  },
  // Source: app/ai/schemas.py, Intent; conversation.last_intent is the fallback reason.
  intent: {
    GREETING: "Saludo", GENERAL_INFORMATION: "Información general", EVENT_INFORMATION: "Información del evento",
    QUOTE_REQUEST: "Solicitud de cotización", MODIFY_EVENT_DATA: "Modificar datos del evento",
    SCHEDULE_VISIT: "Agendar visita", RESCHEDULE_VISIT: "Reprogramar visita", CANCEL_VISIT: "Cancelar visita",
    PAYMENT_MESSAGE: "Mensaje sobre pago", RESERVATION_INFORMATION: "Información de reserva",
    EVENT_CANCELLATION: "Cancelación del evento", HUMAN_REQUEST: "Solicitud de asesor",
    COMPLAINT: "Queja", EMERGENCY: "Emergencia", FAREWELL: "Despedida",
    CONFIRM: "Confirmación", DENY: "Negación", UNKNOWN: "Sin clasificar",
  },
  // Source: app/channel/worker.py and app/channel/delivery.py.
  outboxStatus: {
    PENDING: "Pendiente", SENDING: "Enviando", SENT: "Enviado", FAILED: "Fallido",
    SUPPRESSED: "Suprimido", REVIEW: "En revisión", DISCARDED: "Descartado",
  },
  deliveryReason: {
    AUTOMATION_PAUSED: "Bot pausado por atención humana",
    AUTOMATION_PERIOD_REVOKED: "Mensaje de una etapa anterior del bot",
    HANDOFF_WAIT_ENDED: "La espera del asesor ya terminó",
    PRECEDING_TEXT_FAILED: "Falló el envío del texto previo",
    PRECEDING_TEXT_REVIEW: "El texto previo requiere revisión humana",
    PRECEDING_TEXT_SUPPRESSED: "El texto previo fue suprimido",
    PRECEDING_TEXT_UNPROVEN: "No se pudo validar el texto previo",
  },
  // Source: app/channel/models.py, InboxJob.
  inboxStatus: {
    PENDING: "Pendiente", PROCESSING: "Procesando", EXTERNAL: "En proceso externo",
    COMPLETED: "Completado", FAILED: "Fallido", REVIEW: "En revisión",
  },
  // The message payload uses lowercase types; normalize only for presentation.
  messageType: {
    TEXT: "Texto", DOCUMENT: "Documento", IMAGE: "Imagen", AUDIO: "Audio", VIDEO: "Video",
    STICKER: "Adhesivo", LOCATION: "Ubicación", CONTACTS: "Contactos", INTERACTIVE: "Interactivo",
    BUTTON: "Botón", REACTION: "Reacción", UNKNOWN: "Tipo desconocido", UNSUPPORTED: "Tipo no soportado",
  },
  channel: { WHATSAPP: "WhatsApp" },
  notification: { ENQUEUED: "mensaje al cliente encolado", DEFERRED: "notificación al cliente diferida", SKIPPED: "notificación al cliente omitida" },
};

for (const dictionary of Object.values(labels)) Object.freeze(dictionary);
Object.freeze(labels);

// Known values return text; unknown ones remain inspectable and cannot inject HTML.
// Callers append the result as a DOM child, never interpolate it as HTML or a string.
export function label(kind, value) {
  let original;
  try { original = value == null ? "" : String(value); } catch { original = ""; }
  const dictionary = Object.hasOwn(labels, kind) ? labels[kind] : null;
  const key = kind === "messageType" ? original.toUpperCase() : original;
  if (dictionary && Object.hasOwn(dictionary, key)) return dictionary[key];
  const code = document.createElement("code");
  code.textContent = original.trim() ? original : "Sin dato";
  return code;
}

export function formatDate(value) {
  if (!value) return "Sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  return date.toLocaleString("es-CO", {
    dateStyle: "short", timeStyle: "short", timeZone: "America/Bogota",
  });
}

export function formatCOP(value) {
  return Number.isSafeInteger(value) && value >= 0
    ? `$${new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 }).format(value)}` : "Sin monto";
}

// Interpret form inputs in the business timezone, independently of the browser timezone.
export function bogotaDateTimeToISO(date, time) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) {
    throw new Error("Selecciona una fecha y hora válidas.");
  }
  const wall = new Date(`${date}T${time}:00.000Z`);
  if (!Number.isFinite(wall.getTime()) || wall.toISOString().slice(0, 16) !== `${date}T${time}`) {
    throw new Error("Selecciona una fecha y hora válidas.");
  }
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Bogota", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  const parts = Object.fromEntries(formatter.formatToParts(wall).map(p => [p.type, p.value]));
  const represented = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour), Number(parts.minute), Number(parts.second));
  return new Date(wall.getTime() - (represented - wall.getTime())).toISOString();
}

export function bookingBlockersText(blockers = []) {
  return blockers.map(blocker => {
    const kind = labels.bookingBlocker[blocker.kind] || "Bloqueo de agenda";
    const reference = blocker.ref ? ` (referencia ${blocker.ref})` : "";
    const interval = blocker.starts_at ? ` · ${formatDate(blocker.starts_at)}${blocker.ends_at ? ` – ${formatDate(blocker.ends_at)}` : ""}` : "";
    return `Franja ocupada: ${kind}${reference}${interval}`;
  }).join("\n");
}

export function backendErrorText(detail) {
  if (typeof detail === "string" && /^(fetch failed|Failed to fetch|NetworkError|Load failed)$/i.test(detail)) {
    return "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.";
  }
  if (detail === "Internal Server Error") return "El servidor no pudo completar la operación. Inténtalo de nuevo.";
  if (Array.isArray(detail)) return detail.map(item => {
    if (typeof item?.msg === "string") {
      // FastAPI validation messages may be English; retain Spanish backend messages.
      if (item.msg.startsWith("Value error, ")) return item.msg.slice("Value error, ".length);
      return /^(Input |Field required|String should |Extra inputs )/.test(item.msg)
        ? "Revisa los datos del formulario." : item.msg;
    }
    return backendErrorText(item);
  }).join("; ");
  if (detail && typeof detail === "object") {
    const message = typeof detail.message === "string" ? detail.message : "";
    const blockers = Array.isArray(detail.blockers) ? bookingBlockersText(detail.blockers) : "";
    const reason = labels.bookingWindow[detail.window?.reason || detail.reason] || "";
    return [message, reason, blockers].filter(Boolean).join("\n") || "No se pudo completar la solicitud.";
  }
  return typeof detail === "string" && detail ? detail : "No se pudo completar la solicitud.";
}

// Translate only the structured fields/prefixes produced by app/handoff/service.py
// and app/admin/routes.py. Customer names and message bodies remain verbatim.
export function summaryContent(summary) {
  const content = document.createDocumentFragment();
  const kinds = {
    Motivo: "handoffReason", Estado: "conversationState", Prioridad: "priority",
    Evento: "eventType", "Tipo de evento": "eventType", "Última intención": "intent",
  };
  String(summary || "Sin resumen disponible.").split("\n").forEach((line, index) => {
    if (index) content.append("\n");
    const direction = line.match(/^(-\s*)([A-Z][A-Z_]+)(:\s*)(.*)$/);
    if (direction) {
      content.append(direction[1], label("direction", direction[2]), direction[3], direction[4]);
      return;
    }
    const field = line.match(/^([^:]+):\s*([A-Z][A-Z_]+)(.*)$/);
    if (field && Object.hasOwn(kinds, field[1])) {
      content.append(`${field[1]}: `, label(kinds[field[1]], field[2]), field[3]);
      return;
    }
    content.append(line.replace(/^Telefono:/, "Teléfono:")
      .replace(/^Conversacion:/, "Conversación:").replace(/^Ultimos mensajes:/, "Últimos mensajes:"));
  });
  return content;
}
