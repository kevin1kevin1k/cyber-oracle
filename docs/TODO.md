# ELIN 神域引擎 Implementation Todo

## 說明
本清單依 `docs/PRD.md v0.4` 與現有 codebase 差距整理，依優先度排序。
狀態以 checkbox 追蹤，完成後請在 PR 附上對應測試證據。

## P0（必做 / 上線門檻）
- [x] 建立 Auth 流程：register/login/logout/verify-email/forgot-password
  - [x] `register` API
  - [x] `verify-email` API
  - [x] `login` API
  - [x] `logout` API
  - [x] `forgot-password` API
- [x] 前端 Auth 流程整合（使用既有 API）
  - [x] `register/login/verify-email/forgot-password/reset-password` 頁面與互動流程
  - [x] access token 儲存與失效處理（含 logout）
  - [x] 移除 `NEXT_PUBLIC_DEV_BEARER_TOKEN` 依賴，改為正式登入態
- [x] 未驗證 Email 不可提問（API 與前端雙重限制）
- [x] 建立核心資料表：users/sessions/questions/answers/credit_wallets/credit_transactions/orders/followups
  - [x] `users`
  - [x] `sessions`
  - [x] `questions`
  - [x] `answers`
  - [x] `credit_wallets`
  - [x] `credit_transactions`
  - [x] `orders`
  - [x] `followups`
- [x] 實作點數交易引擎（固定扣 1 點）：reserve/capture/refund + idempotency
  - [x] Backend：`POST /api/v1/ask` 支援 `Idempotency-Key`
  - [x] Backend：餘額不足回 `402` + `INSUFFICIENT_CREDIT`
  - [x] Backend：成功流程 `reserve -> persist question/answer -> capture`
  - [x] Backend：失敗流程 `reserve -> refund`（冪等保護）
  - [x] 測試：成功扣點、失敗回補、同 key 重試不重複扣點
  - [x] 測試：前端提問流程覆蓋 `401/403/402` 錯誤分支與提示文案
- [x] 實作購點方案與訂單流程：1題 168、3題 358、5題 518
  - [x] Backend：`GET /api/v1/credits/balance`
  - [x] Backend：`GET /api/v1/credits/transactions`
  - [x] Backend：`POST /api/v1/orders`（僅 1/3/5 題包）
  - [x] Backend：`POST /api/v1/orders/{id}/simulate-paid`（首次入帳，重複冪等）
  - [x] Backend：`simulate-paid` 僅允許非 production 環境（環境守衛 + 權限限制）
  - [x] Frontend：新增點數錢包區塊（餘額顯示 + 交易流水）
  - [x] Frontend：新增購點操作（1/3/5 題包）與支付成功後餘額刷新
  - [x] Frontend：在提問頁整合餘額顯示與「點數不足」導購入口
  - [x] Frontend：提問成功後即時扣點顯示（含 `-1` 動畫提示與背景對帳）
  - [x] 測試：建單、入帳、餘額/流水一致性
  - [x] 測試：前端購點後 10 秒內反映餘額（含重試冪等）
- [x] 將 `POST /api/v1/ask` 從 mock 升級為可持久化流程（Intake/Router/Persist 最小可用）
  - [x] Backend：`AskResponse.source` 擴充為 `rag/rule/openai/mock`
  - [x] Frontend：更新 `AskResponse` 型別（source 不再只限 `mock`）
  - [x] Frontend：送出提問時自動帶 `Idempotency-Key`，重試沿用同 key
  - [x] Frontend：處理 `402 INSUFFICIENT_CREDIT` 並導向購點流程

## P1（高價值 / MVP 完整）
- [ ] 實作 RAG Top-3 + rerank + 百分比（總和 100）
  - [x] Backend：建立 OpenAI file search 向量庫建置腳本與共用查詢 library（`backend/cyber oracle`）
  - [x] Backend：建立 builder 寫入 rag_files + uploader 寫入 input_files 的 JSON manifest（path -> file_id）持久化
  - [x] Backend：完成雙階段 Responses 流程（first stage `tools.file_search` top3 + VS->UF map + second request 最終輸出）
  - [ ] Backend：將 `POST /api/v1/ask` 串接實際 file_search 檢索與回答（非 mock）
  - [ ] Backend：回傳固定三層百分比且總和為 100（可驗證規則）
- [ ] 實作 deterministic 分流（Router）與工程可維護規則配置
- [x] 前端導覽一致化：提問/錢包/歷史頁共用頂部 nav bar
  - [x] Frontend：抽出共用導覽元件（例如 `AppTopNav`）
  - [x] Frontend：在 `/`、`/wallet`、`/history` 三頁套用同一導覽區塊與一致文案順序
  - [x] Frontend：移除三頁內文區分散的 `helper-links`（避免重複導覽）
  - [x] Frontend：導覽目前頁有 active state（可辨識所在頁）
  - [x] Frontend：手機寬度下導覽不換行破版，保留可點擊性
  - [x] Frontend：導覽列右上角改為帳號下拉選單（顯示 email 與登出）
  - [x] Frontend：未登入時導覽列右上角顯示登入/註冊連結
  - [x] Frontend：帳號選單結構預留後續擴充（個人檔案、設定）
  - [x] 測試：frontend e2e 覆蓋三頁互相跳轉（`/` -> `/wallet` -> `/history` -> `/`）
  - [x] 測試：frontend e2e 覆蓋帳號選單開合、email 顯示與登出流程
- [x] 實作歷史問答頁（問題/答案/時間/扣點）
  - [x] Backend：`GET /api/v1/history/questions`（使用者隔離 + limit/offset + newest-first）
  - [x] Backend：`GET /api/v1/history/questions` 僅顯示每個對話串首題（排除延伸問題）
  - [x] Backend：回傳 `answer_preview` 與 `charged_credits`
  - [x] Frontend：新增 `/history` 頁（列表顯示問題/答案摘要/時間/扣點）
  - [x] Frontend：登入保護與 return path（`/login?next=%2Fhistory`）
  - [x] Frontend：`載入更多`（offset pagination）
  - [x] 測試：backend history endpoint（401、分頁、排序、使用者隔離）
  - [x] 測試：frontend history e2e（未登入導轉、載入與追加）
  - [x] 後續：歷史詳情頁（完整答案、關聯交易、延伸問題樹與對應回覆）
- [x] 實作延伸問題三按鈕互動與即點即問扣點（同主題追問）
  - [x] Backend：`ask` 回應帶出 3 個互異 `followup_options`
  - [x] Backend：新增 followup 點擊提問流程（掛在原問題主題下）
  - [x] Backend：followup 點擊與一般提問共用 `reserve/capture/refund`，每次扣 1 點
  - [x] Backend：一個問題支援 0..N 延伸問題關聯
  - [x] Frontend：回答尾端渲染 3 個延伸問題按鈕
  - [x] Frontend：點擊任一按鈕即送出追問、顯示回覆與即時扣點
  - [x] Frontend：歷史問答詳細頁呈現延伸問題鏈與對應回答
  - [x] 測試：Backend followup API（404/403/409、點擊扣點、子問答建立、餘額不足回復 pending）
  - [x] 測試：Frontend followup 三按鈕顯示與點擊互動
- [ ] 實作後台最小可用：使用者、文件庫、訂單/點數流水查詢

## P2（穩定性 / 營運效率）
- [ ] 建立可觀測性：request_id、錯誤率、延遲、交易審計事件
- [ ] 安全強化：rate limit、輸入防護、key management、個資刪除流程
- [x] 開發流程穩定化：避免 commit 觸發 backend docker reload/shutdown
  - [x] Backend docker `uvicorn --reload` 監看限縮至 `app/` 並排除 `.venv/.git/__pycache__`
  - [x] pre-commit 改用系統層安裝（`uv tool install pre-commit && pre-commit install`），commit 流程不再依賴 `cd backend && uv sync`
- [x] 建立測試與 CI：backend 單元/整合、frontend 關鍵流程測試、自動化檢查
  - [x] backend lint（Ruff）導入與 blocking
  - [x] frontend lint（ESLint）導入與 blocking
  - [x] pre-commit hooks（pre-commit stage）導入
  - [x] 補齊 frontend 關鍵流程測試（提問、購點、餘額刷新）
  - [x] Frontend：補齊 Auth E2E 流程驗證（註冊/登入/登出/忘記密碼/重設密碼）
    - [x] Playwright 測試檔與案例已建立（待安裝依賴後執行）

## Test Cases（必測）
- [x] 未驗證 Email 呼叫 `POST /api/v1/ask` 應被拒絕
- [x] `register` 成功建立 user，重複 email 回傳 409
- [x] `verify-email` 成功啟用帳號，無效或過期 token 回傳 400
- [x] `login` 成功回傳 bearer token，錯誤帳密回傳 401
- [x] 餘額不足時提問失敗且不產生 capture
- [x] 提問成功流程：reserve -> capture
- [x] 提問失敗流程：reserve -> refund
- [ ] `ask` 回傳三層百分比固定 3 筆且總和 100
- [ ] 前台不顯示內部演算法名稱/規則編號/來源摘要
- [x] 三個主頁（`/`、`/wallet`、`/history`）需共用頂部導覽列，並可互相跳轉且正確高亮目前頁面
- [x] 導覽列帳號選單需顯示 email，並可由三個主頁執行登出
- [x] 未登入時導覽列右上角需顯示登入與註冊入口
- [x] 購點成功後餘額更新正確（含重試冪等）
- [x] 歷史紀錄可查完整問答與交易流水
- [x] 每次回答尾端固定顯示 3 個互異延伸問題按鈕
- [x] 點擊任一延伸問題按鈕需建立同主題子問答並扣 1 點（失敗回補）
- [x] 歷史問答詳細頁可查該問題底下全部延伸問題與對應回答

## 驗收定義
- [ ] 通過 PRD v0.4 第 9 節驗收標準
- [ ] 每個完成項目附測試證據（命令、輸出、截圖或 API 回應）
- [ ] 文件與實作一致（README / API schema / UI 文案同步）
  - [x] 更新 `backend/README.md`（API、錯誤碼、env）
  - [ ] 更新 `frontend` 相關說明（含 API 契約、環境變數、畫面流程）
  - [ ] 更新本文件完成勾選與子項
  - [ ] 補齊 backend/frontend 驗證命令與人工測試步驟（可直接執行）
  - [ ] 文件收尾需附 production 切換清單完成證據（API 行為、UI 文案、環境變數、部署流程）

## 備註與依賴
- Router 規則由工程團隊維護
- 前台維持不顯示來源摘要
- 固定扣點策略：每次提問 1 點

## Production Readiness（Dev -> Production）

### 安全與帳務一致性（高優先）
- [x] Auth：`POST /api/v1/auth/register` production 不回傳 `verification_token`
- [x] Auth：`POST /api/v1/auth/forgot-password` production 僅回 `202 accepted`，不回傳 `reset_token`
- [ ] Auth：導入 email provider（SES/SendGrid/Postmark 擇一）發送驗證信與重設信
- [ ] Auth：新增 resend-verification 流程（重發時舊 token 失效）
- [x] Secrets：移除弱預設 `JWT_SECRET`，production 啟動時必填且強度校驗
- [ ] Auth：規劃 access token 儲存策略（MVP localStorage -> production cookie/httpOnly）
- [ ] Billing：production 串接實際金流 callback 與簽章驗證
- [ ] DB：部署流程固定先 `alembic upgrade head`，並驗證 `alembic_version == head`

### 使用者體驗與可營運性（高優先）
- [ ] Frontend：驗證信/重設信改為「請查收 Email」文案（不顯示 token）
- [ ] Frontend：forgot/reset/verify 失敗訊息統一（過期、無效、重試引導）
- [x] Frontend：登入失效（401）全站一致導回 `/login` 並保留 return path
- [ ] Frontend：補齊 production 環境變數文件（API base URL、站點 URL）
- [ ] Observability：auth/交易事件新增 request_id 與審計記錄
- [ ] Runbook：新增「發生 UndefinedColumn / 版本不一致」標準排障步驟
