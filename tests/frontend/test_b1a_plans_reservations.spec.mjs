import { test, expect } from "playwright/test";

const planId = "11111111-1111-4111-8111-111111111111";
const reservationId = "22222222-2222-4222-8222-222222222222";
const initialPlan = {
  plan_id: planId, code: "RITUAL_CORAZON", name: "Ritual del Corazón",
  event_type: "ROMANTIC_DINNER", price_cop: 250000, duration_minutes: 180,
  exclusive: false, weekend_only: false, active: true, sort_order: 1,
  created_at: "2026-09-29T12:00:00Z", updated_at: "2026-09-29T12:00:00Z",
};
const initialReservation = {
  reservation_id: reservationId, plan_id: planId, plan_name: initialPlan.name,
  customer_id: 1, customer_name: "Cliente B1a", conversation_id: 1,
  lead_id: "33333333-3333-4333-8333-333333333333",
  event_id: "44444444-4444-4444-8444-444444444444",
  status: "PAYMENT_REVIEW", starts_at: "2026-10-10T14:00:00Z", ends_at: "2026-10-10T17:00:00Z",
  price_cop: 250000, amount_paid_cop: 125000, payment_kind: "DEPOSIT",
  balance_due_at: null, hold_expires_at: null, external_calendar_id: null, calendar_status: "NONE",
  created_at: "2026-09-29T12:00:00Z", updated_at: "2026-09-29T12:00:00Z",
};

// HTTP doubles isolate the panel contract; real auth/persistence is covered in R4.
// Each test gets fresh data and does not depend on a future production seed.
async function panel(page, role = "ADMIN") {
  const data = {
    plan: { ...initialPlan }, reservation: { ...initialReservation }, writes: [], filters: [],
  };
  await page.addInitScript(() => sessionStorage.setItem("ceiba.sessionToken", "b1a-test-session"));
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/admin/me") {
      return route.fulfill({ json: { id: 1, name: "Admin B1a", role, active: true } });
    }
    if (["/api/health", "/api/ready", "/api/live"].includes(path)) {
      return route.fulfill({ json: { status: "ok", database: "ok", environment: "production" } });
    }
    return route.fulfill({ json: [] });
  });
  await page.route("**/api/admin/plans", route => route.fulfill({ json: [data.plan] }));
  await page.route(`**/api/admin/plans/${planId}`, route => {
    const body = route.request().postDataJSON();
    data.writes.push(body);
    Object.assign(data.plan, body);
    return route.fulfill({ json: data.plan });
  });
  await page.route(/\/api\/admin\/reservations(?:\?.*)?$/, route => {
    const status = new URL(route.request().url()).searchParams.get("status");
    data.filters.push(status);
    const cancelled = {
      ...initialReservation, reservation_id: "55555555-5555-4555-8555-555555555555",
      customer_name: "Cliente cancelado", status: "CANCELLED", payment_kind: "FULL",
    };
    return route.fulfill({ json: [data.reservation, cancelled]
      .filter(row => !status || row.status === status) });
  });
  await page.route(`**/api/admin/reservations/${reservationId}`, route =>
    route.fulfill({ json: data.reservation }));
  await page.route(`**/api/admin/reservations/${reservationId}/cancel`, route => {
    data.writes.push(route.request().postDataJSON());
    data.reservation.status = "CANCELLED";
    return route.fulfill({ json: data.reservation });
  });
  await page.goto("/");
  await expect(page.locator("#admin")).toBeVisible();
  return data;
}

async function openPlans(page) {
  const button = page.getByRole("button", { name: "Planes", exact: true });
  await expect(button, "B1a: falta la vista Planes").toBeVisible();
  await button.click();
  const view = page.locator("#plans");
  await expect(view).toBeVisible();
  return view;
}

async function planRow(page) {
  await openPlans(page);
  // The editable name need not be reflected in an HTML value attribute.
  const row = page.locator("#plans tbody tr").first();
  await expect(row.getByLabel("Nombre", { exact: true })).toHaveValue(initialPlan.name);
  return row;
}

async function reservationDetail(page) {
  const button = page.getByRole("button", { name: "Reservas", exact: true });
  await expect(button, "B1a: falta la vista Reservas").toBeVisible();
  await button.click();
  const view = page.locator("#reservations");
  await view.getByLabel("Estado", { exact: true }).selectOption("PAYMENT_REVIEW");
  await expect(view).not.toContainText("Cliente cancelado");
  const row = view.getByRole("row").filter({ hasText: "Cliente B1a" });
  await expect(row).toContainText("En revisión de pago");
  await row.getByRole("button", { name: "Ver detalle", exact: true }).click();
  const detail = page.locator("#reservationDetail");
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("Abono");
  return detail;
}

test("R6 Planes guarda inline y mantiene Guardando… durante la escritura", async ({ page }) => {
  const data = await panel(page);
  const row = await planRow(page);
  const price = row.getByLabel("Precio (COP)", { exact: true });
  await price.fill("275000");
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route(`**/api/admin/plans/${planId}`, async route => {
    await pending;
    data.writes.push(route.request().postDataJSON());
    Object.assign(data.plan, route.request().postDataJSON());
    await route.fulfill({ json: data.plan });
  });
  try {
    await row.getByRole("button", { name: "Guardar", exact: true }).click();
    await expect(row.getByText("Guardando…", { exact: true })).toBeVisible();
    await expect(row.getByRole("button", { name: /Guardando|Guardar/ })).toBeDisabled();
  } finally { release(); }
  await expect(row.getByRole("button", { name: "Guardar", exact: true })).toBeEnabled();
  expect(data.writes).toHaveLength(1);
  expect(data.writes[0].price_cop).toBe(275000);
  expect(Object.keys(data.writes[0]).every(key => ["name", "price_cop", "duration_minutes",
    "exclusive", "weekend_only", "active", "sort_order"].includes(key))).toBe(true);
  await page.reload();
  await expect(page.locator("#plans").getByLabel("Precio (COP)", { exact: true })).toHaveValue("275000");
});

for (const failure of ["http", "network"]) {
  test(`R6 Planes muestra error en español y permite reintentar (${failure})`, async ({ page }) => {
    await panel(page);
    const row = await planRow(page);
    await row.getByLabel("Precio (COP)", { exact: true }).fill("275000");
    await page.route(`**/api/admin/plans/${planId}`, route => failure === "http"
      ? route.fulfill({ status: 422, json: { detail: "El precio debe ser mayor que cero." } })
      : route.abort("failed"));
    await row.getByRole("button", { name: "Guardar", exact: true }).click();
    const error = page.locator("#plans").getByRole("alert");
    await expect(error).toBeVisible();
    await expect(error).toContainText(failure === "http"
      ? "El precio debe ser mayor que cero." : /conexión|conectar|red|inténtalo/i);
    await expect(error).not.toContainText(/Failed to fetch|NetworkError|Load failed/);
    await expect(row.getByRole("button", { name: "Guardar", exact: true })).toBeEnabled();
    await expect(row.getByLabel("Precio (COP)", { exact: true })).toHaveValue("275000");
  });
}

test("R6 Reservas filtra, abre detalle y cancela con motivo e indicador", async ({ page }) => {
  const data = await panel(page);
  const detail = await reservationDetail(page);
  expect(data.filters).toContain("PAYMENT_REVIEW");
  const note = detail.getByLabel("Motivo", { exact: true });
  const cancel = detail.getByRole("button", { name: "Cancelar reserva", exact: true });
  await note.fill("Cliente solicita cancelar");
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route(`**/api/admin/reservations/${reservationId}/cancel`, async route => {
    await pending;
    data.writes.push(route.request().postDataJSON());
    data.reservation.status = "CANCELLED";
    await route.fulfill({ json: data.reservation });
  });
  try {
    await cancel.click();
    await expect(detail.getByText(/Cancelando…|Guardando…/)).toBeVisible();
    await expect(detail.getByRole("button", { name: /Cancelando|Guardando|Cancelar reserva/ }))
      .toBeDisabled();
  } finally { release(); }
  await expect(detail).toContainText("Cancelada");
  expect(data.writes).toEqual([{ note: "Cliente solicita cancelar" }]);
});

for (const failure of ["http", "network"]) {
  test(`R6 Reservas muestra error en español al cancelar (${failure})`, async ({ page }) => {
    await panel(page);
    const detail = await reservationDetail(page);
    await detail.getByLabel("Motivo", { exact: true }).fill("Cliente solicita cancelar");
    await page.route(`**/api/admin/reservations/${reservationId}/cancel`, route => failure === "http"
      ? route.fulfill({ status: 409, json: { detail: "La reserva ya está cancelada." } })
      : route.abort("failed"));
    await detail.getByRole("button", { name: "Cancelar reserva", exact: true }).click();
    const error = detail.getByRole("alert");
    await expect(error).toBeVisible();
    await expect(error).toContainText(failure === "http"
      ? "La reserva ya está cancelada." : /conexión|conectar|red|inténtalo/i);
    await expect(error).not.toContainText(/Failed to fetch|NetworkError|Load failed/);
    await expect(detail.getByLabel("Motivo", { exact: true })).toHaveValue("Cliente solicita cancelar");
    await expect(detail.getByRole("button", { name: "Cancelar reserva", exact: true })).toBeEnabled();
  });
}

test("R6 labels.mjs define los cinco estados y las dos modalidades en español", async ({ page }) => {
  await page.goto("/");
  const actual = await page.evaluate(async () => {
    const { labels } = await import("/labels.mjs");
    return { reservationStatus: labels.reservationStatus, paymentKind: labels.paymentKind };
  });
  expect(actual).toEqual({
    reservationStatus: { PAYMENT_PENDING: "Pendiente de pago", PAYMENT_REVIEW: "En revisión de pago",
      RESERVED: "Reservada", EXPIRED: "Vencida", CANCELLED: "Cancelada" },
    paymentKind: { DEPOSIT: "Abono", FULL: "Pago total" },
  });
});

test("R6 las vistas nuevas no son accesibles para AGENT", async ({ page }) => {
  await panel(page, "AGENT");
  for (const view of ["Planes", "Reservas"]) {
    // This existing authorization invariant is expected green on G2.
    await expect(page.getByRole("button", { name: view, exact: true })).not.toBeVisible();
  }
});
