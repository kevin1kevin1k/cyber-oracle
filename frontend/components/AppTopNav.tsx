"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "提問" },
  { href: "/wallet", label: "點數錢包" },
  { href: "/history", label: "歷史問答" },
] as const;

export default function AppTopNav() {
  const pathname = usePathname();

  return (
    <nav className="top-nav" data-testid="app-top-nav" aria-label="主導覽">
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
    </nav>
  );
}
