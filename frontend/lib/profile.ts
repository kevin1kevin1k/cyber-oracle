import { apiRequest } from "@/lib/api";

export type UserProfileResponse = {
  full_name: string | null;
  mother_name: string | null;
  is_complete: boolean;
};

export async function getMyProfile(): Promise<UserProfileResponse> {
  return apiRequest<UserProfileResponse>("/api/v1/me/profile", {
    method: "GET",
    auth: true,
  });
}

export async function updateMyProfile(payload: {
  full_name: string;
  mother_name: string;
}): Promise<UserProfileResponse> {
  return apiRequest<UserProfileResponse>("/api/v1/me/profile", {
    method: "PUT",
    auth: true,
    body: JSON.stringify(payload),
  });
}

export async function deleteMyAccount(): Promise<void> {
  return apiRequest<void>("/api/v1/me", {
    method: "DELETE",
    auth: true,
  });
}
