"use client";

import MessengerSessionRequired from "@/components/MessengerSessionRequired";

export default function VerifyEmailPage() {
  return (
    <MessengerSessionRequired
      title="Email 驗證已停用"
      detail="目前不再使用 Email 驗證流程。若需要使用服務，請直接從 Messenger 重新進入。"
    />
  );
}
