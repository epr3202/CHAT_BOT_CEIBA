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
    const dayButton = page.locator("#monthDays button[aria-pressed=true]");
    await expect(dayButton).toContainText("Reserva familiar");
    await page.locator("#agendaEvents").getByRole("button", { name: /Reserva familiar/ }).click();
    await expect(page.locator("#agendaEventDialog")).toBeVisible();
    await expect(page.locator("#agendaEventDialog")).toContainText("Descripción completa");
    await page.keyboard.press("Escape");
    await dayButton.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#monthDays button[aria-pressed=true]")).toBeFocused();
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

for (const [width, initial] of [[375, "PENDING"], [1440, "BOT_ACTIVE"]]) {
  test(`leer, tomar, responder y devolver en la misma conversación a ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await panel(page, { role: "AGENT" });
    let status = initial;
    const posts = [];
    const owner = { id: 1, name: "Asesor del panel" };
    await page.route("**/api/admin/conversations?*", route => {
      const filter = new URL(route.request().url()).searchParams.get("handoff_status");
      const row = {
        id: 18, customer_name: "Contacto de muestra", handoff_id: status === "BOT_ACTIVE" ? null : 21,
        state: { PENDING: "WAITING_FOR_HUMAN", TAKEN: "HUMAN_ACTIVE", RETURNED: "BOT_ACTIVE" }[status] || status,
        handoff_status: status === "BOT_ACTIVE" ? null : status,
        assigned_agent: status === "TAKEN" ? owner : null,
      };
      return route.fulfill({ json: filter && status !== filter ? [] : [row] });
    });
    for (const [path, next] of [
      [initial === "PENDING" ? "handoffs/21/take" : "conversations/18/take", "TAKEN"],
      ["handoffs/21/return", "RETURNED"],
    ]) {
      await page.route("**/api/admin/" + path, route => {
        posts.push(path);
        status = next;
        return route.fulfill({ json: { id: 21, conversation_id: 18, status,
          assigned_agent: status === "TAKEN" ? owner : null } });
      });
    }
    await page.route("**/api/admin/conversations/18/messages", route => {
      if (route.request().method() === "POST") {
        posts.push(route.request().postDataJSON().text);
        return route.fulfill({ json: { status: "PENDING" } });
      }
      return route.fulfill({ json: [{ id: "message-9", body: "Hola, ¿me ayudan?", direction: "INBOUND",
        opened_by_me: true, created_at: "2026-11-20T17:00:00Z" }] });
    });
    await expect(page.locator('#mainNav [data-view="handoffs"]')).toHaveCount(0);
    if (initial === "PENDING") await page.locator("#conversationStateFilter").selectOption("case:PENDING");
    else await page.locator("#refreshCases").click();
    await page.getByRole("button", { name: "Abrir conversación de Contacto de muestra" }).click();
    await expect(page.locator("#activeHistory")).toContainText("Hola, ¿me ayudan?");
    await expect(page.getByLabel("Tu respuesta")).toBeHidden();
    expect(posts).toEqual([]);
    await page.getByRole("button", { name: "Tomar para responder" }).click();
    await expect(page.getByLabel("Tu respuesta")).toBeFocused();
    await page.getByLabel("Tu respuesta").fill("Te ayudo");
    await page.getByRole("button", { name: "Enviar", exact: true }).click();
    await expect(page.locator("#replyStatus")).toContainText("Respuesta en cola");
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("button", { name: "Devolver al bot" }).click();
    await expect(page.getByLabel("Tu respuesta")).toBeHidden();
    await expect(page.locator("#assignedToMeFilter")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#caseList")).toContainText("No tienes conversaciones en atención");
    expect(posts).toEqual([initial === "PENDING" ? "handoffs/21/take" : "conversations/18/take",
      "Te ayudo", "handoffs/21/return"]);
  });
}

test("la bandeja anterior se restaura y un caso de otro asesor abre en lectura", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("ceiba.currentView", "handoffs");
    localStorage.setItem("ceiba.currentStatus", "TAKEN");
  });
  await panel(page, { role: "AGENT" });
  await page.route("**/api/admin/conversations?*", route => route.fulfill({ json: [{
    id: 3, customer_name: "Contacto compartido", handoff_id: 7, state: "HUMAN_ACTIVE",
    handoff_status: "TAKEN", assigned_agent: { id: 2, name: "Laura" },
  }] }));
  await page.locator("#refreshCases").click();
  await expect(page.locator("#assignedToMeFilter")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#caseList")).not.toContainText("Contacto compartido");
  await page.getByRole("button", { name: "Todas", exact: true }).click();
  await expect(page.locator("#conversationStateFilter")).toHaveValue("case:TAKEN");
  await page.getByRole("button", { name: "Abrir conversación de Contacto compartido" }).click();
  await expect(page.locator("#replyRestriction")).toContainText("Laura");
  await expect(page.getByLabel("Tu respuesta")).toBeHidden();
  await expect(page.locator("#chatTake")).toBeHidden();
  await expect(page.locator("#chatReturn")).toBeHidden();
});

test("Mis conversaciones separa por responsable y permite salir de una cola incompatible", async ({ page }) => {
  await panel(page, { role: "AGENT" });
  const names = ["Contacto mío", "Contacto de otra asesora", "Contacto pendiente"];
  const people = [1, 2, null];
  let transferred = false;
  const queries = [];
  await page.route("**/api/admin/conversations?*", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(query));
    const rows = names.map((name, index) => {
      const owner = transferred && index === 0 ? 2 : people[index];
      return { id: index + 1, customer_name: name, state: owner ? "HUMAN_ACTIVE" : "WAITING_FOR_HUMAN",
        handoff_id: index + 10, handoff_status: owner ? "TAKEN" : "PENDING",
        assigned_agent: owner ? { id: owner, name: owner === 1 ? "Asesor del panel" : "Laura" } : null };
    });
    return route.fulfill({ json: rows.filter(row =>
      (!query.get("handoff_status") || row.handoff_status === query.get("handoff_status")) &&
      (!query.has("assigned_to_me") || row.assigned_agent?.id === 1) &&
      (!query.get("state") || row.state === query.get("state"))) });
  });
  const list = page.locator("#caseList");
  await page.locator("#conversationStateFilter").selectOption("case:PENDING");
  await expect(list).toContainText(names[2]);
  await page.getByRole("button", { name: "Mis conversaciones", exact: true }).click();
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(list).toContainText(names[0]);
  await expect(list).toContainText("Asignada a ti");
  expect(queries.at(-1)).toMatchObject({ state: "HUMAN_ACTIVE", handoff_status: "TAKEN", assigned_to_me: "true" });
  await page.reload();
  await expect(page.getByRole("button", { name: "Mis conversaciones" })).toHaveAttribute("aria-pressed", "true");
  await expect(list).toContainText(names[0]);
  await list.getByRole("button").click();
  await expect(page.getByLabel("Tu respuesta")).toBeVisible();
  transferred = true;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(list).toContainText("No tienes conversaciones en atención");
  await expect(page.getByLabel("Tu respuesta")).toBeHidden();
  await page.getByRole("button", { name: "Todas", exact: true }).click();
  await page.locator("#conversationStateFilter").selectOption("case:TAKEN");
  await expect(list.getByRole("button")).toHaveCount(2);
  await expect(list).toContainText("Laura");
  expect(queries.at(-1)).not.toHaveProperty("assigned_to_me");
});
