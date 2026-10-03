import { apiClient } from "./api";
import { pushToast } from "./components/Toast";
import { go } from "./nav";
import { queryClient } from "./queryClient";

export function returnToFromLocation(search = window.location.search): string {
  const next = new URLSearchParams(search).get("next");
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.includes("://")) {
    return next;
  }
  return "/";
}

export async function logoutAndClear(): Promise<void> {
  try {
    await apiClient.logout();
  } catch (err) {
    pushToast(err instanceof Error ? `Logout failed: ${err.message}` : "Logout failed", "alert");
  } finally {
    queryClient.clear();
    go("/login");
  }
}
