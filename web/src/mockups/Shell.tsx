import type { ComponentChildren } from "preact";
import type { TileTone } from "./mockCatalog";

export type MockPage = "downloads" | "shows" | "settings";

export function Poster({
  src,
  letter,
  tone,
  size = "sm",
}: {
  src?: string;
  letter: string;
  tone: TileTone;
  size?: "sm" | "md" | "lg" | "now";
}) {
  if (src) {
    return <img class={`mock-poster ${size}`} src={src} alt="" />;
  }
  return (
    <span class={`mock-poster mock-poster-fallback ${size} ${tone}`}>{letter}</span>
  );
}

export function MockHeader({ current }: { current: MockPage }) {
  return (
    <header class="mock-header">
      <div class="mock-brand">yt-dlp-emby</div>
      <nav class="mock-nav" aria-label="Main">
        <span class={current === "downloads" ? "mock-nav-link is-active" : "mock-nav-link"}>
          Downloads
        </span>
        <span class={current === "shows" ? "mock-nav-link is-active" : "mock-nav-link"}>
          Shows
        </span>
        <span class={current === "settings" ? "mock-nav-link is-active" : "mock-nav-link"}>
          Settings
        </span>
      </nav>
      <button type="button" class="mock-logout">
        Log out
      </button>
    </header>
  );
}

export function MockShell({
  current,
  children,
  playing = false,
}: {
  current: MockPage;
  children: ComponentChildren;
  playing?: boolean;
}) {
  return (
    <div class="mock-shell">
      <MockHeader current={current} />
      <div class={playing ? "mock-page is-playing" : "mock-page"}>{children}</div>
    </div>
  );
}

export function Twist({ open }: { open: boolean }) {
  return (
    <span
      class={open ? "mock-twist is-open" : "mock-twist"}
      aria-hidden="true"
    />
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      class="mock-spinner"
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

export function Skel({
  width,
  height = "0.85em",
}: {
  width: string;
  height?: string;
}) {
  return (
    <span class="mock-skel" style={{ width, height }} aria-hidden="true" />
  );
}

export function OverflowMenu({
  open,
  onToggle,
  onClose,
}: {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
}) {
  return (
    <div class="mock-menu-wrap">
      <button type="button" class="mock-menu" aria-label="More" onClick={onToggle}>
        …
      </button>
      {open && (
        <div class="mock-menu-pop">
          <button type="button" onClick={onClose}>
            Edit
          </button>
          <button type="button" onClick={onClose}>
            Refresh
          </button>
          <button type="button" class="is-danger" onClick={onClose}>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
