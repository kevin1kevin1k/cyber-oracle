"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { apiRequest, ApiError } from "@/lib/api";
import { INVALID_OR_EXPIRED_LINK_MESSAGE } from "@/lib/auth-messages";
import { resolveSafeNext } from "@/lib/navigation";

type VerifyEmailResponse = {
  status: "verified";
};

export default function VerifyEmailPage() {
  const [tokenFromQuery, setTokenFromQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [nextPath, setNextPath] = useState("/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tokenFromQuery = params.get("token");
    if (tokenFromQuery) {
      setTokenFromQuery(tokenFromQuery);
    }
    setNextPath(resolveSafeNext(params.get("next")));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    setLoading(true);
    try {
      await apiRequest<VerifyEmailResponse>("/api/v1/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ token: tokenFromQuery }),
      });
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_OR_EXPIRED_TOKEN") {
        setError(INVALID_OR_EXPIRED_LINK_MESSAGE);
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
        {tokenFromQuery ? (
          <form onSubmit={handleSubmit}>
            <p>已偵測到驗證連結，請送出完成 Email 驗證。</p>
            <button type="submit" disabled={loading}>
              {loading ? "驗證中..." : "送出驗證"}
            </button>
          </form>
        ) : (
          <div className="answer">
            <p>未偵測到驗證連結，請從 Email 中點擊驗證連結後再試一次。</p>
            <p>
              <Link href={`/register?next=${encodeURIComponent(nextPath)}`}>返回註冊</Link>
            </p>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        {success && <p className="success">Email 驗證成功，請前往登入。</p>}
        <p className="helper-links">
          <Link href={`/login?next=${encodeURIComponent(nextPath)}`}>前往登入</Link>
        </p>
      </section>
    </main>
  );
}
