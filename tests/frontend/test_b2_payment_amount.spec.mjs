import { test, expect } from "playwright/test";

test("B2 acceptance submits the verified integer COP amount and rejection requires a note", async ({ page }) => {
  const writes = [];
  await page.addInitScript(() => sessionStorage.setItem("ceiba.sessionToken", "b2-test-session"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/admin/me") {
      return route.fulfill({ json: { id: 1, name: "Admin B2", role: "ADMIN", active: true } });
    }
    if (["/api/health", "/api/ready", "/api/live"].includes(path)) {
      return route.fulfill({ json: { status: "ok", database: "ok", environment: "production" } });
    }
    if (path === "/api/admin/payment-evidence") {
      return route.fulfill({ json: [{ id: 1, customer_name: "Cliente de prueba", customer_phone: "+573000000222",
        conversation_id: 1, mime_type: "image/jpeg", download_status: "DOWNLOADED",
        review_status: "PENDING_REVIEW", created_at: "2026-09-30T12:00:00Z" }] });
    }
    if (path.endsWith("/accept") || path.endsWith("/reject")) {
      writes.push({ path, body: route.request().postDataJSON() });
      return route.fulfill({ json: { customer_notification: "DEFERRED" } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await page.locator('[data-view="paymentEvidence"]').click();
  const card = page.locator(".paymentEvidenceCard");
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Aceptar", exact: true }).click();
  expect(writes).toEqual([]);
  await card.getByLabel("Monto verificado (COP)").fill("125000");
  await card.getByRole("button", { name: "Aceptar", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toEqual({ amount_cop: 125000 });
  await card.getByRole("button", { name: "Rechazar", exact: true }).click();
  expect(writes).toHaveLength(1);
  await card.locator("textarea").fill("Comprobante ilegible");
  await card.getByRole("button", { name: "Rechazar", exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].body).toEqual({ note: "Comprobante ilegible" });
});
