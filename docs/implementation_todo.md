# ELIN 神域引擎 Implementation Todo

## 說明
本清單依 `PRD.md v0.3` 與現有 codebase 差距整理，依優先度排序。
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
- [ ] 實作 deterministic 分流（Router）與工程可維護規則配置
- [ ] 實作歷史問答頁（問題/答案/時間/扣點）
- [ ] 實作延伸問題保存與啟用（啟用再扣 1 點）
- [ ] 實作後台最小可用：使用者、文件庫、訂單/點數流水查詢

## P2（穩定性 / 營運效率）
- [ ] 建立可觀測性：request_id、錯誤率、延遲、交易審計事件
- [ ] 安全強化：rate limit、輸入防護、key management、個資刪除流程
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
- [x] 購點成功後餘額更新正確（含重試冪等）
- [ ] 歷史紀錄可查完整問答與交易流水
- [ ] 延伸問題可保存為 pending，啟用後狀態改 used 並扣點

## 驗收定義
- [ ] 通過 PRD v0.3 第 9 節驗收標準
- [ ] 每個完成項目附測試證據（命令、輸出、截圖或 API 回應）
- [ ] 文件與實作一致（README / API schema / UI 文案同步）
  - [ ] 更新 `backend/README.md`（API、錯誤碼、env）
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
- [ ] Auth：`POST /api/v1/auth/register` production 不回傳 `verification_token`
- [ ] Auth：`POST /api/v1/auth/forgot-password` production 僅回 `202 accepted`，不回傳 `reset_token`
- [ ] Auth：導入 email provider（SES/SendGrid/Postmark 擇一）發送驗證信與重設信
- [ ] Auth：新增 resend-verification 流程（重發時舊 token 失效）
- [ ] Secrets：移除弱預設 `JWT_SECRET`，production 啟動時必填且強度校驗
- [ ] Auth：規劃 access token 儲存策略（MVP localStorage -> production cookie/httpOnly）
- [ ] Billing：`simulate-paid` 僅限非 production（環境守衛 + 權限限制）
- [ ] Billing：production 串接實際金流 callback 與簽章驗證
- [ ] DB：部署流程固定先 `alembic upgrade head`，並驗證 `alembic_version == head`

### 使用者體驗與可營運性（高優先）
- [ ] Frontend：驗證信/重設信改為「請查收 Email」文案（不顯示 token）
- [ ] Frontend：forgot/reset/verify 失敗訊息統一（過期、無效、重試引導）
- [ ] Frontend：登入失效（401）全站一致導回 `/login` 並保留 return path
- [ ] Frontend：補齊 production 環境變數文件（API base URL、站點 URL）
- [ ] Observability：auth/交易事件新增 request_id 與審計記錄
- [ ] Runbook：新增「發生 UndefinedColumn / 版本不一致」標準排障步驟
