"use client";

import { FormEvent, useMemo, useState } from "react";

type AskResponse = {
  answer: string;
  source: "mock";
  layer_percentages: { label: "主層" | "輔層" | "參照層"; pct: number }[];
  request_id: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

  const canSubmit = useMemo(() => question.trim().length > 0 && !loading, [question, loading]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    if (!question.trim()) {
      setError("請先輸入問題。");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ question, lang: "zh", mode: "analysis" })
      });

      if (!res.ok) {
        const payload = await res.text();
        throw new Error(payload || "API 請求失敗");
      }

      const data = (await res.json()) as AskResponse;
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "發生未知錯誤");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>ELIN 神域引擎 MVP</h1>
      <p>輸入問題後，系統會呼叫 FastAPI 後端並回傳 mock 結果。</p>

      <section className="card">
        <form onSubmit={handleSubmit}>
          <label htmlFor="question">問題內容</label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="請輸入你想詢問的問題"
          />
          <button type="submit" disabled={!canSubmit}>
            {loading ? "送出中..." : "送出問題"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <div className="answer">
            <p>
              <strong>回答：</strong>
              {result.answer}
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
          </div>
        )}
      </section>
    </main>
  );
}
