import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "資料刪除說明 | ELIN 神域引擎",
  description: "ELIN 神域引擎的資料刪除流程與聯絡方式"
};

export default function DataDeletionPage() {
  return (
    <main>
      <section className="card legal-page">
        <p className="legal-eyebrow">ELIN 神域引擎</p>
        <h1>資料刪除說明</h1>
        <p className="legal-updated">最後更新日期：2026-03-27</p>

        <p>
          如果你希望刪除與 ELIN 神域引擎相關的帳號資料、Messenger 綁定資料、固定問答資料、歷史問答或交易紀錄，請依照以下方式提出申請。
        </p>

        <h2>1. 申請方式</h2>
        <p>
          請寄信到 <a href="mailto:privacy@elin.example">privacy@elin.example</a>，
          並附上可協助我們辨識帳號的資訊，例如：
        </p>
        <ul className="legal-list">
          <li>你與本服務互動使用的 Facebook / Messenger 顯示名稱。</li>
          <li>你曾在本服務設定頁填寫的姓名。</li>
          <li>你發送過的最近一次問題時間，或其他可協助辨識帳號的資訊。</li>
        </ul>

        <h2>2. 我們會刪除哪些資料</h2>
        <ul className="legal-list">
          <li>Messenger 身份映射與綁定資料。</li>
          <li>WebView session 與固定問答資料。</li>
          <li>歷史問題、回答、延伸問題與相關點數流水。</li>
          <li>在法律或會計義務允許範圍內可刪除的相關資料。</li>
        </ul>

        <h2>3. 可能保留的資料</h2>
        <p>
          若法律、會計、反濫用或安全調查需要，我們可能保留最小必要資料一段時間。這類保留資料不會再用於一般產品功能。
        </p>

        <h2>4. 處理時間</h2>
        <p>我們會在收到請求後盡快處理，並於合理期間內回覆結果或要求補充資訊。</p>

        <div className="legal-links">
          <Link href="/privacy">查看隱私權政策</Link>
          <Link href="/">返回首頁</Link>
        </div>
      </section>
    </main>
  );
}
