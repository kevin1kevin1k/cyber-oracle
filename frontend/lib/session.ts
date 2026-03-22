import { apiRequest } from "@/lib/api";
import { clearAuthSession } from "@/lib/auth";

type RouterLike = {
  replace: (href: string) => void;
};

export async function logoutAndRedirect(
  router: RouterLike,
  nextPath: string = "/"
): Promise<void> {
  try {
    await apiRequest<void>("/api/v1/auth/logout", {
      method: "POST",
      auth: true,
    });
  } catch {
    // Ignore logout failures and clear local state anyway.
  } finally {
    clearAuthSession();
    router.replace(nextPath);
  }
}
