"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api";
import { saveAuthSession } from "@/lib/auth";
import { linkMessengerIdentity } from "@/lib/messenger";

export default function MessengerLinkPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [nextPath, setNextPath] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "linking" | "linked">("idle");
  const [error, setError] = useState<string | null>(null);
  const [linkStatus, setLinkStatus] = useState<"linked_new" | "session_restored" | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token") ?? "");
    const requestedNext = params.get("next");
    setNextPath(requestedNext && requestedNext.startsWith("/") ? requestedNext : null);
  }, []);

  useEffect(() => {
    if (!token) {
      setError("缺少 Messenger 綁定資訊，請回 Messenger 重新點擊按鈕。");
      return;
    }

    let active = true;
    async function runLink() {
      setStatus("linking");
      setError(null);
      try {
        const payload = await linkMessengerIdentity(token);
        if (!active) {
          return;
        }
        saveAuthSession({
          accessToken: payload.access_token,
          userId: payload.user_id,
          userLabel: "Messenger 已連結",
        });
        if (nextPath) {
          router.replace(nextPath);
          return;
        }
        if (payload.link_status === "linked_new") {
          router.replace("/?from=messenger-first-link");
          return;
        }
        setLinkStatus(payload.link_status);
        setStatus("linked");
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError) {
          if (err.code === "MESSENGER_LINK_TOKEN_INVALID") {
            setError("綁定連結無效或已過期，請回 Messenger 重新點擊綁定按鈕。");
            return;
          }
          if (err.code === "MESSENGER_IDENTITY_NOT_FOUND") {
            setError("找不到對應的 Messenger 身份，請回 Messenger 重新發送訊息後再試一次。");
            return;
          }
        }
        setError(err instanceof Error ? err.message : "Messenger 綁定失敗");
      } finally {
        if (active) {
          setStatus((prev) => (prev === "linked" ? prev : "idle"));
        }
      }
    }

    void runLink();
    return () => {
      active = false;
    };
  }, [nextPath, router, token]);

  return (
    <main>
      <h1>Messenger 帳號綁定</h1>
      <section className="card">
        {status === "linked" ? (
          <div className="answer">
            <p>
              {linkStatus === "session_restored"
                ? "已恢復 Messenger WebView session，請回 Messenger 繼續使用。"
                : "綁定完成，請回 Messenger 繼續提問。"}
            </p>
            <p className="helper-links">
              <Link href="/">返回首頁</Link>
            </p>
          </div>
        ) : status === "linking" ? (
          <p>綁定中...</p>
        ) : (
          <p>準備驗證 Messenger 綁定資訊...</p>
        )}
        {error && (
          <div className="answer">
            <p className="error">{error}</p>
            <p className="helper-links">
              <Link href="/">返回首頁</Link>
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
