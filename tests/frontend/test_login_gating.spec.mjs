import { test, expect } from "playwright/test";

async function login(page) {
  await page.locator("#documentId").fill("90000000");
  await page.locator("#pin").fill("123456");
  const response = page.waitForResponse(r => r.url().endsWith("/api/admin/login"));
  await page.locator("#login").click();
  expect((await response).status()).toBe(200);
  await expect(page.locator("#admin")).toBeVisible();
  await expect(page.locator("#loginView")).toBeHidden();
}

for (const publicHostname of [false, true]) {
  test(`production: login, create agent, logout (${publicHostname ? "public hostname" : "localhost"})`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(error.stack));
    let origin = "http://127.0.0.1:5199";
    if (publicHostname) {
      origin = "http://admin.local.test:5199";
      await page.route(`${origin}/**`, async route => {
        const response = await route.fetch({ url: route.request().url().replace(origin, "http://127.0.0.1:5199") });
        await route.fulfill({ response });
      });
    }
    await page.goto(origin);
    await expect(page.locator("#loginView")).toBeVisible();
    await expect(page.locator(".nav")).toBeHidden();
    await login(page);
    await page.waitForTimeout(3000);
    await expect(page.locator("#admin")).toBeVisible();
    expect(await page.evaluate(() => !!sessionStorage.getItem("ceiba.sessionToken"))).toBe(true);
    await expect(page.locator('[data-view="simulator"]')).toBeHidden();
    await page.locator('[data-view="agents"]').click();
    const name = `Frontend ${publicHostname ? "public" : "local"} ${Date.now()}`;
    await page.locator("#agentCreateName").fill(name);
    await page.locator("#agentCreateRole").selectOption("AGENT");
    const created = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/api/admin/agents"));
    await page.locator('#agentCreateForm [type="submit"]').click();
    expect((await created).status()).toBe(200);
    await expect(page.locator("#agentRows")).toContainText(name);
    await page.locator("#logout").click();
    await expect(page.locator("#loginView")).toBeVisible();
    await expect(page.locator(".nav")).toBeHidden();
    expect(await page.evaluate(() => sessionStorage.getItem("ceiba.sessionToken"))).toBeNull();
    expect(errors).toEqual([]);
  });
}

test("cached unversioned JavaScript cannot override the current login UI", async ({ page }) => {
  const obsoleteRequests = [];
  await page.route("**/app.js", async route => {
    obsoleteRequests.push(route.request().url());
    await route.fulfill({ contentType: "application/javascript", body: 'throw new Error("Obsolete unversioned bundle loaded");' });
  });
  const html = await page.goto("/");
  expect(html.headers()["cache-control"]).toBe("no-store");
  const script = await page.locator('script[src*="app.js"]').getAttribute("src");
  expect(script).toMatch(/^\/app\.js\?v=[a-f0-9]+$/);
  await login(page);
  expect(obsoleteRequests).toEqual([]);
});

test("an auth rendering exception is visible and preserves the session", async ({ page }) => {
  const consoleErrors = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/");
  await login(page);
  await page.evaluate(() => {
    document.querySelector(".nav").remove();
  });
  await page.locator("#checkHealth").click();
  await expect(page.locator("#authError")).toBeVisible();
  await expect(page.locator("#authError")).toContainText("No se pudo mostrar el panel");
  expect(await page.evaluate(() => !!sessionStorage.getItem("ceiba.sessionToken"))).toBe(true);
  expect(consoleErrors.some(text => text.includes("No se pudo mostrar el panel"))).toBe(true);
});

test("simulator visibility follows health and fails closed without environment", async ({ page }) => {
  let health = { status: "ok", environment: "development" };
  await page.route("**/api/health", route => route.fulfill({ json: health }));
  await page.goto("/");
  await login(page);
  await expect(page.locator('[data-view="simulator"]')).toBeVisible();
  health = { status: "ok" };
  await page.locator("#checkHealth").click();
  await expect(page.locator('[data-view="simulator"]')).toBeHidden();
  health = { status: "ok", environment: "production" };
  await page.locator("#checkHealth").click();
  await expect(page.locator('[data-view="simulator"]')).toBeHidden();
});
