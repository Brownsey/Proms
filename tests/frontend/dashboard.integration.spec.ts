import { expect, test } from "@playwright/test";

test("controls the isolated FastAPI browser service end to end", async ({ page }) => {
  await page.goto("/control/");
  await expect(page.getByText(/UI is served by the loopback service/i)).toBeVisible();
  await expect(page.getByText(/controls and proxy drafts stay on this PC/i)).toBeVisible();
  await expect(page.getByText(/existing proxy values are never displayed/i)).toBeVisible();

  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByText("Static proxies", { exact: true }).locator("..").locator("dd")).toHaveText("1");
  await expect(page.getByText("Rotating proxies", { exact: true }).locator("..").locator("dd")).toHaveText("0");
  await expect(page.getByText("Windows", { exact: true }).locator("..").locator("dd")).toHaveText("0 active");

  await page.getByText("Local proxy files", { exact: true }).click();
  await page.getByLabel("Static proxies", { exact: true }).fill("first.test:9001\nsecond.test:9002");
  await page.getByRole("button", { name: "Save static list" }).click();
  await expect(page.getByText("Saved 2 static proxies.")).toBeVisible();
  await expect(page.getByText("S / 2", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 2 windows. 2 active.")).toBeVisible();
  await expect(page.getByText("2 active", { exact: true })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Close all" }).click();
  await expect(page.getByText("Closed 2 windows.")).toBeVisible();
  await expect(page.getByText("0 active", { exact: true })).toBeVisible();
});
