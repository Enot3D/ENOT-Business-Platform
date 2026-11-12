import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: process.env.ENOT_E2E_ORIGIN ?? "http://localhost:3000",
    launchOptions: { executablePath: process.env.ENOT_CHROMIUM_PATH },
    proxy: process.env.ENOT_E2E_PROXY ? { server: process.env.ENOT_E2E_PROXY } : undefined,
    ignoreHTTPSErrors: process.env.ENOT_E2E_PROXY ? true : undefined,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "tablet", use: { viewport: { width: 768, height: 1024 }, hasTouch: true } },
    { name: "phone", use: process.env.ENOT_E2E_WEBKIT
      ? { ...devices["iPhone 13"], browserName: "webkit", launchOptions: {} }
      : { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
});
