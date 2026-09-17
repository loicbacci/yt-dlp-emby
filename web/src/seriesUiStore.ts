import { createStore } from "@tanstack/preact-store";

const STORAGE_KEY = "yt-dlp-emby-series-ui";

export type SeriesFolds = Record<string, boolean>;

type SeriesUiState = {
  folds: Record<string, SeriesFolds>;
};

function readFolds(): Record<string, SeriesFolds> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as { folds?: Record<string, SeriesFolds> };
    if (parsed.folds && typeof parsed.folds === "object") return parsed.folds;
  } catch {
    /* ignore */
  }
  return {};
}

export function seriesUiKey(platform: string, slug: string): string {
  return `${platform}:${slug}`;
}

function canUseStorage(): boolean {
  try {
    return typeof localStorage !== "undefined";
  } catch {
    return false;
  }
}

export const seriesUiStore = createStore<SeriesUiState>({
  folds: canUseStorage() ? readFolds() : {},
});

if (canUseStorage()) {
  seriesUiStore.subscribe(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ folds: seriesUiStore.state.folds }),
      );
    } catch {
      /* ignore */
    }
  });
}

export function setSeriesFolds(seriesKey: string, folds: SeriesFolds): void {
  seriesUiStore.setState((prev) => ({
    folds: { ...prev.folds, [seriesKey]: folds },
  }));
}

export function patchSeriesFold(
  seriesKey: string,
  foldKey: string,
  open: boolean,
): void {
  seriesUiStore.setState((prev) => ({
    folds: {
      ...prev.folds,
      [seriesKey]: { ...(prev.folds[seriesKey] ?? {}), [foldKey]: open },
    },
  }));
}
