import type { Run } from "../api";
import { idleRun, useAppRun } from "../useAppQueries";
import { StatusChip } from "./StatusChip";

export function Header({
  run,
  current = "dashboard",
  onLogout,
  onNavigate,
}: {
  run?: Run;
  current?: "dashboard" | "series" | "settings";
  onLogout: () => void;
  onNavigate?: (url: string) => void;
}) {
  const runQuery = useAppRun();
  const live = runQuery.data ?? run ?? idleRun;
  const loading = runQuery.isPending && !runQuery.data && !run;
  const goTo = (url: string) => (event: MouseEvent) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(url);
  };

  return (
    <header class="app-header">
      <div class="brand">
        <span>yt-dlp-emby</span>
      </div>
      <nav class="header-nav" aria-label="Main">
        <a
          href="/"
          class={current === "dashboard" ? "header-link active" : "header-link"}
          aria-current={current === "dashboard" ? "page" : undefined}
          onClick={goTo("/")}
        >
          Downloads
        </a>
        <a
          href="/series"
          class={current === "series" ? "header-link active" : "header-link"}
          aria-current={current === "series" ? "page" : undefined}
          onClick={goTo("/series")}
        >
          Shows
        </a>
        <a
          href="/settings"
          class={current === "settings" ? "header-link active" : "header-link"}
          aria-current={current === "settings" ? "page" : undefined}
          onClick={goTo("/settings")}
        >
          Settings
        </a>
      </nav>
      <div class="header-actions">
        <StatusChip run={live} loading={loading} />
        <button type="button" class="btn-ghost" onClick={onLogout}>
          Log out
        </button>
      </div>
    </header>
  );
}
