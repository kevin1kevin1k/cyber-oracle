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
  await expect(page.getByRole("button", { name: "送出問題" })).toBeDisabled();
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

test("authenticated messenger session can ask and logout", async ({ page }) => {
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
  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "這是 Messenger session 的測試回答。",
        source: "rag",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-home-1",
        followup_options: [],
      }),
    });
  });
  await page.route("**/api/v1/auth/logout", async (route) => {
    logoutCalls += 1;
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto("/");

  await expect(page.getByText("目前已連結 Messenger，可直接提問。")).toBeVisible();
  await page.getByLabel("問題內容").fill("今天適合開始公開測試嗎？");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("這是 Messenger session 的測試回答。")).toBeVisible();

  await page.getByTestId("account-menu-trigger").click();
  await expect(page.getByTestId("account-menu")).toContainText("Messenger 已連結");
  await page.getByRole("menuitem", { name: "登出" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(logoutCalls).toBe(1);
});
