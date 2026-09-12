import type { Run } from "../api";
import { StatusChip } from "./StatusChip";

export function Header({
  run,
  onLogout,
}: {
  run: Run;
  onLogout: () => void;
}) {
  return (
    <header class="app-header">
      <div class="brand">
        <span class="brand-bar" />
        <span>yt-dlp-emby</span>
      </div>
      <div class="header-actions">
        <StatusChip run={run} />
        <button type="button" class="btn-ghost" onClick={onLogout}>
          Log out
        </button>
      </div>
    </header>
  );
}
