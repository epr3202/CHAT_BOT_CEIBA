import {test, expect} from "playwright/test";
import {panel, reservationId} from "./b2_panel_fixture.mjs";

for (const width of [375, 768, 1024, 1440]) {
  test(`Registrar efectivo, revisar saldo y reintentar a ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    const data = await panel(page, {status:"RESERVED"});
    Object.assign(data.reservation, {amount_paid_cop: 125000, missing_cop: 0, payment_kind: "DEPOSIT"});
    const calls = [];
    await page.route(`**/api/admin/reservations/${reservationId}/payments`, route => {
      const body = route.request().postDataJSON();
      calls.push(body);
      if (calls.length === 1) return route.abort("failed");
      Object.assign(data.reservation, {amount_paid_cop: 150000, manual_payments: [{
        payment_id: body.payment_id, method:body.method, amount_cop:body.amount_cop,
        recorded_by:"Valeria", created_at:"2026-11-21T14:00:00Z",
      }]});
      return route.fulfill({json:{reservation:data.reservation, result:"BALANCE_PARTIAL"}});
    });
    const nav = page.locator('[data-view="reservations"]');
    if (!(await nav.isVisible())) await page.locator("#navToggle").click();
    await nav.click();
    await expect(page.getByRole("button",{name:"Nueva reserva"})).toBeVisible();
    await expect(page.locator("#manualReservationForm")).toBeHidden();
    await expect(page.locator("#reservationRows")).toContainText("$125.000");
    await page.getByRole("button",{name:"Ver detalle",exact:true}).click();
    await page.getByRole("button",{name:"Registrar abono",exact:true}).click();
    const dialog = page.getByRole("dialog",{name:"Registrar abono"});
    await dialog.getByLabel("Monto recibido (COP)").fill("25000");
    await expect(dialog).toContainText("$100.000");
    await dialog.getByRole("button",{name:"Confirmar abono"}).click();
    await expect(dialog.getByRole("status")).toContainText("conectar");
    await dialog.getByRole("button",{name:"Confirmar abono"}).click();
    await expect(dialog).toBeHidden();
    expect(calls[1]).toEqual(calls[0]);
    expect(calls[0]).toMatchObject({method:"CASH",amount_cop:25000,expected_paid_cop:125000});
    await expect(page.locator("#reservationMoney")).toContainText("$100.000");
    await expect(page.locator("#manualPaymentHistory")).toContainText("Efectivo");
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button",{name:"Volver a reservas"}).click();
    await expect(page.locator("#reservationRows")).toContainText("$100.000");
  });
}
