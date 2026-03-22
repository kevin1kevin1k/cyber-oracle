"use client";

import MessengerSessionRequired from "@/components/MessengerSessionRequired";

export default function LoginPage() {
  return (
    <MessengerSessionRequired
      title="登入已停用"
      detail="目前網站登入僅支援從 Messenger WebView 建立 session，請回 Messenger 點擊綁定按鈕。"
    />
  );
}
