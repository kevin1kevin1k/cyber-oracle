"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { getAuthSession } from "@/lib/auth";
import {
  getAskHistoryDetail,
  type AskHistoryDetailNode,
  type AskHistoryDetailResponse,
  type AskHistoryDetailTransactionItem,
} from "@/lib/history";
import { buildLoginPathWithNext } from "@/lib/navigation";

function formatDatetime(value: string): string {
  return new Date(value).toLocaleString("zh-TW", { hour12: false });
}

function formatSource(source: AskHistoryDetailNode["source"]): string {
  if (source === "mock") {
    return "Mock";
  }
  return source.toUpperCase();
}

function formatTransactionAction(action: AskHistoryDetailTransactionItem["action"]): string {
  if (action === "capture") {
    return "扣點";
  }
  return "回補";
}

function HistoryNode({ node, depth = 0 }: { node: AskHistoryDetailNode; depth?: number }) {
  return (
    <li className="history-detail-node" style={{ marginLeft: depth * 16 }}>
      <p>
        <strong>問題：</strong>
        {node.question_text}
      </p>
      <p>
        <strong>完整回答：</strong>
        {node.answer_text}
      </p>
      <p>
        <strong>來源：</strong>
        {formatSource(node.source)}
      </p>
      <p>
        <strong>扣點：</strong>
        {node.charged_credits} 點
      </p>
      <p>
        <strong>時間：</strong>
        {formatDatetime(node.created_at)}
      </p>
      <p>
        <strong>Request ID：</strong>
        {node.request_id}
      </p>
      <p>
        <strong>三層比例：</strong>
        {node.layer_percentages.map((layer) => `${layer.label} ${layer.pct}%`).join(" / ")}
      </p>
      {node.children.length > 0 && (
        <ul className="history-detail-tree">
          {node.children.map((child) => (
            <HistoryNode key={child.question_id} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function HistoryDetailPage() {
  const router = useRouter();
  const params = useParams<{ questionId: string }>();
  const questionId = useMemo(
    () => (typeof params?.questionId === "string" ? params.questionId : ""),
    [params]
  );
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AskHistoryDetailResponse | null>(null);

  const isLoggedIn = !!authSession?.accessToken;

  useEffect(() => {
    setAuthSession(getAuthSession());
    setAuthLoaded(true);
  }, []);

  const loadDetail = useCallback(async () => {
    if (!questionId) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setNotFound(false);
    setError(null);
    try {
      const payload = await getAskHistoryDetail(questionId);
      setDetail(payload);
      if (questionId !== payload.root.question_id) {
        router.replace(`/history/${payload.root.question_id}`);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(buildLoginPathWithNext(`/history/${questionId}`));
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        return;
      }
      setError(err instanceof Error ? err.message : "讀取歷史詳情失敗");
    } finally {
      setLoading(false);
    }
  }, [questionId, router]);

  useEffect(() => {
    if (!authLoaded) {
      return;
    }
    if (!isLoggedIn) {
      router.replace(buildLoginPathWithNext(`/history/${questionId || ""}`));
      return;
    }
    void loadDetail();
  }, [authLoaded, isLoggedIn, loadDetail, questionId, router]);

  if (!authLoaded) {
    return (
      <main>
        <h1>歷史問答詳情</h1>
        <p>登入狀態載入中...</p>
      </main>
    );
  }

  if (!isLoggedIn) {
    return null;
  }

  return (
    <main>
      <h1>歷史問答詳情</h1>
      <p className="helper-links">
        <Link href="/history">返回歷史問答</Link> · <Link href="/">返回提問頁</Link>
      </p>

      <section className="card history-section">
        {loading && <p>載入中...</p>}
        {!loading && notFound && <p>查無此歷史問答，或你沒有權限查看。</p>}
        {!loading && !notFound && detail && (
          <>
            <h2>問答樹</h2>
            <ul className="history-detail-tree">
              <HistoryNode node={detail.root} />
            </ul>
            <h2>關聯交易</h2>
            {detail.transactions.length === 0 ? (
              <p>目前沒有關聯交易。</p>
            ) : (
              <ul className="tx-list">
                {detail.transactions.map((tx) => (
                  <li key={tx.id} className="tx-item">
                    <p>
                      <strong>類型：</strong>
                      {formatTransactionAction(tx.action)}
                    </p>
                    <p>
                      <strong>點數：</strong>
                      {tx.amount}
                    </p>
                    <p>
                      <strong>原因碼：</strong>
                      {tx.reason_code}
                    </p>
                    <p>
                      <strong>Question ID：</strong>
                      {tx.question_id ?? "-"}
                    </p>
                    <p>
                      <strong>Request ID：</strong>
                      {tx.request_id}
                    </p>
                    <p>
                      <strong>時間：</strong>
                      {formatDatetime(tx.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      {error && <p className="error">{error}</p>}
    </main>
  );
}
