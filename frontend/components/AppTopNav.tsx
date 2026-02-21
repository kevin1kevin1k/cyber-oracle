"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { logoutAndRedirect } from "@/lib/session";
import { getAuthSession } from "@/lib/auth";

const NAV_ITEMS = [
  { href: "/", label: "提問" },
  { href: "/wallet", label: "點數錢包" },
  { href: "/history", label: "歷史問答" },
] as const;

export default function AppTopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authLoaded, setAuthLoaded] = useState(false);
  const [authEmail, setAuthEmail] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const session = getAuthSession();
    setAuthEmail(session?.email ?? null);
    setAuthLoaded(true);
  }, []);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    function handleEsc(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEsc);
    };
  }, []);

  async function handleLogout() {
    setMenuOpen(false);
    await logoutAndRedirect(router, "/");
  }

  return (
    <nav className="top-nav" data-testid="app-top-nav" aria-label="主導覽">
      <div className="top-nav-main">
        <ul className="top-nav-list">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`top-nav-link${isActive ? " active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="top-nav-account" ref={menuRef}>
          {!authLoaded ? null : authEmail ? (
            <>
              <button
                type="button"
                className="account-trigger"
                data-testid="account-menu-trigger"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((prev) => !prev)}
              >
                帳號選單
              </button>
              {menuOpen && (
                <div className="account-menu" role="menu" data-testid="account-menu">
                  <p className="account-email">{authEmail}</p>
                  <button type="button" className="account-action" role="menuitem" disabled>
                    個人檔案（即將推出）
                  </button>
                  <button type="button" className="account-action" role="menuitem" disabled>
                    設定（即將推出）
                  </button>
                  <button
                    type="button"
                    className="account-action account-action-danger"
                    role="menuitem"
                    onClick={() => void handleLogout()}
                  >
                    登出
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="top-nav-auth-links">
              <Link href="/login">登入</Link>
              <span> · </span>
              <Link href="/register">註冊</Link>
            </p>
          )}
        </div>
      </div>
    </nav>
  );
}
