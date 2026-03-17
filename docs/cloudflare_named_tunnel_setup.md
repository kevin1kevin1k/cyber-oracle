# Cloudflare Named Tunnel 設定指南

## 目的
本文件說明如何用 Cloudflare named tunnel 為專案建立固定的公開開發網址，避免 `trycloudflare.com` quick tunnel 網址經常變動，導致：
- Meta webhook callback URL 需要重填
- `MESSENGER_WEB_BASE_URL` 與 `CORS_ORIGINS` 需要重填

建議目標架構：
- `https://messenger-dev.<your-domain>/api/...` -> local backend `http://localhost:8000`
- `https://messenger-dev.<your-domain>/...` -> local frontend `http://localhost:3000`

## 前置條件
1. 你有自己的網域，且由 Cloudflare 管理 DNS
2. 本機已安裝 `cloudflared`
3. local backend 與 frontend 可正常啟動

驗證：

```bash
curl -i http://localhost:8000/api/v1/health && curl -i http://localhost:3000
```

## 建議命名
建議使用固定的開發子網域，例如：

```text
messenger-dev.cyber-oracle.app
```

這個 hostname 可同時作為：
- Meta webhook callback URL
- Messenger WebView base URL
- local/dev 驗證入口

## 步驟 1：建立 named tunnel
登入 Cloudflare：

```bash
cloudflared tunnel login
```

建立 tunnel：

```bash
cloudflared tunnel create cyber-oracle-dev
```

建立完成後，請記下：
- tunnel name，例如 `cyber-oracle-dev`
- tunnel UUID
- credentials JSON 路徑，通常在 `~/.cloudflared/<UUID>.json`

## 步驟 2：建立固定 DNS
讓固定 hostname 指到 named tunnel：

```bash
cloudflared tunnel route dns cyber-oracle-dev messenger-dev.cyber-oracle.app
```

這會由 Cloudflare 自動建立 DNS record。對這個 tunnel hostname，不建議再手動建立同名 A / CNAME record。

## 步驟 3：建立 `cloudflared` 設定檔
建議在本機使用：

```text
~/.cloudflared/config.yml
```

範例：

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /Users/<your-user>/.cloudflared/<YOUR_TUNNEL_UUID>.json

ingress:
  - hostname: messenger-dev.cyber-oracle.app
    path: ^/api/.*
    service: http://localhost:8000

  - hostname: messenger-dev.cyber-oracle.app
    service: http://localhost:3000

  - service: http_status:404
```

規則說明：
- `/api/...` 先導向 backend
- 同一個 hostname 的其他 path 導向 frontend
- 最後一條是 catch-all

## 步驟 4：驗證 ingress
驗證設定檔語法：

```bash
cloudflared tunnel ingress validate
```

驗證路由：

```bash
cloudflared tunnel ingress rule https://messenger-dev.cyber-oracle.app/api/v1/health && cloudflared tunnel ingress rule https://messenger-dev.cyber-oracle.app/messenger/link
```

預期結果：
- `/api/v1/health` 命中 backend
- `/messenger/link` 命中 frontend

## 步驟 5：啟動 tunnel

```bash
cloudflared tunnel run cyber-oracle-dev
```

## 步驟 6：更新 backend 設定
backend 需要固定使用這個 hostname：

```env
MESSENGER_WEB_BASE_URL=https://messenger-dev.cyber-oracle.app
CORS_ORIGINS=http://localhost:3000,https://messenger-dev.cyber-oracle.app
```

如果你之後完全不再從本機瀏覽器直接打 `localhost:3000`，可再把 `CORS_ORIGINS` 簡化成固定 hostname。

## Repo 同源 API 設定
本 repo 建議改成：
- 在 `localhost` / `127.0.0.1` 直接開發時，frontend 預設打 `http://localhost:8000`
- 在固定 HTTPS host 下，frontend 若未設定 `NEXT_PUBLIC_API_BASE_URL`，自動改走 same-origin API

這樣固定開發網址下，frontend 會直接呼叫：

```text
https://messenger-dev.cyber-oracle.app/api/...
```

而不需要再為固定開發網址額外硬寫另一組 frontend API base。

## 步驟 7：更新 Meta webhook callback URL
在 Meta Developers 後台，將 callback URL 改成：

```text
https://messenger-dev.cyber-oracle.app/api/v1/messenger/webhook
```

`Verify Token` 保持原本設定不變。

## 步驟 8：驗證固定網址
驗證 backend：

```bash
curl -i https://messenger-dev.cyber-oracle.app/api/v1/health
```

驗證 frontend：

```bash
curl -i https://messenger-dev.cyber-oracle.app/
```

驗證 WebView 入口：

```bash
curl -i https://messenger-dev.cyber-oracle.app/messenger/link
```

## 驗證 Messenger 流程
完成以上設定後，再實際驗證：
1. Messenger webhook 能正常進 backend
2. `登入並綁定` 會固定開到 `https://messenger-dev.cyber-oracle.app/messenger/link?...`
3. `前往購點` 會固定開到 `https://messenger-dev.cyber-oracle.app/wallet?...`
4. 不需要再因 quick tunnel 變動去重填 `.env` 或 Meta webhook

## 常見錯誤
### 1. `/api` 被導去 frontend
通常是 ingress 順序錯誤；`/api` 規則必須放前面。

### 2. WebView 出現 `Failed to fetch`
通常是 backend `CORS_ORIGINS` 沒有包含固定 hostname。

### 3. Meta webhook verify 失敗
優先檢查：
- callback URL 是否為 `https://messenger-dev.cyber-oracle.app/api/v1/messenger/webhook`
- `META_VERIFY_TOKEN` 是否一致
- named tunnel 是否仍在執行
- backend 是否能透過 `/api/v1/health` 正常回應

## 相關文件
- `docs/messenger_validation_runbook.md`
- `docs/PRD.md`
- `docs/TODO.md`
- `backend/README.md`
