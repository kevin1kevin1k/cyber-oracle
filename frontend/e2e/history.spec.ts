import { expect, test } from "@playwright/test";

test("history route redirects to the single-page settings center", async ({ page }) => {
  await page.goto("/history");

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Messenger 設定中心" })).toBeVisible();
});

test("history detail route redirects to the single-page settings center", async ({ page }) => {
  await page.goto("/history/q-root-1");

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Messenger 設定中心" })).toBeVisible();
});
