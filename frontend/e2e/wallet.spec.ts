import { expect, test } from "@playwright/test";

async function seedMessengerSession(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "messenger-session-token");
    window.localStorage.setItem("elin_auth_user_label", "Messenger 已連結");
    window.localStorage.setItem("elin_auth_user_id", "user-wallet-1");
  });
}

test("wallet shows messenger session required when unauthenticated", async ({ page }) => {
  await page.goto("/wallet");

  await expect(page.getByRole("heading", { name: "點數錢包" })).toBeVisible();
  await expect(page.getByText("目前這個頁面只支援從 Messenger WebView 進入。")).toBeVisible();
  await expect(
    page.getByText("請回聊天室點擊「前往購點」；系統會再發一顆可直接開啟點數錢包的按鈕。")
  ).toBeVisible();
});

test("wallet shows readonly launch mode when payments are disabled", async ({ page }) => {
  await seedMessengerSession(page);
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        balance: 12,
        updated_at: "2026-03-22T10:00:00Z",
        payments_enabled: false,
      }),
    });
  });
  await page.route("**/api/v1/credits/transactions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "tx-launch-1",
            action: "grant",
            amount: 50,
            reason_code: "MESSENGER_LINK_BETA_GRANT",
            request_id: "req-launch-1",
            question_id: null,
            order_id: null,
            created_at: "2026-03-22T10:00:01Z",
          },
        ],
        total: 1,
      }),
    });
  });

  await page.goto("/wallet?from=messenger-insufficient-credit");

  await expect(page.getByText("Messenger 體驗版提醒")).toBeVisible();
  await expect(page.getByText("目前為體驗版，暫未開放購點。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "體驗版說明" })).toBeVisible();
  await expect(page.getByText("系統發放")).toBeVisible();
  await expect(page.getByRole("button", { name: /購買/ })).toHaveCount(0);
});
