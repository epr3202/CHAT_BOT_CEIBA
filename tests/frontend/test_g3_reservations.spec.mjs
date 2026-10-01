import { test, expect } from "playwright/test";
import { panel, detail, reservationId } from "./b2_panel_fixture.mjs";

test("G3 cancelar avisa si el evento de calendario no se pudo eliminar", async ({ page }) => {
  await panel(page, { status: "RESERVED", calendarSynced: false });
  const view = await detail(page);
  await view.getByLabel("Motivo", { exact: true }).fill("Cancelación solicitada");
  await view.getByRole("button", { name: "Cancelar reserva", exact: true }).click();
  await expect(view.locator("#reservationDetailFeedback")).toContainText("Reserva cancelada; falta retirar el evento del calendario");
  await expect(view).toContainText("Cancelada");
});

test("G3 reprogramación confirmada pendiente de calendario permite reintentar", async ({ page }) => {
  const data = await panel(page, { status: "RESERVED", calendarSynced: false });
  const view = await detail(page);
  const form = view.locator("#reservationScheduleForm");
  await form.getByLabel("Nueva fecha").fill("2026-10-09");
  await form.getByLabel("Nueva hora").fill("18:00");
  await form.getByRole("button", { name: "Reprogramar", exact: true }).click();
  await expect(view.locator("#reservationDetailFeedback")).toContainText("Confirmada; falta sincronizar calendario");
  await view.getByRole("button", { name: "Reintentar calendario", exact: true }).click();
  await expect(view).toContainText("Calendario sincronizado");
  expect(data.calls.some(c => c.key === `POST /api/admin/reservations/${reservationId}/sync-calendar`)).toBe(true);
});
