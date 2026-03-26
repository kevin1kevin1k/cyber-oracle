import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "隱私權政策 | ELIN 神域引擎",
  description: "ELIN 神域引擎 Messenger 問答服務的隱私權政策"
};

export default function PrivacyPage() {
  return (
    <main>
      <section className="card legal-page">
        <p className="legal-eyebrow">ELIN 神域引擎</p>
        <h1>隱私權政策</h1>
        <p className="legal-updated">最後更新日期：2026-03-27</p>

        <p>
          ELIN 神域引擎（以下稱「本服務」）透過 Facebook Messenger 與 WebView
          提供 AI 問答功能。本頁說明我們會收集哪些資料、如何使用這些資料，以及你可以如何聯絡我們或要求刪除資料。
        </p>

        <h2>1. 我們會收集哪些資料</h2>
        <p>當你使用本服務時，我們可能收集以下資料：</p>
        <ul className="legal-list">
          <li>Messenger 身份識別資料，例如 PSID、Page 關聯資訊與綁定狀態。</li>
          <li>你在 WebView 主動提供的固定問答資料，例如姓名與母親姓名。</li>
          <li>你輸入的問題、延伸問題、回答內容與歷史問答紀錄。</li>
          <li>點數餘額、點數交易、訂單與相關操作記錄。</li>
          <li>系統操作與除錯所需的技術紀錄，例如 request id、錯誤訊息與基本存取日誌。</li>
        </ul>

        <h2>2. 我們如何使用資料</h2>
        <ul className="legal-list">
          <li>提供 Messenger 問答、WebView 綁定、設定頁與歷史查詢功能。</li>
          <li>在提問前自動帶入你已儲存的固定問答資料，以產生回答。</li>
          <li>維護點數扣點、回補、交易對帳與帳號安全。</li>
          <li>診斷錯誤、提升服務穩定性並防止濫用。</li>
        </ul>

        <h2>3. 第三方服務</h2>
        <p>本服務目前可能使用以下第三方服務處理資料：</p>
        <ul className="legal-list">
          <li>Meta / Facebook：處理 Messenger 平台訊息傳遞與 Page 相關功能。</li>
          <li>OpenAI：處理 AI 問答與檢索相關請求。</li>
          <li>Render：提供網站、API 與資料庫託管。</li>
          <li>若未來啟用正式購點，付款資料將由支付服務商處理，不會由本服務自行儲存完整信用卡資料。</li>
        </ul>

        <h2>4. 資料保存與刪除</h2>
        <p>
          我們會在提供服務、維護歷史紀錄、交易對帳與安全排障所需期間內保存資料。若你希望刪除帳號或相關資料，可依照
          <Link href="/data-deletion">資料刪除說明</Link>
          與我們聯絡。
        </p>

        <h2>5. 資料分享</h2>
        <p>
          我們不會將你的個人資料出售給第三方。資料僅會在提供本服務、遵守法律義務、處理支付需求或維護系統安全時，於必要範圍內交由相關服務供應商處理。
        </p>

        <h2>6. 你的選擇與權利</h2>
        <ul className="legal-list">
          <li>你可以透過 WebView 設定頁更新姓名與母親姓名等固定資料。</li>
          <li>你可以要求刪除帳號與歷史資料。</li>
          <li>若你不希望繼續使用本服務，可停止與 Messenger bot 互動。</li>
        </ul>

        <h2>7. 聯絡方式</h2>
        <p>
          若你對本隱私權政策有任何問題，或需要提出資料查詢與刪除請求，請來信：
          <a href="mailto:privacy@elin.example">privacy@elin.example</a>
        </p>

        <div className="legal-links">
          <Link href="/data-deletion">查看資料刪除說明</Link>
          <Link href="/">返回首頁</Link>
        </div>
      </section>
    </main>
  );
}
