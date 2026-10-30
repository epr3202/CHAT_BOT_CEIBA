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
