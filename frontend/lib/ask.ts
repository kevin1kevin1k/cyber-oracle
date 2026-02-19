import { apiRequest } from "@/lib/api";

export type AskResponse = {
  answer: string;
  source: "rag" | "rule" | "openai" | "mock";
  layer_percentages: { label: "主層" | "輔層" | "參照層"; pct: number }[];
  request_id: string;
  followup_options: { id: string; content: string }[];
};

export async function askQuestion(question: string, idempotencyKey: string): Promise<AskResponse> {
  return apiRequest<AskResponse>("/api/v1/ask", {
    method: "POST",
    auth: true,
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ question, lang: "zh", mode: "analysis" }),
  });
}

export async function askFollowup(followupId: string): Promise<AskResponse> {
  return apiRequest<AskResponse>(`/api/v1/followups/${followupId}/ask`, {
    method: "POST",
    auth: true,
  });
}
