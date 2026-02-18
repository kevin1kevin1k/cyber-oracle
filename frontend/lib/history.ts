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

export async function getAskHistory(limit = 20, offset = 0): Promise<AskHistoryListResponse> {
  return apiRequest<AskHistoryListResponse>(`/api/v1/history/questions?limit=${limit}&offset=${offset}`, {
    method: "GET",
    auth: true,
  });
}
