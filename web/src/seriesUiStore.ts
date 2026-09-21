import { createStore } from "@tanstack/preact-store";

const STORAGE_KEY = "yt-dlp-emby-series-ui";
const LRU_MAX = 50;

export type SeriesFolds = Record<string, boolean>;
export type SeriesTab = "sources" | "emby" | "yaml";

type SeriesUiState = {
  folds: Record<string, SeriesFolds>;
  folderView: Record<string, SeriesTab>;
};

function readState(): SeriesUiState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { folds: {}, folderView: {} };
    const parsed = JSON.parse(raw) as Partial<SeriesUiState>;
    const folds =
      parsed.folds && typeof parsed.folds === "object" && !Array.isArray(parsed.folds)
        ? parsed.folds
        : {};
    const folderView =
      parsed.folderView && typeof parsed.folderView === "object" ? parsed.folderView : {};
    return { folds, folderView };
  } catch {
    return { folds: {}, folderView: {} };
  }
}

function lruCap<T>(map: Record<string, T>, key: string, value: T): Record<string, T> {
  const next = { ...map, [key]: value };
  const keys = Object.keys(next);
  if (keys.length <= LRU_MAX) return next;
  const drop = keys.slice(0, keys.length - LRU_MAX);
  for (const item of drop) delete next[item];
  return next;
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

export const seriesUiStore = createStore<SeriesUiState>(
  canUseStorage() ? readState() : { folds: {}, folderView: {} },
);

let persistTimer: number | undefined;
if (canUseStorage()) {
  seriesUiStore.subscribe(() => {
    if (persistTimer !== undefined) window.clearTimeout(persistTimer);
    persistTimer = window.setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(seriesUiStore.state));
      } catch {
        /* ignore */
      }
    }, 250);
  });
}

export function setSeriesFolds(seriesKey: string, folds: SeriesFolds): void {
  seriesUiStore.setState((prev) => ({
    ...prev,
    folds: lruCap(prev.folds, seriesKey, folds),
  }));
}

export function patchSeriesFold(seriesKey: string, foldKey: string, open: boolean): void {
  seriesUiStore.setState((prev) => ({
    ...prev,
    folds: lruCap(prev.folds, seriesKey, {
      ...(prev.folds[seriesKey] ?? {}),
      [foldKey]: open,
    }),
  }));
}

export function setFolderViewPref(seriesKey: string, view: SeriesTab): void {
  seriesUiStore.setState((prev) => ({
    ...prev,
    folderView: lruCap(prev.folderView, seriesKey, view),
  }));
}
