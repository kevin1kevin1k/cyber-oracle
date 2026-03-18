"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { PasswordField } from "@/components/PasswordField";
import { apiRequest, ApiError } from "@/lib/api";
import { INVALID_OR_EXPIRED_LINK_MESSAGE } from "@/lib/auth-messages";

type ResetPasswordResponse = {
  status: "password_reset";
};

const PASSWORD_MISMATCH_MESSAGE = "兩次輸入的密碼不一致。";

export default function ResetPasswordPage() {
  const [tokenFromQuery, setTokenFromQuery] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    const tokenFromQuery = new URLSearchParams(window.location.search).get("token");
    if (tokenFromQuery) {
      setTokenFromQuery(tokenFromQuery);
    }
  }, []);

  const passwordMismatch = useMemo(
    () => confirmNewPassword.length > 0 && newPassword !== confirmNewPassword,
    [confirmNewPassword, newPassword]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordMismatch) {
      setError(PASSWORD_MISMATCH_MESSAGE);
      return;
    }
    setError(null);
    setSuccess(false);
    setLoading(true);
    try {
      await apiRequest<ResetPasswordResponse>("/api/v1/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token: tokenFromQuery, new_password: newPassword }),
      });
      setSuccess(true);
      setNewPassword("");
      setConfirmNewPassword("");
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_OR_EXPIRED_TOKEN") {
        setError(INVALID_OR_EXPIRED_LINK_MESSAGE);
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
        {tokenFromQuery ? (
          <form onSubmit={handleSubmit}>
            <PasswordField
              id="new-password"
              label="新密碼"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              showPassword={showPassword}
              onToggleVisibility={() => setShowPassword((current) => !current)}
              autoComplete="new-password"
              ariaInvalid={passwordMismatch}
            />
            <PasswordField
              id="confirm-new-password"
              label="確認新密碼"
              value={confirmNewPassword}
              onChange={(e) => setConfirmNewPassword(e.target.value)}
              showPassword={showPassword}
              onToggleVisibility={() => setShowPassword((current) => !current)}
              autoComplete="new-password"
              ariaInvalid={passwordMismatch}
            />
            {passwordMismatch && <p className="error-inline">{PASSWORD_MISMATCH_MESSAGE}</p>}
            <button type="submit" disabled={loading || passwordMismatch}>
              {loading ? "送出中..." : "重設密碼"}
            </button>
          </form>
        ) : (
          <div className="answer">
            <p>未偵測到重設連結，請從 Email 中點擊重設連結後再試一次。</p>
            <p>
              <Link href="/forgot-password">返回忘記密碼</Link>
            </p>
          </div>
        )}
        {error && !passwordMismatch && <p className="error">{error}</p>}
        {success && <p className="success">密碼已重設，請使用新密碼登入。</p>}
        <p className="helper-links">
          <Link href="/login">前往登入</Link>
        </p>
      </section>
    </main>
  );
}
