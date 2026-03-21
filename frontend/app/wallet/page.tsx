"use client";

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
} from "@/lib/billing";
import { getAuthSession } from "@/lib/auth";
import { buildLoginPathWithNext } from "@/lib/navigation";
import AppTopNav from "@/components/AppTopNav";

const PACKAGE_OPTIONS: Array<{ size: 1 | 3 | 5; amountTwd: 168 | 358 | 518 }> = [
  { size: 1, amountTwd: 168 },
  { size: 3, amountTwd: 358 },
  { size: 5, amountTwd: 518 },
];

const MESSENGER_WALLET_SOURCES = new Set(["messenger-insufficient-credit", "ask-402"]);

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
  const [walletSource, setWalletSource] = useState<string | null>(null);
  const [balance, setBalance] = useState<CreditBalanceResponse | null>(null);
  const [paymentsEnabled, setPaymentsEnabled] = useState(true);
  const [transactions, setTransactions] = useState<CreditTransactionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasingSize, setPurchasingSize] = useState<1 | 3 | 5 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isLoggedIn = !!authSession?.accessToken;
  const isMessengerWalletFlow =
    walletSource !== null && MESSENGER_WALLET_SOURCES.has(walletSource);
  const walletPath = isMessengerWalletFlow
    ? `/wallet?from=${encodeURIComponent(walletSource)}`
    : "/wallet";

  useEffect(() => {
    setAuthSession(getAuthSession());
    setWalletSource(new URLSearchParams(window.location.search).get("from"));
    setAuthLoaded(true);
  }, []);

  const reloadWallet = useCallback(async () => {
    const [balancePayload, transactionPayload] = await Promise.all([
      getCreditsBalance(),
      getCreditTransactions(20, 0),
    ]);
    setBalance(balancePayload);
    setPaymentsEnabled(balancePayload.payments_enabled ?? true);
    setTransactions(transactionPayload.items);
  }, []);

  useEffect(() => {
    if (!authLoaded) {
      return;
    }

    if (!isLoggedIn) {
      router.replace(buildLoginPathWithNext(walletPath));
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
          router.replace(buildLoginPathWithNext(walletPath));
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
  }, [authLoaded, isLoggedIn, reloadWallet, router, walletPath]);

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
      setSuccess(
        isMessengerWalletFlow
          ? `購買 ${packageSize} 題包成功，餘額已更新。請回 Messenger 繼續提問；若剛才是延伸問題，請點擊「購買完成，重新顯示延伸問題」。`
          : `購買 ${packageSize} 題包成功，餘額已更新。`,
      );
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          router.replace(buildLoginPathWithNext(walletPath));
          return;
        }
        if (err.code === "PAYMENTS_DISABLED") {
          setPaymentsEnabled(false);
          setError("目前為體驗版，暫未開放購點。");
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
      <AppTopNav />
      <h1>點數錢包</h1>

      <section className="card">
        <p>
          <strong>目前餘額：</strong>
          {loading ? "載入中..." : `${balance?.balance ?? 0} 點`}
        </p>
        <p>
          <strong>最後更新：</strong>
          {balance?.updated_at ? formatDatetime(balance.updated_at) : "尚無紀錄"}
        </p>
      </section>

      {isMessengerWalletFlow && (
        <section className="card wallet-section wallet-messenger-note">
          <h2>{paymentsEnabled ? "Messenger 購點提醒" : "Messenger 體驗版提醒"}</h2>
          <p>你是從 Messenger 的點數不足提示進入購點流程。</p>
          {paymentsEnabled ? (
            <>
              <p>購買完成後，請回 Messenger 繼續提問。</p>
              <p>若剛才是延伸問題點數不足，請回 Messenger 點擊「購買完成，重新顯示延伸問題」。</p>
            </>
          ) : (
            <p>目前為體驗版，暫未開放購點。若點數已用完，請等待後續開放通知。</p>
          )}
        </section>
      )}

      <section className="card wallet-section">
        <h2>{paymentsEnabled ? "購點方案" : "體驗版說明"}</h2>
        {paymentsEnabled ? (
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
        ) : (
          <p>目前帳號僅提供固定體驗點數。點數用完後，這個頁面會保留餘額與交易流水查詢，但不提供自動購點。</p>
        )}
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
