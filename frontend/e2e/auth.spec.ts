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
        followup_options: [],
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
  await expect(page.getByTestId("account-menu-trigger")).toBeVisible();

  await page.getByLabel("問題內容").fill("今天該聚焦什麼？");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("這是回覆")).toBeVisible();

  await page.getByTestId("account-menu-trigger").click();
  await expect(page.getByTestId("account-menu")).toContainText("new@example.com");
  await page.getByRole("menuitem", { name: "登出" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("home top nav shows login and register links when unauthenticated", async ({ page }) => {
  await page.goto("/");
  const topNav = page.getByTestId("app-top-nav");
  await expect(topNav).toBeVisible();
  await expect(topNav.getByRole("link", { name: "登入" })).toBeVisible();
  await expect(topNav.getByRole("link", { name: "註冊" })).toBeVisible();
});

test("register success without verification token shows check-email message", async ({ page }) => {
  await page.route("**/api/v1/auth/register", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "u-2",
        email: "prod@example.com",
        email_verified: false,
        verification_token: null,
      }),
    });
  });

  await page.goto("/register");
  await page.getByLabel("Email").fill("prod@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "註冊" }).click();

  await expect(page).toHaveURL(/\/register/);
  await expect(page.getByText("註冊成功，請查收 prod@example.com 的驗證信件。")).toBeVisible();
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

  await expect(page.getByText("若帳號存在，請查收 Email 內的重設密碼連結。")).toBeVisible();
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
  await expect(page.getByText("你已登入但尚未驗證 Email。")).toBeVisible();
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
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 3, updated_at: "2026-02-18T12:00:00Z" }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("user401@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");

  await page.getByLabel("問題內容").fill("401 測試");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page).toHaveURL(/\/login\?next=%2F$/);
  await page.getByLabel("Email").fill("user401@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
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
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 3, updated_at: "2026-02-18T12:00:00Z" }),
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

test("login next path rejects backslash payload and does not auto-forward on stale local token", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-safe-next",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "stale-token");
    window.localStorage.setItem("elin_auth_email_verified", "true");
    window.localStorage.setItem("elin_auth_email", "stale@example.com");
  });

  await page.goto("/login?next=%2F%5Cevil.com");
  await expect(page).toHaveURL(/\/login\?next=%2F%5Cevil.com$/);
  await expect(page.getByRole("heading", { name: "登入" })).toBeVisible();

  await page.getByLabel("Email").fill("safe-next@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
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
        followup_options: [
          { id: "f-credit-live-1", content: "再給我一個例子" },
          { id: "f-credit-live-2", content: "請幫我列步驟" },
          { id: "f-credit-live-3", content: "有沒有常見錯誤" },
        ],
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
  await expect(page.getByText("來源：")).toHaveCount(0);
  await expect(page.getByText("Request ID：")).toHaveCount(0);
  await expect(page.getByText("三層比例：")).toHaveCount(0);
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
        followup_options: [],
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

test("ask response renders followup buttons and clicking one asks followup with immediate credit update", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-followup-success",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  let balanceCalls = 0;
  await page.route("**/api/v1/credits/balance", async (route) => {
    balanceCalls += 1;
    const balance = balanceCalls === 1 ? 5 : balanceCalls === 2 ? 4 : 3;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance, updated_at: "2026-02-19T00:00:00Z" }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "第一層回答",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-followup-entry",
        followup_options: [
          { id: "f1", content: "延伸 A" },
          { id: "f2", content: "延伸 B" },
          { id: "f3", content: "延伸 C" },
        ],
      }),
    });
  });

  await page.route("**/api/v1/followups/f1/ask", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "延伸回答 A",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 65 },
          { label: "輔層", pct: 25 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-followup-a",
        followup_options: [
          { id: "f4", content: "下一步要做什麼？" },
          { id: "f5", content: "風險有哪些？" },
          { id: "f6", content: "如何驗證？" },
        ],
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("followup-success@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前點數：5 點")).toBeVisible();

  await page.getByLabel("問題內容").fill("主問題");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("第一層回答")).toBeVisible();
  await expect(page.getByRole("button", { name: "延伸 A" })).toBeVisible();
  await expect(page.getByRole("button", { name: "延伸 B" })).toBeVisible();
  await expect(page.getByRole("button", { name: "延伸 C" })).toBeVisible();
  await expect(page.getByText("目前點數：4 點")).toBeVisible();

  await page.getByRole("button", { name: "延伸 A" }).click();
  await expect(page.getByText("延伸回答 A")).toBeVisible();
  await expect(page.getByText("目前點數：3 點")).toBeVisible();
  await expect(page.locator(".credit-delta")).toHaveText("-1");
  await expect(page.getByText("來源：")).toHaveCount(0);
  await expect(page.getByText("Request ID：")).toHaveCount(0);
  await expect(page.getByText("三層比例：")).toHaveCount(0);
});

test("followup ask 409 shows used message and does not decrement credit", async ({ page }) => {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "token-followup-409",
        token_type: "bearer",
        email_verified: true,
      }),
    });
  });

  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ balance: 4, updated_at: "2026-02-19T00:00:00Z" }),
    });
  });

  await page.route("**/api/v1/ask", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        answer: "主回答",
        source: "mock",
        layer_percentages: [
          { label: "主層", pct: 70 },
          { label: "輔層", pct: 20 },
          { label: "參照層", pct: 10 },
        ],
        request_id: "req-followup-409-entry",
        followup_options: [
          { id: "f-used", content: "已用過延伸題" },
          { id: "f-open-1", content: "可用延伸 1" },
          { id: "f-open-2", content: "可用延伸 2" },
        ],
      }),
    });
  });

  await page.route("**/api/v1/followups/f-used/ask", async (route) => {
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "FOLLOWUP_ALREADY_USED", message: "Followup already used" },
      }),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("followup-409@example.com");
  await page.getByLabel("密碼").fill("Password123");
  await page.getByRole("button", { name: "登入" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("目前點數：4 點")).toBeVisible();

  await page.getByLabel("問題內容").fill("主問題 409");
  await page.getByRole("button", { name: "送出問題" }).click();
  await expect(page.getByText("主回答")).toBeVisible();
  await expect(page.getByText("目前點數：4 點")).toBeVisible();

  await page.getByRole("button", { name: "已用過延伸題" }).click();
  await expect(page.getByText("這個延伸問題已被使用，請改選其他按鈕。")).toBeVisible();
  await expect(page.getByText("目前點數：4 點")).toBeVisible();
});
