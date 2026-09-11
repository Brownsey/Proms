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
  await page.goto("/control/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

test("connects automatically and explains the local-only boundary", async ({ page }) => {
  await mockConnectedApi(page);
  await page.goto("/control/");

  await expect(page).toHaveTitle("Proms | Local control");
  await expect(page.getByRole("heading", { level: 1, name: "Launch manifest" })).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh status" })).toBeVisible();
  await expect(page.getByText(/UI is served by the loopback service/i)).toBeVisible();
  await expect(page.getByText(/controls and proxy drafts stay on this PC/i)).toBeVisible();
  await expect(page.getByText(/existing proxy values are never displayed/i)).toBeVisible();
  await expect(page.getByText(/local network access/i)).toHaveCount(0);
  await expect(page.getByText(/Safari/i)).toHaveCount(0);
  await page.getByText("Local proxy files", { exact: true }).click();
  const staticDraft = page.getByLabel("Static proxies", { exact: true });
  const rotatingDraft = page.getByLabel("Rotating proxies", { exact: true });
  await staticDraft.fill("static-draft.test:8001");
  await rotatingDraft.fill("rotating-draft.test:9001");
  await expect(staticDraft).toHaveValue("static-draft.test:8001");
  await expect(rotatingDraft).toHaveValue("rotating-draft.test:9001");
  await expect(page.getByRole("button", { name: "Save static list" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Save rotating list" })).toBeEnabled();
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
  await page.goto("/control/");

  const connectButton = page.getByRole("button", { name: "Connecting…" });
  await expect(connectButton).toBeDisabled();
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "true");
  await expect.poll(() => requestCount).toBe(2);

  releaseRequests();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
});

test("offers retry after automatic connection failure", async ({ page }) => {
  let available = false;
  await page.route(`${API}/configuration`, (route) =>
    available
      ? route.fulfill({ json: { static_proxy_count: 4, rotating_proxy_count: 2 } })
      : route.abort("connectionrefused"),
  );
  await page.route(`${API}/browsers`, (route) =>
    available ? route.fulfill({ json: { active: 3 } }) : route.abort("connectionrefused"),
  );

  await page.goto("/control/");
  const retry = page.getByRole("button", { name: "Retry connection" });
  await expect(retry).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: `Start the local service at ${API}, then retry.` }),
  ).toBeVisible();

  available = true;
  await retry.click();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByText("3 active", { exact: true })).toBeVisible();
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
  await page.goto("/control/");

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

test("supports keyboard status refresh and form submission", async ({ page }) => {
  await mockConnectedApi(page);
  await page.goto("/control/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({ timeout: 15_000 });

  await page.keyboard.press("Tab");
  const refreshButton = page.getByRole("button", { name: "Refresh status" });
  await expect(refreshButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Status refreshed.", { exact: true })).toBeVisible();

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

test("saves static and rotating proxy drafts with exact payloads", async ({ page }) => {
  await connect(page);
  const payloads: unknown[] = [];
  await page.route(`${API}/configuration/proxies`, (route) => {
    const body = route.request().postDataJSON() as { mode: "static" | "rotating" };
    payloads.push(body);
    return route.fulfill({ json: { mode: body.mode, count: body.mode === "static" ? 2 : 1 } });
  });
  await page.getByText("Local proxy files", { exact: true }).click();

  await page.getByLabel("Static proxies", { exact: true }).fill("static-one.test:8001\nstatic-two.test:8002");
  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByText("Saved 2 static proxies.")).toBeVisible();
  await expect(page.getByLabel("Static proxies", { exact: true })).toBeEmpty();
  await expect(page.getByText("S / 2", { exact: true })).toBeVisible();

  await page.getByLabel("Rotating proxies", { exact: true }).fill("http://rotate-one.test:9001");
  await page.getByRole("button", { name: "Save rotating list" }).click();
  await expect(page.getByText("Saved 1 rotating proxy.")).toBeVisible();
  await expect(page.getByLabel("Rotating proxies", { exact: true })).toBeEmpty();
  await expect(page.getByText("R / 1", { exact: true })).toBeVisible();
  expect(payloads).toEqual([
    { mode: "static", proxies: "static-one.test:8001\nstatic-two.test:8002" },
    { mode: "rotating", proxies: "http://rotate-one.test:9001" },
  ]);
});

test("disables proxy mutations while a save is in flight", async ({ page }) => {
  await connect(page);
  let releaseSave: () => void = () => undefined;
  const saveReleased = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  let saveRequests = 0;
  await page.route(`${API}/configuration/proxies`, async (route) => {
    saveRequests += 1;
    await saveReleased;
    return route.fulfill({ json: { mode: "static", count: 1 } });
  });
  await page.getByText("Local proxy files", { exact: true }).click();
  await page.getByLabel("Static proxies", { exact: true }).fill("single.test:8001");

  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByRole("button", { name: "Saving static…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save rotating list" })).toBeDisabled();
  await expect.poll(() => saveRequests).toBe(1);
  releaseSave();

  await expect(page.getByText("Saved 1 static proxy.")).toBeVisible();
  expect(saveRequests).toBe(1);
});

test("retains drafts through save failures without reflecting credentials", async ({ page }) => {
  await connect(page);
  const draft = "http://tester:fake-secret@invalid.test:9000";
  let failure: "api" | "malformed" | "offline" = "api";
  await page.route(`${API}/configuration/proxies`, (route) => {
    if (failure === "api") {
      return route.fulfill({ status: 400, json: { detail: `Invalid proxy ${draft}` } });
    }
    if (failure === "malformed") {
      return route.fulfill({ json: { mode: "static", count: "1" } });
    }
    return route.abort("connectionrefused");
  });
  await page.getByText("Local proxy files", { exact: true }).click();
  const editor = page.getByLabel("Static proxies", { exact: true });
  await editor.fill(draft);

  await page.getByRole("button", { name: "Save static list" }).click();
  const rejected = page.getByRole("alert").filter({ hasText: "Static proxy list was not saved" });
  await expect(rejected).toBeVisible();
  await expect(rejected).not.toContainText("fake-secret");
  await expect(editor).toHaveValue(draft);

  failure = "malformed";
  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "unexpected save response" })).toBeVisible();
  await expect(editor).toHaveValue(draft);

  failure = "offline";
  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /start the local service/i })).toBeVisible();
  await expect(editor).toHaveValue(draft);
  await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
});

test("confirms clearing a comment-only proxy list", async ({ page }) => {
  await connect(page);
  let payload: unknown;
  let saveCalls = 0;
  await page.route(`${API}/configuration/proxies`, (route) => {
    saveCalls += 1;
    payload = route.request().postDataJSON();
    return route.fulfill({ json: { mode: "static", count: 0 } });
  });
  await page.getByText("Local proxy files", { exact: true }).click();
  const editor = page.getByLabel("Static proxies", { exact: true });
  await editor.fill("# clear this list");

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Save static list" }).click();
  expect(saveCalls).toBe(0);
  await expect(editor).toHaveValue("# clear this list");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByText("Cleared static proxies.")).toBeVisible();
  await expect(editor).toBeEmpty();
  await expect(page.getByText("S / 0", { exact: true })).toBeVisible();
  expect(saveCalls).toBe(1);
  expect(payload).toEqual({ mode: "static", proxies: "# clear this list", confirm_clear: true });
});

test("does not persist or restore proxy drafts", async ({ page }) => {
  await connect(page);
  await page.getByText("Local proxy files", { exact: true }).click();
  await page.getByLabel("Static proxies", { exact: true }).fill("draft-only.test:8001");
  await page.getByLabel("Rotating proxies", { exact: true }).fill("rotate-draft.test:9001");
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toMatch(/draft-only|rotate-draft/);

  await page.reload();
  await page.getByText("Local proxy files", { exact: true }).click();
  await expect(page.getByLabel("Static proxies", { exact: true })).toBeEmpty();
  await expect(page.getByLabel("Rotating proxies", { exact: true })).toBeEmpty();
});

test("warns before unloading only while proxy drafts remain unsaved", async ({ page }) => {
  await connect(page);
  await page.route(`${API}/configuration/proxies`, (route) => {
    const { mode } = route.request().postDataJSON() as { mode: "static" | "rotating" };
    return route.fulfill({ json: { mode, count: 1 } });
  });
  await page.getByText("Local proxy files", { exact: true }).click();
  const staticEditor = page.getByLabel("Static proxies", { exact: true });
  const rotatingEditor = page.getByLabel("Rotating proxies", { exact: true });
  const unloadPrevented = () =>
    page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    });

  expect(await unloadPrevented()).toBe(false);
  await staticEditor.fill("unsaved-static.test:8001");
  await rotatingEditor.fill("unsaved-rotating.test:9001");
  await expect.poll(unloadPrevented).toBe(true);

  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(staticEditor).toBeEmpty();
  expect(await unloadPrevented()).toBe(true);

  await page.getByRole("button", { name: "Save rotating list" }).click();
  await expect(rotatingEditor).toBeEmpty();
  await expect.poll(unloadPrevented).toBe(false);
});

test("saves a proxy draft with the keyboard", async ({ page }) => {
  await connect(page);
  await page.route(`${API}/configuration/proxies`, (route) =>
    route.fulfill({ json: { mode: "static", count: 1 } }),
  );
  await page.getByText("Local proxy files", { exact: true }).click();
  await page.getByLabel("Static proxies", { exact: true }).fill("keyboard.test:8001");
  const save = page.getByRole("button", { name: "Save static list" });
  await save.focus();
  await expect(save).toBeFocused();
  await save.press("Enter");

  await expect(page.getByText("Saved 1 static proxy.")).toBeVisible();
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
  await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
});

test("persists only versioned nonsecret launch settings", async ({ page }) => {
  await connect(page);
  await page.getByLabel("Static windows per proxy").fill("2");
  await page.getByLabel("Rotating windows per proxy").fill("1");
  await page.getByLabel("Target URL").fill("https://example.com/job?token=signed-secret");
  await page.getByLabel("Rotation attempts").fill("9");

  const expectedStoredSettings = JSON.stringify({
    version: 1,
    staticWindows: "2",
    rotatingWindows: "1",
    rotationAttempts: "9",
  });
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("proms.launch-settings.v1")))
    .toBe(expectedStoredSettings);
  const beforeReload = await page.evaluate(() => ({ ...localStorage }));
  expect(JSON.stringify(beforeReload)).not.toContain("signed-secret");
  await page.reload();

  await expect(page.getByLabel("Static windows per proxy")).toHaveValue("2");
  await expect(page.getByLabel("Rotating windows per proxy")).toHaveValue("1");
  await expect(page.getByLabel("Target URL")).toHaveValue("about:blank");
  await expect(page.getByLabel("Rotation attempts")).toHaveValue("9");
  const storage = await page.evaluate(() => ({ ...localStorage }));
  expect(Object.keys(storage)).toEqual(["proms.launch-settings.v1"]);
  expect(storage["proms.launch-settings.v1"]).toBe(expectedStoredSettings);
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

  await page.goto("/control/");

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
  await mockConnectedApi(page);
  await page.goto("/control/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByText("Local proxy files", { exact: true }).click();

  await expect(page.getByRole("button", { name: "Refresh status" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Launch windows" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close all" })).toBeVisible();
  await expect(page.getByLabel("Static proxies", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Rotating proxies", { exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await connect(page);
  await page.getByText("Local proxy files", { exact: true }).click();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
