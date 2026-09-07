import { expect, test } from "@playwright/test";

test("controls the isolated FastAPI browser service end to end", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/only contacts http:\/\/127\.0\.0\.1:8123/i)).toBeVisible();

  await page.getByRole("button", { name: "Connect local service" }).click();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(page.getByText("1", { exact: true })).toBeVisible();
  await expect(page.getByText("R / 0", { exact: true })).toBeVisible();
  await expect(page.getByText("0 active", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Launch windows" }).click();
  await expect(page.getByText("Launched 1 windows. 1 active.")).toBeVisible();
  await expect(page.getByText("1 active", { exact: true })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Close all" }).click();
  await expect(page.getByText("Closed 1 windows.")).toBeVisible();
  await expect(page.getByText("0 active", { exact: true })).toBeVisible();
});
