import { test, expect } from "playwright/test";
import { panel } from "./b2_panel_fixture.mjs";

for (const width of [375, 768, 1024, 1440]) {
  test(`contexto al seleccionar y columnas independientes a ${width}px`, async ({ page }) => {
    await page.setViewportSize({width, height: 820});
    await panel(page);
    await page.route("**/api/admin/conversations?*", route => route.fulfill({json: [
      {id: 31, customer_name: "Marina Lago", state: "HUMAN_ACTIVE", handoff_status: "TAKEN",
        handoff_reason: "PAYMENT_REVIEW", assigned_agent: {id: 1, name: "Asesor del panel"},
        reservation_context: {plan_name: "Cena en el jardín", status: "RESERVED",
          starts_at: "2026-11-23T01:00:00Z", ends_at: "2026-11-23T04:00:00Z", guest_count: 4},
        reservation_details: "Servicios solicitados: Violín en vivo", last_message_at: "2026-11-20T20:00:00Z"},
      {id: 32, customer_name: "Sol Río", state: "BOT_ACTIVE", bot_enabled: true,
        booking_draft: {plan_code: "PLAN_TERRAZA", time: "17:00"}},
    ]}));
    await page.locator("#refreshCases").click();
    const menu = page.locator("#navToggle"), list = page.locator("#directoryToggle");
    const directory = page.locator(".contactDirectory"), context = page.locator("#chatCaseContext");
    const reply = page.getByLabel("Tu respuesta");
    await page.getByRole("button", {name: "Abrir conversación de Marina Lago"}).click();
    await expect(context).toBeVisible();
    for (const value of ["Revisión de comprobante", "Asesor del panel", "Cena en el jardín", "Confirmada", "20:00", "23:00", "4 personas"]) {
      await expect(context.getByText(value, {exact: false}).first()).toBeVisible();
    }
    await reply.fill("¿Sigue en pie la decoración?");
    if (width > 920) {
      await list.focus(); await page.keyboard.press("Enter");
    }
    await expect(directory).toBeHidden();
    await expect(list).toHaveAttribute("aria-expanded", "false");
    await list.click();
    await expect(directory).toBeVisible();
    await expect(list).toHaveAttribute("aria-expanded", "true");
    await menu.focus(); await page.keyboard.press("Enter");
    await expect(menu).toHaveAttribute("aria-expanded", width > 920 ? "false" : "true");
    await expect(list).toHaveAttribute("aria-expanded", "true");
    await menu.click(); await list.click();
    await expect(reply).toBeVisible();
    await expect(reply).toHaveValue("¿Sigue en pie la decoración?");
    await page.locator("#chatSummary").click();
    await expect(page.locator("#summaryModal")).toContainText("Violín en vivo");
    await page.locator("#closeSummaryModal").click();
    await list.click();
    await page.getByRole("button", {name: "Abrir conversación de Sol Río"}).click();
    await expect(context).toContainText("17:00");
    await expect(context).not.toContainText("Cena en el jardín");
    await expect(reply).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
