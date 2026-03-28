import { expect, test } from "@playwright/test";

async function seedMessengerSession(
  page: import("@playwright/test").Page,
  label = "Messenger 已連結"
) {
  await page.addInitScript((sessionLabel) => {
    window.localStorage.setItem("elin_access_token", "messenger-session-token");
    window.localStorage.setItem("elin_auth_user_label", sessionLabel);
    window.localStorage.setItem("elin_auth_user_id", "user-messenger-1");
  }, label);
}

test("home shows messenger-only entry message when unauthenticated", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("這個頁面僅支援從 Messenger WebView 進入。")).toBeVisible();
  await expect(page.getByText("這裡是 Messenger WebView 的配套首頁")).toBeVisible();
});

test("legacy auth pages show disabled messenger-only notice", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登入已停用" })).toBeVisible();

  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "註冊已停用" })).toBeVisible();

  await page.goto("/verify-email");
  await expect(page.getByRole("heading", { name: "Email 驗證已停用" })).toBeVisible();

  await page.goto("/forgot-password");
  await expect(page.getByRole("heading", { name: "密碼重設已停用" })).toBeVisible();

  await page.goto("/reset-password");
  await expect(page.getByRole("heading", { name: "密碼重設已停用" })).toBeVisible();
});

test("authenticated messenger session sees home hub and can logout", async ({ page }) => {
  await seedMessengerSession(page);
  let logoutCalls = 0;
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        balance: 50,
        updated_at: "2026-03-22T10:00:00Z",
        payments_enabled: false,
      }),
    });
  });
  await page.route("**/api/v1/me/profile", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: "王小明",
        mother_name: "林淑芬",
        is_complete: true,
      }),
    });
  });
  await page.route("**/api/v1/auth/logout", async (route) => {
    logoutCalls += 1;
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/");

  await expect(page.getByText("目前已連結 Messenger，可回 Messenger 直接提問。")).toBeVisible();
  await expect(page.getByRole("link", { name: "設定" })).toBeVisible();
  await expect(page.getByRole("link", { name: "點數錢包" }).nth(1)).toBeVisible();
  await expect(page.getByRole("link", { name: "歷史問答" }).nth(1)).toBeVisible();

  await page.getByTestId("account-menu-trigger").click();
  await expect(page.getByTestId("account-menu")).toContainText("Messenger 已連結");
  await page.getByRole("menuitem", { name: "登出" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(logoutCalls).toBe(1);
});
