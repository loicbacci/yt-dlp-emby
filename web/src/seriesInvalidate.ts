import type { QueryClient } from "@tanstack/preact-query";
import { queryKeys } from "./queryKeys";
import type { SeriesPlatform } from "./seriesView";

export async function invalidateSeriesState(
  queryClient: QueryClient,
  items: { platform: SeriesPlatform; slug: string; tvdb_id?: number | null }[],
  extras: { plan?: boolean } = {},
): Promise<void> {
  const jobs = [queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() })];
  if (extras.plan !== false) {
    jobs.push(queryClient.invalidateQueries({ queryKey: queryKeys.plan() }));
  }
  for (const item of items) {
    jobs.push(
      queryClient.invalidateQueries({
        queryKey: queryKeys.series(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.episodesSeries(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.disk(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.missing(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({ queryKey: queryKeys.check(item.slug) }),
    );
    if (item.tvdb_id != null) {
      jobs.push(
        queryClient.invalidateQueries({
          queryKey: queryKeys.sonarrEpisodes(item.tvdb_id),
        }),
      );
    }
  }
  await Promise.all(jobs);
}

export async function invalidateAfterQueueRebuild(
  queryClient: QueryClient,
  affected?: { platform: string; slug: string; tvdb_id?: number | null }[],
): Promise<void> {
  const jobs = [
    queryClient.invalidateQueries({ queryKey: queryKeys.plan() }),
    queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() }),
  ];
  for (const item of affected ?? []) {
    jobs.push(
      queryClient.invalidateQueries({
        queryKey: queryKeys.series(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.episodesSeries(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.disk(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.missing(item.platform, item.slug),
      }),
      queryClient.invalidateQueries({ queryKey: queryKeys.check(item.slug) }),
    );
    if (item.tvdb_id != null) {
      jobs.push(
        queryClient.invalidateQueries({
          queryKey: queryKeys.sonarrEpisodes(item.tvdb_id),
        }),
      );
    }
  }
  await Promise.all(jobs);
}
