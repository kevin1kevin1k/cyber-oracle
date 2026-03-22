"use client";

import MessengerSessionRequired from "@/components/MessengerSessionRequired";

export default function RegisterPage() {
  return (
    <MessengerSessionRequired
      title="註冊已停用"
      detail="目前帳號建立改由 Messenger 綁定流程自動完成，請回 Messenger 點擊綁定按鈕。"
    />
  );
}
