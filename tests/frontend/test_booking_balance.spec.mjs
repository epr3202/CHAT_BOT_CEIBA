import { test, expect } from "playwright/test";
import { panel, reservationId, reservations } from "./b2_panel_fixture.mjs";

test.use({ timezoneId: "Pacific/Honolulu", viewport: { width: 1440, height: 1050 } });
test.setTimeout(20000);

test("R7 reservas muestran saldo pendiente/vencido, filtro y recordatorios en español", async ({ page }) => {
  const data = await panel(page, { status: "RESERVED" });
  const pending = { ...data.reservation, customer_name: "Ana saldo pendiente", price_cop: 400000,
    amount_paid_cop: 200000, payment_kind: "DEPOSIT", balance_due_at: "2026-10-09T00:00:00Z",
    balance_overdue_at: null, customer_notifications: [
      { kind: "BALANCE_REMINDER_EARLY", status: "SENT", sent_at: "2026-10-03T15:00:00Z",
        created_at: "2026-10-03T15:00:00Z" },
      { kind: "BALANCE_REMINDER_DUE", status: "DELIVERED", sent_at: "2026-10-05T15:00:00Z",
        created_at: "2026-10-05T15:00:00Z" },
    ] };
  const overdue = { ...pending, reservation_id: "22222222-2222-4222-8222-333333333333",
    customer_name: "Bruno saldo vencido", balance_overdue_at: "2026-10-09T00:00:00Z" };
  const paid = { ...pending, reservation_id: "22222222-2222-4222-8222-444444444444",
    customer_name: "Clara pago completo", amount_paid_cop: 400000, payment_kind: "FULL",
    balance_due_at: null, customer_notifications: [] };
  const filters = [];
  await page.route("**/api/admin/reservations?*", route => {
    const query = new URL(route.request().url()).searchParams;
    filters.push(query.get("balance_status"));
    const rows = [pending, overdue, paid].filter(row => {
      if (query.get("balance_status") === "pending") return row.amount_paid_cop < row.price_cop;
      if (query.get("balance_status") === "overdue") return Boolean(row.balance_overdue_at);
      return true;
    });
    return route.fulfill({ json: rows });
  });
  await page.route(`**/api/admin/reservations/${reservationId}`, route => route.fulfill({ json: pending }));
  const view = await reservations(page);
  const row = name => view.getByRole("row").filter({ hasText: name });
  await expect(row("Ana saldo pendiente")).toContainText("Saldo pendiente");
  await expect(row("Bruno saldo vencido")).toContainText("Saldo vencido");
  await expect(row("Clara pago completo")).not.toContainText("Saldo pendiente");
  await expect(row("Clara pago completo")).not.toContainText("Saldo vencido");
  const filter = view.getByLabel("Saldo", { exact: true });
  await expect(filter).toBeVisible();
  await filter.selectOption({ label: "Saldo pendiente" });
  await expect.poll(() => filters.at(-1)).toBe("pending");
  await expect(row("Clara pago completo")).toHaveCount(0);
  await filter.selectOption({ label: "Saldo vencido" });
  await expect.poll(() => filters.at(-1)).toBe("overdue");
  await expect(row("Ana saldo pendiente")).toHaveCount(0);
  await expect(row("Bruno saldo vencido")).toBeVisible();
  await filter.selectOption("");
  await row("Ana saldo pendiente").getByRole("button", { name: "Ver detalle", exact: true }).click();
  const details = page.locator("#reservationDetail");
  await expect(details).toContainText("Pagado");
  await expect(details).toContainText("Saldo pendiente");
  await expect(details).toContainText("200.000");
  await expect(details).toContainText("Vencimiento del saldo");
  await expect(details).toContainText("Recordatorios");
  await expect(details).toContainText("Recordatorio anticipado");
  await expect(details).toContainText("Recordatorio de vencimiento");
  await expect(details).toContainText("Enviado");
  await expect(details).toContainText("Entregado");
  const bogotaDate = await page.evaluate(() => new Date("2026-10-03T15:00:00Z")
    .toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short", timeZone: "America/Bogota" }));
  await expect(details).toContainText(bogotaDate);
  await expect(details).not.toContainText("BALANCE_REMINDER");
});

test("F1/F5 crear y editar asesor acepta teléfono local y muestra advertencia sin bloquear", async ({ page }) => {
  await panel(page);
  const warning = "Este número tiene conversaciones como cliente. Mientras esté activo como asesor, el bot no le responderá.";
  const targets = [];
  const changes = [];
  await page.route("**/api/admin/notification-recipients**", route => {
    const request = route.request();
    if (request.method() === "POST") {
      changes.push({ method: "POST", body: request.postDataJSON() });
      targets.push({ id: 1, ...request.postDataJSON(), phone_number: "+573001234567" });
      return route.fulfill({ status: 201, json: { ...targets[0], warning } });
    }
    if (request.method() === "PATCH") {
      changes.push({ method: "PATCH", body: request.postDataJSON() });
      Object.assign(targets[0], request.postDataJSON());
      return route.fulfill({ json: { ...targets[0], warning } });
    }
    return route.fulfill({ json: targets });
  });
  await page.getByRole("button", { name: "Avisos a asesores", exact: true }).click();
  const view = page.locator("#staffNotifications");
  const form = view.locator("#notificationRecipientForm");
  await expect(form.getByLabel("Teléfono", { exact: true })).toHaveAttribute("placeholder", "+57 300 123 4567");
  await form.getByLabel("Nombre", { exact: true }).fill("Operador de prueba");
  await form.getByLabel("Teléfono", { exact: true }).fill("300 123 4567");
  await form.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(view.locator("#staffNotificationFeedback")).toContainText(warning);
  expect(changes).toHaveLength(1);
  await expect(view.locator("#notificationRecipientList")).toContainText("+573001234567");
  await view.getByRole("button", { name: "Editar", exact: true }).click();
  await form.getByLabel("Nombre", { exact: true }).fill("Operador corregido");
  await form.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(view.locator("#staffNotificationFeedback")).toContainText(warning);
  await expect(view.locator("#notificationRecipientList")).toContainText("Operador corregido");
  expect(changes.map(change => change.method)).toEqual(["POST", "PATCH"]);
});
