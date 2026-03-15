import { apiRequest } from "@/lib/api";

export type MessengerLinkResponse = {
  status: "linked";
  user_id: string;
  psid: string;
  page_id: string;
};

export async function linkMessengerIdentity(token: string): Promise<MessengerLinkResponse> {
  return apiRequest<MessengerLinkResponse>("/api/v1/messenger/link", {
    method: "POST",
    auth: true,
    body: JSON.stringify({ token }),
  });
}
