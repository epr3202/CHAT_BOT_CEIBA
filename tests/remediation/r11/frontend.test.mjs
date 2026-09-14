import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";

for (const environment of ["", "development", "testing", "invalid"]) {
  test(`deployed frontend rejects environment ${environment || "missing"}`, {timeout: 10000}, async () => {
    const child = spawn(process.execPath, ["frontend/server.mjs"], {
      env: {...process.env, DEPLOYED_RUNTIME: "true", ENVIRONMENT: environment}, stdio: "pipe",
    });
    const [code] = await once(child, "exit");
    assert.notEqual(code, 0);
  });
}

for (const environment of ["staging", "production"]) {
  test(`protected frontend ${environment}: liveness, headers, simulator`, {timeout: 10000}, async () => {
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1");
    await once(reservation, "listening");
    const port = reservation.address().port;
    await new Promise(resolve => reservation.close(resolve));
    const child = spawn(process.execPath, ["frontend/server.mjs"], {
      env: {...process.env, DEPLOYED_RUNTIME: "true", ENVIRONMENT: environment,
        FRONTEND_HOST: "127.0.0.1", FRONTEND_PORT: String(port)}, stdio: "pipe",
    });
    try {
      await Promise.race([once(child.stdout, "data"), once(child, "exit").then(() => {
        throw new Error("Startup failed");
      })]);
      const base = `http://127.0.0.1:${port}`;
      const live = await fetch(`${base}/live`);
      assert.equal(live.status, 200);
      assert.equal(live.headers.get("x-content-type-options"), "nosniff");
      assert.equal((await fetch(`${base}/api/webhook/simulate`, {method: "POST"})).status, 403);
      assert.equal((await fetch(`${base}/server.mjs`)).status, 404);
    } finally {
      child.kill();
      await once(child, "exit");
    }
  });
}
