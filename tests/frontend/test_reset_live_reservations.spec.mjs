import { test, expect } from "playwright/test";
import { panel, reservationId } from "./b2_panel_fixture.mjs";

test("PR49 el reset advierte las reservas que siguen vigentes", async ({ page }) => {
  await panel(page);
  await page.route("**/api/admin/conversations/reset", route => route.fulfill({ json: {
    phone_number: "+573000008100", customer_id: 1, dry_run: true,
    conversations_found: 1, conversations_closed: 1, handoffs_resolved: 0,
    inbox_jobs_completed: 0, pending_outbox_suppressed: 0, customer_name_cleared: true,
    request_id: "pr49.reset", live_reservations: [{
      reservation_id: reservationId, status: "RESERVED", starts_at: "2026-11-07T20:00:00Z",
    }],
  } }));
  await page.locator('[data-view="tools"]').click();
  await page.locator("#resetPhone").fill("+573000008100");
  await page.locator("#previewReset").click();
  const summary = page.locator("#resetSummary");
  await expect(summary).toContainText("El reinicio no cancela estas reservas");
  await expect(summary).toContainText(reservationId);
  await expect(summary).toContainText("Reservada");
});

test("Herramientas permite verificar, cancelar y ejecutar con una sola confirmación", async ({page}) => {
  await panel(page);
  const executions = [];
  await page.route("**/api/admin/conversations/reset", route => {
    const body = route.request().postDataJSON();
    if (!body.dry_run) executions.push(body);
    return route.fulfill({json: {...body, customer_id: 1, conversations_found: 1, request_id: "reset-demo"}});
  });
  await page.getByRole("button", {name: "Herramientas", exact: true}).click();
  await expect(page.locator("#resetReason, #resetConfirmPhone")).toHaveCount(0);
  await page.getByLabel("Indicativo", {exact:true}).selectOption("MX");
  await page.locator("#resetPhone").fill("5512345678");
  await page.getByRole("button", {name: "Verificar", exact:true}).click();
  await expect(page.locator("#resetSummary")).toContainText("+525512345678");
  await page.locator("#executeReset").click();
  await page.keyboard.press("Escape");
  expect(executions).toEqual([]);
  await page.locator("#resetPhone").fill("+57 300 111 2233");
  await expect(page.locator("#executeReset")).toBeDisabled();
  await expect(page.getByLabel("Indicativo",{exact:true})).toHaveValue("CO");
  await page.locator("#previewReset").click();
  await page.locator("#executeReset").click();
  await expect(page.getByRole("dialog")).toContainText("+573001112233");
  await page.locator("#confirmDialogAccept").click();
  await expect(page.locator("#resetFeedback")).toContainText("Reinicio completado");
  expect(executions).toEqual([{phone_number:"+573001112233",dry_run:false}]);
});
