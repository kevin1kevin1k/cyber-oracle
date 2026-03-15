import { expect, test } from "@playwright/test";

test("messenger link page redirects to login and completes linking after login", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-messenger-link",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/messenger/link", async (route) => {
    const auth = route.request().headers()["authorization"];
    expect(auth).toBe("Bearer token-messenger-link");
    expect(JSON.parse(route.request().postData() ?? "{}")).toEqual({ token: "link-token-123" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "linked",
        user_id: "u-messenger",
        psid: "psid-1",
        page_id: "page-1",
      }),
    });
  });

  await page.goto("/messenger/link?token=link-token-123");
  await expect(page).toHaveURL(/\/login\?next=%2Fmessenger%2Flink%3Ftoken%3Dlink-token-123$/);

  await page.getByLabel("Email").fill("messenger@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();

  await expect(page).toHaveURL("/messenger/link?token=link-token-123");
  await expect(page.getByText("綁定完成，請回 Messenger 繼續提問。")).toBeVisible();
  await expect(page.getByRole("link", { name: "前往錢包" })).toBeVisible();
});


test("messenger link page shows verification guidance for unverified user", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-messenger-unverified",
        token_type: "bearer",
        email_verified: false,
      }),
    });
  });

  await page.goto("/messenger/link?token=link-token-456");
  await expect(page).toHaveURL(/\/login\?next=%2Fmessenger%2Flink%3Ftoken%3Dlink-token-456$/);

  await page.getByLabel("Email").fill("unverified@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();

  await expect(page).toHaveURL("/messenger/link?token=link-token-456");
  await expect(page.getByText("請先完成 Email 驗證後，再回到這裡完成 Messenger 綁定。")).toBeVisible();
});
