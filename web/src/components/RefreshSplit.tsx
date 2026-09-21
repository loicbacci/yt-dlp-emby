import { useRef, useState } from "preact/hooks";
import { useDismiss } from "../hooks/useDismiss";

export type RefreshPart = "all" | "listings" | "disk" | "sonarr";

export function RefreshSplit({
  disabled,
  showSonarr,
  busy,
  title,
  onRefresh,
}: {
  disabled?: boolean;
  showSonarr?: boolean;
  busy?: boolean;
  title?: string;
  onRefresh: (part: RefreshPart) => void;
}) {
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  useDismiss(
    open,
    () => setOpen(false),
    ".refresh-split",
    toggleRef as unknown as import("preact").RefObject<HTMLElement | null>,
  );
  const pick = (part: RefreshPart) => {
    setOpen(false);
    onRefresh(part);
    requestAnimationFrame(() => toggleRef.current?.focus());
  };

  return (
    <div class="refresh-split">
      <button
        type="button"
        class="btn-secondary"
        disabled={disabled}
        aria-busy={busy}
        title={title}
        onClick={() => onRefresh("all")}
      >
        {busy ? <span class="spinner" aria-hidden="true" /> : null}
        Refresh
      </button>
      <button
        ref={toggleRef}
        type="button"
        class="btn-secondary refresh-split-toggle"
        disabled={disabled}
        aria-expanded={open}
        aria-label="Refresh options"
        aria-haspopup="true"
        title={title}
        onClick={() => setOpen((value) => !value)}
      >
        ▾
      </button>
      {open && (
        <div class="overflow-panel refresh-split-menu">
          <button type="button" onClick={() => pick("listings")}>
            Listings
          </button>
          <button type="button" onClick={() => pick("disk")}>
            Disk
          </button>
          {showSonarr && (
            <button type="button" onClick={() => pick("sonarr")}>
              Sonarr
            </button>
          )}
        </div>
      )}
    </div>
  );
}
