"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { clearAuthSession, getAuthSession } from "@/lib/auth";
import { getCreditsBalance } from "@/lib/billing";
import { deleteMyAccount, getMyProfile, updateMyProfile } from "@/lib/profile";

const MESSENGER_PROFILE_SOURCES = new Set([
  "messenger-get-started",
  "messenger-profile-required",
  "messenger-first-link",
]);

export default function HomePage() {
  const router = useRouter();
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [profileSource, setProfileSource] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [motherName, setMotherName] = useState("");
  const [replyMode, setReplyMode] = useState<"structured" | "free">("structured");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [profileComplete, setProfileComplete] = useState<boolean | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const isMessengerProfileFlow =
    profileSource !== null && MESSENGER_PROFILE_SOURCES.has(profileSource);
  const isFirstMessengerLinkFlow = profileSource === "messenger-first-link";
  const isGetStartedFlow = profileSource === "messenger-get-started";
  const canSave = useMemo(
    () => !loading && !saving && fullName.trim().length > 0 && motherName.trim().length > 0,
    [fullName, loading, motherName, saving]
  );

  useEffect(() => {
    setAuthSession(getAuthSession());
    setProfileSource(new URLSearchParams(window.location.search).get("from"));
    setAuthLoaded(true);
  }, []);

  useEffect(() => {
    if (!authLoaded) {
      return;
    }

    let active = true;
    async function loadHomeState() {
      if (!isLoggedIn) {
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const [profilePayload, balancePayload] = await Promise.all([
          getMyProfile(),
          getCreditsBalance(),
        ]);
        if (!active) {
          return;
        }
        setFullName(profilePayload.full_name ?? "");
        setMotherName(profilePayload.mother_name ?? "");
        setReplyMode(profilePayload.reply_mode ?? "structured");
        setProfileComplete(profilePayload.is_complete);
        setCreditBalance(balancePayload.balance);
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError && err.status === 401) {
          clearAuthSession();
          setAuthSession(null);
          setCreditBalance(null);
          return;
        }
        setError(err instanceof Error ? err.message : "讀取設定失敗");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadHomeState();
    return () => {
      active = false;
    };
  }, [authLoaded, isLoggedIn]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSaving(true);
    try {
      await updateMyProfile({
        full_name: fullName.trim(),
        mother_name: motherName.trim(),
        reply_mode: replyMode,
      });
      setProfileComplete(true);
      setSuccess(
        isFirstMessengerLinkFlow || isGetStartedFlow
          ? "個人設定已儲存，現在可以回 Messenger 直接提問。"
          : "個人設定已儲存，之後 Messenger 提問會自動帶入這兩個固定資料。"
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearAuthSession();
        setAuthSession(null);
        setError("登入狀態已失效，請回 Messenger 重新進入。");
        return;
      }
      setError(err instanceof Error ? err.message : "儲存設定失敗");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteAccount() {
    setError(null);
    setSuccess(null);
    setDeleting(true);
    try {
      await deleteMyAccount();
      clearAuthSession();
      setAuthSession(null);
      setFullName("");
      setMotherName("");
      setReplyMode("structured");
      setCreditBalance(null);
      setProfileComplete(null);
      setShowDeleteConfirm(false);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearAuthSession();
        setAuthSession(null);
        setError("登入狀態已失效，請回 Messenger 重新進入。");
        return;
      }
      setError(err instanceof Error ? err.message : "刪除帳號失敗");
      setDeleting(false);
    }
  }

  if (!authLoaded) {
    return (
      <main>
        <h1>Messenger 設定中心</h1>
        <p>登入狀態載入中...</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Messenger 設定中心</h1>

      <section className="card">
        {!isLoggedIn ? (
          <>
            <p>這個頁面僅支援從 Messenger WebView 進入。請回 Messenger 點擊綁定或設定按鈕。</p>
            <p>目前版本的 WebView 只提供目前點數、固定資料設定、回覆方式設定與刪除帳號。真正提問請回 Messenger 對話進行。</p>
          </>
        ) : (
          <>
            <p>
              {loading
                ? "帳號資料載入中..."
                : profileComplete === false
                ? "目前已連結 Messenger，但還沒完成個人設定。"
                : "目前已連結 Messenger，可回 Messenger 直接提問。"}
            </p>
            <p className="credit-line">
              目前點數：<span className="credit-count">{loading ? "讀取中..." : `${creditBalance ?? 0} 點`}</span>
            </p>
            <p>這裡只保留查看點數、設定姓名/母親姓名、回覆方式，以及刪除帳號。真正提問請回 Messenger 對話進行。</p>
          </>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      {!isLoggedIn ? null : (
        <>
          {isMessengerProfileFlow && (
            <section className="card wallet-section wallet-messenger-note">
              <h2>
                {isFirstMessengerLinkFlow
                  ? "綁定完成，請先補資料"
                  : isGetStartedFlow
                    ? "開始使用前，請先補資料"
                    : "Messenger 提問前設定"}
              </h2>
              <p>這套問答需要固定使用你的姓名與母親姓名作為背景資料。</p>
              <p>
                {isFirstMessengerLinkFlow
                  ? "你已完成 Messenger 綁定。再完成這一步，之後就能直接回 Messenger 提問。"
                  : isGetStartedFlow
                    ? "你已啟用 Messenger 助手。再完成這一步，之後就能直接回 Messenger 提問。"
                    : "完成儲存後，就能直接回 Messenger 繼續提問。"}
              </p>
            </section>
          )}

          <section className="card">
            <p>你只需要設定一次，之後每次提問時系統都會自動帶入，不用重複輸入。</p>
            <form onSubmit={handleSubmit}>
              <label htmlFor="full-name">我的姓名</label>
              <input
                id="full-name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder="請輸入你的姓名"
                disabled={loading || saving}
              />

              <label htmlFor="mother-name">我母親的姓名</label>
              <input
                id="mother-name"
                value={motherName}
                onChange={(event) => setMotherName(event.target.value)}
                placeholder="請輸入你母親的姓名"
                disabled={loading || saving}
              />

              <label htmlFor="reply-mode">回覆方式</label>
              <select
                id="reply-mode"
                value={replyMode}
                onChange={(event) => setReplyMode(event.target.value as "structured" | "free")}
                disabled={loading || saving}
              >
                <option value="structured">結構化回覆</option>
                <option value="free">自由回覆</option>
              </select>
              <p className="field-hint">
                結構化回覆會維持固定版型；自由回覆會保留 ELIN 調性，但不固定段落格式。
              </p>

              <button type="submit" disabled={!canSave}>
                {saving ? "儲存中..." : "儲存設定"}
              </button>
            </form>

            {success && (
              <div className="answer">
                <p className="success">{success}</p>
              </div>
            )}
          </section>

          <section className="card danger-zone">
            <h2>危險操作</h2>
            <p>
              刪除帳號後，系統會清除你的點數、固定問答設定與目前登入狀態；之後同一個 Messenger
              帳號會回到未綁定狀態，需要重新走完整新手流程。
            </p>

            {!showDeleteConfirm ? (
              <button
                type="button"
                className="danger-button"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={deleting || saving}
              >
                刪除帳號
              </button>
            ) : (
              <div className="danger-confirm">
                <p className="danger-note">這個操作無法復原。確認後會直接刪除帳號與所有相關資料。</p>
                <div className="danger-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setShowDeleteConfirm(false)}
                    disabled={deleting}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => void handleDeleteAccount()}
                    disabled={deleting}
                  >
                    {deleting ? "刪除中..." : "確認刪除帳號"}
                  </button>
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
