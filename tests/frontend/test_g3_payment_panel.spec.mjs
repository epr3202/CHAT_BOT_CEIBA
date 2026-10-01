import { test, expect } from "playwright/test";
import { panel } from "./b2_panel_fixture.mjs";

for (const decision of ["accept", "reject"]) {
  test(`G3 comprobantes conserva datos y detail español al fallar ${decision}`, async ({ page }) => {
    const data = await panel(page);
    data.failures[`POST /api/admin/payment-evidence/11/${decision}`] = "El comprobante ya fue revisado.";
    await page.locator('[data-view="paymentEvidence"]').click();
    const card = page.locator("#paymentEvidenceList .paymentEvidenceCard");
    await card.getByLabel("Monto verificado (COP)").fill("125000");
    await card.getByLabel("Nota de revisión").fill("Validación humana");
    await card.getByRole("button", { name: decision === "accept" ? "Aceptar" : "Rechazar", exact: true }).click();
    await expect(page.locator("#paymentEvidenceFeedback")).toHaveAttribute("role", "alert");
    await expect(page.locator("#paymentEvidenceFeedback")).toContainText("El comprobante ya fue revisado.");
    await expect(card.getByLabel("Monto verificado (COP)")).toHaveValue("125000");
    await expect(card.getByLabel("Nota de revisión")).toHaveValue("Validación humana");
  });
}

