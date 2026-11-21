import { test, expect } from "playwright/test";
import { panel } from "./b2_panel_fixture.mjs";

for (const width of [375, 768, 1024, 1440]) {
  test(`bandeja, comprobante y calendario a ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await panel(page);
    let opened = false;
    let sends = 0;
    await page.route("**/api/admin/conversations?*", (route) =>
      route.fulfill({
        json: [
          {
            id: 18,
            customer_name: "Contacto de muestra",
            state: "HUMAN_ACTIVE",
            handoff_id: 21,
            assigned_agent: { id: 1, name: "Asesor del panel" },
            handoff_status: "TAKEN",
            unopened_count: opened ? 0 : 1,
          },
        ],
      }),
    );
    await page.route("**/api/admin/conversations/18/messages", (route) => {
      if (route.request().method() === "POST") {
        sends++;
        return route.fulfill(
          sends === 1
            ? { status: 409, json: { detail: "Caso en revisión" } }
            : { json: { status: "PENDING" } },
        );
      }
      return route.fulfill({
        json: [
          {
            id: "message-1",
            direction: "INBOUND",
            body: "Mensaje de muestra",
            message_type: "text",
            created_at: "2026-11-20T16:00:00Z",
            opened_by_me: opened,
          },
        ],
      });
    });
    await page.route(
      "**/api/admin/conversations/18/messages/opened",
      (route) => {
        expect(route.request().postDataJSON()).toEqual({ message_ids: [1] });
        opened = true;
        return route.fulfill({ status: 204 });
      },
    );
    await page.route("**/api/admin/calendar/events?*", (route) => {
      const start = new URL(route.request().url()).searchParams.get("start");
      return route.fulfill({
        json: [
          {
            title: "Reserva familiar",
            description: "Plan de jardín\nDescripción completa",
            all_day: true,
            start_date: start,
            end_date: start.slice(0, 8) + "02",
            start: start + "T05:00:00Z",
            end: start.slice(0, 8) + "02T05:00:00Z",
          },
        ],
      });
    });
    await page.route("**/api/admin/payment-evidence/*/download", (route) =>
      route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX2kAAAAASUVORK5CYII=",
          "base64",
        ),
      }),
    );
    await page.locator("#refreshCases").click();
    await page
      .getByRole("button", {
        name: "Abrir conversación de Contacto de muestra",
      })
      .click();
    const chat = page.locator("#activeChat");
    await expect(chat).toContainText("Mensaje de muestra");
    await expect(chat).toContainText("Abierto por ti");
    await chat.getByLabel("Tu respuesta").fill("Respuesta del asesor");
    await chat.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(chat).toContainText("Caso en revisión");
    await expect(chat.getByLabel("Tu respuesta")).toHaveValue(
      "Respuesta del asesor",
    );
    await chat.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(chat).toContainText("Respuesta en cola");
    await chat.getByRole("button", { name: "Volver a la lista" }).click();
    async function navigate(id) {
      const b = page.locator('[data-view="' + id + '"]');
      if (!(await b.isVisible())) await page.locator("#navToggle").click();
      await b.click();
    }
    await navigate("paymentEvidence");
    await page
      .getByRole("button", { name: "Ver comprobante", exact: true })
      .first()
      .click();
    await expect(page.locator("#proofDialog img")).toBeVisible();
    await page.keyboard.press("Escape");
    await navigate("calendar");
    await page
      .locator("#agendaDate")
      .fill(
        (await page.locator("#agendaDate").inputValue()).slice(0, 8) + "01",
      );
    await page.locator("#agendaDate").dispatchEvent("change");
    await expect(page.locator("#calendar")).toContainText(
      "Descripción completa",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  });
}

test("PDF local de varias páginas abre y pagina sin descargar", async ({
  page,
}) => {
  const data = await panel(page);
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 170] /Resources <<>> >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 160 90] /Resources <<>> >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((value, i) => {
    offsets.push(pdf.length);
    pdf += i + 1 + " 0 obj\n" + value + "\nendobj\n";
  });
  const start = pdf.length;
  pdf +=
    "xref\n0 5\n0000000000 65535 f \n" +
    offsets
      .slice(1)
      .map((n) => String(n).padStart(10, "0") + " 00000 n \n")
      .join("") +
    "trailer\n<< /Root 1 0 R /Size 5 >>\nstartxref\n" +
    start +
    "\n%%EOF\n";
  await page.route("**/api/admin/payment-evidence/*/download", (route) =>
    route.fulfill({ contentType: "application/pdf", body: pdf }),
  );
  const downloads = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  await page.locator('[data-view="paymentEvidence"]').click();
  await page
    .getByRole("button", { name: "Ver comprobante", exact: true })
    .first()
    .click();
  const dialog = page.locator("#proofDialog");
  await expect(dialog).toContainText("Página 1 de 2");
  await dialog.getByRole("button", { name: "Página siguiente" }).click();
  await expect(dialog).toContainText("Página 2 de 2");
  await expect(dialog.locator("canvas")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect(downloads).toEqual([]);
  expect(data.calls.some((c) => c.key.endsWith("/accept"))).toBeFalsy();
});

test("apertura registrada desde el panel y consultada en la API real de prueba", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator("#documentId").fill("90000000");
  await page.locator("#pin").fill("123456");
  await page.locator("#login").click();
  await page
    .getByRole("button", { name: "Abrir conversación de Ana Lucía" })
    .click();
  await expect(page.locator("#activeHistory")).toContainText("Abierto por ti");
  const states = await page.evaluate(async () => {
    const headers = {
      Authorization: "Bearer " + sessionStorage.getItem("ceiba.sessionToken"),
    };
    const cases = await (
      await fetch("/api/admin/conversations", { headers })
    ).json();
    const row = cases.find((r) => r.customer_name === "Ana Lucía");
    const messages = await (
      await fetch("/api/admin/conversations/" + row.id + "/messages", {
        headers,
      })
    ).json();
    return {
      opened: messages.some((m) => m.direction === "INBOUND" && m.opened_by_me),
      count: row.unopened_count,
    };
  });
  expect(states).toEqual({ opened: true, count: 0 });
});

test("administrar bloqueos y festivo de la fecha seleccionada", async ({
  page,
}) => {
  await panel(page);
  let block = null,
    holiday = null;
  await page.route("**/api/admin/blocked-dates**", (route) => {
    const req = route.request();
    if (req.method() === "GET")
      return route.fulfill({ json: block ? [block] : [] });
    if (req.method() === "DELETE") {
      block = null;
      return route.fulfill({ status: 204 });
    }
    block = { ...block, ...req.postDataJSON() };
    return route.fulfill({ json: block });
  });
  await page.route("**/api/admin/holidays", (route) => {
    holiday = route.request().postDataJSON();
    return route.fulfill({ json: holiday });
  });
  await page.locator('[data-view="calendar"]').click();
  await page.locator("#calendar details summary").click();
  const reason = page.locator("#blockReason");
  await reason.fill("Cierre de prueba");
  await page.getByRole("button", { name: "Guardar bloqueo" }).click();
  await expect(page.locator("#blockStatus")).toHaveText(
    "Fecha bloqueada: Cierre de prueba",
  );
  await reason.fill("Cambio de motivo");
  await page.getByRole("button", { name: "Guardar bloqueo" }).click();
  await expect(page.locator("#blockStatus")).toHaveText(
    "Fecha bloqueada: Cambio de motivo",
  );
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Retirar bloqueo" }).click();
  await expect(page.locator("#blockStatus")).toHaveText("Sin bloqueo manual.");
  await reason.fill("Festivo de prueba");
  await page.getByRole("button", { name: "Registrar festivo" }).click();
  await expect.poll(() => holiday?.name).toBe("Festivo de prueba");
});

test("cambiar de conversación durante un envío conserva cada borrador y evita duplicar la respuesta", async ({
  page,
}) => {
  await panel(page);
  const names = ["Olga", "Sol"];
  await page.route("**/api/admin/conversations?*", (route) =>
    route.fulfill({
      json: names.map((name, i) => ({
        id: i + 30,
        customer_name: name,
        state: "HUMAN_ACTIVE",
        handoff_id: i + 40,
        handoff_status: "TAKEN",
        assigned_agent: { id: 1, name: "Asesor del panel" },
      })),
    }),
  );
  let release;
  const wait = new Promise((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route("**/api/admin/conversations/*/messages", async (route) => {
    if (route.request().method() === "POST") {
      count++;
      await wait;
      return route.fulfill({ json: { status: "PENDING" } });
    }
    return route.fulfill({ json: [] });
  });
  await page.locator("#refreshCases").click();
  const contact = (name) =>
    page.getByRole("button", { name: "Abrir conversación de " + name });
  const input = page.getByLabel("Tu respuesta");
  await contact("Olga").focus();
  await page.keyboard.press("Enter");
  await input.fill("Respuesta pendiente");
  await input.press("Control+Enter");
  await expect(page.locator("#replySend")).toHaveText("Enviando…");
  await expect(page.locator("#replySend")).toBeDisabled();
  await contact("Sol").click();
  await input.fill("Segundo borrador");
  await contact("Olga").click();
  await expect(input).toHaveValue("Respuesta pendiente");
  release();
  await expect(input).toHaveValue("");
  await expect(page.locator("#replyStatus")).toContainText("Respuesta en cola");
  await contact("Sol").click();
  await expect(input).toHaveValue("Segundo borrador");
  expect(count).toBe(1);
});
