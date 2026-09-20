import { createStore, useSelector } from "@tanstack/preact-store";

type RefreshState = { keys: Set<string> };

export const seriesRefreshStore = createStore<RefreshState>({
  keys: new Set<string>(),
});

export function refreshSeriesKey(platform: string, slug: string): string {
  return `${platform}|${slug}`;
}

export function beginRefresh(keys: string[]): void {
  if (!keys.length) return;
  seriesRefreshStore.setState((state) => {
    const next = new Set(state.keys);
    for (const key of keys) next.add(key);
    return { keys: next };
  });
}

export function endRefresh(keys: string[]): void {
  if (!keys.length) return;
  seriesRefreshStore.setState((state) => {
    const next = new Set(state.keys);
    for (const key of keys) next.delete(key);
    return { keys: next };
  });
}

export function isRefreshing(platform: string, slug: string): boolean {
  return seriesRefreshStore.state.keys.has(refreshSeriesKey(platform, slug));
}

export function useSeriesRefreshing(platform: string, slug: string): boolean {
  const key = refreshSeriesKey(platform, slug);
  return useSelector(seriesRefreshStore, (state) => state.keys.has(key));
}

export function useAnyRefreshing(): Set<string> {
  return useSelector(seriesRefreshStore, (state) => state.keys);
}
