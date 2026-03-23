"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import AppTopNav from "@/components/AppTopNav";
import MessengerSessionRequired from "@/components/MessengerSessionRequired";
import { ApiError } from "@/lib/api";
import { getAuthSession } from "@/lib/auth";
import { getMyProfile, updateMyProfile } from "@/lib/profile";

const MESSENGER_PROFILE_SOURCES = new Set(["messenger-profile-required"]);

export default function SettingsPage() {
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [profileSource, setProfileSource] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [motherName, setMotherName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const isMessengerProfileFlow =
    profileSource !== null && MESSENGER_PROFILE_SOURCES.has(profileSource);
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
    async function loadProfile() {
      if (!isLoggedIn) {
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const payload = await getMyProfile();
        if (!active) {
          return;
        }
        setFullName(payload.full_name ?? "");
        setMotherName(payload.mother_name ?? "");
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError && err.status === 401) {
          setAuthSession(null);
          setError("登入狀態已失效，請回 Messenger 重新進入。");
          return;
        }
        setError(err instanceof Error ? err.message : "讀取設定失敗");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadProfile();
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
      });
      setSuccess("個人設定已儲存，之後提問會自動帶入這兩個固定資料。");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthSession(null);
        setError("登入狀態已失效，請回 Messenger 重新進入。");
        return;
      }
      setError(err instanceof Error ? err.message : "儲存設定失敗");
    } finally {
      setSaving(false);
    }
  }

  if (!authLoaded) {
    return (
      <main>
        <h1>設定</h1>
        <p>登入狀態載入中...</p>
      </main>
    );
  }

  if (!isLoggedIn) {
    return (
      <MessengerSessionRequired
        title="設定"
        detail="請回 Messenger 重新點擊綁定或設定按鈕，建立 WebView session 後再修改固定資料。"
      />
    );
  }

  return (
    <main>
      <AppTopNav />
      <h1>固定問答設定</h1>

      {isMessengerProfileFlow && (
        <section className="card wallet-section wallet-messenger-note">
          <h2>Messenger 提問前設定</h2>
          <p>這套問答需要固定使用你的姓名與母親姓名作為背景資料。</p>
          <p>完成儲存後，就可以回首頁或回 Messenger 繼續提問。</p>
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

          <button type="submit" disabled={!canSave}>
            {saving ? "儲存中..." : "儲存設定"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}
        {success && (
          <div className="answer">
            <p className="success">{success}</p>
            <p className="helper-links">
              <Link href="/">前往提問</Link>
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
