"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  createOrder,
  getCreditsBalance,
  getCreditTransactions,
  simulateOrderPaid,
  type CreditBalanceResponse,
  type CreditTransactionItem,
} from "@/lib/credits";
import { getAuthSession } from "@/lib/auth";
import { buildLoginPathWithNext } from "@/lib/navigation";

const PACKAGE_OPTIONS: Array<{ size: 1 | 3 | 5; amountTwd: 168 | 358 | 518 }> = [
  { size: 1, amountTwd: 168 },
  { size: 3, amountTwd: 358 },
  { size: 5, amountTwd: 518 },
];

function formatDatetime(value: string): string {
  return new Date(value).toLocaleString("zh-TW", { hour12: false });
}

function formatAction(action: CreditTransactionItem["action"]): string {
  if (action === "purchase") {
    return "購點入帳";
  }
  if (action === "reserve") {
    return "預扣";
  }
  if (action === "capture") {
    return "扣點確認";
  }
  if (action === "refund") {
    return "回補";
  }
  return "系統發放";
}

export default function WalletPage() {
  const router = useRouter();
  const [authSession, setAuthSession] = useState<ReturnType<typeof getAuthSession>>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [balance, setBalance] = useState<CreditBalanceResponse | null>(null);
  const [transactions, setTransactions] = useState<CreditTransactionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasingSize, setPurchasingSize] = useState<1 | 3 | 5 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isLoggedIn = !!authSession?.accessToken;

  useEffect(() => {
    setAuthSession(getAuthSession());
    setAuthLoaded(true);
  }, []);

  const reloadWallet = useCallback(async () => {
    const [balancePayload, transactionPayload] = await Promise.all([
      getCreditsBalance(),
      getCreditTransactions(20, 0),
    ]);
    setBalance(balancePayload);
    setTransactions(transactionPayload.items);
  }, []);

  useEffect(() => {
    if (!authLoaded) {
      return;
    }

    if (!isLoggedIn) {
      router.replace(buildLoginPathWithNext("/wallet"));
      return;
    }

    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        await reloadWallet();
      } catch (err) {
        if (!active) {
          return;
        }
        if (err instanceof ApiError && err.status === 401) {
          router.replace(buildLoginPathWithNext("/wallet"));
          return;
        }
        setError(err instanceof Error ? err.message : "讀取錢包資料失敗");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [authLoaded, isLoggedIn, reloadWallet, router]);

  const canPurchase = useMemo(() => !loading && purchasingSize === null, [loading, purchasingSize]);

  async function handlePurchase(packageSize: 1 | 3 | 5) {
    setError(null);
    setSuccess(null);
    setPurchasingSize(packageSize);
    try {
      const idempotencyKey = crypto.randomUUID();
      const order = await createOrder(packageSize, idempotencyKey);
      await simulateOrderPaid(order.id);
      await reloadWallet();
      setSuccess(`購買 ${packageSize} 題包成功，餘額已更新。`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          router.replace(buildLoginPathWithNext("/wallet"));
          return;
        }
        if (err.code === "FORBIDDEN_IN_PRODUCTION") {
          setError("目前環境不允許 simulate-paid。Production 需改用真實金流 callback 入帳。");
          return;
        }
      }
      setError(err instanceof Error ? err.message : "購點失敗");
    } finally {
      setPurchasingSize(null);
    }
  }

  if (!authLoaded) {
    return (
      <main>
        <h1>點數錢包</h1>
        <p>登入狀態載入中...</p>
      </main>
    );
  }

  if (!isLoggedIn) {
    return null;
  }

  return (
    <main>
      <h1>點數錢包</h1>
      <p>檢視目前餘額、交易流水，並購買 1/3/5 題包。</p>

      <section className="card">
        <p>
          <strong>目前餘額：</strong>
          {loading ? "載入中..." : `${balance?.balance ?? 0} 點`}
        </p>
        <p>
          <strong>最後更新：</strong>
          {balance?.updated_at ? formatDatetime(balance.updated_at) : "尚無紀錄"}
        </p>
        <p className="helper-links">
          <Link href="/">返回提問頁</Link>
        </p>
      </section>

      <section className="card wallet-section">
        <h2>購點方案</h2>
        <div className="package-grid">
          {PACKAGE_OPTIONS.map((option) => (
            <button
              key={option.size}
              type="button"
              className="package-button"
              onClick={() => void handlePurchase(option.size)}
              disabled={!canPurchase}
            >
              {purchasingSize === option.size ? "處理中..." : `購買 ${option.size} 題包（NT$ ${option.amountTwd}）`}
            </button>
          ))}
        </div>
      </section>

      <section className="card wallet-section">
        <h2>交易流水</h2>
        {loading ? (
          <p>載入中...</p>
        ) : transactions.length === 0 ? (
          <p>目前沒有交易紀錄。</p>
        ) : (
          <ul className="tx-list">
            {transactions.map((tx) => (
              <li key={tx.id} className="tx-item">
                <p>
                  <strong>{formatAction(tx.action)}</strong>
                  <span className={tx.amount >= 0 ? "credit-positive" : "credit-negative"}>
                    {tx.amount > 0 ? ` +${tx.amount}` : ` ${tx.amount}`} 點
                  </span>
                </p>
                <p>{tx.reason_code}</p>
                <p>{formatDatetime(tx.created_at)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {error && <p className="error">{error}</p>}
      {success && <p className="success">{success}</p>}
    </main>
  );
}
