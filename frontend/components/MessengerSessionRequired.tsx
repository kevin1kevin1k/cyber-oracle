"use client";

type MessengerSessionRequiredProps = {
  title: string;
  detail?: string;
};

export default function MessengerSessionRequired({
  title,
  detail = "請回 Messenger 對話，重新點擊對應功能入口；系統會再發一顆可直接開啟這個頁面的按鈕。",
}: MessengerSessionRequiredProps) {
  return (
    <main>
      <h1>{title}</h1>
      <section className="card">
        <p>目前這個頁面只支援從 Messenger WebView 進入。</p>
        <p>{detail}</p>
      </section>
    </main>
  );
}
