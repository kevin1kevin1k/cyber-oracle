import { expect, test } from "@playwright/test";

test("wallet route redirects to the single-page settings center", async ({ page }) => {
  await page.goto("/wallet");

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Messenger 設定中心" })).toBeVisible();
});
