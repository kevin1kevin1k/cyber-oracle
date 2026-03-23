import { expect, test } from "@playwright/test";

async function seedMessengerSession(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("elin_access_token", "messenger-session-token");
    window.localStorage.setItem("elin_auth_user_label", "Messenger 已連結");
    window.localStorage.setItem("elin_auth_user_id", "user-settings-1");
  });
}

test("home blocks ask and links to settings when profile is incomplete", async ({ page }) => {
  await seedMessengerSession(page);
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
        full_name: null,
        mother_name: null,
        is_complete: false,
      }),
    });
  });

  await page.goto("/");

  await expect(page.getByText("目前已連結 Messenger，但還沒完成個人設定。")).toBeVisible();
  await expect(page.getByRole("button", { name: "送出問題" })).toBeDisabled();
  await expect(page.getByRole("link", { name: "先完成個人設定" })).toBeVisible();
});

test("settings page loads and saves fixed ask profile fields", async ({ page }) => {
  await seedMessengerSession(page);
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

  await page.goto("/settings?from=messenger-profile-required");

  await expect(page.getByRole("heading", { name: "固定問答設定" })).toBeVisible();
  await expect(page.getByText("Messenger 提問前設定")).toBeVisible();
  await page.getByLabel("我的姓名").fill("陳大文");
  await page.getByLabel("我母親的姓名").fill("黃美玉");
  await page.getByRole("button", { name: "儲存設定" }).click();

  await expect(page.getByText("個人設定已儲存，之後提問會自動帶入這兩個固定資料。")).toBeVisible();
  await expect(page.getByRole("link", { name: "前往提問" })).toBeVisible();
});

test("messenger link page redirects to requested next path after bootstrap", async ({ page }) => {
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

  await expect(page).toHaveURL(/\/settings\?from=messenger-profile-required$/);
  const accessToken = await page.evaluate(() => window.localStorage.getItem("elin_access_token"));
  expect(accessToken).toBe("token-3");
});
