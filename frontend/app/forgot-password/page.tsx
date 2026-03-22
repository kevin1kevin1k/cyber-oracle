"use client";

import MessengerSessionRequired from "@/components/MessengerSessionRequired";

export default function ForgotPasswordPage() {
  return (
    <MessengerSessionRequired
      title="密碼重設已停用"
      detail="目前不再提供 Email/Password 找回流程，請從 Messenger WebView 使用帳號。"
    />
  );
}
