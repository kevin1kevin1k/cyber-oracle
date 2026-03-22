import { apiRequest } from "@/lib/api";

export type MessengerLinkResponse = {
  status: "linked";
  link_status: "linked_new" | "session_restored";
  user_id: string;
  psid: string;
  page_id: string;
  access_token: string;
  token_type: "bearer";
};

export async function linkMessengerIdentity(token: string): Promise<MessengerLinkResponse> {
  return apiRequest<MessengerLinkResponse>("/api/v1/messenger/link", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}
