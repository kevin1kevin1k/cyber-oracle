export function resolveSafeNext(rawNext: string | null): string {
  const next = (rawNext ?? "").trim();
  if (!next.startsWith("/")) {
    return "/";
  }
  if (next.startsWith("//")) {
    return "/";
  }
  if (next.includes("\\")) {
    return "/";
  }
  if (next.includes("://")) {
    return "/";
  }
  return next;
}

export function buildLoginPathWithNext(nextPath: string): string {
  const safeNext = resolveSafeNext(nextPath);
  return `/login?next=${encodeURIComponent(safeNext)}`;
}
