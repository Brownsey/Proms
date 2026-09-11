import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PROMPT = [
  "Set up https://github.com/Brownsey/Proms on this Windows PC.",
  "Locate the existing checkout; if absent, run: git clone https://github.com/Brownsey/Proms.git",
  "Enter the repository root.",
  "If the checkout existed, preserve local changes, then run: git pull --ff-only",
  "Read AGENTS.md before doing substantive work.",
  "Never read or print proxy files or proxy values.",
  "Run the full idempotent setup command: powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1",
  "Start uv run proms persistently.",
  "Verify GET http://127.0.0.1:8000/health.",
  "Read only the numeric counts from GET http://127.0.0.1:8000/configuration.",
  "Open http://127.0.0.1:8000/control/ and report the result.",
].join("\n");

test("presents the public page as an installation handoff without local controls", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: /run proms on this pc/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /github repository/i })).toHaveAttribute(
    "href",
    "https://github.com/Brownsey/Proms",
  );
  await expect(page.getByRole("link", { name: /setup guide/i })).toHaveAttribute(
    "href",
    "https://github.com/Brownsey/Proms#setup",
  );
  await expect(page.getByText(/controls and proxy values stay on this computer/i)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Codex setup prompt" })).toHaveValue(PROMPT);
  await expect(page.getByRole("textbox", { name: "Codex setup prompt" })).toHaveAttribute("readonly", "");
  await expect(page.getByLabel("Static proxies", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Launch windows" })).toHaveCount(0);
});

test("copies the complete Codex prompt with keyboard feedback", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");

  const copy = page.getByRole("button", { name: "Copy Codex prompt" });
  await copy.focus();
  await expect(copy).toBeFocused();
  await copy.press("Enter");

  await expect(page.getByText("Copied", { exact: true })).toBeVisible();
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe(PROMPT);
});

test("offers manual selection when clipboard access fails", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: () => Promise.reject(new Error("denied")) },
    });
  });

  await page.getByRole("button", { name: "Copy Codex prompt" }).click();

  await expect(page.getByText(/copy failed.*copy it manually/i)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Codex setup prompt" })).toBeFocused();
});

test("keeps the installation handoff usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Copy Codex prompt" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Codex setup prompt" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
