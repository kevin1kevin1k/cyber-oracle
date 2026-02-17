import { apiRequest } from "@/lib/api";

export type CreditBalanceResponse = {
  balance: number;
  updated_at: string | null;
};

export type CreditTransactionItem = {
  id: string;
  action: "reserve" | "capture" | "refund" | "grant" | "purchase";
  amount: number;
  reason_code: string;
  request_id: string;
  question_id: string | null;
  order_id: string | null;
  created_at: string;
};

export type CreditTransactionListResponse = {
  items: CreditTransactionItem[];
  total: number;
};

export type OrderResponse = {
  id: string;
  user_id: string;
  package_size: 1 | 3 | 5;
  amount_twd: 168 | 358 | 518;
  status: "pending" | "paid" | "failed" | "refunded";
  idempotency_key: string;
  created_at: string;
  paid_at: string | null;
};

export type SimulatePaidResponse = {
  order: OrderResponse;
  wallet_balance: number;
};

export async function getCreditsBalance(): Promise<CreditBalanceResponse> {
  return apiRequest<CreditBalanceResponse>("/api/v1/credits/balance", {
    method: "GET",
    auth: true,
  });
}

export async function getCreditTransactions(
  limit = 20,
  offset = 0
): Promise<CreditTransactionListResponse> {
  return apiRequest<CreditTransactionListResponse>(
    `/api/v1/credits/transactions?limit=${limit}&offset=${offset}`,
    {
      method: "GET",
      auth: true,
    }
  );
}

export async function createOrder(packageSize: 1 | 3 | 5, idempotencyKey: string): Promise<OrderResponse> {
  return apiRequest<OrderResponse>("/api/v1/orders", {
    method: "POST",
    auth: true,
    body: JSON.stringify({ package_size: packageSize, idempotency_key: idempotencyKey }),
  });
}

export async function simulateOrderPaid(orderId: string): Promise<SimulatePaidResponse> {
  return apiRequest<SimulatePaidResponse>(`/api/v1/orders/${orderId}/simulate-paid`, {
    method: "POST",
    auth: true,
  });
}
