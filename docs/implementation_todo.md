# ELIN 神域引擎 Implementation Todo

## 說明
本清單依 `PRD.md v0.3` 與現有 codebase 差距整理，依優先度排序。  
狀態以 checkbox 追蹤，完成後請在 PR 附上對應測試證據。

## P0（必做 / 上線門檻）
- [ ] 建立 Auth 流程：register/login/logout/verify-email/forgot-password
- [x] 未驗證 Email 不可提問（API 與前端雙重限制）
- [ ] 建立核心資料表：users/sessions/questions/answers/credit_wallets/credit_transactions/orders/followups
- [ ] 實作點數交易引擎（固定扣 1 點）：reserve/capture/refund + idempotency
- [ ] 實作購點方案與訂單流程：1題 168、3題 358、5題 518
- [ ] 將 `POST /api/v1/ask` 從 mock 升級為可持久化流程（Intake/Router/Persist 最小可用）

## P1（高價值 / MVP 完整）
- [ ] 實作 RAG Top-3 + rerank + 百分比（總和 100）
- [ ] 實作 deterministic 分流（Router）與工程可維護規則配置
- [ ] 實作歷史問答頁（問題/答案/時間/扣點）
- [ ] 實作延伸問題保存與啟用（啟用再扣 1 點）
- [ ] 實作後台最小可用：使用者、文件庫、訂單/點數流水查詢

## P2（穩定性 / 營運效率）
- [ ] 建立可觀測性：request_id、錯誤率、延遲、交易審計事件
- [ ] 安全強化：rate limit、輸入防護、key management、個資刪除流程
- [ ] 建立測試與 CI：backend 單元/整合、frontend 關鍵流程測試、自動化檢查

## Test Cases（必測）
- [x] 未驗證 Email 呼叫 `POST /api/v1/ask` 應被拒絕
- [ ] 餘額不足時提問失敗且不產生 capture
- [ ] 提問成功流程：reserve -> capture
- [ ] 提問失敗流程：reserve -> refund
- [ ] `ask` 回傳三層百分比固定 3 筆且總和 100
- [ ] 前台不顯示內部演算法名稱/規則編號/來源摘要
- [ ] 購點成功後餘額更新正確（含重試冪等）
- [ ] 歷史紀錄可查完整問答與交易流水
- [ ] 延伸問題可保存為 pending，啟用後狀態改 used 並扣點

## 驗收定義
- [ ] 通過 PRD v0.3 第 9 節驗收標準
- [ ] 每個完成項目附測試證據（命令、輸出、截圖或 API 回應）
- [ ] 文件與實作一致（README / API schema / UI 文案同步）

## 備註與依賴
- Router 規則由工程團隊維護
- 前台維持不顯示來源摘要
- 固定扣點策略：每次提問 1 點
