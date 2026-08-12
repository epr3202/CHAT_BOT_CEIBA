import { createHmac, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const port = Number.parseInt(process.env.FRONTEND_PORT || "5173", 10);
const host = process.env.FRONTEND_HOST || "127.0.0.1";
const backendBaseUrl = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const metaAppSecret = process.env.META_APP_SECRET || "";

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function sendJson(response, status, payload) {
  response.writeHead(status, {"Content-Type": "application/json; charset=utf-8"});
  response.end(JSON.stringify(payload));
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  if (chunks.length === 0) {
    return "";
  }
  return Buffer.concat(chunks).toString("utf8");
}

function signedWhatsAppPayload({ phone, text, messageId }) {
  const digits = String(phone || "").replace(/\D/g, "");
  const providerPhone = digits || "573001112233";
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "local_frontend_waba",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: "573001112233",
                phone_number_id: "local_frontend_phone_number",
              },
              contacts: [
                {
                  profile: { name: "Cliente local" },
                  wa_id: providerPhone,
                },
              ],
              messages: [
                {
                  from: providerPhone,
                  id: messageId || `wamid.frontend.${Date.now()}.${randomUUID()}`,
                  timestamp: String(Math.floor(Date.now() / 1000)),
                  text: { body: String(text || "") },
                  type: "text",
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

async function proxy(request, response, targetPath) {
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await readBody(request);
  const headers = {"Content-Type": request.headers["content-type"] || "application/json"};
  if (request.headers.authorization) {
    headers.Authorization = request.headers.authorization;
  }

  const upstream = await fetch(`${backendBaseUrl}${targetPath}`, {
    method: request.method,
    headers,
    body,
  });
  const text = await upstream.text();
  response.writeHead(upstream.status, {
    "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
  });
  response.end(text);
}

async function simulateWebhook(request, response) {
  let input;
  try {
    input = JSON.parse(await readBody(request));
  } catch {
    sendJson(response, 400, { detail: "JSON inválido" });
    return;
  }

  const signingSecret = metaAppSecret || input.metaSecret;
  if (!signingSecret || !input.text) {
    sendJson(response, 400, { detail: "META_APP_SECRET y texto son obligatorios" });
    return;
  }

  const payload = signedWhatsAppPayload(input);
  const body = JSON.stringify(payload);
  const signature = createHmac("sha256", String(signingSecret)).update(body).digest("hex");
  const upstream = await fetch(`${backendBaseUrl}/webhook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Signature-256": `sha256=${signature}`,
      "X-Request-ID": `frontend-${Date.now()}`,
    },
    body,
  });

  const text = await upstream.text();
  response.writeHead(upstream.status, {
    "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
  });
  response.end(text);
}

async function serveStatic(request, response) {
  const requestUrl = new URL(request.url || "/", "http://localhost");
  const pathName = requestUrl.pathname === "/" ? "/index.html" : requestUrl.pathname;
  const normalized = normalize(pathName).replace(/^(\.\.[/\\])+/, "");
  const filePath = join(frontendRoot, normalized);

  if (!filePath.startsWith(frontendRoot)) {
    response.writeHead(403);
    response.end("Forbidden");
    return;
  }

  try {
    const content = await readFile(filePath);
    response.writeHead(200, {"Content-Type": contentTypes[extname(filePath)] || "application/octet-stream"});
    response.end(content);
  } catch {
    response.writeHead(404);
    response.end("Not found");
  }
}

const server = createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    const path = requestUrl.pathname;

    if (path === "/api/health") {
      await proxy(request, response, "/health");
      return;
    }
    if (path === "/api/webhook/simulate" && request.method === "POST") {
      await simulateWebhook(request, response);
      return;
    }
    if (path === "/api/admin/handoffs") {
      await proxy(request, response, `/admin/handoffs${requestUrl.search}`);
      return;
    }
    if (path.startsWith("/api/admin/handoffs/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }
    if (path === "/api/admin/conversations") {
      await proxy(request, response, `/admin/conversations${requestUrl.search}`);
      return;
    }
    if (path === "/api/admin/me") {
      await proxy(request, response, "/admin/me");
      return;
    }
    if (path === "/api/admin/agents") {
      await proxy(request, response, "/admin/agents");
      return;
    }
    if (path.startsWith("/api/admin/conversations/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }

    await serveStatic(request, response);
  } catch (error) {
    sendJson(response, 502, { detail: error instanceof Error ? error.message : "Error del proxy" });
  }
});

server.listen(port, host, () => {
  console.log(`Frontend La Ceiba: http://${host}:${port}`);
  console.log(`Backend API: ${backendBaseUrl}`);
});
