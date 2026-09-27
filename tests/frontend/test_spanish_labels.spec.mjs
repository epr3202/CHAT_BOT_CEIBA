import { test, expect } from "playwright/test";

test.use({ timezoneId: "Pacific/Honolulu", viewport: { width: 1440, height: 1050 } });

async function login(page) {
  await page.goto("/");
  await page.locator("#documentId").fill("90000000");
  await page.locator("#pin").fill("123456");
  await page.locator("#login").click();
  await expect(page.locator("#admin")).toBeVisible();
  await expect(page.locator("#caseList")).toContainText("Ana Lucía");
}

async function expectSpanish(page) {
  const visible = (await page.locator("body").innerText()).replace(/\bRESP-[A-Z0-9-]+\b/g, "");
  const allowed = new Set(["ID", "PIN", "API", "PDF"]);
  const untranslated = [...visible.matchAll(/\b[A-Z][A-Z_]{3,}\b/g)]
    .map(match => match[0]).filter(value => !allowed.has(value));
  expect(untranslated, "Enums visibles sin traducción").toEqual([]);
}

async function capture(page, testInfo, view) {
  await expectSpanish(page);
  const path = testInfo.outputPath(`${view}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(view, { path, contentType: "image/png" });
}

test("cinco vistas en español con datos sembrados y valores API intactos", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page);
  const human = page.locator(".caseRow").filter({ hasText: "Ana Lucía" });
  await expect(human).toContainText("Atendida por asesor");
  await expect(human).toContainText("Recibido ·");
  const expectedDate = await page.evaluate(() => new Date("2026-09-24T16:10:00Z")
    .toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short", timeZone: "America/Bogota" }));
  await expect(human).toContainText(expectedDate);
  await capture(page, testInfo, "conversaciones");
  const filtered = page.waitForRequest(request => request.url().includes("/api/admin/conversations?")
    && new URL(request.url()).searchParams.get("state") === "HUMAN_ACTIVE");
  await page.locator("#conversationStateFilter").selectOption({ label: "Atendida por asesor" });
  await filtered;
  await expect(page.locator("#caseList")).not.toContainText("María del Carmen");
  await page.locator("#conversationStateFilter").selectOption("");
  const pending = page.locator(".caseRow").filter({ hasText: "María del Carmen" });
  await expect(pending).toContainText("Revisión de comprobante");
  await pending.getByRole("button", { name: "Ver resumen" }).click();
  await expect(page.locator("#summaryModalBody")).toContainText("Motivo: Revisión de comprobante");
  await expect(page.locator("#summaryModalBody")).toContainText("Recibido: Adjunto el comprobante.");
  await expectSpanish(page);
  await page.locator("#closeSummaryModal").click();

  await page.locator('[data-view="handoffs"]').click();
  await expect(page.locator("#handoffList")).toContainText("Revisión de comprobante");
  await expect(page.locator("#handoffList")).toContainText("Pendiente");
  await expect(page.locator("#handoffList")).toContainText("Urgente");
  await expect(page.locator(".chatMeta").last()).toContainText("Suprimido");
  await capture(page, testInfo, "handoffs");

  await page.locator('[data-view="agents"]').click();
  await page.locator("#agentStatusFilter").selectOption("inactive");
  const agent = page.locator("#agentRows tr").filter({ hasText: "Asesora de prueba" });
  await expect(agent).toContainText("Asesor");
  await expect(agent).toContainText("Inactivo");
  await agent.getByRole("button", { name: "Editar", exact: true }).click();
  await expect(page.locator("#agentEditRole")).toHaveValue("AGENT");
  await capture(page, testInfo, "agentes");

  await page.locator('[data-view="catalogsModule"]').click();
  const catalog = page.locator(".catalogAsset").filter({ hasText: "Planes románticos — etiquetas" });
  await expect(catalog).toContainText("Cena romántica · A solicitud");
  await catalog.getByRole("button", { name: "Editar asignaciones" }).click();
  await expect(catalog.getByLabel("Modo de envío", { exact: true })).toHaveValue("ON_REQUEST");
  await capture(page, testInfo, "catalogos");
  await catalog.getByRole("button", { name: "Cancelar", exact: true }).click();

  await page.locator('[data-view="paymentEvidence"]').click();
  await expect(page.locator("#paymentEvidenceList")).toContainText("Pendiente de revisión");
  await expect(page.locator("#paymentEvidenceList")).toContainText("Fallo temporal");
  await capture(page, testInfo, "comprobantes");

  await page.locator('[data-view="tools"]').click();
  await page.locator("#resetPhone").fill("573000000101");
  await page.locator("#previewReset").click();
  await expect(page.locator("#resetSummary")).toContainText("Previsualización");
  await expectSpanish(page);
  expect(errors).toEqual([]);
});

test("un enum desconocido se conserva como code y no rompe la vista", async ({ page }) => {
  await page.route("**/api/admin/conversations?*", async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.find(conversation => conversation.customer_name === "Ana Lucía").state = "FUTURE_STATE";
    await route.fulfill({ response, json: data });
  });
  await login(page);
  await expect(page.locator(".caseStatus code")).toHaveText("FUTURE_STATE");
  const fallback = await page.evaluate(async () => {
    const { label } = await import("/labels.mjs");
    return [label("missing", "<script>"), label("conversationState", null), label("role", "")]
      .map(node => ({ tag: node.tagName, text: node.textContent, children: node.children.length }));
  });
  expect(fallback).toEqual([
    { tag: "CODE", text: "<script>", children: 0 },
    { tag: "CODE", text: "Sin dato", children: 0 },
    { tag: "CODE", text: "Sin dato", children: 0 },
  ]);
});
