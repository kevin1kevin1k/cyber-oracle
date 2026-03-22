import { expect, test } from "@playwright/test";

test("messenger link page bootstraps a new session", async ({ page }) => {
  await page.route("**/api/v1/messenger/link", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "linked",
        link_status: "linked_new",
        user_id: "user-1",
        psid: "psid-1",
        page_id: "page-1",
        access_token: "token-1",
        token_type: "bearer",
      }),
    });
  });

  await page.goto("/messenger/link?token=link-token-123");

  await expect(page.getByText("綁定完成，請回 Messenger 繼續提問。")).toBeVisible();
  const accessToken = await page.evaluate(() => window.localStorage.getItem("elin_access_token"));
  expect(accessToken).toBe("token-1");
});

test("messenger link page restores existing session", async ({ page }) => {
  await page.route("**/api/v1/messenger/link", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "linked",
        link_status: "session_restored",
        user_id: "user-2",
        psid: "psid-2",
        page_id: "page-2",
        access_token: "token-2",
        token_type: "bearer",
      }),
    });
  });

  await page.goto("/messenger/link?token=link-token-456");

  await expect(
    page.getByText("已恢復 Messenger WebView session，請回 Messenger 繼續使用。")
  ).toBeVisible();
});

test("messenger link page handles invalid token", async ({ page }) => {
  await page.route("**/api/v1/messenger/link", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "MESSENGER_LINK_TOKEN_INVALID",
          message: "invalid token",
        },
      }),
    });
  });

  await page.goto("/messenger/link?token=bad-token");

  await expect(page.getByText("綁定連結無效或已過期，請回 Messenger 重新點擊綁定按鈕。")).toBeVisible();
});
