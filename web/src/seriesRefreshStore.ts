import { createStore, useSelector } from "@tanstack/preact-store";

type RefreshState = { counts: Map<string, number>; serverKeys: Set<string> };

export const seriesRefreshStore = createStore<RefreshState>({
  counts: new Map<string, number>(),
  serverKeys: new Set<string>(),
});

export function refreshSeriesKey(platform: string, slug: string): string {
  return `${platform}|${slug}`;
}

export function beginRefresh(keys: string[]): void {
  if (!keys.length) return;
  seriesRefreshStore.setState((state) => {
    const next = new Map(state.counts);
    for (const key of new Set(keys)) next.set(key, (next.get(key) ?? 0) + 1);
    return { ...state, counts: next };
  });
}

export function endRefresh(keys: string[]): void {
  if (!keys.length) return;
  seriesRefreshStore.setState((state) => {
    const next = new Map(state.counts);
    for (const key of new Set(keys)) {
      const count = next.get(key) ?? 0;
      if (count <= 1) next.delete(key);
      else next.set(key, count - 1);
    }
    return { ...state, counts: next };
  });
}

export function setServerRefreshing(keys: string[]): void {
  seriesRefreshStore.setState((state) => ({
    ...state,
    serverKeys: new Set(keys),
  }));
}

export function isRefreshing(platform: string, slug: string): boolean {
  const key = refreshSeriesKey(platform, slug);
  return seriesRefreshStore.state.counts.has(key) || seriesRefreshStore.state.serverKeys.has(key);
}

export function useSeriesRefreshing(platform: string, slug: string): boolean {
  const key = refreshSeriesKey(platform, slug);
  return useSelector(
    seriesRefreshStore,
    (state) => state.counts.has(key) || state.serverKeys.has(key),
  );
}

export function useAnyRefreshing(): string[] {
  return useSelector(seriesRefreshStore, (state) => [
    ...new Set([...state.counts.keys(), ...state.serverKeys]),
  ]);
}
