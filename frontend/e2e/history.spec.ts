import { expect, test } from "@playwright/test";

async function seedMessengerSession(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "messenger-session-token");
    window.localStorage.setItem("elin_auth_user_label", "Messenger 已連結");
    window.localStorage.setItem("elin_auth_user_id", "user-history-1");
  });
}

test("history shows messenger session required when unauthenticated", async ({ page }) => {
  await page.goto("/history");

  await expect(page.getByRole("heading", { name: "歷史問答" })).toBeVisible();
  await expect(page.getByText("目前這個頁面只支援從 Messenger WebView 進入。")).toBeVisible();
});

test("history loads list and detail with existing messenger session", async ({ page }) => {
  await seedMessengerSession(page);
  await page.route("**/api/v1/history/questions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            question_id: "q-root-1",
            question_text: "主問題",
            answer_preview: "摘要內容",
            source: "rag",
            charged_credits: 1,
            created_at: "2026-03-22T10:00:00Z",
          },
        ],
        total: 1,
      }),
    });
  });
  await page.route("**/api/v1/history/questions/q-root-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        root: {
          question_id: "q-root-1",
          question_text: "主問題",
          answer_text: "完整回答",
          source: "rag",
          layer_percentages: [
            { label: "主層", pct: 70 },
            { label: "輔層", pct: 20 },
            { label: "參照層", pct: 10 },
          ],
          charged_credits: 1,
          request_id: "req-history-1",
          created_at: "2026-03-22T10:00:00Z",
          children: [],
        },
        transactions: [
          {
            id: "tx-1",
            action: "capture",
            amount: -1,
            reason_code: "ASK_SUCCEEDED",
            question_id: "q-root-1",
            request_id: "req-history-1",
            created_at: "2026-03-22T10:00:01Z",
          },
        ],
      }),
    });
  });

  await page.goto("/history");

  await expect(page.getByText("主問題")).toBeVisible();
  await page.getByRole("link", { name: "查看詳情" }).click();

  await expect(page).toHaveURL(/\/history\/q-root-1$/);
  await expect(page.getByText("完整回答")).toBeVisible();
  await expect(page.getByText("ASK_SUCCEEDED")).toBeVisible();
});
