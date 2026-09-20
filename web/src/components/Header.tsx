import type { Run } from "../api";
import { go } from "../nav";
import { StatusChip } from "./StatusChip";

export function Header({
  run,
  current = "dashboard",
  onLogout,
  onNavigate,
}: {
  run: Run;
  current?: "dashboard" | "series" | "settings";
  onLogout: () => void;
  onNavigate?: (url: string) => void;
}) {
  const goTo = (url: string) => (event: Event) => {
    event.preventDefault();
    if (onNavigate) {
      onNavigate(url);
      return;
    }
    go(url);
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
        <StatusChip run={run} />
        <button type="button" class="btn-ghost" onClick={onLogout}>
          Log out
        </button>
      </div>
    </header>
  );
}
