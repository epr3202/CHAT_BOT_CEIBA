import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.mjs",
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5199",
    headless: true,
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
  },
  webServer: [
    {
      command: "cd ../.. && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/ready",
      reuseExistingServer: false,
    },
    {
      command: "node ../../frontend/server.mjs",
      url: "http://127.0.0.1:5199",
      env: {
        ENVIRONMENT: "production", NODE_ENV: "production",
        FRONTEND_HOST: "0.0.0.0", FRONTEND_PORT: "5199",
        API_BASE_URL: "http://127.0.0.1:8000",
      },
      reuseExistingServer: false,
    },
  ],
});
