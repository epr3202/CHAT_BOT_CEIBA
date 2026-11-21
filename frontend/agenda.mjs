const bogota = "America/Bogota";
const dayFormat = new Intl.DateTimeFormat("sv-SE", { timeZone: bogota });
const clock = new Intl.DateTimeFormat("es-CO", {
  timeZone: bogota,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const monthFormat = new Intl.DateTimeFormat("es-CO", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const iso = (d) => d.toISOString().slice(0, 10);
const asDate = (day) => new Date(day + "T12:00:00Z");
const fullDay = new Intl.DateTimeFormat("es-CO", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
const capital = (value) => value.charAt(0).toUpperCase() + value.slice(1);
const kindLabel = { reservation: "Reserva", visit: "Visita", event: "Evento" };
function shiftDay(day, offset) {
  const d = asDate(day);
  d.setUTCDate(d.getUTCDate() + offset);
  return iso(d);
}
function eventTime(event) {
  if (event.all_day) return "Todo el día";
  const end = new Date(event.end);
  const endDate = dayFormat.format(end);
  const nextDate = endDate !== event.start_date ? end.toLocaleDateString("es-CO", { timeZone: bogota }) + " " : "";
  return clock.format(new Date(event.start)) + " – " + nextDate + clock.format(end);
}
function shiftMonth(day, delta) {
  const d = asDate(day.slice(0, 7) + "-01");
  d.setUTCMonth(d.getUTCMonth() + delta);
  return iso(d);
}
export function createAgenda(api) {
  const root = document.querySelector("#calendar");
  const $ = (id) => root.querySelector("#" + id);
  const picker = $("agendaDate"),
    grid = $("monthDays"),
    form = $("agendaRules");
  let version = 0,
    day = "",
    month = "",
    events = [],
    block = null,
    mutation = null;
  const list = (id, values, empty) => {
    const el = $(id);
    el.replaceChildren(...values);
    if (!values.length) el.textContent = empty;
  };
  function occurrence(event, day) {
    if (event.all_day) return event.start_date <= day && day < event.end_date;
    // Compare the local day of the last included instant, not the exclusive end.
    return (
      event.start_date <= day &&
      day <= dayFormat.format(new Date(Date.parse(event.end) - 1))
    );
  }
  function showGrid() {
    const start = asDate(month),
      days = new Date(
        Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0),
      ).getUTCDate();
    $("agendaMonth").textContent = capital(monthFormat.format(start));
    $("agendaDay").textContent = capital(fullDay.format(asDate(day)));
    const restoreFocus = grid.contains(document.activeElement);
    const today = dayFormat.format(new Date());
    const leading = (start.getUTCDay() + 6) % 7;
    const cells = document.createDocumentFragment();
    for (let i = 0; i < Math.ceil((leading + days) / 7) * 7; i++) {
      const n = i - leading + 1;
      if (n < 1 || n > days) {
        const blank = document.createElement("span");
        blank.className = "outsideDay";
        blank.setAttribute("aria-hidden", "true");
        cells.append(blank);
        continue;
      }
      const date = month.slice(0, 8) + String(n).padStart(2, "0");
      const entries = events.filter(event => occurrence(event, date));
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.day = date;
      b.tabIndex = day === date ? 0 : -1;
      b.setAttribute("aria-label", fullDay.format(asDate(date)) + ", " + entries.length + " eventos");
      b.setAttribute("aria-pressed", String(day === date));
      if (date === today) b.setAttribute("aria-current", "date");
      const num = document.createElement("span");
      num.className = "dateNumber";
      num.textContent = String(n);
      b.append(num);
      for (const event of entries.slice(0, 2)) {
        const chip = document.createElement("span");
        chip.className = "calItem " + (event.kind === "visit" ? "visit" : "event");
        chip.textContent = event.title;
        chip.title = event.title;
        b.append(chip);
      }
      if (entries.length > 2) {
        const extra = document.createElement("small");
        extra.textContent = "+" + (entries.length - 2) + " más";
        b.append(extra);
      }
      b.onclick = () => choose(date);
      cells.append(b);
    }
    grid.replaceChildren(cells);
    if (restoreFocus) grid.querySelector('[aria-pressed="true"]')?.focus({ preventScroll: true });
  }
  function showDetails(event) {
    $("agendaEventTitle").textContent = event.title;
    const lastDay = event.all_day ? shiftDay(event.end_date, -1) : dayFormat.format(new Date(Date.parse(event.end) - 1));
    const dates = fullDay.format(asDate(event.start_date)) + (lastDay === event.start_date ? "" : " – " + fullDay.format(asDate(lastDay)));
    $("agendaEventWhen").textContent = capital(dates) + " · " + eventTime(event) + " · Bogotá";
    $("agendaDescriptionHeading").textContent = event.kind === "reservation" ? "Descripción de la reserva" : "Descripción del evento";
    const notes = $("agendaDescription");
    notes.replaceChildren();
    const text = event.description?.trim() || "Sin descripción registrada.";
    if (event.kind === "reservation") {
      const seen = new Set();
      for (const line of text.split(/\r?\n/).filter(Boolean)) {
        if (seen.has(line)) continue;
        seen.add(line);
        const p = document.createElement("p");
        const at = line.indexOf(":");
        if (at > 0) {
          const label = document.createElement("strong");
          label.textContent = line.slice(0, at + 1);
          p.append(label, line.slice(at + 1));
        } else p.textContent = line;
        notes.append(p);
      }
    } else notes.textContent = text;
    $("agendaEventDialog").showModal();
  }
  function showEvents() {
    const nodes = events.filter(e => occurrence(e, day)).map(event => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "dayEvent " + (event.kind === "visit" ? "visit" : "event");
      const t = document.createElement("small"), h = document.createElement("strong"), k = document.createElement("span");
      t.textContent = eventTime(event);
      h.textContent = event.title;
      k.textContent = (kindLabel[event.kind] || "Evento") + "  ›";
      card.append(t, h);
      const description = (event.description || "").split(/\r?\n/).find(line =>
        line.trim() && !/^(fecha confirmada|horario confirmado|plan|reservation_id):/i.test(line));
      if (description) {
        const preview = document.createElement("span");
        preview.className = "dayExcerpt";
        preview.textContent = description;
        card.append(preview);
      }
      card.append(k);
      card.onclick = () => showDetails(event);
      return card;
    });
    list("agendaEvents", nodes, "Sin eventos para este día.");
  }
  grid.onkeydown = e => {
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (!delta || mutation) return;
    e.preventDefault();
    choose(shiftDay(day, delta));
  };
  async function choose(date, force = false) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || mutation) return;
    const oldMonth = month;
    day = date;
    month = date.slice(0, 7) + "-01";
    picker.value = date;
    const current = ++version;
    if (force || month !== oldMonth) {
      events = [];
      root.dataset.loaded = "";
    }
    showGrid();
    $("agendaNotice").textContent = "";
    block = null;
    form.reset();
    form.querySelector("fieldset").disabled = true;
    $("removeBlock").hidden = true;
    const valid = () => current === version && !root.hidden;
    async function load(id, url, done) {
      $(id).textContent = "Cargando…";
      try {
        const rows = await api(url);
        if (valid()) done(rows);
      } catch (error) {
        if (valid())
          $(id).textContent = "No se pudo consultar. " + error.message;
      }
    }
    const queries = [
      load(
        "agendaVisits",
        "/api/admin/appointments?appointment_date=" + date,
        (rows) => {
          const statuses = {
            PENDING_CONFIRMATION: "Por confirmar",
            CONFIRMED: "Confirmada",
            RESCHEDULED: "Reprogramada",
            CANCELLED: "Cancelada",
            LATE_CANCEL: "Cancelación tardía",
            COMPLETED: "Completada",
            NO_SHOW: "Inasistencia",
          };
          list(
            "agendaVisits",
            rows.map((r) => {
              const p = document.createElement("p");
              p.textContent =
                r.start_time.slice(0, 5) +
                " · " +
                (r.visit_reason || "Visita") +
                " · " +
                (statuses[r.appointment_status] || "Estado sin identificar") +
                " · " +
                r.attendee_count +
                " asistentes";
              return p;
            }),
            "Sin visitas registradas.",
          );
        },
      ),
      load("blockStatus", "/api/admin/blocked-dates", (rows) => {
        block = rows.find((r) => r.blocked_date === date) || null;
        $("blockStatus").textContent = block
          ? "Fecha bloqueada: " + block.reason
          : "Sin bloqueo manual.";
        $("blockReason").value = block?.reason || "";
        $("removeBlock").hidden = !block;
        form.querySelector("fieldset").disabled = false;
      }),
    ];
    if (root.dataset.loaded !== month) {
      queries.push(
        load(
          "agendaEvents",
          "/api/admin/calendar/events?start=" +
            month +
            "&end=" +
            shiftMonth(month, 1),
          (rows) => {
            events = rows;
            root.dataset.loaded = month;
            showGrid();
            showEvents();
          },
        ),
      );
    } else {
      showEvents();
    }
    await Promise.all(queries);
  }
  async function changeRule(event) {
    event.preventDefault();
    if (mutation) return;
    const action = event.submitter?.value;
    const reason = $("blockReason").value.trim();
    if (!reason && action !== "remove") {
      $("agendaNotice").textContent =
        "Escribe un motivo o el nombre del festivo.";
      return;
    }
    if (
      action === "remove" &&
      !window.confirm("¿Retirar el bloqueo del " + day + "?")
    )
      return;
    const suffix = block ? "/" + day : "";
    const endpoint =
      action === "holiday"
        ? "/api/admin/holidays"
        : "/api/admin/blocked-dates" + suffix;
    const method =
      action === "remove"
        ? "DELETE"
        : action === "holiday" || !block
          ? "POST"
          : "PATCH";
    const data =
      action === "holiday"
        ? { holiday_date: day, name: reason }
        : block
          ? { reason }
          : { blocked_date: day, reason };
    const current = version,
      date = day;
    mutation = current;
    lockControls(true);
    form.querySelector("fieldset").disabled = true;
    try {
      await api(endpoint, {
        method,
        ...(method === "DELETE" ? {} : { body: JSON.stringify(data) }),
      });
      if (current === version) {
        mutation = null;
        lockControls(false);
        const refreshed = version + 1;
        await choose(date, true);
        if (version === refreshed)
          $("agendaNotice").textContent = "Cambio guardado.";
      }
    } catch (error) {
      if (current === version) $("agendaNotice").textContent = error.message;
    } finally {
      if (mutation === current) {
        mutation = null;
        lockControls(false);
        form.querySelector("fieldset").disabled = false;
      }
    }
  }
  function lockControls(disabled) {
    picker.disabled = disabled;
    for (const button of root.querySelectorAll(
      "#monthDays button, #previousMonth, #nextMonth, #agendaToday, #agendaRefresh",
    ))
      button.disabled = disabled;
  }
  form.onsubmit = changeRule;
  picker.onchange = () => choose(picker.value);
  $("previousMonth").onclick = () => choose(shiftMonth(month, -1));
  $("nextMonth").onclick = () => choose(shiftMonth(month, 1));
  $("agendaToday").onclick = () => choose(dayFormat.format(new Date()));
  $("agendaRefresh").onclick = () => choose(day, true);
  return {
    open: () => choose(day || dayFormat.format(new Date()), true),
    reset() {
      version++;
      mutation = null;
      if ($("agendaEventDialog").open) $("agendaEventDialog").close();
      $("agendaDescription").replaceChildren();
      $("agendaEventTitle").textContent = "";
      $("agendaEventWhen").textContent = "";
      lockControls(false);
      day = "";
      month = "";
      events = [];
      block = null;
      root.dataset.loaded = "";
      form.reset();
      for (const id of [
        "agendaEvents",
        "agendaVisits",
        "blockStatus",
        "agendaNotice",
        "monthDays",
      ])
        $(id).replaceChildren();
    },
  };
}
