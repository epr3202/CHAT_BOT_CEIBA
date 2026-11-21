import { test, expect } from "playwright/test";
import { panel, detail } from "./b2_panel_fixture.mjs";

for (const scope of ["list", "reservation"]) {
  test(`D pre-review ${scope}: proposal fills amount, human accepts with review_id`, async ({ page }) => {
    const data = await panel(page);
    data.reservation.evidences[0].review = {
      review_id: "44444444-4444-4444-8444-444444444444", status: "COMPLETED", suggestion: "ACCEPT",
      suggested_amount_cop: 125000, extracted: { amount_cop: 125000, bank: "Banco de prueba" },
      checks: [{ code: "AMOUNT", result: "OK", detail: "Monto suficiente" }],
    };
    if (scope === "reservation") await detail(page);
    else await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator(scope === "list" ? "#paymentEvidenceList" : "#reservationEvidences")
      .locator(".paymentEvidenceCard").first();
    await expect(card.getByText("Pre-revisión", { exact: true })).toBeVisible();
    const amount = card.getByLabel("Monto verificado (COP)", { exact: true });
    await expect(amount).toHaveValue("125000");
    await amount.fill("95000");
    if (scope === "list") await card.getByRole("button", { name: "Aceptar propuesta", exact: true }).click();
    await expect(amount).toHaveValue(scope === "list" ? "125000" : "95000");
    expect(data.calls.filter(c => c.key.endsWith("/accept"))).toHaveLength(0);
    await card.getByRole("button", { name: "Aceptar", exact: true }).click();
    await expect.poll(() => data.calls.filter(c => c.key.endsWith("/accept")).length).toBe(1);
    expect(data.calls.find(c => c.key.endsWith("/accept")).body).toEqual({
      amount_cop: scope === "list" ? 125000 : 95000, review_id: "44444444-4444-4444-8444-444444444444",
    });
  });
}

for (const [code, note] of [["ACCOUNT", "Cuenta destino no coincide"], ["REFERENCE", "Referencia ya usada"]]) {
  test(`D rejection fills ${code} note and waits for human`, async ({ page }) => {
    const data = await panel(page);
    data.reservation.evidences[0].review = { status: "COMPLETED", suggestion: "REJECT", suggested_amount_cop: 35000, extracted: { amount_cop: 35000 },
      checks: [{ code, result: "FAIL", detail: note }] };
    await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
    await expect(card.getByLabel("Nota interna")).toHaveValue(note);
    await expect(card.getByLabel("Monto verificado (COP)")).toHaveValue("35000");
    expect(data.calls.filter(c => c.key.endsWith("/reject"))).toHaveLength(0);
    await card.getByRole("button", { name: "Rechazar", exact: true }).click();
    await expect.poll(() => data.calls.filter(c => c.key.endsWith("/reject")).length).toBe(1);
    expect(data.calls.find(c => c.key.endsWith("/reject")).body).toEqual({ note });
  });
}

for (const scope of ["list", "reservation"]) {
  test(`D pre-review ${scope}: loading and Spanish error preserve the manual form`, async ({ page }) => {
    await panel(page);
    let release;
    const waiting = new Promise(resolve => { release = resolve; });
    await page.route("**/api/admin/payment-evidence/11/prereview", async route => {
      await waiting;
      await route.fulfill({ status: 409, json: { detail: "La lectura no está disponible." } });
    });
    if (scope === "reservation") await detail(page);
    else await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator(scope === "list" ? "#paymentEvidenceList" : "#reservationEvidences")
      .locator(".paymentEvidenceCard").first();
    await card.getByLabel("Monto verificado (COP)").fill("50000");
    await card.getByLabel("Nota interna").fill("Verificación manual");
    await card.getByRole("button", { name: "Solicitar pre-revisión", exact: true }).click();
    await expect(card.getByRole("button", { name: "Leyendo comprobante…", exact: true })).toBeDisabled();
    await expect(card.getByLabel("Monto verificado (COP)")).toBeDisabled();
    release();
    const feedback = page.locator(scope === "list" ? "#paymentEvidenceFeedback" : "#reservationDetailFeedback");
    await expect(feedback).toContainText("No se pudo completar la pre-revisión: La lectura no está disponible.");
    await expect(card.getByLabel("Monto verificado (COP)")).toHaveValue("50000");
    await expect(card.getByLabel("Nota interna")).toHaveValue("Verificación manual");
    await expect(card.getByRole("button", { name: "Solicitar pre-revisión", exact: true })).toBeEnabled();
  });
}

for (const scope of ["list", "reservation"]) {
  test(`la pre-revisión solicitada carga el monto sin confirmar el pago en ${scope}`, async ({ page }) => {
    const data = await panel(page);
    const review = { review_id: "44444444-4444-4444-8444-444444444449", status: "COMPLETED",
      suggestion: "REVIEW", suggested_amount_cop: 37500, extracted: { amount_cop: 37500 }, checks: [] };
    await page.route("**/api/admin/payment-evidence/11/prereview", route => {
      data.reservation.evidences[0].review = review;
      return route.fulfill({ json: { id: 11, review } });
    });
    if (scope === "reservation") await detail(page);
    else await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator(scope === "list" ? "#paymentEvidenceList" : "#reservationEvidences")
      .locator(".paymentEvidenceCard").first();
    const amount = card.getByLabel("Monto verificado (COP)", { exact: true });
    await expect(amount).toHaveValue("");
    await card.getByRole("button", { name: "Solicitar pre-revisión", exact: true }).click();
    await expect(amount).toHaveValue("37500");
    expect(data.calls.filter(c => c.key.endsWith("/accept"))).toHaveLength(0);
    await card.getByRole("button", { name: "Aceptar", exact: true }).click();
    await expect.poll(() => data.calls.find(c => c.key.endsWith("/accept"))?.body).toEqual({
      amount_cop: 37500, review_id: review.review_id });
  });
}

test("una lectura en otra moneda deja el monto COP para verificación manual", async ({ page }) => {
  const data = await panel(page);
  data.reservation.evidences[0].review = { status: "COMPLETED", suggestion: "REVIEW",
    suggested_amount_cop: 300, extracted: { amount_cop: 300, currency: "USD" },
    checks: [{ code: "CURRENCY", result: "FAIL", detail: "Moneda distinta de COP." }] };
  await page.locator('[data-view="paymentEvidence"]').click();
  const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
  await expect(card.getByLabel("Monto verificado (COP)")).toHaveValue("");
  await expect(card).toContainText("Moneda distinta de COP");
  await card.getByRole("button", { name: "Aceptar", exact: true }).click();
  expect(data.calls.filter(c => c.key.endsWith("/accept"))).toHaveLength(0);
});
