import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8123";

async function connect(page: Page, active = 3) {
  await page.route(`${API}/configuration`, (route) => route.fulfill({ json: { proxy_count: 6 } }));
  await page.route(`${API}/browsers`, (route) => route.request().method() === "GET" ? route.fulfill({ json: { active } }) : route.fallback());
  await page.goto("/control/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({ timeout: 15_000 });
}

test("labels the browser count as unavailable while status is loading", async ({ page }) => {
  let release: () => void = () => undefined;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`${API}/**`, async (route) => {
    await pending;
    return route.request().url().endsWith("/configuration")
      ? route.fulfill({ json: { proxy_count: 6 } })
      : route.fulfill({ json: { active: 3 } });
  });
  await page.goto("/control/");

  await expect(page.locator(".orbit")).toHaveAttribute(
    "aria-label",
    "Active browser windows count unavailable",
  );
  release();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
});

test("connects and exposes one confidential proxy list", async ({ page }) => {
  await connect(page);
  await expect(page.getByText("Proxies", { exact: true }).locator("..").locator("dd")).toHaveText("6");
  await expect(page.getByText(/controls and proxy drafts stay on this PC/i)).toBeVisible();
  await expect(
    page.getByText(/each window starts with its own cookies and site storage/i),
  ).toBeVisible();
  await page.getByText("Local proxy file", { exact: true }).click();
  await expect(page.getByText(/fixed proxies and sticky-session proxy credentials are accepted/i)).toBeVisible();
  await expect(page.getByLabel("Proxies", { exact: true })).toBeEditable();
  await expect(page.getByText(/rotating/i)).toHaveCount(0);
});

test("offers retry after connection failure", async ({ page }) => {
  let available = false;
  await page.route(`${API}/configuration`, (route) => available ? route.fulfill({ json: { proxy_count: 6 } }) : route.abort("connectionrefused"));
  await page.route(`${API}/browsers`, (route) => available ? route.fulfill({ json: { active: 3 } }) : route.abort("connectionrefused"));
  await page.goto("/control/");
  const retry = page.getByRole("button", { name: "Retry connection" });
  await expect(retry).toBeVisible();
  await expect(retry).toBeEnabled();
  available = true;
  await retry.focus();
  await retry.press("Enter");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
});

test("lets the user replace an invalid proxy list", async ({ page }) => {
  await page.route(`${API}/configuration`, (route) => route.fulfill({
    status: 400,
    json: { detail: "Invalid proxy on line 1." },
  }));
  await page.route(`${API}/browsers`, (route) => route.fulfill({ json: { active: 0 } }));
  await page.route(`${API}/configuration/proxies`, (route) => route.fulfill({ json: { count: 1 } }));
  await page.goto("/control/");
  await expect(page.getByRole("alert")).toContainText("Invalid proxy on line 1.");
  await page.getByText("Local proxy file", { exact: true }).click();
  await page.getByLabel("Proxies", { exact: true }).fill("one.test:8001");
  await page.getByRole("button", { name: "Save proxy list" }).click();
  await expect(page.getByText("Saved 1 proxy.")).toBeVisible();
});

test("launches with an optional total cap", async ({ page }) => {
  await connect(page, 2);
  let body: unknown;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    body = route.request().postDataJSON();
    return route.fulfill({ json: { launched: 50, active: 52 } });
  });
  await page.getByLabel("Windows per proxy").fill("2");
  await page.getByLabel("Maximum windows").fill("50");
  await page.getByLabel("Target URL").fill("https://example.com/path");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 50 windows. 52 active.")).toBeVisible();
  expect(body).toEqual({ windows_per_proxy: 2, max_windows: 50, url: "https://example.com/path" });
});

test("launches with temporary Chrome profiles and remembers the mode", async ({ page }) => {
  await connect(page);
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    expect(route.request().postDataJSON()).toMatchObject({ chrome_profiles: true });
    return route.fulfill({ json: { launched: 6, active: 9 } });
  });
  const mode = page.getByLabel("Launch mode");
  await mode.selectOption({ label: "Google Chrome (temporary profiles)" });
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 6 windows. 9 active.")).toBeVisible();
  await page.reload();
  await expect(mode).toHaveValue("chrome");
});

test("launches eight Chrome windows directly with no saved proxies", async ({ page }) => {
  await page.route(`${API}/configuration`, (route) => route.fulfill({ json: { proxy_count: 0 } }));
  let body: unknown;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: { active: 0 } });
    body = route.request().postDataJSON();
    return route.fulfill({ json: { launched: 8, active: 8 } });
  });
  await page.goto("/control/");
  await page.getByLabel("Launch mode").selectOption("chrome");
  const network = page.getByLabel("Network connection");
  await network.selectOption("direct");
  await page.getByLabel("Window count").fill("8");
  await expect(page.getByLabel("Windows per proxy")).toHaveCount(0);
  await page.getByLabel("Target URL").fill("about:blank");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 8 windows. 8 active.")).toBeVisible();
  expect(body).toEqual({ direct_windows: 8, chrome_profiles: true, url: "about:blank" });
  await page.reload();
  await expect(network).toHaveValue("direct");
  await expect(page.getByLabel("Window count")).toHaveValue("8");
});

test("allows launches when browser storage is unavailable", async ({ page }) => {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() { throw new DOMException("Storage disabled", "SecurityError"); },
    });
  });
  await connect(page);
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({ json: { launched: 6, active: 9 } });
  });
  await page.getByLabel("Launch mode").selectOption("chrome");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 6 windows. 9 active.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("offers cleanup when a failed launch leaves a window open", async ({ page }) => {
  await connect(page, 0);
  let active = 0;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: { active } });
    active = 1;
    return route.fulfill({
      status: 400,
      json: { detail: "Unable to load the target URL. 1 browser(s) remain active after cleanup." },
    });
  });
  const close = page.getByRole("button", { name: "Close all" });
  await expect(close).toBeDisabled();
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByRole("alert")).toContainText("remain active");
  await expect(close).toBeEnabled();
});

test("omits the total cap when blank and validates both counts", async ({ page }) => {
  await connect(page);
  await expect(page.getByLabel("Target URL")).toHaveValue("https://whatismyipaddress.com/");
  let body: unknown;
  await page.route(`${API}/browsers`, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    body = route.request().postDataJSON();
    return route.fulfill({ json: { launched: 6, active: 9 } });
  });
  await page.getByRole("button", { name: "Launch windows" }).click();
  expect(body).toEqual({ windows_per_proxy: 1, url: "https://whatismyipaddress.com/" });
  await page.getByLabel("Windows per proxy").fill("0");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.locator("p[role=alert]")).toContainText("Windows per proxy must be 1 or greater");
  await page.getByLabel("Windows per proxy").fill("1");
  await page.getByLabel("Maximum windows").fill("0");
  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.locator("p[role=alert]")).toContainText("Maximum windows must be 1 or greater");
});

test("saves one proxy draft without persisting it", async ({ page }) => {
  await connect(page);
  let body: unknown;
  await page.route(`${API}/configuration/proxies`, (route) => { body = route.request().postDataJSON(); return route.fulfill({ json: { count: 2 } }); });
  await page.getByText("Local proxy file", { exact: true }).click();
  const editor = page.getByLabel("Proxies", { exact: true });
  await editor.fill("one.test:8001\ntwo.test:8002");
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain("one.test");
  await page.getByRole("button", { name: "Save proxy list" }).click();
  await expect(page.getByText("Saved 2 proxies.")).toBeVisible();
  await expect(editor).toBeEmpty();
  expect(body).toEqual({ proxies: "one.test:8001\ntwo.test:8002" });
});

test("retains draft after a secret-safe failure", async ({ page }) => {
  await connect(page);
  await page.route(`${API}/configuration/proxies`, (route) => route.fulfill({ status: 400, json: { detail: "invalid secret-marker" } }));
  await page.getByText("Local proxy file", { exact: true }).click();
  const editor = page.getByLabel("Proxies", { exact: true });
  await editor.fill("http://user:secret-marker@bad.test:8001");
  await page.getByRole("button", { name: "Save proxy list" }).click();
  await expect(page.locator("p[role=alert]")).not.toContainText("secret-marker");
  await expect(editor).toHaveValue("http://user:secret-marker@bad.test:8001");
});

test("confirms clearing", async ({ page }) => {
  await connect(page);
  let body: unknown;
  await page.route(`${API}/configuration/proxies`, (route) => { body = route.request().postDataJSON(); return route.fulfill({ json: { count: 0 } }); });
  await page.getByText("Local proxy file", { exact: true }).click();
  await page.getByLabel("Proxies", { exact: true }).fill("# clear");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save proxy list" }).click();
  await expect(page.getByText("Cleared proxies.")).toBeVisible();
  expect(body).toEqual({ proxies: "# clear", confirm_clear: true });
});

test("persists only nonsecret launch settings", async ({ page }) => {
  await connect(page);
  await page.getByLabel("Windows per proxy").fill("2");
  await page.getByLabel("Maximum windows").fill("50");
  await page.getByLabel("Target URL").fill("https://example.com/?token=secret");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("proms.launch-settings.v2"))).toBe(JSON.stringify({ version: 2, windowsPerProxy: "2", maxWindows: "50" }));
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain("token");
  await page.reload();
  await expect(page.getByLabel("Windows per proxy")).toHaveValue("2");
  await expect(page.getByLabel("Maximum windows")).toHaveValue("50");
  await expect(page.getByLabel("Target URL")).toHaveValue("https://whatismyipaddress.com/");
});

test("removes legacy settings without retaining their secrets", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("proms.launch-settings.v1", JSON.stringify({
      version: 1,
      staticWindows: "4",
      rotatingWindows: "2",
      rotationAttempts: "8",
      targetUrl: "https://example.com/?token=legacy-secret",
      proxyDraft: "http://user:legacy-password@proxy.test:8001",
    }));
  });
  await connect(page);

  await expect(page.getByLabel("Windows per proxy")).toHaveValue("4");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("proms.launch-settings.v1"))).toBeNull();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("proms.launch-settings.v2"))).toBe(
    JSON.stringify({ version: 2, windowsPerProxy: "4", maxWindows: "" }),
  );
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toMatch(/legacy-secret|legacy-password|targetUrl|proxyDraft/);
});

test("is responsive and accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await connect(page);
  await page.getByText("Local proxy file", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Launch windows" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
