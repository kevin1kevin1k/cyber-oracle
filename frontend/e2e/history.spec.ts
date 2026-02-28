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
  await expect(page.getByText("來源：")).toHaveCount(0);
  await expect(page.getByText("扣點：1 點")).toBeVisible();

  await page.getByRole("button", { name: "載入更多" }).click();
  await expect(page.getByText("問題：第二題")).toBeVisible();
  await expect(page.getByText("來源：")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看詳情" }).first()).toBeVisible();
});

test("history detail page renders question tree and transactions", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-history-detail",
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
        total: 1,
        items: [
          {
            question_id: "q-root",
            question_text: "主問題",
            answer_preview: "主問題摘要",
            source: "mock",
            charged_credits: 1,
            created_at: "2026-02-20T10:00:00Z",
          },
        ],
      }),
    });
  });

  await page.route("**/api/v1/history/questions/q-root", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        root: {
          question_id: "q-root",
          question_text: "主問題",
          answer_text: "主回答完整內容",
          source: "mock",
          layer_percentages: [
            { label: "主層", pct: 70 },
            { label: "輔層", pct: 20 },
            { label: "參照層", pct: 10 },
          ],
          charged_credits: 1,
          request_id: "req-root",
          created_at: "2026-02-20T10:00:00Z",
          children: [
            {
              question_id: "q-child",
              question_text: "延伸問題",
              answer_text: "延伸回答完整內容",
              source: "openai",
              layer_percentages: [
                { label: "主層", pct: 60 },
                { label: "輔層", pct: 30 },
                { label: "參照層", pct: 10 },
              ],
              charged_credits: 1,
              request_id: "req-child",
              created_at: "2026-02-20T10:01:00Z",
              children: [],
            },
          ],
        },
        transactions: [
          {
            id: "tx-1",
            action: "capture",
            amount: -1,
            reason_code: "ASK_CAPTURED",
            question_id: "q-root",
            request_id: "req-root",
            created_at: "2026-02-20T10:00:00Z",
          },
          {
            id: "tx-2",
            action: "refund",
            amount: 1,
            reason_code: "ASK_REFUNDED",
            question_id: "q-child",
            request_id: "req-child",
            created_at: "2026-02-20T10:02:00Z",
          },
        ],
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("history-detail@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/history");
  await page.getByRole("link", { name: "查看詳情" }).first().click();
  await expect(page).toHaveURL("/history/q-root");
  await expect(page.getByText("主回答完整內容")).toBeVisible();
  await expect(page.getByText("延伸回答完整內容")).toBeVisible();
  await expect(page.getByText("關聯交易")).toBeVisible();
  await expect(page.getByText("類型：扣點")).toBeVisible();
  await expect(page.getByText("類型：回補")).toBeVisible();
  await expect(page.getByText("來源：")).toHaveCount(0);
  await expect(page.getByText("Request ID：")).toHaveCount(0);
  await expect(page.getByText("三層比例：")).toHaveCount(0);
});

test("history detail redirects unauthenticated user to login with next", async ({ page }) => {
  await page.goto("/history/q-root");
  await expect(page).toHaveURL(/\/login\?next=%2Fhistory%2Fq-root$/);
});

test("history detail child url auto-redirects to root url", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-history-child-redirect",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/history/questions/q-child", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        root: {
          question_id: "q-root",
          question_text: "主問題",
          answer_text: "主回答",
          source: "mock",
          layer_percentages: [
            { label: "主層", pct: 70 },
            { label: "輔層", pct: 20 },
            { label: "參照層", pct: 10 },
          ],
          charged_credits: 1,
          request_id: "req-root",
          created_at: "2026-02-20T10:00:00Z",
          children: [
            {
              question_id: "q-child",
              question_text: "子問題",
              answer_text: "子回答",
              source: "openai",
              layer_percentages: [
                { label: "主層", pct: 60 },
                { label: "輔層", pct: 30 },
                { label: "參照層", pct: 10 },
              ],
              charged_credits: 1,
              request_id: "req-child",
              created_at: "2026-02-20T10:01:00Z",
              children: [],
            },
          ],
        },
        transactions: [],
      }),
    });
  });

  await page.route("**/api/v1/history/questions/q-root", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        root: {
          question_id: "q-root",
          question_text: "主問題",
          answer_text: "主回答",
          source: "mock",
          layer_percentages: [
            { label: "主層", pct: 70 },
            { label: "輔層", pct: 20 },
            { label: "參照層", pct: 10 },
          ],
          charged_credits: 1,
          request_id: "req-root",
          created_at: "2026-02-20T10:00:00Z",
          children: [
            {
              question_id: "q-child",
              question_text: "子問題",
              answer_text: "子回答",
              source: "openai",
              layer_percentages: [
                { label: "主層", pct: 60 },
                { label: "輔層", pct: 30 },
                { label: "參照層", pct: 10 },
              ],
              charged_credits: 1,
              request_id: "req-child",
              created_at: "2026-02-20T10:01:00Z",
              children: [],
            },
          ],
        },
        transactions: [],
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("history-child-redirect@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/history/q-child");
  await expect(page).toHaveURL("/history/q-root");
  await expect(page.getByText("主回答")).toBeVisible();
  await expect(page.getByText("子回答")).toBeVisible();
});
