"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { getAuthSession } from "@/lib/auth";
import { getAskHistory, type AskHistoryItem } from "@/lib/history";
import { buildLoginPathWithNext } from "@/lib/navigation";
import AppTopNav from "@/components/AppTopNav";

const PAGE_SIZE = 20;

function formatDatetime(value: string): string {
  return new Date(value).toLocaleString("zh-TW", { hour12: false });
}

function formatSource(source: AskHistoryItem["source"]): string {
  if (source === "mock") {
    return "Mock";
  }
  return source.toUpperCase();
}

export default function HistoryPage() {
  const router = useRouter();
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [items, setItems] = useState<AskHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const hasMore = useMemo(() => items.length < total, [items.length, total]);

  useEffect(() => {
    setAuthSession(getAuthSession());
    setAuthLoaded(true);
  }, []);

  const loadHistory = useCallback(
    async (offset: number, append: boolean) => {
      const payload = await getAskHistory(PAGE_SIZE, offset);
      setItems((prev) => (append ? [...prev, ...payload.items] : payload.items));
      setTotal(payload.total);
    },
    []
  );

  useEffect(() => {
    if (!authLoaded) {
      return;
    }

    if (!isLoggedIn) {
      router.replace(buildLoginPathWithNext("/history"));
      return;
    }

    let active = true;
    async function loadInitial() {
      setLoading(true);
      setError(null);
      try {
        await loadHistory(0, false);
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError && err.status === 401) {
          router.replace(buildLoginPathWithNext("/history"));
          return;
        }
        setError(err instanceof Error ? err.message : "讀取歷史問答失敗");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadInitial();
    return () => {
      active = false;
    };
  }, [authLoaded, isLoggedIn, loadHistory, router]);

  async function handleLoadMore() {
    if (loadingMore || !hasMore) {
      return;
    }
    setLoadingMore(true);
    setError(null);
    try {
      await loadHistory(items.length, true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(buildLoginPathWithNext("/history"));
        return;
      }
      setError(err instanceof Error ? err.message : "讀取更多歷史問答失敗");
    } finally {
      setLoadingMore(false);
    }
  }

  if (!authLoaded) {
    return (
      <main>
        <h1>歷史問答</h1>
        <p>登入狀態載入中...</p>
      </main>
    );
  }

  if (!isLoggedIn) {
    return null;
  }

  return (
    <main>
      <AppTopNav />
      <h1>歷史問答</h1>

      <section className="card history-header">
        <p>
          <strong>總筆數：</strong>
          {loading ? "載入中..." : `${total} 筆`}
        </p>
      </section>

      <section className="card history-section">
        <h2>問答紀錄</h2>
        {loading ? (
          <p>載入中...</p>
        ) : items.length === 0 ? (
          <p>目前沒有歷史問答。</p>
        ) : (
          <ul className="history-list">
            {items.map((item) => (
              <li key={item.question_id} className="history-item">
                <p>
                  <strong>問題：</strong>
                  {item.question_text}
                </p>
                <p>
                  <strong>答案摘要：</strong>
                  {item.answer_preview}
                </p>
                <p>
                  <strong>來源：</strong>
                  {formatSource(item.source)}
                </p>
                <p>
                  <strong>扣點：</strong>
                  {item.charged_credits} 點
                </p>
                <p>
                  <strong>時間：</strong>
                  {formatDatetime(item.created_at)}
                </p>
                <p className="helper-links">
                  <Link href={`/history/${item.question_id}`}>查看詳情</Link>
                </p>
              </li>
            ))}
          </ul>
        )}
        {!loading && hasMore && (
          <button type="button" onClick={() => void handleLoadMore()} disabled={loadingMore}>
            {loadingMore ? "載入中..." : "載入更多"}
          </button>
        )}
      </section>

      {error && <p className="error">{error}</p>}
    </main>
  );
}
