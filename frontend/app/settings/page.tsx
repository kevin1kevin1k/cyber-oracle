import { redirect } from "next/navigation";

type SettingsRedirectPageProps = {
  searchParams?: {
    from?: string | string[];
  };
};

export default function SettingsRedirectPage({
  searchParams,
}: SettingsRedirectPageProps) {
  const from = Array.isArray(searchParams?.from)
    ? searchParams?.from[0]
    : searchParams?.from;

  redirect(from ? `/?from=${encodeURIComponent(from)}` : "/");
}
