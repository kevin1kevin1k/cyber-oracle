"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { apiRequest, ApiError } from "@/lib/api";

type RegisterResponse = {
  user_id: string;
  email: string;
  email_verified: boolean;
  verification_token: string;
};

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const payload = await apiRequest<RegisterResponse>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.replace(`/verify-email?token=${encodeURIComponent(payload.verification_token)}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_ALREADY_EXISTS") {
        setError("此 Email 已註冊，請直接登入。");
      } else {
        setError(err instanceof Error ? err.message : "註冊失敗");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>註冊</h1>
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
            {loading ? "註冊中..." : "註冊"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        <p className="helper-links">
          <Link href="/login">已有帳號？前往登入</Link>
        </p>
      </section>
    </main>
  );
}
