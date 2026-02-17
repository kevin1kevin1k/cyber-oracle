"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { apiRequest, ApiError } from "@/lib/api";

type ResetPasswordResponse = {
  status: "password_reset";
};

export default function ResetPasswordPage() {
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
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
      await apiRequest<ResetPasswordResponse>("/api/v1/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, new_password: newPassword }),
      });
      setSuccess(true);
      setNewPassword("");
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_OR_EXPIRED_TOKEN") {
        setError("重設 token 無效或已過期。");
      } else {
        setError(err instanceof Error ? err.message : "重設失敗");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>重設密碼</h1>
      <section className="card">
        <form onSubmit={handleSubmit}>
          <label htmlFor="token">重設 Token</label>
          <textarea
            id="token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="請貼上 reset token"
          />
          <label htmlFor="new-password">新密碼</label>
          <input
            id="new-password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={8}
            required
          />
          <button type="submit" disabled={loading || !token.trim()}>
            {loading ? "送出中..." : "重設密碼"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        {success && <p className="success">密碼已重設，請使用新密碼登入。</p>}
        <p className="helper-links">
          <Link href="/login">前往登入</Link>
        </p>
      </section>
    </main>
  );
}
