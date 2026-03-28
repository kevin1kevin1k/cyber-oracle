import { expect, test } from "@playwright/test";

async function seedMessengerSession(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "messenger-session-token");
    window.localStorage.setItem("elin_auth_user_label", "Messenger 已連結");
    window.localStorage.setItem("elin_auth_user_id", "user-settings-1");
  });
}

async function mockBalance(page: import("@playwright/test").Page, balance = 50) {
  await page.route("**/api/v1/credits/balance", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        balance,
        updated_at: "2026-03-22T10:00:00Z",
        payments_enabled: false,
      }),
    });
  });
}

test("home highlights settings when profile is incomplete", async ({ page }) => {
  await seedMessengerSession(page);
  await mockBalance(page);
  await page.route("**/api/v1/me/profile", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: null,
        mother_name: null,
        is_complete: false,
      }),
    });
  });

  await page.goto("/");

  await expect(page.getByText("目前已連結 Messenger，但還沒完成個人設定。")).toBeVisible();
  await expect(page.getByLabel("我的姓名")).toBeVisible();
  await expect(page.getByText("目前點數：")).toBeVisible();
});

test("home page loads and saves fixed ask profile fields", async ({ page }) => {
  await seedMessengerSession(page);
  await mockBalance(page);
  await page.route("**/api/v1/me/profile", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          full_name: "王小明",
          mother_name: "林淑芬",
          is_complete: true,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: "陳大文",
        mother_name: "黃美玉",
        is_complete: true,
      }),
    });
  });

  await page.goto("/?from=messenger-profile-required");

  await expect(page.getByRole("heading", { name: "Messenger 設定中心" })).toBeVisible();
  await expect(page.getByText("Messenger 提問前設定")).toBeVisible();
  await page.getByLabel("我的姓名").fill("陳大文");
  await page.getByLabel("我母親的姓名").fill("黃美玉");
  await page.getByRole("button", { name: "儲存設定" }).click();

  await expect(page.getByText("個人設定已儲存，之後 Messenger 提問會自動帶入這兩個固定資料。")).toBeVisible();
});

test("home page shows first-link onboarding hint and messenger success copy", async ({ page }) => {
  await seedMessengerSession(page);
  await mockBalance(page);
  await page.route("**/api/v1/me/profile", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          full_name: null,
          mother_name: null,
          is_complete: false,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: "陳大文",
        mother_name: "黃美玉",
        is_complete: true,
      }),
    });
  });

  await page.goto("/?from=messenger-first-link");

  await expect(page.getByText("綁定完成，請先補資料")).toBeVisible();
  await expect(
    page.getByText("你已完成 Messenger 綁定。再完成這一步，之後就能直接回 Messenger 提問。")
  ).toBeVisible();

  await page.getByLabel("我的姓名").fill("陳大文");
  await page.getByLabel("我母親的姓名").fill("黃美玉");
  await page.getByRole("button", { name: "儲存設定" }).click();

  await expect(page.getByText("個人設定已儲存，現在可以回 Messenger 直接提問。")).toBeVisible();
});

test("home page shows get-started onboarding hint and messenger success copy", async ({ page }) => {
  await seedMessengerSession(page);
  await mockBalance(page);
  await page.route("**/api/v1/me/profile", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          full_name: null,
          mother_name: null,
          is_complete: false,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: "陳大文",
        mother_name: "黃美玉",
        is_complete: true,
      }),
    });
  });

  await page.goto("/?from=messenger-get-started");

  await expect(page.getByText("開始使用前，請先補資料")).toBeVisible();
  await expect(
    page.getByText("你已啟用 Messenger 助手。再完成這一步，之後就能直接回 Messenger 提問。")
  ).toBeVisible();

  await page.getByLabel("我的姓名").fill("陳大文");
  await page.getByLabel("我母親的姓名").fill("黃美玉");
  await page.getByRole("button", { name: "儲存設定" }).click();

  await expect(page.getByText("個人設定已儲存，現在可以回 Messenger 直接提問。")).toBeVisible();
});

test("home page can delete account and clear local session", async ({ page }) => {
  await seedMessengerSession(page);
  await mockBalance(page);
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
  await page.route("**/api/v1/me", async (route) => {
    await route.fulfill({
      status: 204,
      body: "",
    });
  });

  await page.goto("/");

  await page.getByRole("button", { name: "刪除帳號" }).click();
  await expect(page.getByText("這個操作無法復原。確認後會直接刪除帳號與所有相關資料。")).toBeVisible();
  await page.getByRole("button", { name: "確認刪除帳號" }).click();

  await expect(page).toHaveURL(/\/$/);
  const accessToken = await page.evaluate(() => window.localStorage.getItem("elin_access_token"));
  expect(accessToken).toBeNull();
});

test("settings route redirects to single-page settings center", async ({ page }) => {
  await page.goto("/settings?from=messenger-profile-required");

  await expect(page).toHaveURL(/\/\?from=messenger-profile-required$/);
});

test("messenger link page redirects to requested next path after bootstrap", async ({ page }) => {
  await mockBalance(page);
  await page.route("**/api/v1/messenger/link", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "linked",
        link_status: "linked_new",
        user_id: "user-3",
        psid: "psid-3",
        page_id: "page-3",
        access_token: "token-3",
        token_type: "bearer",
      }),
    });
  });
  await page.route("**/api/v1/me/profile", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        full_name: null,
        mother_name: null,
        is_complete: false,
      }),
    });
  });

  await page.goto("/messenger/link?token=link-token-789&next=%2Fsettings%3Ffrom%3Dmessenger-profile-required");

  await expect(page).toHaveURL(/\/\?from=messenger-profile-required$/);
  const accessToken = await page.evaluate(() => window.localStorage.getItem("elin_access_token"));
  expect(accessToken).toBe("token-3");
});
