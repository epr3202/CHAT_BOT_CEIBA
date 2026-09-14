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
const environment = process.env.ENVIRONMENT || "production";
if (!["development", "testing", "production", "staging"].includes(environment)) {
  throw new Error("Invalid ENVIRONMENT");
}
if (process.env.DEPLOYED_RUNTIME === "true" && (!process.env.ENVIRONMENT || !["staging", "production"].includes(environment))) {
  throw new Error("Deployed runtime requires explicit staging/production ENVIRONMENT");
}
const simulationAllowed = ["development", "testing"].includes(environment)
  && !["production", "staging"].includes(process.env.NODE_ENV);

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

async function readRawBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 20 * 1024 * 1024) {
      const error = new Error("Body too large");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  return chunks.length === 0 ? Buffer.alloc(0) : Buffer.concat(chunks);
}

async function readBody(request) {
  return (await readRawBody(request)).toString("utf8");
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
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await readRawBody(request);
  const headers = {"Content-Type": request.headers["content-type"] || "application/json"};
  if (request.headers.authorization) {
    headers.Authorization = request.headers.authorization;
  }

  const upstream = await fetch(`${backendBaseUrl}${targetPath}`, {
    signal: AbortSignal.timeout(20000),
    method: request.method,
    headers,
    body,
  });
  const payload = Buffer.from(await upstream.arrayBuffer());
  const responseHeaders = {
    "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
  };
  const contentDisposition = upstream.headers.get("content-disposition");
  if (contentDisposition) responseHeaders["Content-Disposition"] = contentDisposition;
  response.writeHead(upstream.status, responseHeaders);
  response.end(payload);
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
    signal: AbortSignal.timeout(20000),
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

  if (!Object.hasOwn(contentTypes, extname(filePath)) || filePath.includes("server.mjs")) {
    response.writeHead(404); response.end("Not found"); return;
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
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("Referrer-Policy", "no-referrer");
  try {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    const path = requestUrl.pathname;

    if (path === "/live") { sendJson(response, 200, {status: "alive"}); return; }
    if (path === "/api/health") {
      await proxy(request, response, "/health");
      return;
    }
    if (path === "/api/webhook/simulate" && request.method === "POST") {
      if (!simulationAllowed) {
        sendJson(response, 403, { detail: "Simulation disabled" });
        return;
      }
      await simulateWebhook(request, response);
      return;
    }
    if (path === "/api/admin/handoffs") {
      await proxy(request, response, `/admin/handoffs${requestUrl.search}`);
      return;
    }
    if (path === "/api/admin/login") {
      await proxy(request, response, "/admin/login");
      return;
    }
    if (path === "/api/admin/logout") {
      await proxy(request, response, "/admin/logout");
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
    if (path === "/api/admin/catalogs/categories") {
      await proxy(request, response, "/admin/catalogs/categories");
      return;
    }
    if (path === "/api/admin/catalogs/upload") {
      await proxy(request, response, "/admin/catalogs/upload");
      return;
    }
    if (path.startsWith("/api/admin/catalogs/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }
    if (path === "/api/admin/payment-evidence" || path.startsWith("/api/admin/payment-evidence/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }
    if (path.startsWith("/api/admin/agents/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }
    if (path.startsWith("/api/admin/conversations/")) {
      await proxy(request, response, path.replace("/api", ""));
      return;
    }

    await serveStatic(request, response);
  } catch (error) {
    sendJson(response, error.statusCode === 413 ? 413 : 502, { detail: "Solicitud no disponible" });
  }
});

server.requestTimeout = 30000;
server.headersTimeout = 10000;
server.listen(port, host, () => {
  console.log(`Frontend La Ceiba: http://${host}:${port}`);
  console.log(`Backend API: ${backendBaseUrl}`);
});
