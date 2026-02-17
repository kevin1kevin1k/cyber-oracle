"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { apiRequest, ApiError } from "@/lib/api";

type VerifyEmailResponse = {
  status: "verified";
};

export default function VerifyEmailPage() {
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    const tokenFromQuery = new URLSearchParams(window.location.search).get("token");
    if (tokenFromQuery) {
      setToken(tokenFromQuery);
    }
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    setLoading(true);
    try {
      await apiRequest<VerifyEmailResponse>("/api/v1/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_OR_EXPIRED_TOKEN") {
        setError("驗證 token 無效或已過期。");
      } else {
        setError(err instanceof Error ? err.message : "驗證失敗");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>Email 驗證</h1>
      <section className="card">
        <form onSubmit={handleSubmit}>
          <label htmlFor="token">驗證 Token</label>
          <textarea
            id="token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="請貼上 verification token"
          />
          <button type="submit" disabled={loading || !token.trim()}>
            {loading ? "驗證中..." : "送出驗證"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        {success && <p className="success">Email 驗證成功，請前往登入。</p>}
        <p className="helper-links">
          <Link href="/login">前往登入</Link>
        </p>
      </section>
    </main>
  );
}
