import { test, expect } from "playwright/test";

const RESET_ENDPOINT = "/api/admin/conversations/reset";

const EXPECTED_COUNTRIES = [
  ["CO", "Colombia (+57)"],
  ["MX", "México (+52)"],
  ["US", "Estados Unidos (+1)"],
  ["CA", "Canadá (+1)"],
  ["RU", "Rusia (+7)"],
  ["KZ", "Kazajistán (+7)"],
  ["ES", "España (+34)"],
  ["VE", "Venezuela (+58)"],
  ["EC", "Ecuador (+593)"],
  ["PA", "Panamá (+507)"],
  ["BR", "Brasil (+55)"],
  ["GB", "Reino Unido (+44)"],
];

/**
 * Inicia sesión con el ADMIN sembrado por seed_admin.py y abre la vista Herramientas.
 * @param {import("playwright/test").Page} page página del navegador de la prueba.
 * @returns {Promise<void>} se resuelve cuando la vista Herramientas está visible.
 */
async function openTools(page) {
  await page.goto("/");
  await page.locator("#documentId").fill("90000000");
  await page.locator("#pin").fill("123456");
  await page.locator("#login").click();
  await expect(page.locator("#admin")).toBeVisible();
  await page.locator('[data-view="tools"]').click();
  await expect(page.locator("#tools")).toBeVisible();
}

/**
 * Localiza el selector de indicativo del formulario de verificación por su label visible.
 * @param {import("playwright/test").Page} page página del navegador de la prueba.
 * @returns {import("playwright/test").Locator} el control etiquetado "Indicativo".
 */
function countrySelect(page) {
  return page.locator("#resetPreviewForm").getByLabel("Indicativo", { exact: true });
}

/**
 * Localiza el campo de teléfono del formulario de verificación por su label visible.
 * @param {import("playwright/test").Page} page página del navegador de la prueba.
 * @returns {import("playwright/test").Locator} el control etiquetado "Teléfono".
 */
function phoneInput(page) {
  return page.locator("#resetPreviewForm").getByLabel("Teléfono", { exact: true });
}

/**
 * Escribe un número nacional, pulsa Verificar y captura la petición y la respuesta reales del backend.
 * @param {import("playwright/test").Page} page página del navegador de la prueba.
 * @param {string} nationalNumber número sin indicativo, tal como lo escribiría el usuario.
 * @returns {Promise<{body: object, summary: object}>} cuerpo JSON enviado y resumen JSON devuelto por el backend.
 */
async function previewReset(page, nationalNumber) {
  await phoneInput(page).fill(nationalNumber);
  const [request, response] = await Promise.all([
    page.waitForRequest(r => r.method() === "POST" && r.url().endsWith(RESET_ENDPOINT)),
    page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(RESET_ENDPOINT)),
    page.locator("#previewReset").click(),
  ]);
  expect(response.status()).toBe(200);
  return { body: request.postDataJSON(), summary: await response.json() };
}

/**
 * Calcula la relación de contraste WCAG entre el color del texto de un elemento y su primer fondo opaco.
 * @param {import("playwright/test").Locator} locator elemento a medir.
 * @returns {Promise<number>} relación de contraste, por ejemplo 4.5.
 */
async function contrastRatio(locator) {
  return locator.evaluate(element => {
    const channels = color => color.match(/[\d.]+/g).slice(0, 3).map(Number).map(value => {
      const v = value / 255;
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    const luminance = color => {
      const [r, g, b] = channels(color);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    let background = element;
    while (background && getComputedStyle(background).backgroundColor.match(/[\d.]+/g)?.[3] === "0") {
      background = background.parentElement;
    }
    const fg = luminance(getComputedStyle(element).color);
    const bg = luminance(getComputedStyle(background || document.body).backgroundColor);
    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
  });
}

test.describe("Reiniciar conversación: indicativo de país", () => {
  test("un navegador sin preferencia guardada muestra Colombia (+57) seleccionado", async ({ page }) => {
    await openTools(page);
    await expect(countrySelect(page)).toHaveValue("CO");
    await expect(countrySelect(page).locator("option:checked")).toHaveText("Colombia (+57)");
  });

  test("el selector lista todos los países con nombre en español e indicativo, ordenados y sin duplicados", async ({ page }) => {
    await openTools(page);
    const options = await countrySelect(page).locator("option").evaluateAll(nodes =>
      nodes.map(node => ({ value: node.value, text: node.textContent.trim() })));
    expect(options.length).toBeGreaterThanOrEqual(200);
    for (const option of options) {
      expect(option.value).toMatch(/^[A-Z]{2}$/);
      expect(option.text).toMatch(/^\S.* \(\+\d{1,4}\)$/);
    }
    expect(new Set(options.map(option => option.value)).size).toBe(options.length);
    const names = options.map(option => option.text);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, "es")));
    for (const [value, text] of EXPECTED_COUNTRIES) {
      expect(options).toContainEqual({ value, text });
    }
  });

  test("el campo de teléfono no pide escribir el indicativo", async ({ page }) => {
    await openTools(page);
    await expect(phoneInput(page)).toHaveAttribute("type", "tel");
    await expect(phoneInput(page)).not.toHaveAttribute("placeholder", /\+/);
  });

  test("la verificación envía al backend el número con el indicativo por defecto", async ({ page }) => {
    await openTools(page);
    const { body, summary } = await previewReset(page, "300 111 2233");
    expect(body).toEqual({ phone_number: "+573001112233", dry_run: true });
    expect(summary.phone_number).toBe("+573001112233");
    await expect(page.locator("#resetSummary")).toContainText("+573001112233");
  });

  test("la verificación usa el indicativo que elige el usuario", async ({ page }) => {
    await openTools(page);
    await countrySelect(page).selectOption("MX");
    const { body, summary } = await previewReset(page, "55 1234 5678");
    expect(body.phone_number).toBe("+525512345678");
    expect(summary.phone_number).toBe("+525512345678");
  });

  test("el navegador recuerda el indicativo elegido y no lo impone a otro navegador", async ({ page, browser }) => {
    await openTools(page);
    await countrySelect(page).selectOption("MX");
    await page.reload();
    await expect(page.locator('[data-view="tools"]')).toBeVisible();
    await page.locator('[data-view="tools"]').click();
    await expect(countrySelect(page)).toHaveValue("MX");

    const otherContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
    const otherPage = await otherContext.newPage();
    await openTools(otherPage);
    await expect(countrySelect(otherPage)).toHaveValue("CO");
    await otherContext.close();
  });

  test("pegar un número con indicativo actualiza el selector, deja el número nacional y guarda la preferencia", async ({ page }) => {
    await openTools(page);
    await phoneInput(page).fill("+52 55 1234 5678");
    await expect(countrySelect(page)).toHaveValue("MX");
    await expect(phoneInput(page)).toHaveValue("55 1234 5678");

    const [request] = await Promise.all([
      page.waitForRequest(r => r.method() === "POST" && r.url().endsWith(RESET_ENDPOINT)),
      page.locator("#previewReset").click(),
    ]);
    expect(request.postDataJSON().phone_number).toBe("+525512345678");

    await page.reload();
    await expect(page.locator('[data-view="tools"]')).toBeVisible();
    await page.locator('[data-view="tools"]').click();
    await expect(countrySelect(page)).toHaveValue("MX");
  });

  test("escribir el indicativo tecla por tecla también actualiza el selector", async ({ page }) => {
    await openTools(page);
    await phoneInput(page).pressSequentially("+593 99 123 4567");
    await expect(countrySelect(page)).toHaveValue("EC");
    await expect(phoneInput(page)).toHaveValue("99 123 4567");
  });

  test("un indicativo compartido selecciona su país principal", async ({ page }) => {
    await openTools(page);
    await phoneInput(page).fill("+1 305 555 0123");
    await expect(countrySelect(page)).toHaveValue("US");
    await expect(phoneInput(page)).toHaveValue("305 555 0123");
  });

  test("con el selector cerrado se ve solo el indicativo, sin el nombre del país", async ({ page }) => {
    await openTools(page);
    await expect(countrySelect(page).locator("selectedcontent")).toHaveText("+57", { useInnerText: true });
    await phoneInput(page).fill("+52 55 1234 5678");
    await expect(countrySelect(page).locator("selectedcontent")).toHaveText("+52", { useInnerText: true });
  });

  test("el botón de verificación se llama Verificar", async ({ page }) => {
    await openTools(page);
    await expect(page.locator("#previewReset")).toHaveText("Verificar");
  });

  test("Reiniciar pide confirmación en un modal; cancelar o Escape no ejecutan y confirmar envía el teléfono completo", async ({ page }) => {
    await openTools(page);
    await previewReset(page, "3001112233");
    await page.locator("#resetReason").fill("Prueba de reinicio desde el panel");
    await expect(page.locator("#resetConfirmPhone")).toHaveCount(0);

    const executions = [];
    page.on("request", r => {
      if (r.method() === "POST" && r.url().endsWith(RESET_ENDPOINT) && r.postDataJSON().dry_run === false) executions.push(r);
    });
    const dialog = page.getByRole("dialog", { name: "¿Está seguro que desea realizar esta operación?" });
    const cancel = dialog.getByRole("button", { name: "No, cancelar operación" });
    const accept = dialog.getByRole("button", { name: "Sí, quiero reiniciar la conversación" });

    await page.locator("#executeReset").click();
    await expect(dialog).toBeVisible();
    await expect(cancel).toBeFocused();
    await cancel.click();
    await expect(dialog).toBeHidden();

    await page.locator("#executeReset").click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(executions).toHaveLength(0);

    await page.locator("#executeReset").click();
    const [request, response] = await Promise.all([
      page.waitForRequest(r => r.method() === "POST" && r.url().endsWith(RESET_ENDPOINT)),
      page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(RESET_ENDPOINT)),
      accept.click(),
    ]);
    expect(response.status()).toBe(200);
    expect(request.postDataJSON()).toMatchObject({
      phone_number: "+573001112233", dry_run: false, reason: "Prueba de reinicio desde el panel",
    });
    await expect(page.locator("#resetFeedback")).toContainText("Reinicio completado");
  });

  test("el sidebar ocupa todo el alto aunque una extensión inyecte elementos en la página", async ({ page }) => {
    await openTools(page);
    await page.locator("#resetReason").click();
    await page.evaluate(() => document.body.append(document.createElement("div")));
    const [viewport, sidebar] = await page.evaluate(() =>
      [innerHeight, document.querySelector(".sidebar").getBoundingClientRect().height]);
    expect(sidebar).toBeGreaterThanOrEqual(viewport);
  });

  for (const width of [360, 1280]) {
    test(`ui-ux-must-check a ${width}px: sin desbordamiento, objetivos de 24px, controles con nombre y contraste AA`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await openTools(page);

      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow).toBe(false);

      for (const control of [countrySelect(page), phoneInput(page)]) {
        const box = await control.boundingBox();
        expect(box.width).toBeGreaterThanOrEqual(24);
        expect(box.height).toBeGreaterThanOrEqual(24);
        expect(await contrastRatio(control)).toBeGreaterThanOrEqual(4.5);
      }

      const unnamed = await page.locator("#tools").evaluate(root =>
        [...root.querySelectorAll("input, select, textarea, button")]
          .filter(element => element.offsetParent)
          .filter(element => !(element.labels?.length || element.getAttribute("aria-label")
            || element.getAttribute("aria-labelledby") || (element.tagName === "BUTTON" && element.textContent.trim())))
          .map(element => element.id || element.name || element.tagName));
      expect(unnamed).toEqual([]);
    });
  }

  test("ui-ux-must-check: el indicativo precede al teléfono al tabular y muestra foco visible", async ({ page }) => {
    await openTools(page);
    await phoneInput(page).focus();
    await page.keyboard.press("Shift+Tab");
    await expect(countrySelect(page)).toBeFocused();

    const focus = await countrySelect(page).evaluate(element => {
      const style = getComputedStyle(element);
      return {
        focusVisible: element.matches(":focus-visible"),
        outline: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0,
        shadow: style.boxShadow !== "none",
      };
    });
    expect(focus.focusVisible).toBe(true);
    expect(focus.outline || focus.shadow).toBe(true);

    await page.keyboard.press("Tab");
    await expect(phoneInput(page)).toBeFocused();
  });
});
