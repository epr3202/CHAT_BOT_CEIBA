const bogota = "America/Bogota";
const dayFormat = new Intl.DateTimeFormat("sv-SE", { timeZone: bogota });
const clock = new Intl.DateTimeFormat("es-CO", {
  timeZone: bogota,
  hour: "2-digit",
  minute: "2-digit",
});
const monthFormat = new Intl.DateTimeFormat("es-CO", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const iso = (d) => d.toISOString().slice(0, 10);
const asDate = (day) => new Date(day + "T12:00:00Z");
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
    $("agendaMonth").textContent = monthFormat.format(start);
    grid.replaceChildren();
    for (let n = 1; n <= days; n++) {
      const date = month.slice(0, 8) + String(n).padStart(2, "0");
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = String(n);
      if (n === 1)
        b.style.gridColumnStart = String(((start.getUTCDay() + 6) % 7) + 1);
      b.setAttribute("aria-label", date);
      b.setAttribute("aria-pressed", String(day === date));
      if (events.some((e) => occurrence(e, date))) b.classList.add("hasEvents");
      b.onclick = () => choose(date);
      grid.append(b);
    }
  }
  function showEvents() {
    const nodes = events
      .filter((e) => occurrence(e, day))
      .map((event) => {
        const card = document.createElement("article"),
          h = document.createElement("h4"),
          t = document.createElement("small"),
          p = document.createElement("p");
        h.textContent = event.title;
        t.textContent = event.all_day
          ? "Todo el día"
          : clock.format(new Date(event.start)) +
            " – " +
            clock.format(new Date(event.end));
        p.textContent =
          event.description?.trim() || "Sin descripción registrada.";
        card.append(t, h, p);
        return card;
      });
    list("agendaEvents", nodes, "Sin eventos para este día.");
  }
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
