"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { askFollowup, askQuestion, type AskResponse } from "@/lib/ask";
import { getAuthSession } from "@/lib/auth";
import { getCreditsBalance } from "@/lib/billing";
import { buildLoginPathWithNext } from "@/lib/navigation";
import AppTopNav from "@/components/AppTopNav";

export default function HomePage() {
  const router = useRouter();
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [pendingAskKey, setPendingAskKey] = useState<string | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [creditDelta, setCreditDelta] = useState<number | null>(null);
  const [activeFollowupId, setActiveFollowupId] = useState<string | null>(null);
  const creditDeltaTimerRef = useRef<number | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const isVerified = !!authSession?.emailVerified;
  const canSubmit = useMemo(
    () => authLoaded && question.trim().length > 0 && !loading && isLoggedIn && isVerified,
    [authLoaded, question, loading, isLoggedIn, isVerified]
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
    } catch {
      setCreditBalance(null);
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
        setError("尚未登入或登入資訊失效，請重新登入。");
        router.replace(buildLoginPathWithNext("/"));
        return;
      }
      if (err.code === "EMAIL_NOT_VERIFIED") {
        setError("Email 尚未驗證，請先完成驗證後再提問。");
        return;
      }
      if (err.code === "INSUFFICIENT_CREDIT") {
        setError("點數不足，請先購點再提問。");
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
      setError("請先登入後再提問。");
      return;
    }

    if (!isVerified) {
      setError("Email 尚未驗證，請先完成驗證後再提問。");
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
      <p>輸入問題後，系統會呼叫 FastAPI 後端並回傳結果。</p>

      <section className="card">
        <div className="auth-bar">
          {!authLoaded ? (
            <p>登入狀態載入中...</p>
          ) : isLoggedIn ? (
            <>
              {!isVerified && (
                <p className="error-inline">
                  你已登入但尚未驗證 Email。請前往 <Link href="/verify-email">Email 驗證</Link>
                </p>
              )}
            </>
          ) : (
            <p>
              尚未登入，請先 <Link href="/login">登入</Link> 或 <Link href="/register">註冊</Link>。
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
            disabled={!authLoaded || !isLoggedIn || !isVerified}
          />
          <button type="submit" disabled={!canSubmit}>
            {loading ? "送出中..." : "送出問題"}
          </button>
        </form>

        {error && (
          <p className="error">
            {error}
            {error.includes("點數不足") && (
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
            <p>
              <strong>來源：</strong>
              {result.source}
            </p>
            <p>
              <strong>Request ID：</strong>
              {result.request_id}
            </p>
            <p>
              <strong>三層比例：</strong>
            </p>
            <ul>
              {result.layer_percentages.map((layer) => (
                <li key={layer.label}>{`${layer.label}: ${layer.pct}%`}</li>
              ))}
            </ul>
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
