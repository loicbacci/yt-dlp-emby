import { useJobs } from "../hooks/useJobs";
import { JobProgress } from "./JobProgress";

export function Header({
  current = "dashboard",
  onLogout,
  onNavigate,
}: {
  current?: "dashboard" | "series" | "settings";
  onLogout: () => void;
  onNavigate?: (url: string) => void;
}) {
  const jobs = useJobs();
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
        <span class="status-chip" role="status">
          {jobs.data?.active?.status ?? jobs.data?.focused?.status ?? "Idle"}
        </span>
        <button type="button" class="btn-ghost" onClick={onLogout}>
          Log out
        </button>
      </div>
      {jobs.data?.focused && <JobProgress job={jobs.data.focused} history={jobs.data.history} />}
    </header>
  );
}
