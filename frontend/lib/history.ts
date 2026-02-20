import { apiRequest } from "@/lib/api";

export type AskHistoryItem = {
  question_id: string;
  question_text: string;
  answer_preview: string;
  source: "rag" | "rule" | "openai" | "mock";
  charged_credits: number;
  created_at: string;
};

export type AskHistoryListResponse = {
  items: AskHistoryItem[];
  total: number;
};

export type AskHistoryDetailNode = {
  question_id: string;
  question_text: string;
  answer_text: string;
  source: "rag" | "rule" | "openai" | "mock";
  layer_percentages: { label: "主層" | "輔層" | "參照層"; pct: number }[];
  charged_credits: number;
  request_id: string;
  created_at: string;
  children: AskHistoryDetailNode[];
};

export type AskHistoryDetailTransactionItem = {
  id: string;
  action: "capture" | "refund";
  amount: number;
  reason_code: string;
  question_id: string | null;
  request_id: string;
  created_at: string;
};

export type AskHistoryDetailResponse = {
  root: AskHistoryDetailNode;
  transactions: AskHistoryDetailTransactionItem[];
};

export async function getAskHistory(limit = 20, offset = 0): Promise<AskHistoryListResponse> {
  return apiRequest<AskHistoryListResponse>(`/api/v1/history/questions?limit=${limit}&offset=${offset}`, {
    method: "GET",
    auth: true,
  });
}

export async function getAskHistoryDetail(questionId: string): Promise<AskHistoryDetailResponse> {
  return apiRequest<AskHistoryDetailResponse>(`/api/v1/history/questions/${questionId}`, {
    method: "GET",
    auth: true,
  });
}
