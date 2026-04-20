# Production Launch Runbook

## 目的
本文件定義 ELIN 神域引擎目前這個最小公開體驗版的正式切換步驟。目標是讓同一套 repo 可在 Render 上部署 `frontend + backend + postgres`，並完成 Messenger webhook / persistent menu / WebView 的正式切換。

目前 runbook 的範圍是：
- Messenger-primary MVP
- `PAYMENTS_ENABLED=false`
- Render 作為正式託管平台

不在本次正式切換範圍內：
- 真實 Stripe callback 入帳閉環
- Send API dashboard / 告警 / 人工補償流程完整化
- access token 升級為 cookie / httpOnly

## 固定部署拓樸
- Frontend：`https://app.<your-domain>`
- Backend：`https://api.<your-domain>`
- Database：Render Managed PostgreSQL
- Meta webhook callback：`https://api.<your-domain>/api/v1/messenger/webhook`

## 必要環境變數
### Backend（Render Web Service）
- `APP_ENV=prod`
- `DATABASE_URL=<Render Postgres connection string>`
- `JWT_SECRET=<至少 32 字元>`
- `OPENAI_API_KEY=<prod key>`
- `VECTOR_STORE_ID=<prod vector store id>`
- `CORS_ORIGINS=https://app.<your-domain>`
- `PAYMENTS_ENABLED=false`
- `LAUNCH_CREDIT_GRANT_AMOUNT=50`
- `MESSENGER_ENABLED=true`
- `META_VERIFY_TOKEN=<Meta verify token>`
- `META_PAGE_ACCESS_TOKEN=<Page access token>`
- `META_APP_SECRET=<Meta app secret>`
- `MESSENGER_VERIFY_SIGNATURE=true`
- `MESSENGER_OUTBOUND_MODE=meta_graph`
- `MESSENGER_SEND_TIMEOUT_SECONDS=10`
- `MESSENGER_SEND_MAX_ATTEMPTS=3`
- `MESSENGER_SEND_INITIAL_BACKOFF_MS=500`
- `MESSENGER_PROFILE_SYNC_ON_STARTUP=true`
- `MESSENGER_WEB_BASE_URL=https://app.<your-domain>`

### Frontend（Render Web Service）
- `NEXT_PUBLIC_API_BASE_URL=https://api.<your-domain>`

補充：
- backend 會自動把 Render 常見的 `postgresql://...` 連線字串正規化為 `postgresql+psycopg://...`，因此直接使用 Render 注入的 Postgres connection string 也能正常啟動
- frontend 如果未設定 `NEXT_PUBLIC_API_BASE_URL`，在 HTTPS 非 localhost 情境會走 same-origin；但正式部署仍建議明確填入 `https://api.<your-domain>`，避免 WebView / custom domain 切換時判斷混淆。
- `PAYMENTS_ENABLED=false` 是目前公開體驗版的正式策略；WebView 只保留單頁設定中心，不開放真實購點或歷史查詢，點數不足時僅回體驗版提示。

## Render 建立步驟
1. 在 Render 建立 Blueprint，直接指向 repo root 的 [render.yaml](/Users/kevin1kevin1k/cyber-oracle/render.yaml)。
2. 確認 Render 會建立：
   - `elin-postgres`
   - `elin-backend`
   - `elin-frontend`
3. 在 Render Dashboard 補齊所有 `sync: false` 的 env。
4. 為 frontend 設定 custom domain：`app.<your-domain>`。
5. 為 backend 設定 custom domain：`api.<your-domain>`。
6. 等待 frontend/backend 各自完成首次 deploy。

## 首次 deploy 後檢查
1. 確認 backend deploy command 會先跑 migration，再啟服務。
2. 驗證 backend health：
```bash
curl -i https://api.<your-domain>/api/v1/health
```
預期結果：
- status `200`
- body 類似 `{"status":"ok"}`

3. 在 Render backend shell 驗證 Alembic revision：
```bash
cd /opt/render/project/src/backend && uv run alembic current
```
預期結果：
- output 顯示 `(head)`

4. 驗證 frontend 可正常載入：
```bash
curl -I https://app.<your-domain>
```
預期結果：
- status `200` 或 `307/308` 後最終可成功打開首頁

## Meta 後台切換
0. 先確認這次目標是「app role 內測」還是「對外公開試用」。
   - 若只是 role 內測，`Administrators / Developers / Testers` 即可。
   - 若要讓一般使用者可試用，必須另外完成 Meta app review / advanced access / publish 流程；只部署 Render 與設定 webhook 不足以公開。
1. 到 Meta Developers 後台更新 Messenger webhook：
   - Callback URL：`https://api.<your-domain>/api/v1/messenger/webhook`
   - Verify Token：必須與 backend `META_VERIFY_TOKEN` 完全一致
2. 重新確認 Page subscription 至少包含：
   - `messages`
   - `messaging_postbacks`
3. 檢查 Meta app 的公開化前置條件：
   - `Settings > Basic` 已補齊公開前置資料（至少 App Icon、Privacy Policy URL、Data Deletion URL、聯絡資訊）
   - app type / dashboard access mode 已確認，知道這個 app 應在哪裡切到公開可用
   - Messenger 相關 review / permission request 已通過，至少涵蓋 `pages_messaging`
   - 若 dashboard 顯示 Messenger / Page 綁定還需要其他 permissions，再追加申請；不要預設先送一大包不必要權限
   - 若目前 app 可避開 business portfolio / business verification 路徑，優先沿用該配置，不要為了公開試用重新引入額外 blocker
4. 檢查對外使用的 Facebook Page：
   - Page 已發布
   - Messenger 已開啟
   - 沒有年齡 / 國家限制把目標試用者擋掉
5. 取得 production 用 `META_PAGE_ACCESS_TOKEN` 時，避免直接把 Graph API Explorer 臨時 token 當成長期 production token。
   - 先用 Access Token Debugger 驗證 token 是否有效、是否仍帶有 `pages_messaging`
   - token 更新後，必須同步更新 Render backend `META_PAGE_ACCESS_TOKEN`，並重新 deploy backend
   - 若 token 曾在聊天、截圖、螢幕分享或其他非 secrets 管道外露，視同外洩，應立即重發並替換
6. 若 `MESSENGER_PROFILE_SYNC_ON_STARTUP=true`，backend 每次 deploy / restart 都會 best-effort 自動同步 Messenger profile（`greeting` + `Get Started` + `persistent_menu`），失敗只記 warning，不阻止服務啟動。
7. 如需手動重刷或在 deploy 前先驗證，也可用 production env 執行 persistent menu sync：
```bash
cd /Users/kevin1kevin1k/cyber-oracle/backend && \
META_PAGE_ACCESS_TOKEN='<prod-page-token>' \
MESSENGER_OUTBOUND_MODE=meta_graph \
MESSENGER_WEB_BASE_URL='https://app.<your-domain>' \
uv run python scripts/sync_messenger_profile.py && \
cd ..
```
預期結果：
- Meta Page 的 `Get Started` 與 `persistent_menu` 都被成功更新
- `查看剩餘點數` 為 `SHOW_BALANCE` postback
- `回覆方式` 為 `OPEN_REPLY_MODE` postback，會回 `結構化回覆` / `自由回覆` quick replies
- `前往設定` 為 `OPEN_SETTINGS` postback，會再回帶 signed token 的 WebView 按鈕
- `composer_input_disabled` 目前維持關閉，保留 Messenger 內直接輸入提問；因此手機版 persistent menu 是否明顯可見不作為 release blocker

## 正式上線 Smoke Test
在進入這一段前，先確認：
- `pages_messaging` 已通過 review / permission request
- app 已 publish / live，非 app role 帳號理論上可互動

### API / Web
1. `GET /api/v1/health`
   - 預期 `200`
2. 用一個新 Messenger 使用者完成 linking
   - 預期 `/messenger/link` 可建立 session
3. 進入首頁單頁設定中心，填入 `姓名` 與 `母親姓名`
   - 預期儲存成功
4. 確認首頁單頁設定中心
   - 預期可看到帳號狀態、目前點數、固定資料設定與刪除帳號

### Messenger
1. 用 app role 帳號直接在 Messenger 提問
   - 預期收到回答與 followups
2. 點 `查看剩餘點數`
   - 預期收到正確餘額
3. 若 profile 未完成就先提問
   - 預期收到 `前往設定` + `設定完成，重新送出剛剛的問題`
4. 若 launch credits 用完再提問
   - 預期只收到體驗版提示，不應導向真實購點
5. 清掉 WebView session 後，從 persistent menu 點 `前往設定`
   - 預期 bot 會先回 bridge 按鈕；點擊後仍可成功開啟單頁設定中心，不會卡在 static menu dead end

### 對外公開試用額外 Smoke Test
1. 用一個沒有任何 app role 的 Facebook 帳號打開同一個 Page 對話。
   - 預期可以正常開始聊天；若完全沒有回覆，優先懷疑 app 仍停留在 role-only 測試模式。
2. 非 role 帳號直接傳第一句訊息。
   - 預期 bot 會回覆，而不是只對 admin / developer / tester 有反應。
3. 非 role 帳號完成 linking、settings、Messenger ask。
   - 預期整條主流程都可用，WebView 端則可正常進入首頁單頁設定中心。
4. 非 role 帳號測 `查看剩餘點數`、`前往設定`。
   - 預期 menu bridge 與 WebView 入口都正常。

## App Review 提交重點
目前最小公開版本建議 submission scope：
- `pages_messaging`

Reviewer materials 建議至少包含：
1. 一段完整 screencast：
   - 打開 Page 對話
   - greeting / `Get Started`
   - linking
   - 設定姓名 / 母親姓名
   - 回 Messenger 提問
   - bot 回答 + followup + 自動餘額訊息
2. Reviewer instructions：
   - 直接提供 Page、測試步驟、測試帳號前提
3. 測試重點：
   - 以 Messenger 對話主流程為主，不依賴手機版 persistent menu 漢堡圖示是否顯眼

## 排障與回滾
### 1. `UndefinedColumn` / `UndefinedTable`
第一步不要先改 code，先檢查 migration：
```bash
cd /opt/render/project/src/backend && uv run alembic upgrade head && uv run alembic current
```
若 `current` 不是 `head`，先完成 migration 再重試。

### 2. Messenger WebView 開頁後 `Failed to fetch` / preflight 失敗
優先檢查：
- `CORS_ORIGINS` 是否包含 `https://app.<your-domain>`
- `NEXT_PUBLIC_API_BASE_URL` 是否確實指到 `https://api.<your-domain>`
- `MESSENGER_WEB_BASE_URL` 是否確實指到 `https://app.<your-domain>`

### 3. Webhook verify 失敗
優先檢查：
- Meta 後台 Verify Token 與 backend `META_VERIFY_TOKEN` 是否一致
- callback URL 是否確實是 `https://api.<your-domain>/api/v1/messenger/webhook`
- `MESSENGER_VERIFY_SIGNATURE=true` 時，`META_APP_SECRET` 是否正確

### 4. 懷疑 webhook 重送造成重複執行
先查 backend DB 的 `messenger_webhook_receipts`：
```bash
cd /opt/render/project/src/backend && uv run python - <<'PY'
from sqlalchemy import create_engine, text
from app.config import settings

engine = create_engine(settings.database_url, future=True)
with engine.connect() as conn:
    rows = conn.execute(text("""
        select delivery_key, event_type, signature_status, processing_status, error_code, received_at, processed_at
        from messenger_webhook_receipts
        order by received_at desc
        limit 20
    """)).fetchall()
    for row in rows:
        print(row)
PY
```
預期結果：
- 同一個 Messenger event 只會保留一筆對應 `delivery_key`
- 正常事件應看到 `succeeded`
- 驗章失敗 request 應看到 `event_type=request`、`signature_status=invalid`

### 5. 快速回滾
1. 先在 Render 將 frontend/backend rollback 到上一個 healthy deploy。
2. 若 webhook 仍在打壞版本，可暫時把 backend `MESSENGER_OUTBOUND_MODE` 切成 `noop`，降低錯誤擴散。
3. 若問題是 schema drift，優先補 migration，不要直接 downgrade DB。
4. rollback 完成後，重新執行：
   - `GET /api/v1/health`
   - Messenger linking
   - `SHOW_BALANCE`

### 6. Messenger 有收 webhook，但完全回不出訊息
若 Render backend log 出現：
- `OAuthException`
- `code 190`
- `error_subcode 463`

代表目前 `META_PAGE_ACCESS_TOKEN` 已失效或已過期。優先處置：
1. 在 Meta 重新取得新的 Page Access Token。
2. 用 Access Token Debugger 檢查 token 是否有效、權限是否正確。
3. 更新 Render backend `META_PAGE_ACCESS_TOKEN`。
4. 重新 deploy backend。
5. 重新測：
   - `查看剩餘點數`
   - 直接提問

### 7. 只有 app role 帳號可用，其他人完全收不到 bot 回覆
優先檢查：
1. Meta app 是否仍停留在 role-only 測試狀態。
2. `pages_messaging` 與相關必要 access 是否已完成 review / advanced access。
3. 對外試用的 Facebook 帳號是否真的不在 app roles 內。
4. Page 是否已發布且可被公開互動。

## 完成定義
完成這份 runbook 的正式切換，才代表目前最小公開體驗版具備：
- 固定 production domain
- production DB migration baseline
- Meta webhook / persistent menu 正式綁定
- Messenger -> WebView -> settings center 主流程可用
- 非 role 一般使用者也能實際與 bot 互動
- launch mode (`PAYMENTS_ENABLED=false`) 的正式行為與文件一致
