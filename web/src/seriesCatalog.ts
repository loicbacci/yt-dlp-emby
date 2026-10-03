import { useQueries, useQuery } from "@tanstack/preact-query";
import { type SeriesEpisode, type SeriesSource, type Source, apiClient } from "./api";
import { DISK_STALE_MS, EPISODE_STALE_MS } from "./queryClient";
import { queryKeys } from "./queryKeys";
import { diskSlotKey, seasonFoldKey } from "./seriesView";

export function onDiskSet(slots: { season: number; episode: number }[] | undefined): Set<string> {
  const next = new Set<string>();
  for (const slot of slots ?? []) {
    next.add(diskSlotKey(slot.season, slot.episode));
  }
  return next;
}

export function mergeOnDisk(
  disk: { season: number; episode: number }[] | undefined,
  extras: { on_disk?: { season: number; episode: number }[] }[],
): Set<string> {
  if (disk) return onDiskSet(disk);
  const next = new Set<string>();
  for (const extra of extras) {
    for (const slot of extra.on_disk ?? []) {
      next.add(diskSlotKey(slot.season, slot.episode));
    }
  }
  return next;
}

export function useSeriesCatalog(
  platform: Source,
  slug: string,
  sources: SeriesSource[] | undefined,
) {
  const jobs: { sourceId: number; seasonId: number }[] = [];
  for (const [sourceId, source] of (sources ?? []).entries()) {
    source.seasons.forEach((_season, seasonId) => {
      jobs.push({ sourceId, seasonId });
    });
  }
  const episodeQueries = useQueries({
    queries: jobs.map((job) => ({
      queryKey: queryKeys.episodes(platform, slug, job.sourceId, job.seasonId),
      queryFn: () => apiClient.getSeriesEpisodes(platform, slug, job.sourceId, job.seasonId),
      staleTime: EPISODE_STALE_MS,
      enabled: Boolean(slug),
    })),
  });
  const diskQuery = useQuery({
    queryKey: queryKeys.disk(platform, slug),
    queryFn: () => apiClient.getSeriesDisk(platform, slug),
    staleTime: DISK_STALE_MS,
    enabled: Boolean(slug && jobs.length),
  });
  const episodeMap: Record<string, SeriesEpisode[]> = {};
  const loadingMap: Record<string, boolean> = {};
  for (const [index, job] of jobs.entries()) {
    const key = seasonFoldKey(job.sourceId, job.seasonId);
    const query = episodeQueries[index];
    if (!query) continue;
    if (query.data) {
      episodeMap[key] = query.data.episodes ?? [];
    }
    loadingMap[key] = Boolean(query.isPending && !query.data);
  }
  return {
    episodeMap,
    loadingMap,
    diskState: diskQuery.data?.state ?? (diskQuery.data ? "ready" : "unavailable"),
    diskReady: Boolean(
      diskQuery.data && diskQuery.data.state !== "unavailable" && diskQuery.data.state !== "stale",
    ),
    diskError:
      diskQuery.data?.error ?? (diskQuery.error instanceof Error ? diskQuery.error.message : null),
    onDisk:
      diskQuery.data && diskQuery.data.state !== "unavailable" && diskQuery.data.state !== "stale"
        ? mergeOnDisk(
            diskQuery.data.on_disk,
            episodeQueries.map((query) => query.data ?? {}),
          )
        : new Set<string>(),
  };
}
