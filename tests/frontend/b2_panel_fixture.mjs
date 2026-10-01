export const planId = "11111111-1111-4111-8111-111111111111";
export const reservationId = "22222222-2222-4222-8222-222222222222";

export async function panel(page, options = {}) {
  const data = {
    calls: [], failures: {}, gates: {}, result: options.result || "RESERVED",
    available: true, blockers: [], calendarSynced: options.calendarSynced ?? true,
    reservation: {
      reservation_id: reservationId, plan_id: planId, plan_name: "Ritual del Corazón",
      customer_id: 1, customer_name: "Cliente del panel", conversation_id: null,
      status: options.status || "PAYMENT_REVIEW", starts_at: "2026-10-07T00:00:00Z",
      ends_at: "2026-10-07T03:00:00Z", price_cop: 250000, amount_paid_cop: 0,
      deposit_amount_cop: 125000, missing_cop: 125000, payment_kind: null,
      balance_due_at: null, calendar_status: "NONE", external_calendar_id: null,
      evidences: [
        { id: 11, status: "PENDING_REVIEW", review_status: "PENDING_REVIEW", amount_cop: null,
          created_at: "2026-09-30T12:00:00Z", download_status: "DOWNLOADED" },
        { id: 12, status: "ACCEPTED", review_status: "ACCEPTED", amount_cop: 50000,
          created_at: "2026-09-29T12:00:00Z", download_status: "DOWNLOADED" },
      ],
    },
  };
  await page.addInitScript(() => sessionStorage.setItem("ceiba.sessionToken", "b2-panel-fixture"));
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const key = `${request.method()} ${path}`;
    data.calls.push({ key, params: Object.fromEntries(url.searchParams), body: request.postDataJSON() });
    if (data.gates[key]) await data.gates[key];
    if (data.failures[key]) return route.fulfill({ status: 409, json: { detail: data.failures[key] } });
    if (path === "/api/admin/me") return route.fulfill({ json: {
      id: 1, name: "Asesor del panel", role: options.role || "ADMIN", active: true,
    } });
    if (["/api/health", "/api/live", "/api/ready"].includes(path)) {
      return route.fulfill({ json: { status: "ok", database: "ok", environment: "production" } });
    }
    if (path === "/api/admin/plans") return route.fulfill({ json: [
      { plan_id: planId, name: "Ritual del Corazón", active: true, sort_order: 1 },
      { plan_id: "33333333-3333-4333-8333-333333333333", name: "Plan retirado", active: false },
    ] });
    if (path === "/api/admin/reservations/availability") return route.fulfill({ json: {
      available: data.available, blockers: data.blockers, deposit_amount_cop: 125000,
      window: { ok: true },
    } });
    if (path === "/api/admin/reservations") {
      if (request.method() === "POST") {
        data.reservation.status = "PAYMENT_PENDING";
        return route.fulfill({ json: data.reservation });
      }
      return route.fulfill({ json: [data.reservation] });
    }
    if (path === `/api/admin/reservations/${reservationId}`) return route.fulfill({ json: data.reservation });
    if (path.endsWith("/schedule")) {
      data.reservation.starts_at = request.postDataJSON().starts_at;
      return route.fulfill({ json: { ...data.reservation, calendar_synced: data.calendarSynced } });
    }
    if (path.endsWith("/sync-calendar")) {
      data.reservation.calendar_status = "CONFIRMED";
      return route.fulfill({ json: { ...data.reservation, calendar_synced: true } });
    }
    if (path.endsWith("/cancel")) {
      data.reservation.status = "CANCELLED";
      return route.fulfill({ json: { ...data.reservation, calendar_synced: data.calendarSynced } });
    }
    if (path === "/api/admin/payment-evidence") return route.fulfill({ json: [{
      ...data.reservation.evidences[0], customer_name: "Cliente del panel", customer_phone: "+573000000222",
      reservation_id: reservationId, conversation_id: 1, mime_type: "image/jpeg",
    }] });
    if (path.endsWith("/accept") || path.endsWith("/reject")) {
      const rejecting = path.endsWith("/reject");
      const result = rejecting ? "REJECTED" : data.result;
      if (result === "RESERVED") {
        Object.assign(data.reservation, { status: "RESERVED", amount_paid_cop: 125000, missing_cop: 0,
          payment_kind: "DEPOSIT", calendar_status: data.calendarSynced ? "CONFIRMED" : "NONE" });
      } else if (result === "PARTIAL") {
        Object.assign(data.reservation, { status: "PAYMENT_PENDING", amount_paid_cop: 50000, missing_cop: 75000 });
      } else if (rejecting) data.reservation.status = "PAYMENT_PENDING";
      data.reservation.evidences[0].status = rejecting ? "REJECTED" : "ACCEPTED";
      return route.fulfill({ json: { result, reservation: data.reservation,
        missing_cop: result === "PARTIAL" ? 75000 : 0, calendar_synced: data.calendarSynced,
        customer_notification: "SKIPPED", detail: data.calendarSynced ? null : "No se pudo sincronizar el calendario." } });
    }
    if (path.endsWith("/download")) return route.fulfill({ contentType: "image/jpeg", body: "fake-image" });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  return data;
}

export async function reservations(page) {
  await page.getByRole("button", { name: "Reservas", exact: true }).click();
  return page.locator("#reservations");
}

export async function detail(page) {
  await reservations(page);
  await page.getByRole("button", { name: "Ver detalle", exact: true }).click();
  return page.locator("#reservationDetail");
}

export async function manual(page) {
  await reservations(page);
  return page.locator("#manualReservationForm");
}

export async function fillManual(form) {
  await form.getByLabel("Teléfono", { exact: true }).fill("+573000000222");
  await form.getByLabel("Nombre", { exact: true }).fill("Cliente manual");
  await form.getByLabel("Plan", { exact: true }).selectOption(planId);
  await form.getByLabel("Fecha", { exact: true }).fill("2026-10-07");
  await form.getByLabel("Hora", { exact: true }).fill("19:00");
}
