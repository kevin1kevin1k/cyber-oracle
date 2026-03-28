"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import AppTopNav from "@/components/AppTopNav";
import { ApiError } from "@/lib/api";
import { getAuthSession } from "@/lib/auth";
import { getCreditsBalance } from "@/lib/billing";
import { getMyProfile } from "@/lib/profile";

export default function HomePage() {
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [paymentsEnabled, setPaymentsEnabled] = useState(true);
  const [profileComplete, setProfileComplete] = useState<boolean | null>(null);

  const isLoggedIn = !!authSession?.accessToken;

  useEffect(() => {
    setAuthSession(getAuthSession());
    setAuthLoaded(true);
  }, []);

  const refreshBalance = useCallback(async () => {
    if (!authLoaded || !isLoggedIn) {
      setCreditBalance(null);
      return;
    }
    try {
      const payload = await getCreditsBalance();
      setCreditBalance(payload.balance);
      setPaymentsEnabled(payload.payments_enabled ?? true);
    } catch {
      setCreditBalance(null);
      setPaymentsEnabled(true);
    }
  }, [authLoaded, isLoggedIn]);

  const refreshProfile = useCallback(async () => {
    if (!authLoaded || !isLoggedIn) {
      setProfileComplete(null);
      return;
    }
    try {
      const payload = await getMyProfile();
      setProfileComplete(payload.is_complete);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthSession(null);
        setProfileComplete(null);
        return;
      }
      setProfileComplete(false);
      setError(err instanceof Error ? err.message : "讀取設定失敗");
    }
  }, [authLoaded, isLoggedIn]);

  useEffect(() => {
    let active = true;
    async function loadHomeState() {
      if (!active) {
        return;
      }
      await Promise.all([refreshBalance(), refreshProfile()]);
    }
    void loadHomeState();
    return () => {
      active = false;
    };
  }, [refreshBalance, refreshProfile]);

  return (
    <main>
      <AppTopNav />
      <h1>Messenger 配套首頁</h1>

      <section className="card">
        <div className="auth-bar">
          {!authLoaded ? (
            <p>登入狀態載入中...</p>
          ) : isLoggedIn ? (
            <p>
              {profileComplete === false
                ? "目前已連結 Messenger，但還沒完成個人設定。"
                : "目前已連結 Messenger，可回 Messenger 直接提問。"}
            </p>
          ) : (
            <p>這個頁面僅支援從 Messenger WebView 進入。請回 Messenger 點擊綁定或功能按鈕。</p>
          )}
          {isLoggedIn && (
            <p className="credit-line">
              目前點數：<span className="credit-count">{creditBalance === null ? "讀取中..." : `${creditBalance} 點`}</span>
            </p>
          )}
        </div>
        <p>
          這裡是 Messenger WebView 的配套首頁，用來查看帳號狀態、完成固定資料設定，以及進入點數錢包與歷史問答。
          真正提問請回 Messenger 對話進行。
        </p>
        {error && <p className="error">{error}</p>}
      </section>

      {isLoggedIn && profileComplete === false && (
        <section className="card">
          <h2>下一步先完成固定資料設定</h2>
          <p>這套問答會固定使用你的姓名與母親姓名作為背景資料。完成後，就能回 Messenger 直接提問。</p>
          <p className="helper-links">
            <Link href="/settings">先完成個人設定</Link>
          </p>
        </section>
      )}

      {isLoggedIn && (
        <section className="card">
          <h2>常用入口</h2>
          <p>設定固定資料、查看點數與瀏覽歷史問答，都可以從這裡進入。</p>
          <p className="helper-links">
            <Link href="/settings">設定</Link> · <Link href="/wallet">點數錢包</Link> · <Link href="/history">歷史問答</Link>
          </p>
          {!paymentsEnabled && <p>目前為體驗版，暫未開放購點；若點數用完，請等待後續開放通知。</p>}
        </section>
      )}

      {!isLoggedIn && (
        <section className="card">
          <h2>如何開始使用</h2>
          <p>請從 Messenger 對話中點擊綁定或功能按鈕。完成 WebView session 建立後，你就能在這裡查看設定、錢包與歷史。</p>
        </section>
      )}
    </main>
  );
}
