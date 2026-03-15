"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { getAuthSession } from "@/lib/auth";
import { linkMessengerIdentity } from "@/lib/messenger";
import { buildLoginPathWithNext } from "@/lib/navigation";

export default function MessengerLinkPage() {
  const router = useRouter();
  const [authLoaded, setAuthLoaded] = useState(false);
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<"idle" | "linking" | "linked">("idle");
  const [error, setError] = useState<string | null>(null);

  const currentPath = useMemo(() => {
    if (typeof window === "undefined") {
      return "/messenger/link";
    }
    return `${window.location.pathname}${window.location.search}`;
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token") ?? "");
    setAuthSession(getAuthSession());
    setAuthLoaded(true);
  }, []);

  useEffect(() => {
    if (!authLoaded) {
      return;
    }
    if (!token) {
      setError("缺少 Messenger 綁定資訊，請回 Messenger 重新點擊按鈕。");
      return;
    }
    if (!authSession?.accessToken) {
      router.replace(buildLoginPathWithNext(currentPath));
      return;
    }
    if (!authSession.emailVerified) {
      setError("請先完成 Email 驗證後，再回到這裡完成 Messenger 綁定。");
      return;
    }

    let active = true;
    async function runLink() {
      setStatus("linking");
      setError(null);
      try {
        await linkMessengerIdentity(token);
        if (!active) {
          return;
        }
        setStatus("linked");
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError) {
          if (err.status === 401) {
            router.replace(buildLoginPathWithNext(currentPath));
            return;
          }
          if (err.code === "MESSENGER_LINK_TOKEN_INVALID") {
            setError("綁定連結無效或已過期，請回 Messenger 重新點擊綁定按鈕。");
            return;
          }
          if (err.code === "MESSENGER_IDENTITY_NOT_FOUND") {
            setError("找不到對應的 Messenger 身份，請回 Messenger 重新發送訊息後再試一次。");
            return;
          }
          if (err.code === "MESSENGER_IDENTITY_ALREADY_LINKED") {
            setError("這個 Messenger 帳號已經綁定到其他網站帳號。");
            return;
          }
          if (err.code === "EMAIL_NOT_VERIFIED") {
            setError("請先完成 Email 驗證後，再回到這裡完成 Messenger 綁定。");
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
  }, [authLoaded, authSession, currentPath, router, token]);

  return (
    <main>
      <h1>Messenger 帳號綁定</h1>
      <section className="card">
        {!authLoaded ? (
          <p>登入狀態載入中...</p>
        ) : status === "linked" ? (
          <div className="answer">
            <p>綁定完成，請回 Messenger 繼續提問。</p>
            <p className="helper-links">
              <Link href="/">返回首頁</Link>
              <span> · </span>
              <Link href="/wallet">前往錢包</Link>
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
              <Link href="/login">前往登入</Link>
              <span> · </span>
              <Link href="/register">註冊新帳號</Link>
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
