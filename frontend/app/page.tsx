"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { askFollowup, askQuestion, type AskResponse } from "@/lib/ask";
import { getAuthSession } from "@/lib/auth";
import { getCreditsBalance } from "@/lib/billing";
import AppTopNav from "@/components/AppTopNav";

export default function HomePage() {
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [pendingAskKey, setPendingAskKey] = useState<string | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [paymentsEnabled, setPaymentsEnabled] = useState(true);
  const [creditDelta, setCreditDelta] = useState<number | null>(null);
  const [activeFollowupId, setActiveFollowupId] = useState<string | null>(null);
  const creditDeltaTimerRef = useRef<number | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const canSubmit = useMemo(
    () => authLoaded && question.trim().length > 0 && !loading && isLoggedIn,
    [authLoaded, question, loading, isLoggedIn]
  );

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

  useEffect(() => {
    let active = true;
    async function loadBalance() {
      if (!active) {
        return;
      }
      await refreshBalance();
    }
    void loadBalance();
    return () => {
      active = false;
    };
  }, [refreshBalance]);

  useEffect(() => {
    return () => {
      if (creditDeltaTimerRef.current !== null) {
        window.clearTimeout(creditDeltaTimerRef.current);
      }
    };
  }, []);

  const applyImmediateCreditDeduction = useCallback(() => {
    setCreditBalance((prev) => (prev === null ? null : Math.max(0, prev - 1)));
    setCreditDelta(-1);
    if (creditDeltaTimerRef.current !== null) {
      window.clearTimeout(creditDeltaTimerRef.current);
    }
    creditDeltaTimerRef.current = window.setTimeout(() => {
      setCreditDelta(null);
    }, 1000);
    void refreshBalance();
  }, [refreshBalance]);

  function handleAskApiError(err: unknown) {
      if (err instanceof ApiError) {
      if (err.status === 401 || err.code === "UNAUTHORIZED") {
        setAuthSession(null);
        setError("登入狀態已失效，請回 Messenger 重新進入。");
        return;
      }
      if (err.code === "INSUFFICIENT_CREDIT") {
        setError(
          paymentsEnabled
            ? "點數不足，請先購點再提問。"
            : "體驗點數已用完，目前暫未開放購點。"
        );
        return;
      }
      if (err.code === "PAYMENTS_DISABLED") {
        setPaymentsEnabled(false);
        setError("目前為體驗版，暫未開放購點。");
        return;
      }
      if (err.status === 403) {
        setError("這個延伸問題不屬於你的帳號。");
        return;
      }
      if (err.status === 404) {
        setError("延伸問題不存在或已失效，請重新提問。");
        return;
      }
      if (err.status === 409) {
        setError("這個延伸問題已被使用，請改選其他按鈕。");
        return;
      }
    }
    setError(err instanceof Error ? err.message : "發生未知錯誤");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    if (!authLoaded) {
      setError("登入狀態載入中，請稍後再試。");
      return;
    }

    if (!isLoggedIn) {
      setError("請從 Messenger 開啟這個頁面或重新點擊綁定按鈕後再提問。");
      return;
    }

    if (!question.trim()) {
      setError("請先輸入問題。");
      return;
    }

    setLoading(true);
    const askKey = pendingAskKey ?? crypto.randomUUID();
    if (!pendingAskKey) {
      setPendingAskKey(askKey);
    }
    try {
      const data = await askQuestion(question, askKey);
      setResult(data);
      setPendingAskKey(null);
      applyImmediateCreditDeduction();
    } catch (err) {
      handleAskApiError(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleFollowupAsk(followupId: string) {
    if (loading || activeFollowupId !== null) {
      return;
    }
    setError(null);
    setActiveFollowupId(followupId);
    try {
      const data = await askFollowup(followupId);
      setResult(data);
      applyImmediateCreditDeduction();
    } catch (err) {
      handleAskApiError(err);
    } finally {
      setActiveFollowupId(null);
    }
  }

  return (
    <main>
      <AppTopNav />
      <h1>ELIN 神域引擎 MVP</h1>

      <section className="card">
        <div className="auth-bar">
          {!authLoaded ? (
            <p>登入狀態載入中...</p>
          ) : isLoggedIn ? (
            <p>目前已連結 Messenger，可直接提問。</p>
          ) : (
            <p>
              這個頁面僅支援從 Messenger WebView 進入。請回 Messenger 點擊綁定或功能按鈕。
            </p>
          )}
          {isLoggedIn && (
            <p className="credit-line">
              目前點數：<span className="credit-count">{creditBalance === null ? "讀取中..." : `${creditBalance} 點`}</span>
              {creditDelta !== null && <span className="credit-delta">{creditDelta}</span>}
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit}>
          <label htmlFor="question">問題內容</label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => {
              if (e.target.value !== question) {
                setPendingAskKey(null);
              }
              setQuestion(e.target.value);
            }}
            placeholder="請輸入你想詢問的問題"
            disabled={!authLoaded || !isLoggedIn}
          />
          <button type="submit" disabled={!canSubmit}>
            {loading ? "送出中..." : "送出問題"}
          </button>
        </form>

        {error && (
          <p className="error">
            {error}
            {paymentsEnabled && error.includes("點數不足") && (
              <>
                {" "}
                <Link href="/wallet?from=ask-402">立即前往購點</Link>
              </>
            )}
          </p>
        )}

        {result && (
          <div className="answer">
            <p>
              <strong>回答：</strong>
              {result.answer}
            </p>
            {Array.isArray(result.followup_options) && result.followup_options.length > 0 && (
              <div className="followup-section">
                <p>
                  <strong>延伸問題：</strong>
                </p>
                <div className="followup-buttons">
                  {result.followup_options.map((followup) => {
                    const isActive = activeFollowupId === followup.id;
                    return (
                      <button
                        key={followup.id}
                        type="button"
                        className="followup-button"
                        disabled={loading || activeFollowupId !== null}
                        onClick={() => void handleFollowupAsk(followup.id)}
                      >
                        {isActive ? "送出延伸問題中..." : followup.content}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
