import { test, expect as baseExpect } from "playwright/test";
import { panel, reservations, detail, manual, fillManual, planId, reservationId } from "./b2_panel_fixture.mjs";

const expect = baseExpect.configure({ timeout: 2500 });
test.use({ timezoneId: "Europe/Paris" });

test("C-1 filtros de estado y fechas, importes, calendario y etiqueta Manual", async ({ page }) => {
  const data = await panel(page);
  const view = await reservations(page);
  await expect(view.getByLabel("Desde", { exact: true })).toBeVisible();
  await view.getByLabel("Desde", { exact: true }).fill("2026-10-01");
  await view.getByLabel("Hasta", { exact: true }).fill("2026-10-31");
  await view.getByLabel("Estado", { exact: true }).selectOption("PAYMENT_REVIEW");
  await expect.poll(() => data.calls.filter(c => c.key === "GET /api/admin/reservations").at(-1)?.params)
    .toEqual({ status: "PAYMENT_REVIEW", from: "2026-10-01T05:00:00.000Z", to: "2026-11-01T04:59:59.999Z" });
  const row = view.getByRole("row").filter({ hasText: "Cliente del panel" });
  await expect(row).toContainText("125.000");
  await expect(row).toContainText("Sin sincronizar");
  await expect(row).toContainText("Manual");
});

test("C-2 crea manual después de verificar disponibilidad con hora Bogotá", async ({ page }) => {
  const data = await panel(page);
  const form = await manual(page);
  await expect(form).toBeVisible();
  await fillManual(form);
  await expect(form.getByRole("option", { name: "Plan retirado" })).toHaveCount(0);
  await form.getByRole("button", { name: "Verificar disponibilidad", exact: true }).click();
  await expect(page.locator("#manualReservationFeedback")).toContainText(/Disponible.*125\.000/);
  const availability = data.calls.find(c => c.key === "GET /api/admin/reservations/availability");
  expect(availability.params).toEqual({ plan_id: planId, starts_at: "2026-10-08T00:00:00.000Z" });
  await form.getByRole("button", { name: "Crear", exact: true }).click();
  await expect(page.locator("#manualReservationFeedback")).toContainText("Reserva creada");
  expect(data.calls.find(c => c.key === "POST /api/admin/reservations").body).toEqual({
    phone: "+573000000222", full_name: "Cliente manual", plan_id: planId, starts_at: "2026-10-08T00:00:00.000Z",
  });
});

test("C-2 disponibilidad ocupada conserva bloqueadores legibles", async ({ page }) => {
  const data = await panel(page);
  data.available = false;
  data.blockers = [{ kind: "CALENDAR_EXCLUSIVE", starts_at: "2026-10-08T00:00:00Z", ends_at: "2026-10-08T03:00:00Z" }];
  const form = await manual(page);
  await expect(form).toBeVisible();
  await fillManual(form);
  await form.getByRole("button", { name: "Verificar disponibilidad", exact: true }).click();
  await expect(page.locator("#manualReservationFeedback")).toContainText("Franja ocupada: Evento exclusivo en calendario");
});

for (const result of ["RESERVED", "PARTIAL", "CONFLICT"]) {
  test(`C-1 acepta con monto y presenta ${result}`, async ({ page }) => {
    const data = await panel(page, { result });
    const view = await detail(page);
    const evidence = view.locator(".paymentEvidenceCard").filter({ hasText: "Comprobante #11" });
    await expect(evidence).toBeVisible();
    await expect(view).toContainText("50.000");
    await evidence.getByRole("button", { name: "Aceptar", exact: true }).click();
    expect(data.calls.filter(c => c.key.endsWith("/accept"))).toHaveLength(0);
    await evidence.getByLabel("Monto verificado (COP)").fill(result === "PARTIAL" ? "50000" : "125000");
    await evidence.getByRole("button", { name: "Aceptar", exact: true }).click();
    await expect(view.locator("#reservationDetailFeedback")).toContainText({
      RESERVED: "Reserva confirmada", PARTIAL: "Abono registrado, faltan $75.000",
      CONFLICT: "Franja ya reservada; reprograma o cancela",
    }[result]);
    expect(data.calls.find(c => c.key.endsWith("/accept")).body.amount_cop).toBe(result === "PARTIAL" ? 50000 : 125000);
  });
}

test("C-1 rechaza con motivo obligatorio y descarga el comprobante", async ({ page }) => {
  const data = await panel(page);
  const view = await detail(page);
  const evidence = view.locator(".paymentEvidenceCard").filter({ hasText: "Comprobante #11" });
  await expect(evidence).toBeVisible();
  await evidence.getByRole("button", { name: "Rechazar", exact: true }).click();
  expect(data.calls.filter(c => c.key.endsWith("/reject"))).toHaveLength(0);
  await evidence.getByLabel("Nota interna").fill("Comprobante ilegible");
  const download = page.waitForEvent("download");
  await evidence.getByRole("button", { name: "Descargar", exact: true }).click();
  await download;
  await evidence.getByRole("button", { name: "Rechazar", exact: true }).click();
  await expect(view.locator("#reservationDetailFeedback")).toContainText("Comprobante rechazado");
  expect(data.calls.find(c => c.key.endsWith("/reject")).body).toEqual({ note: "Comprobante ilegible" });
});

test("C-1 pago confirmado con Calendar caído permite reintentar", async ({ page }) => {
  await panel(page, { calendarSynced: false });
  const view = await detail(page);
  const evidence = view.locator(".paymentEvidenceCard").filter({ hasText: "Comprobante #11" });
  await expect(evidence).toBeVisible();
  await evidence.getByLabel("Monto verificado (COP)").fill("125000");
  await evidence.getByRole("button", { name: "Aceptar", exact: true }).click();
  await expect(view.locator("#reservationDetailFeedback")).toContainText("Confirmada; falta sincronizar calendario");
  await view.getByRole("button", { name: "Reintentar calendario", exact: true }).click();
  await expect(view).toContainText("Calendario sincronizado");
});

test("C-1 reprograma usando Bogotá y cancela con motivo", async ({ page }) => {
  const data = await panel(page, { status: "RESERVED" });
  const view = await detail(page);
  const form = view.locator("#reservationScheduleForm");
  await expect(form).toBeVisible();
  await form.getByLabel("Nueva fecha").fill("2026-10-09");
  await form.getByLabel("Nueva hora").fill("18:00");
  await form.getByRole("button", { name: "Reprogramar", exact: true }).click();
  await expect(view.locator("#reservationDetailFeedback")).toContainText("Reserva reprogramada");
  expect(data.calls.find(c => c.key.endsWith("/schedule")).body).toEqual({ starts_at: "2026-10-09T23:00:00.000Z" });
  await view.getByLabel("Motivo", { exact: true }).fill("Cambio de planes");
  await view.getByRole("button", { name: "Cancelar reserva", exact: true }).click();
  await expect(view).toContainText("Reserva cancelada");
  expect(data.calls.find(c => c.key.endsWith("/cancel")).body).toEqual({ note: "Cambio de planes" });
});

for (const status of ["EXPIRED", "CANCELLED"]) {
  test(`C-1 ${status} oculta reprogramar y reintentar`, async ({ page }) => {
    await panel(page, { status });
    const view = await detail(page);
    await expect(view).toContainText("Sin sincronizar");
    await expect(view.getByRole("button", { name: "Reprogramar", exact: true })).not.toBeVisible();
    await expect(view.getByRole("button", { name: "Reintentar calendario", exact: true })).not.toBeVisible();
  });
}

for (const action of ["availability", "create", "accept", "reject", "schedule", "sync-calendar", "cancel"]) {
  test(`C-5 error 4xx ${action} muestra detail español y permite reintentar`, async ({ page }) => {
    const data = await panel(page, { status: action === "sync-calendar" ? "RESERVED" : "PAYMENT_REVIEW" });
    const key = action === "availability" ? "GET /api/admin/reservations/availability"
      : action === "create" ? "POST /api/admin/reservations"
      : ["accept", "reject"].includes(action) ? `POST /api/admin/payment-evidence/11/${action}`
      : `${action === "schedule" ? "PATCH" : "POST"} /api/admin/reservations/${reservationId}/${action}`;
    data.failures[key] = { message: "No se puede completar la operación.", blockers: [
      { kind: "RESERVED_CONFLICT", ref: reservationId },
    ] };
    let button, feedback;
    if (["availability", "create"].includes(action)) {
      const form = await manual(page);
      await expect(form).toBeVisible();
      await fillManual(form);
      button = form.getByRole("button", { name: action === "availability" ? "Verificar disponibilidad" : "Crear", exact: true });
      feedback = page.locator("#manualReservationFeedback");
    } else {
      const view = await detail(page);
      feedback = view.locator("#reservationDetailFeedback");
      if (["accept", "reject"].includes(action)) {
        const evidence = view.locator(".paymentEvidenceCard").filter({ hasText: "Comprobante #11" });
        await expect(evidence).toBeVisible();
        await evidence.getByLabel("Monto verificado (COP)").fill("125000");
        await evidence.getByLabel("Nota interna").fill("Revisar comprobante");
        button = evidence.getByRole("button", { name: action === "accept" ? "Aceptar" : "Rechazar", exact: true });
      } else if (action === "schedule") {
        const form = view.locator("#reservationScheduleForm");
        await expect(form).toBeVisible();
        await form.getByLabel("Nueva fecha").fill("2026-10-09");
        await form.getByLabel("Nueva hora").fill("18:00");
        button = form.getByRole("button", { name: "Reprogramar", exact: true });
      } else if (action === "cancel") {
        await view.getByLabel("Motivo", { exact: true }).fill("Cambio de planes");
        button = view.getByRole("button", { name: "Cancelar reserva", exact: true });
      } else button = view.getByRole("button", { name: "Reintentar calendario", exact: true });
    }
    await expect(button).toBeVisible();
    await button.click();
    await expect(feedback).toHaveAttribute("role", "alert");
    await expect(feedback).toContainText("No se puede completar la operación.");
    await expect(feedback).toContainText("Franja ocupada: Reserva confirmada");
    await expect(feedback).not.toContainText(/\{"|Failed to fetch/);
    await expect(button).toBeEnabled();
  });
}

for (const result of ["RESERVED", "PARTIAL", "CONFLICT"]) {
  test(`C-3 comprobantes enlaza reserva y presenta ${result}`, async ({ page }) => {
    await panel(page, { result });
    await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
    await expect(card.getByRole("button", { name: "Ver reserva", exact: true })).toBeVisible();
    await card.getByLabel("Monto verificado (COP)").fill("125000");
    await card.getByRole("button", { name: "Aceptar", exact: true }).click();
    await expect(page.locator("#paymentEvidenceFeedback")).toContainText({
      RESERVED: "Reserva confirmada", PARTIAL: "Abono registrado, faltan $75.000",
      CONFLICT: "Franja ya reservada; reprograma o cancela",
    }[result]);
    await page.getByRole("button", { name: "Ver reserva", exact: true }).first().click();
    await expect(page.locator("#reservationDetail")).toContainText("Cliente del panel");
  });
}

test("C-4 labels de calendario, bloqueadores y resultados en español", async ({ page }) => {
  await page.goto("/");
  const labels = await page.evaluate(async () => (await import("/labels.mjs")).labels);
  expect(labels.calendarStatus).toEqual({ NONE: "Sin sincronizar", CONFIRMED: "Sincronizado" });
  expect(labels.bookingBlocker).toMatchObject({ RESERVED_CONFLICT: "Reserva confirmada", RESERVED_EXCLUSIVE: "Reserva exclusiva confirmada", CALENDAR_EXCLUSIVE: "Evento exclusivo en calendario" });
  expect(labels.settlementResult).toMatchObject({ RESERVED: "Reserva confirmada", PARTIAL: "Abono registrado", CONFLICT: "Franja ya reservada; reprograma o cancela", REJECTED: "Comprobante rechazado" });
});

test("C-2 AGENT crea manual con las dos lecturas autorizadas sin acciones ADMIN", async ({ page }) => {
  const data = await panel(page, { role: "AGENT" });
  const create = page.getByRole("button", { name: "Crear reserva", exact: true });
  await expect(create).toBeVisible();
  await expect(page.getByRole("button", { name: "Reservas", exact: true })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Planes", exact: true })).not.toBeVisible();
  await create.click();
  const form = page.locator("#manualReservationForm");
  await fillManual(form);
  await form.getByRole("button", { name: "Verificar disponibilidad", exact: true }).click();
  await expect(page.locator("#manualReservationFeedback")).toContainText("Disponible");
  await form.getByRole("button", { name: "Crear", exact: true }).click();
  await expect(page.locator("#manualReservationFeedback")).toContainText("Reserva creada");
  expect(data.calls.some(c => c.key === "GET /api/admin/reservations")).toBe(false);
  for (const name of ["Reprogramar", "Reintentar calendario", "Aceptar", "Rechazar"]) {
    await expect(page.getByRole("button", { name, exact: true })).not.toBeVisible();
  }
});

for (const action of ["availability", "create", "accept", "reject", "schedule", "sync-calendar", "cancel"]) {
  test(`C-5 indicador de carga y bloqueo de doble envío ${action}`, async ({ page }) => {
    const data = await panel(page, { status: action === "sync-calendar" ? "RESERVED" : "PAYMENT_REVIEW" });
    const key = action === "availability" ? "GET /api/admin/reservations/availability"
      : action === "create" ? "POST /api/admin/reservations"
      : ["accept", "reject"].includes(action) ? `POST /api/admin/payment-evidence/11/${action}`
      : `${action === "schedule" ? "PATCH" : "POST"} /api/admin/reservations/${reservationId}/${action}`;
    let release;
    data.gates[key] = new Promise(resolve => { release = resolve; });
    let button;
    if (["availability", "create"].includes(action)) {
      const form = await manual(page);
      await expect(form).toBeVisible();
      await fillManual(form);
      button = form.getByRole("button", { name: action === "availability" ? "Verificar disponibilidad" : "Crear", exact: true });
    } else {
      const view = await detail(page);
      if (["accept", "reject"].includes(action)) {
        const evidence = view.locator(".paymentEvidenceCard").filter({ hasText: "Comprobante #11" });
        await expect(evidence).toBeVisible();
        await evidence.getByLabel("Monto verificado (COP)").fill("125000");
        await evidence.getByLabel("Nota interna").fill("Ilegible");
        button = evidence.getByRole("button", { name: action === "accept" ? "Aceptar" : "Rechazar", exact: true });
      } else if (action === "schedule") {
        const form = view.locator("#reservationScheduleForm");
        await expect(form).toBeVisible();
        await form.getByLabel("Nueva fecha").fill("2026-10-09");
        await form.getByLabel("Nueva hora").fill("18:00");
        button = form.getByRole("button", { name: "Reprogramar", exact: true });
      } else if (action === "cancel") {
        await view.getByLabel("Motivo", { exact: true }).fill("Cliente cancela");
        button = view.getByRole("button", { name: "Cancelar reserva", exact: true });
      } else button = view.getByRole("button", { name: "Reintentar calendario", exact: true });
    }
    await expect(button).toBeVisible();
    try {
      await button.click();
      await expect.poll(() => data.calls.filter(c => c.key === key).length).toBe(1);
      // Name changes during the request, so assert the visible disabled action.
      await expect(page.getByRole("button", { name: /Verificando…|Creando…|Aceptando…|Rechazando…|Reprogramando…|Sincronizando…|Cancelando…|Guardando…/ }).first()).toBeDisabled();
    } finally { release(); }
  });
}
