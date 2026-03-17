import { clearAuthSession, getAccessToken } from "@/lib/auth";

const DEFAULT_LOCAL_API_BASE = "http://localhost:8000";

function resolveApiBase(): string {
  const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configuredBase) {
    return configuredBase;
  }

  if (typeof window !== "undefined") {
    const { hostname, origin, protocol } = window.location;
    const isLocalHost = hostname === "localhost" || hostname === "127.0.0.1";

    if (!isLocalHost && protocol === "https:") {
      return origin;
    }
  }

  return DEFAULT_LOCAL_API_BASE;
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {}
): Promise<T> {
  const apiBase = resolveApiBase();
  const { auth = false, headers, ...rest } = options;
  const mergedHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (auth) {
    const token = getAccessToken();
    if (token) {
      mergedHeaders.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${apiBase}${path}`, {
    ...rest,
    headers: mergedHeaders,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const code = payload?.detail?.code as string | undefined;
    const message =
      (payload?.detail?.message as string | undefined) ??
      (payload?.message as string | undefined) ??
      `API request failed with status ${response.status}`;

    if (response.status === 401) {
      clearAuthSession();
    }

    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
