"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { apiRequest } from "@/lib/api";

type ForgotPasswordResponse = {
  status: "accepted";
  reset_token?: string | null;
};

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ForgotPasswordResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const payload = await apiRequest<ForgotPasswordResponse>("/api/v1/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失敗");
    } finally {
      setLoading(false);
    }
  }

  const resetToken = result?.reset_token ?? "";

  return (
    <main>
      <h1>忘記密碼</h1>
      <section className="card">
        <form onSubmit={handleSubmit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <button type="submit" disabled={loading}>
            {loading ? "送出中..." : "送出"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        {result && (
          <div className="answer">
            <p>已送出重設請求（若帳號存在）。</p>
            {resetToken && (
              <>
                <p>
                  <strong>開發環境重設 token：</strong>
                </p>
                <p className="token-box">{resetToken}</p>
                <p>
                  <Link href={`/reset-password?token=${encodeURIComponent(resetToken)}`}>
                    帶入 token 前往重設密碼
                  </Link>
                </p>
              </>
            )}
          </div>
        )}
        <p className="helper-links">
          <Link href="/login">返回登入</Link>
        </p>
      </section>
    </main>
  );
}
