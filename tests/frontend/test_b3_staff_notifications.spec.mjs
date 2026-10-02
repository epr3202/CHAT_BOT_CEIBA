import { test, expect } from "playwright/test";
import { panel } from "./b2_panel_fixture.mjs";

test.use({ viewport: { width: 1440, height: 1050 } });
test.setTimeout(20000);

test("B3 solo ADMIN ve Avisos a asesores", async ({ page }) => {
  await panel(page, { role: "AGENT" });
  await expect(page.getByRole("button", { name: "Avisos a asesores", exact: true })).not.toBeVisible();
  await page.reload();
  await page.route("**/api/admin/me", route => route.fulfill({ json: {
    id: 1, name: "Administrador", role: "ADMIN", active: true,
  } }));
  await page.reload();
  await expect(page.getByRole("button", { name: "Avisos a asesores", exact: true })).toBeVisible();
});

test("B3 crear, editar, enviar prueba y estados en español", async ({ page }) => {
  await panel(page);
  const targets = [];
  const calls = [];
  await page.route("**/api/admin/notification-recipients**", async route => {
    const request = route.request();
    calls.push({ method: request.method(), url: request.url(), body: request.postDataJSON() });
    if (request.method() === "POST" && request.url().endsWith("/test")) {
      return route.fulfill({ status: 201, json: { id: 1, status: "PENDING" } });
    }
    if (request.method() === "POST") targets.push({ id: 1, active: true,
      notify_on_evidence: true, notify_on_payment_pending: false, ...request.postDataJSON() });
    if (request.method() === "PATCH") Object.assign(targets[0], request.postDataJSON());
    return route.fulfill({ status: request.method() === "POST" ? 201 : 200,
      json: request.method() === "GET" ? targets : targets[0] });
  });
  await page.route("**/api/admin/staff-notifications**", route => route.fulfill({ json:
    ["PENDING", "SENDING", "SENT", "DELIVERED", "READ", "FAILED", "DEFERRED", "EXPIRED"].map(
      (status, i) => ({ id: i + 1, display_name: "Asesor", phone_number: "+57 *** 0123",
        event_kind: "EVIDENCE_RECEIVED", status, message_kind: i % 2 ? "TEXT" : "TEMPLATE" }),
    ) }));
  await expect(page.getByRole("button", { name: "Avisos a asesores", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Avisos a asesores", exact: true }).click();
  const view = page.locator("#staffNotifications");
  await expect(view).toContainText("no puede usarse como número de prueba de cliente");
  const form = view.locator("form");
  await form.getByLabel("Nombre", { exact: true }).fill("Laura");
  await form.getByLabel("Teléfono", { exact: true }).fill("+573000000123");
  await form.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(view.locator("#notificationRecipientList")).toContainText("Laura");
  await view.getByRole("button", { name: "Editar", exact: true }).click();
  await form.getByLabel("Nombre", { exact: true }).fill("Laura Gómez");
  await form.getByLabel("Solicitudes", { exact: true }).check();
  await form.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(view.locator("#notificationRecipientList")).toContainText("Laura Gómez");
  await view.getByRole("button", { name: "Enviar prueba", exact: true }).click();
  await expect(view.locator("#staffNotificationFeedback")).toContainText("Prueba encolada");
  expect(calls.some(c => c.method === "PATCH" && c.body.notify_on_payment_pending)).toBeTruthy();
  expect(calls.some(c => c.url.endsWith("/1/test"))).toBeTruthy();
  for (const label of ["Pendiente", "Enviando", "Enviado", "Entregado", "Leído", "Fallido",
    "En espera", "Vencido", "Texto", "Plantilla"]) {
    await expect(view.locator("#staffNotificationList")).toContainText(label);
  }
});

test("D3 rechazo sin reserva separa nota interna y motivo del cliente", async ({ page }) => {
  await panel(page);
  await page.route("**/api/admin/payment-evidence", route => route.fulfill({ json: [{
    id: 11, customer_name: "Cliente", customer_phone: "+573000000222", reservation_id: null,
    conversation_id: 1, mime_type: "image/jpeg", download_status: "DOWNLOADED",
    review_status: "PENDING_REVIEW", created_at: "2026-10-02T15:00:00Z",
  }] }));
  let sent;
  await page.route("**/api/admin/payment-evidence/11/reject", route => {
    sent = route.request().postDataJSON();
    return route.fulfill({ status: 409, json: { detail: "Prueba de formulario" } });
  });
  await page.locator('[data-view="paymentEvidence"]').click();
  const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
  await expect(card.getByLabel("Nota interna", { exact: true })).toBeVisible();
  await card.getByLabel("Nota interna", { exact: true }).fill("Solo para el asesor");
  await card.getByLabel("Motivo visible para el cliente", { exact: true }).fill("Imagen borrosa");
  await card.getByRole("button", { name: "Rechazar", exact: true }).click();
  await expect(page.locator("#paymentEvidenceFeedback")).toContainText("Prueba de formulario");
  expect(sent).toEqual({ note: "Solo para el asesor", customer_reason: "Imagen borrosa" });
});
