"""The fixture-backed panel must also work through the real Node HTTP proxy."""

import subprocess
from pathlib import Path


def test_g3_booking_proxy_preserves_routes_queries_auth_and_bodies() -> None:
    script = r"""
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
const backend = createServer(async (request, response) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  response.writeHead(200, {"Content-Type": "application/json"});
  response.end(JSON.stringify({url: request.url, method: request.method,
    authorization: request.headers.authorization, body: Buffer.concat(chunks).toString()}));
});
await new Promise(resolve => backend.listen(0, "127.0.0.1", resolve));
const probe = createServer();
await new Promise(resolve => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise(resolve => probe.close(resolve));
const frontend = spawn("node", ["frontend/server.mjs"], {env: {...process.env,
  FRONTEND_HOST: "127.0.0.1", FRONTEND_PORT: String(port), ENVIRONMENT: "testing",
  API_BASE_URL: `http://127.0.0.1:${backend.address().port}`}, stdio: "ignore"});
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { await fetch(`http://127.0.0.1:${port}/`); ready = true; break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert(ready, "Node frontend must start");
  const queries = "?status=PAYMENT_REVIEW&from=2030-10-01T05%3A00%3A00Z"
    + "&to=2030-11-01T04%3A59%3A59Z";
  const routes = [
    ["GET", "/api/admin/plans", undefined],
    ["PATCH", "/api/admin/plans/test-plan", {price_cop: 250000}],
    ["GET", "/api/admin/reservations" + queries, undefined],
    ["GET", "/api/admin/reservations/availability?plan_id=test-plan"
      + "&starts_at=2030-10-10T17%3A00%3A00Z", undefined],
    ["GET", "/api/admin/reservations/test-reservation", undefined],
    ["POST", "/api/admin/reservations", {phone: "+573000000222", plan_id: "test-plan"}],
    ["PATCH", "/api/admin/reservations/test-reservation/schedule",
      {starts_at: "2030-10-11T17:00:00Z"}],
    ["POST", "/api/admin/reservations/test-reservation/sync-calendar", undefined],
    ["POST", "/api/admin/reservations/test-reservation/cancel", {note: "Cliente cancela"}],
    ["GET", "/api/admin/payment-evidence/test-evidence", undefined],
    ["POST", "/api/admin/payment-evidence/test-evidence/prereview", undefined],
    ["POST", "/api/admin/payment-evidence/test-evidence/accept",
      {amount_cop: 125000, review_id: "44444444-4444-4444-8444-444444444444"}],
  ];
  for (const [method, path, payload] of routes) {
    const body = payload ? JSON.stringify(payload) : undefined;
    const response = await fetch(`http://127.0.0.1:${port}${path}`, {method, body,
      headers: {"Content-Type": "application/json", Authorization: "Bearer fixture-proxy"}});
    assert.equal(response.status, 200, `Proxy missing: ${method} ${path}`);
    assert.deepEqual(await response.json(), {url: path.replace("/api", ""), method,
      authorization: "Bearer fixture-proxy", body: body || ""});
  }
} finally {
  frontend.kill("SIGTERM");
  await new Promise(resolve => frontend.once("exit", resolve));
  await new Promise(resolve => backend.close(resolve));
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
