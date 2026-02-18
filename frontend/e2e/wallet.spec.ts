import { expect, test } from "@playwright/test";

async function loginVerifiedUser(page: import("@playwright/test").Page, email = "wallet@example.com") {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-wallet",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
}

test("wallet page loads balance and transactions", async ({ page }) => {
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 4, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  await page.route("**/api/v1/credits/transactions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "tx-1",
            action: "purchase",
            amount: 3,
            reason_code: "ORDER_PAID",
            request_id: "req-1",
            question_id: null,
            order_id: "order-1",
            created_at: "2026-02-17T12:00:00Z",
          },
        ],
        total: 1,
      }),
    });
  });

  await loginVerifiedUser(page);
  await page.goto("/wallet");

  await expect(page.getByText("目前餘額：4 點")).toBeVisible();
  await expect(page.getByText("購點入帳 +3 點")).toBeVisible();
});

test("wallet purchase updates balance and transactions", async ({ page }) => {
  let balanceCall = 0;
  await page.route("**/api/v1/credits/balance", async (route) => {
    balanceCall += 1;
    const balance = balanceCall >= 2 ? 3 : 0;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  let txCall = 0;
  await page.route("**/api/v1/credits/transactions?limit=20&offset=0", async (route) => {
    txCall += 1;
    const payload =
      txCall >= 2
        ? {
            items: [
              {
                id: "tx-purchase",
                action: "purchase",
                amount: 3,
                reason_code: "ORDER_PAID",
                request_id: "req-purchase",
                question_id: null,
                order_id: "order-3",
                created_at: "2026-02-17T12:01:00Z",
              },
            ],
            total: 1,
          }
        : { items: [], total: 0 };

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  await page.route("**/api/v1/orders", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    expect(body.package_size).toBe(3);
    expect(body.idempotency_key).toBeTruthy();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "order-3",
        user_id: "u-1",
        package_size: 3,
        amount_twd: 358,
        status: "pending",
        idempotency_key: body.idempotency_key,
        created_at: "2026-02-17T12:01:00Z",
        paid_at: null,
      }),
    });
  });

  await page.route("**/api/v1/orders/order-3/simulate-paid", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        order: {
          id: "order-3",
          user_id: "u-1",
          package_size: 3,
          amount_twd: 358,
          status: "paid",
          idempotency_key: "k-order-3",
          created_at: "2026-02-17T12:01:00Z",
          paid_at: "2026-02-17T12:01:05Z",
        },
        wallet_balance: 3,
      }),
    });
  });

  await loginVerifiedUser(page, "wallet2@example.com");
  await page.goto("/wallet");
  await page.getByRole("button", { name: "購買 3 題包（NT$ 358）" }).click();

  await expect(page.getByText("購買 3 題包成功，餘額已更新。")).toBeVisible();
  await expect(page.getByText("目前餘額：3 點")).toBeVisible();
  await expect(page.getByText("購點入帳 +3 點")).toBeVisible();
});

test("wallet redirects to login with next and returns after login", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-wallet-next",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 2, updated_at: "2026-02-18T12:00:00Z" }),
    });
  });

  await page.route("**/api/v1/credits/transactions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  await page.goto("/wallet");
  await expect(page).toHaveURL(/\/login\?next=%2Fwallet$/);

  await page.getByLabel("Email").fill("wallet-next@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/wallet");
  await expect(page.getByText("目前餘額：2 點")).toBeVisible();
});

test("ask 402 provides wallet cta", async ({ page }) => {
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 0, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 402,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "INSUFFICIENT_CREDIT", message: "Insufficient credit balance" },
      }),
    });
  });

  await loginVerifiedUser(page, "wallet3@example.com");
  await page.getByLabel("問題內容").fill("點數不足測試");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByRole("link", { name: "立即前往購點" })).toBeVisible();

  await page.getByRole("link", { name: "立即前往購點" }).click();
  await expect(page).toHaveURL(/\/wallet\?from=ask-402/);
});

test("wallet purchase handles forbidden simulate-paid", async ({ page }) => {
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 0, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  await page.route("**/api/v1/credits/transactions?limit=20&offset=0", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  await page.route("**/api/v1/orders", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "order-forbidden",
        user_id: "u-2",
        package_size: 1,
        amount_twd: 168,
        status: "pending",
        idempotency_key: "k-order-forbidden",
        created_at: "2026-02-17T12:01:00Z",
        paid_at: null,
      }),
    });
  });

  await page.route("**/api/v1/orders/order-forbidden/simulate-paid", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "FORBIDDEN_IN_PRODUCTION",
          message: "simulate-paid is disabled in production",
        },
      }),
    });
  });

  await loginVerifiedUser(page, "wallet4@example.com");
  await page.goto("/wallet");
  await page.getByRole("button", { name: "購買 1 題包（NT$ 168）" }).click();

  await expect(page.getByText("目前環境不允許 simulate-paid。Production 需改用真實金流 callback 入帳。")).toBeVisible();
});

test("home does not emit hydration mismatch when auth exists in localStorage", async ({ page }) => {
  const hydrationSignals: string[] = [];

  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error" && text.includes("Text content does not match server-rendered HTML")) {
      hydrationSignals.push(text);
    }
  });
  page.on("pageerror", (error) => {
    const text = String(error);
    if (text.includes("Text content does not match server-rendered HTML")) {
      hydrationSignals.push(text);
    }
  });

  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 2, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "token-hydration");
    window.localStorage.setItem("elin_auth_email_verified", "true");
    window.localStorage.setItem("elin_auth_email", "hydration@example.com");
  });

  await page.goto("/");
  await expect(page.getByText("目前狀態：已登入（已驗證）")).toBeVisible();
  await expect(page.getByText("目前點數：2 點")).toBeVisible();
  expect(hydrationSignals).toHaveLength(0);
});
