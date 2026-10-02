import { test, expect } from "playwright/test";
import { panel, detail } from "./b2_panel_fixture.mjs";

for (const scope of ["list", "reservation"]) {
  test(`F2 failed download ${scope}: acceptance disabled, human rejection audited by API`, async ({ page }) => {
    const data = await panel(page);
    data.reservation.evidences[0].download_status = "FAILED_PERMANENT";
    if (scope === "reservation") await detail(page);
    else await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator(scope === "list" ? "#paymentEvidenceList" : "#reservationEvidences")
      .locator(".paymentEvidenceCard").first();
    await expect(card.getByRole("button", { name: "Aceptar", exact: true })).toBeDisabled();
    await expect(card).toContainText("No se pudo descargar el comprobante");
    await expect(card.getByLabel("Nota de revisión")).toHaveValue(
      "No se pudo descargar el comprobante. Envía una nueva imagen.");
    expect(data.calls.filter(c => c.key.endsWith("/reject"))).toHaveLength(0);
    await card.getByRole("button", { name: "Rechazar", exact: true }).click();
    await expect.poll(() => data.calls.filter(c => c.key.endsWith("/reject")).length).toBe(1);
    expect(data.calls.find(c => c.key.endsWith("/reject")).body).toEqual({
      note: "No se pudo descargar el comprobante. Envía una nueva imagen.",
    });
    expect(data.calls.filter(c => c.key.endsWith("/accept"))).toHaveLength(0);
  });
}

test("F2 failed rejection keeps acceptance disabled and preserves the note", async ({ page }) => {
  const data = await panel(page);
  data.reservation.evidences[0].download_status = "FAILED_PERMANENT";
  data.failures["POST /api/admin/payment-evidence/11/reject"] = "No se pudo guardar la revisión.";
  await page.locator('[data-view="paymentEvidence"]').click();
  const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
  await card.getByRole("button", { name: "Rechazar", exact: true }).click();
  await expect(page.locator("#paymentEvidenceFeedback")).toContainText("No se pudo guardar la revisión.");
  await expect(card.getByRole("button", { name: "Aceptar", exact: true })).toBeDisabled();
  await expect(card.getByRole("button", { name: "Rechazar", exact: true })).toBeEnabled();
  await expect(card.getByLabel("Nota de revisión")).toHaveValue(
    "No se pudo descargar el comprobante. Envía una nueva imagen.");
});

for (const [reason, description] of [
  ["AUTOMATION_PAUSED", "Bot pausado por atención humana"],
  ["PRECEDING_TEXT_FAILED", "Falló el envío del texto previo"],
]) {
test(`F2 suppressed outbox ${reason} is visible in Spanish`, async ({ page }) => {
  await panel(page);
  await page.route("**/api/admin/handoffs?*", route => route.fulfill({ json: [{
    id: 1, conversation_id: 1, status: "PENDING", priority: "NORMAL",
    reason: "PAYMENT_REVIEW", customer_name: "Cliente del panel", summary: "Comprobante",
  }] }));
  await page.route("**/api/admin/conversations/1/messages", route => route.fulfill({ json: [{
    id: "outbox-1", direction: "OUTBOUND", message_type: "text", body: "Respuesta aprobada",
    status: "SUPPRESSED", delivery_reason: reason, created_at: "2026-10-01T15:00:00Z",
  }] }));
  await page.locator('[data-view="handoffs"]').click();
  await expect(page.locator(".chatMeta").last()).toContainText("Suprimido");
  await expect(page.locator(".chatMeta").last()).toContainText(`Motivo: ${description}`);
});
}
