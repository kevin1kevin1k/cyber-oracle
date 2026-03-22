export type AuthSession = {
  accessToken: string;
  userId?: string;
  userLabel?: string;
};

const ACCESS_TOKEN_KEY = "elin_access_token";
const USER_ID_KEY = "elin_auth_user_id";
const USER_LABEL_KEY = "elin_auth_user_label";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function saveAuthSession(session: AuthSession): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  if (session.userId) {
    window.localStorage.setItem(USER_ID_KEY, session.userId);
  } else {
    window.localStorage.removeItem(USER_ID_KEY);
  }
  if (session.userLabel) {
    window.localStorage.setItem(USER_LABEL_KEY, session.userLabel);
  } else {
    window.localStorage.removeItem(USER_LABEL_KEY);
  }
}

export function clearAuthSession(): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(USER_ID_KEY);
  window.localStorage.removeItem(USER_LABEL_KEY);
  window.localStorage.removeItem("elin_auth_email_verified");
  window.localStorage.removeItem("elin_auth_email");
}

export function getAuthSession(): AuthSession | null {
  if (!isBrowser()) {
    return null;
  }
  const accessToken = window.localStorage.getItem(ACCESS_TOKEN_KEY);
  if (!accessToken) {
    return null;
  }
  return {
    accessToken,
    userId: window.localStorage.getItem(USER_ID_KEY) ?? undefined,
    userLabel:
      window.localStorage.getItem(USER_LABEL_KEY) ??
      window.localStorage.getItem("elin_auth_email") ??
      undefined,
  };
}

export function getAccessToken(): string | null {
  return getAuthSession()?.accessToken ?? null;
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}
