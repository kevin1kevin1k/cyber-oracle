"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { PasswordField } from "@/components/PasswordField";
import { apiRequest, ApiError } from "@/lib/api";
import { resolveSafeNext } from "@/lib/navigation";

type RegisterResponse = {
  user_id: string;
  email: string;
  email_verified: boolean;
  verification_token?: string | null;
};

const PASSWORD_MISMATCH_MESSAGE = "兩次輸入的密碼不一致。";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const [nextPath, setNextPath] = useState("/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setNextPath(resolveSafeNext(params.get("next")));
  }, []);

  const passwordMismatch = useMemo(
    () => confirmPassword.length > 0 && password !== confirmPassword,
    [confirmPassword, password]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordMismatch) {
      setError(PASSWORD_MISMATCH_MESSAGE);
      return;
    }
    setError(null);
    setSubmittedEmail(null);
    setLoading(true);
    try {
      const payload = await apiRequest<RegisterResponse>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      const token = payload.verification_token?.trim();
      if (token) {
        router.replace(
          `/verify-email?token=${encodeURIComponent(token)}&next=${encodeURIComponent(nextPath)}`
        );
        return;
      }
      setSubmittedEmail(payload.email);
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
            autoComplete="email"
          />
          <PasswordField
            id="password"
            label="密碼"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            showPassword={showPassword}
            onToggleVisibility={() => setShowPassword((current) => !current)}
            autoComplete="new-password"
            ariaInvalid={passwordMismatch}
          />
          <PasswordField
            id="confirm-password"
            label="確認密碼"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            showPassword={showPassword}
            onToggleVisibility={() => setShowPassword((current) => !current)}
            autoComplete="new-password"
            ariaInvalid={passwordMismatch}
          />
          {passwordMismatch && <p className="error-inline">{PASSWORD_MISMATCH_MESSAGE}</p>}
          <button type="submit" disabled={loading || passwordMismatch}>
            {loading ? "註冊中..." : "註冊"}
          </button>
        </form>
        {error && !passwordMismatch && <p className="error">{error}</p>}
        {submittedEmail && (
          <p className="success">註冊成功，請查收 {submittedEmail} 的驗證信件。</p>
        )}
        <p className="helper-links">
          <Link href={`/login?next=${encodeURIComponent(nextPath)}`}>已有帳號？前往登入</Link>
        </p>
      </section>
    </main>
  );
}
