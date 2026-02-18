import { expect, test } from "@playwright/test";

test("history redirects unauthenticated user to login with next", async ({ page }) => {
  await page.goto("/history");
  await expect(page).toHaveURL(/\/login\?next=%2Fhistory$/);
});

test("history loads items and supports load more", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-history",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/history/questions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 22,
        items: [
          {
            question_id: "q-1",
            question_text: "第一題",
            answer_preview: "第一題摘要",
            source: "mock",
            charged_credits: 1,
            created_at: "2026-02-18T10:00:00Z",
          },
        ],
      }),
    });
  });

  await page.route("**/api/v1/history/questions?limit=20&offset=1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 22,
        items: [
          {
            question_id: "q-2",
            question_text: "第二題",
            answer_preview: "第二題摘要",
            source: "openai",
            charged_credits: 1,
            created_at: "2026-02-18T09:00:00Z",
          },
        ],
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("history@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/history");
  await expect(page.getByText("問題：第一題")).toBeVisible();
  await expect(page.getByText("來源：Mock")).toBeVisible();
  await expect(page.getByText("扣點：1 點")).toBeVisible();

  await page.getByRole("button", { name: "載入更多" }).click();
  await expect(page.getByText("問題：第二題")).toBeVisible();
  await expect(page.getByText("來源：OPENAI")).toBeVisible();
});
