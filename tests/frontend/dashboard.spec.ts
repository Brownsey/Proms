import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8123";

async function mockConnectedApi(page: Page, active = 3) {
  await page.route(`${API}/configuration`, (route) =>
    route.fulfill({
      json: { static_proxy_count: 4, rotating_proxy_count: 2 },
      headers: { "access-control-allow-origin": "*" },
    }),
  );
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: { active },
        headers: { "access-control-allow-origin": "*" },
      });
    }
    return route.fallback();
  });
}

async function connect(page: Page, active = 3) {
  await mockConnectedApi(page, active);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect local service" }).click();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

test("starts disconnected and explains local-service permission", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));

  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Launch manifest" })).toBeVisible();
  await expect(page.getByText("Not connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect local service" })).toBeVisible();
  await expect(page.getByText(/browser may ask permission to reach devices on your local network/i)).toBeVisible();
  await expect(page.getByText(/Safari does not support this remote-to-local control flow/i)).toBeVisible();
  expect(requests.filter((url) => url.startsWith(API))).toEqual([]);
});

test("exposes the connecting state and prevents duplicate connect actions", async ({ page }) => {
  let releaseRequests: () => void = () => undefined;
  const requestsReleased = new Promise<void>((resolve) => {
    releaseRequests = resolve;
  });
  let requestCount = 0;

  await page.route(`${API}/**`, async (route) => {
    requestCount += 1;
    await requestsReleased;
    if (route.request().url().endsWith("/configuration")) {
      return route.fulfill({ json: { static_proxy_count: 4, rotating_proxy_count: 2 } });
    }
    return route.fulfill({ json: { active: 3 } });
  });
  await page.goto("/");

  const connectButton = page.getByRole("button", { name: "Connecting…" });
  await page.getByRole("button", { name: "Connect local service" }).click();
  await expect(connectButton).toBeDisabled();
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "true");
  await expect.poll(() => requestCount).toBe(2);

  releaseRequests();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
});

test("connects, shows proxy and browser counts, then refreshes", async ({ page }) => {
  let statusCalls = 0;
  await page.route(`${API}/configuration`, (route) =>
    route.fulfill({ json: { static_proxy_count: 4, rotating_proxy_count: 2 } }),
  );
  await page.route(`${API}/browsers`, (route) => {
    statusCalls += 1;
    return route.fulfill({ json: { active: statusCalls === 1 ? 3 : 5 } });
  });
  await page.goto("/");

  await page.getByRole("button", { name: "Connect local service" }).click();
  await expect(page.getByText("4", { exact: true })).toBeVisible();
  await expect(page.getByText("2", { exact: true })).toBeVisible();
  await expect(page.getByText("3 active", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByText("5 active", { exact: true })).toBeVisible();
});

test("launches with exact settings and reports active windows", async ({ page }) => {
  await connect(page, 2);
  let launchBody: unknown;
  await page.route(`${API}/browsers`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    launchBody = route.request().postDataJSON();
    return route.fulfill({ status: 200, json: { launched: 5, active: 7 } });
  });

  await page.getByLabel("Static windows per proxy").fill("2");
  await page.getByLabel("Rotating windows per proxy").fill("3");
  await page.getByLabel("Target URL").fill("https://example.com/path");
  await page.getByLabel("Rotation attempts").fill("7");
  await page.getByRole("button", { name: "Launch windows" }).click();

  await expect(page.getByText("Launched 5 windows. 7 active.")).toBeVisible();
  await expect(page.getByText("7 active", { exact: true })).toBeVisible();
  expect(launchBody).toEqual({
    static_windows_per_proxy: 2,
    rotating_windows_per_proxy: 3,
    url: "https://example.com/path",
    rotation_attempts: 7,
  });
});

test("supports keyboard connection and form submission", async ({ page }) => {
  await mockConnectedApi(page);
  await page.goto("/");

  await page.keyboard.press("Tab");
  const connectButton = page.getByRole("button", { name: "Connect local service" });
  await expect(connectButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();

  let launchCalls = 0;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    launchCalls += 1;
    return route.fulfill({ json: { launched: 1, active: 1 } });
  });
  const staticCount = page.getByLabel("Static windows per proxy");
  await staticCount.focus();
  await expect(staticCount).toBeFocused();
  await staticCount.press("Enter");

  await expect(page.getByText("Launched 1 windows. 1 active.")).toBeVisible();
  expect(launchCalls).toBe(1);
});

test("requires confirmation before closing every active window", async ({ page }) => {
  await connect(page, 4);
  let deleteCalls = 0;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() === "DELETE") {
      deleteCalls += 1;
      return route.fulfill({ json: { closed: 4 } });
    }
    return route.fallback();
  });

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Close all" }).click();
  expect(deleteCalls).toBe(0);
  await expect(page.getByText("4 active", { exact: true })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Close all" }).click();
  await expect(page.getByText("Closed 4 windows.")).toBeVisible();
  await expect(page.getByText("0 active", { exact: true })).toBeVisible();
  expect(deleteCalls).toBe(1);
});

test("disables close when no windows are active", async ({ page }) => {
  await connect(page, 0);

  await expect(page.getByRole("button", { name: "Close all" })).toBeDisabled();
});

test("rejects invalid launch settings before calling the backend", async ({ page }) => {
  await connect(page);
  let postCalls = 0;
  page.on("request", (request) => {
    if (request.url() === `${API}/browsers` && request.method() === "POST") postCalls += 1;
  });
  await page.getByLabel("Static windows per proxy").fill("0");
  await page.getByLabel("Rotating windows per proxy").fill("0");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "At least one window count" })).toContainText(
    "At least one window count must be greater than zero",
  );

  await page.getByLabel("Static windows per proxy").fill("1.5");
  await page.getByLabel("Target URL").fill("/relative");
  await page.getByLabel("Rotation attempts").fill("21");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "whole number" })).toBeVisible();
  expect(postCalls).toBe(0);
});

test("shows safe FastAPI errors and offline recovery guidance", async ({ page }) => {
  await connect(page);
  await page.route(`${API}/browsers`, (route) =>
    route.fulfill({
      status: 400,
      json: { detail: [{ loc: ["body", "url"], msg: "Value error, target blocked" }] },
    }),
  );

  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "url: Value error, target blocked" })).toBeVisible();

  await page.unrouteAll();
  await page.route(`${API}/configuration`, (route) => route.abort("connectionrefused"));
  await page.route(`${API}/browsers`, (route) => route.abort("connectionrefused"));
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: /start the local service at http:\/\/127\.0\.0\.1:8123/i }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect local service" })).toBeVisible();
});

test("persists only versioned nonsecret launch settings", async ({ page }) => {
  await connect(page);
  await page.getByLabel("Static windows per proxy").fill("2");
  await page.getByLabel("Rotating windows per proxy").fill("1");
  await page.getByLabel("Target URL").fill("https://example.com/job?token=signed-secret");
  await page.getByLabel("Rotation attempts").fill("9");

  const beforeReload = await page.evaluate(() => ({ ...localStorage }));
  expect(JSON.stringify(beforeReload)).not.toContain("signed-secret");
  await page.reload();

  await expect(page.getByLabel("Static windows per proxy")).toHaveValue("2");
  await expect(page.getByLabel("Rotating windows per proxy")).toHaveValue("1");
  await expect(page.getByLabel("Target URL")).toHaveValue("about:blank");
  await expect(page.getByLabel("Rotation attempts")).toHaveValue("9");
  const storage = await page.evaluate(() => ({ ...localStorage }));
  expect(Object.keys(storage)).toEqual(["proms.launch-settings.v1"]);
  expect(storage["proms.launch-settings.v1"]).toBe(
    JSON.stringify({
      version: 1,
      staticWindows: "2",
      rotatingWindows: "1",
      rotationAttempts: "9",
    }),
  );
  expect(JSON.stringify(storage)).not.toMatch(/proxy|password|token|secret/i);
});

test("rewrites legacy v1 settings without retaining its target URL", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "proms.launch-settings.v1",
      JSON.stringify({
        version: 1,
        staticWindows: "4",
        rotatingWindows: "2",
        targetUrl: "https://example.com/job?token=legacy-secret",
        rotationAttempts: "8",
      }),
    );
  });

  await page.goto("/");

  await expect(page.getByLabel("Static windows per proxy")).toHaveValue("4");
  await expect(page.getByLabel("Rotating windows per proxy")).toHaveValue("2");
  await expect(page.getByLabel("Target URL")).toHaveValue("about:blank");
  await expect(page.getByLabel("Rotation attempts")).toHaveValue("8");
  const stored = await page.evaluate(() => localStorage.getItem("proms.launch-settings.v1"));
  expect(stored).toBe(
    JSON.stringify({
      version: 1,
      staticWindows: "4",
      rotatingWindows: "2",
      rotationAttempts: "8",
    }),
  );
});

test("keeps key actions visible without horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Connect local service" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Launch windows" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close all" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await connect(page);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
