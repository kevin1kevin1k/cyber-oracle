"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { apiRequest, ApiError } from "@/lib/api";
import { saveAuthSession } from "@/lib/auth";
import { resolveSafeNext } from "@/lib/navigation";

type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  email_verified: boolean;
};

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextPath, setNextPath] = useState("/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setNextPath(resolveSafeNext(params.get("next")));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const payload = await apiRequest<LoginResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      saveAuthSession({
        accessToken: payload.access_token,
        emailVerified: payload.email_verified,
        email,
      });
      router.replace(nextPath);
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_CREDENTIALS") {
        setError("帳號或密碼錯誤。");
      } else {
        setError(err instanceof Error ? err.message : "登入失敗");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>登入</h1>
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
          <label htmlFor="password">密碼</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          <button type="submit" disabled={loading}>
            {loading ? "登入中..." : "登入"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        <p className="helper-links">
          <Link href="/register">註冊新帳號</Link>
          <span> · </span>
          <Link href="/forgot-password">忘記密碼</Link>
        </p>
      </section>
    </main>
  );
}
