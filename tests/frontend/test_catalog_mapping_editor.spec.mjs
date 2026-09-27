import { test, expect } from "playwright/test";

async function openCatalog(page, testInfo) {
  await page.goto("/");
  await page.locator("#documentId").fill("90000000");
  await page.locator("#pin").fill("123456");
  await page.locator("#login").click();
  await expect(page.locator("#admin")).toBeVisible();
  const token = await page.evaluate(() => sessionStorage.getItem("ceiba.sessionToken"));
  const uploaded = await page.request.post("/api/admin/catalogs/upload", {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      name: `Planes románticos · ${testInfo.title}`,
      event_type: "ROMANTIC_DINNER",
      send_mode: "ON_REQUEST",
      file: {
        name: "planes-romanticos.pdf", mimeType: "application/pdf",
        buffer: Buffer.from(`%PDF-1.4\n${testInfo.title}\n%%EOF\n`),
      },
    },
  });
  expect(uploaded.status(), await uploaded.text()).toBe(200);
  const catalog = await uploaded.json();
  await page.locator('[data-view="catalogsModule"]').click();
  const card = () => page.locator(`.catalogAsset[data-catalog-id="${catalog.catalog_asset_id}"]`).first();
  await expect(card()).toBeVisible();
  return { catalog, card };
}

test("editar modo de envío y persistir Proactivo", async ({ page }, testInfo) => {
  const { catalog, card } = await openCatalog(page, testInfo);
  await expect(card()).toContainText("Cena romántica · A solicitud");
  await card().getByRole("button", { name: "Editar asignaciones" }).click();
  const editor = card().getByRole("form");
  const eventType = editor.getByLabel("Tipo de evento", { exact: true });
  await expect(eventType.locator("option")).toHaveCount(17);
  await expect(eventType).toHaveValue("ROMANTIC_DINNER");
  await editor.getByLabel("Modo de envío", { exact: true }).selectOption("PROACTIVE");
  const editorCapture = testInfo.outputPath("catalog-mappings-editor.png");
  await card().screenshot({ path: editorCapture });
  await testInfo.attach("editor", { path: editorCapture, contentType: "image/png" });
  const saved = page.waitForResponse(response => response.request().method() === "PUT"
    && response.url().endsWith(`/api/admin/catalogs/${catalog.catalog_asset_id}/event-types`));
  await editor.getByRole("button", { name: "Guardar", exact: true }).click();
  const response = await saved;
  expect(response.request().postDataJSON()).toEqual({
    event_types: [{ event_type: "ROMANTIC_DINNER", send_mode: "PROACTIVE" }],
  });
  expect(response.status(), await response.text()).toBe(200);
  await expect(card().getByRole("form")).toHaveCount(0);
  await expect(card()).toContainText("Cena romántica · Proactivo");
  await page.reload();
  await expect(card()).toContainText("Cena romántica · Proactivo");
  const savedCapture = testInfo.outputPath("catalog-mappings-saved.png");
  await card().screenshot({ path: savedCapture });
  await testInfo.attach("guardado", { path: savedCapture, contentType: "image/png" });
});

test("añadir, cancelar y quitar todas las asignaciones conserva el catálogo", async ({ page }, testInfo) => {
  const { catalog, card } = await openCatalog(page, testInfo);
  const writes = [];
  page.on("request", request => {
    if (request.method() === "PUT") writes.push(request.postDataJSON());
  });
  await card().getByRole("button", { name: "Editar asignaciones" }).click();
  await card().getByRole("button", { name: "Añadir fila" }).click();
  await expect(card().getByLabel("Tipo de evento", { exact: true })).toHaveCount(2);
  await card().getByRole("button", { name: "Cancelar", exact: true }).click();
  expect(writes).toEqual([]);
  await card().getByRole("button", { name: "Editar asignaciones" }).click();
  await expect(card().getByLabel("Tipo de evento", { exact: true })).toHaveCount(1);
  await card().getByRole("button", { name: "Quitar fila" }).click();
  await card().getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(card()).toContainText("Sin asignaciones");
  expect(writes).toEqual([{ event_types: [] }]);
  await card().getByRole("button", { name: "Editar asignaciones" }).click();
  await card().getByRole("button", { name: "Añadir fila" }).click();
  await card().getByLabel("Tipo de evento", { exact: true }).selectOption("ROMANTIC_DINNER");
  await card().getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(card()).toContainText("Cena romántica · A solicitud");
  await expect(card().getByRole("form")).toHaveCount(0);
  expect(writes[1]).toEqual({ event_types: [{ event_type: "ROMANTIC_DINNER", send_mode: "ON_REQUEST" }] });
  const toggled = page.waitForResponse(response => response.request().method() === "PATCH"
    && response.url().endsWith(`/api/admin/catalogs/${catalog.catalog_asset_id}`));
  await card().getByRole("button", { name: "Desactivar", exact: true }).click();
  expect((await toggled).status()).toBe(200);
  await expect(card()).toContainText("Inactivo");
});

for (const [status, detail, shown] of [
  [409, "Las asignaciones cambiaron. Actualiza e inténtalo de nuevo.", "Las asignaciones cambiaron."],
  [422, { invalid_send_modes: ["modo inválido"] }, '"invalid_send_modes"'],
]) {
  test(`muestra detail ${status} y conserva la edición`, async ({ page }, testInfo) => {
    const { catalog, card } = await openCatalog(page, testInfo);
    await page.route(`**/api/admin/catalogs/${catalog.catalog_asset_id}/event-types`, route =>
      route.fulfill({ status, json: { detail } }));
    await card().getByRole("button", { name: "Editar asignaciones" }).click();
    await card().getByLabel("Modo de envío", { exact: true }).selectOption("PROACTIVE");
    await card().getByRole("button", { name: "Guardar", exact: true }).click();
    await expect(card().getByRole("alert")).toContainText(shown);
    await expect(card().getByLabel("Modo de envío", { exact: true })).toHaveValue("PROACTIVE");
    await expect(card().getByRole("button", { name: "Guardar", exact: true })).toBeEnabled();
    await expect(card()).toContainText("Cena romántica · A solicitud");
    await card().getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(card().getByRole("form")).toHaveCount(0);
  });
}

test("Pedida de mano conserva el tipo de evento en el editor y en la API", async ({ page }, testInfo) => {
  const { catalog, card } = await openCatalog(page, testInfo);
  await card().getByRole("button", { name: "Editar asignaciones" }).click();
  const eventType = card().getByLabel("Tipo de evento", { exact: true });
  await expect(eventType.locator('option[value="PROPOSAL"]')).toHaveText("Pedida de mano");
  await expect(page.locator('#catalogEventType option[value="PROPOSAL"]')).toHaveText("Pedida de mano");
  const labelText = await page.evaluate(async () => {
    const { label } = await import("/labels.mjs");
    return label("eventType", "PROPOSAL");
  });
  expect(labelText).toBe("Pedida de mano");
  await eventType.selectOption({ label: "Pedida de mano" });
  const saved = page.waitForResponse(response => response.request().method() === "PUT"
    && response.url().endsWith(`/api/admin/catalogs/${catalog.catalog_asset_id}/event-types`));
  await card().getByRole("button", { name: "Guardar", exact: true }).click();
  const response = await saved;
  expect(response.status(), await response.text()).toBe(200);
  expect(response.request().postDataJSON()).toEqual({
    event_types: [{ event_type: "PROPOSAL", send_mode: "ON_REQUEST" }],
  });
  await expect(card()).toContainText("Pedida de mano · A solicitud");
  await page.reload();
  await expect(card()).toContainText("Pedida de mano · A solicitud");
});
