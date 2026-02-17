export type AuthSession = {
  accessToken: string;
  emailVerified: boolean;
  email?: string;
};

const ACCESS_TOKEN_KEY = "elin_access_token";
const EMAIL_VERIFIED_KEY = "elin_auth_email_verified";
const EMAIL_KEY = "elin_auth_email";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function saveAuthSession(session: AuthSession): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  window.localStorage.setItem(EMAIL_VERIFIED_KEY, String(session.emailVerified));
  if (session.email) {
    window.localStorage.setItem(EMAIL_KEY, session.email);
  } else {
    window.localStorage.removeItem(EMAIL_KEY);
  }
}

export function clearAuthSession(): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(EMAIL_VERIFIED_KEY);
  window.localStorage.removeItem(EMAIL_KEY);
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
    emailVerified: window.localStorage.getItem(EMAIL_VERIFIED_KEY) === "true",
    email: window.localStorage.getItem(EMAIL_KEY) ?? undefined,
  };
}

export function getAccessToken(): string | null {
  return getAuthSession()?.accessToken ?? null;
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

export function isEmailVerified(): boolean {
  return getAuthSession()?.emailVerified ?? false;
}
