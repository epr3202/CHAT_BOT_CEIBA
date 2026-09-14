import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";

for (const environment of ["production", "staging", "development", "testing", "missing"]) {
  test(`simulator boundary: ${environment}`, { timeout: 10000 }, async () => {
    let inbound = 0;
    const backend = createServer((request, response) => {
      inbound += 1;
      request.resume();
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end('{}');
    });
    backend.listen(0, "127.0.0.1");
    await once(backend, "listening");
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1");
    await once(reservation, "listening");
    const port = reservation.address().port;
    await new Promise(resolve => reservation.close(resolve));
    const env = { ...process.env, FRONTEND_PORT: String(port), FRONTEND_HOST: "127.0.0.1",
      API_BASE_URL: `http://127.0.0.1:${backend.address().port}`,
      META_APP_SECRET: "synthetic-r10-secret", ENVIRONMENT: environment };
    delete env.NODE_ENV;
    if (environment === "missing") delete env.ENVIRONMENT;
    const child = spawn(process.execPath, ["frontend/server.mjs"], { env, stdio: "pipe" });
    try {
      await Promise.race([
        once(child.stdout, "data"),
        once(child, "exit").then(() => { throw new Error("Frontend exited before readiness"); }),
      ]);
      const response = await fetch(`http://127.0.0.1:${port}/api/webhook/simulate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: "573001112233", text: "Synthetic R10" }),
      });
      const allowed = ["development", "testing"].includes(environment);
      assert.equal(response.status, allowed ? 200 : 403);
      assert.equal(inbound, allowed ? 1 : 0);
    } finally {
      child.kill();
      await once(child, "exit");
      backend.closeAllConnections();
      await new Promise(resolve => backend.close(resolve));
    }
  });
}
