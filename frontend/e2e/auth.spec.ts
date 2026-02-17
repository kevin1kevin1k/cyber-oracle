import { expect, test } from "@playwright/test";

test("register -> verify -> login -> ask -> logout", async ({ page }) => {
  await page.route("**/api/v1/auth/register", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "u-1",
        email: "new@example.com",
        email_verified: false,
        verification_token: "verify-token-123",
      }),
    });
  });

  await page.route("**/api/v1/auth/verify-email", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "verified" }),
    });
  });

  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    const auth = route.request().headers()["authorization"];
    expect(auth).toBe("Bearer token-verified");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "這是回覆",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-123",
      }),
    });
  });

  await page.route("**/api/v1/auth/logout", async (route) => {
    await route.fulfill({ status: 204 });
  });

  await page.goto("/register");
  await page.getByLabel("Email").fill("new@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "註冊" }).click();

  await expect(page).toHaveURL(/\/verify-email\?token=verify-token-123/);
  await page.getByRole("button", { name: "送出驗證" }).click();
  await expect(page.getByText("Email 驗證成功，請前往登入。"))
    .toBeVisible();

  await page.getByRole("link", { name: "前往登入" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill("new@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前狀態：已登入（已驗證）")).toBeVisible();

  await page.getByLabel("問題內容").fill("今天該聚焦什麼？");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("這是回覆")).toBeVisible();

  await page.getByRole("button", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("forgot -> reset password flow", async ({ page }) => {
  await page.route("**/api/v1/auth/forgot-password", async (route) => {
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        status: "accepted",
        reset_token: "reset-token-xyz",
      }),
    });
  });

  await page.route("**/api/v1/auth/reset-password", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    expect(body.token).toBe("reset-token-xyz");
    expect(body.new_password).toBe("NewPassword123");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "password_reset" }),
    });
  });

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("user@example.com");
  await page.getByRole("button", { name: "送出" }).click();

  await expect(page.getByText("已送出重設請求（若帳號存在）。")).toBeVisible();
  await page.getByRole("link", { name: "帶入 token 前往重設密碼" }).click();

  await expect(page).toHaveURL(/\/reset-password\?token=reset-token-xyz/);
  await page.getByLabel("新密碼").fill("NewPassword123");
  await page.getByRole("button", { name: "重設密碼" }).click();
  await expect(page.getByText("密碼已重設，請使用新密碼登入。"))
    .toBeVisible();
});

test("unverified login enters home but ask is disabled", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-unverified",
        token_type: "bearer",
        email_verified: false,
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("unverified@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前狀態：已登入（未驗證）")).toBeVisible();
  await expect(page.getByLabel("問題內容")).toBeDisabled();
});

test("ask handles 401 by redirecting to login", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-401",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "UNAUTHORIZED", message: "Authentication required" },
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("user401@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.getByLabel("問題內容").fill("401 測試");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("ask handles 403 email verification required", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-403",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "EMAIL_NOT_VERIFIED", message: "Email verification required" },
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("user403@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.getByLabel("問題內容").fill("403 測試");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("Email 尚未驗證，請先完成驗證後再提問。")).toBeVisible();
});

test("ask handles 402 insufficient credit", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-402",
        token_type: "bearer",
        email_verified: true,
      }),
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

  await page.goto("/login");
  await page.getByLabel("Email").fill("user402@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.getByLabel("問題內容").fill("402 測試");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("點數不足，請先購點再提問。")).toBeVisible();
});

test("ask success updates credit balance immediately", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-credit-live",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  let balanceCalls = 0;
  await page.route("**/api/v1/credits/balance", async (route) => {
    balanceCalls += 1;
    if (balanceCalls === 1) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ balance: 5, updated_at: "2026-02-17T12:00:00Z" }),
      });
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 4, updated_at: "2026-02-17T12:00:01Z" }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "即時扣點測試",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-credit-live",
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("credit-live@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前點數：5 點")).toBeVisible();

  await page.getByLabel("問題內容").fill("即時扣點");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("目前點數：4 點")).toBeVisible();
  await expect(page.locator(".credit-delta")).toHaveText("-1");
});

test("ask failure does not decrement credit balance", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-credit-fail",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 5, updated_at: "2026-02-17T12:00:00Z" }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "ASK_PROCESSING_FAILED", message: "Failed to process ask request" },
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("credit-fail@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前點數：5 點")).toBeVisible();

  await page.getByLabel("問題內容").fill("不應扣點");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("Failed to process ask request")).toBeVisible();
  await expect(page.getByText("目前點數：5 點")).toBeVisible();
  await expect(page.locator(".credit-delta")).toHaveCount(0);
});

test("ask retry uses the same Idempotency-Key", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-verified-idempotency",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  const keys: string[] = [];
  let askCount = 0;
  await page.route("**/api/v1/ask", async (route) => {
    const key = route.request().headers()["idempotency-key"];
    keys.push(key ?? "");
    if (askCount === 0) {
      askCount += 1;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          detail: { code: "ASK_PROCESSING_FAILED", message: "Failed to process ask request" },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "重試成功",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-retry",
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("retry@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.getByLabel("問題內容").fill("重試同一題");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("Failed to process ask request")).toBeVisible();

  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("重試成功")).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[0]).toBe(keys[1]);
});
