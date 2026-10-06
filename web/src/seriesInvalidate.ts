import type { QueryClient } from "@tanstack/preact-query";
import { type SeriesDetail, type SeriesEpisode, apiClient } from "./api";
import { queryKeys } from "./queryKeys";
import { beginRefresh, endRefresh, refreshSeriesKey } from "./seriesRefreshStore";
import {
  type SeriesPlatform,
  type SeriesSummary,
  applySeasonToEpisode,
  diskSlotKey,
} from "./seriesView";

export enum SeriesChangeType {
  Presentation = "presentation",
  EpisodeMapping = "episode_mapping",
  SeasonMapping = "season_mapping",
  Catalog = "catalog",
  LibraryPath = "library_path",
  SonarrMapping = "sonarr_mapping",
}

export type MetadataRefreshPart = "all" | "listings" | "disk" | "sonarr";

type SeriesRefreshAction = "episode_listings" | "disk_slots" | "disk_inventory" | "sonarr";

const refreshActionsByChange: Record<SeriesChangeType, readonly SeriesRefreshAction[]> = {
  [SeriesChangeType.Presentation]: [],
  [SeriesChangeType.EpisodeMapping]: ["disk_slots"],
  [SeriesChangeType.SeasonMapping]: ["disk_slots"],
  [SeriesChangeType.Catalog]: ["episode_listings"],
  [SeriesChangeType.LibraryPath]: ["disk_inventory"],
  [SeriesChangeType.SonarrMapping]: ["sonarr"],
};

function needsRefresh(changes: SeriesChangeType[], action: SeriesRefreshAction): boolean {
  return changes.some((change) => refreshActionsByChange[change].includes(action));
}

export function classifySeriesChange(
  previous: SeriesDetail,
  next: SeriesDetail,
): SeriesChangeType[] {
  const changes = new Set<SeriesChangeType>();
  if (previous.platform !== next.platform || previous.sources.length !== next.sources.length) {
    changes.add(SeriesChangeType.Catalog);
  }
  for (const [sourceId, source] of previous.sources.entries()) {
    const nextSource = next.sources[sourceId];
    if (
      !nextSource ||
      source.url !== nextSource.url ||
      source.seasons.length !== nextSource.seasons.length
    ) {
      changes.add(SeriesChangeType.Catalog);
      continue;
    }
    for (const [seasonId, season] of source.seasons.entries()) {
      const nextSeason = nextSource.seasons[seasonId];
      if (!nextSeason || season.url !== nextSeason.url) {
        changes.add(SeriesChangeType.Catalog);
      }
    }
  }
  if (previous.path !== next.path) changes.add(SeriesChangeType.LibraryPath);
  if (previous.tvdb_id !== next.tvdb_id) changes.add(SeriesChangeType.SonarrMapping);

  let seasonMappingChanged = false;
  let episodeMappingChanged = JSON.stringify(previous.tvdb_skip) !== JSON.stringify(next.tvdb_skip);
  for (const [sourceId, source] of previous.sources.entries()) {
    const nextSource = next.sources[sourceId];
    if (!nextSource) continue;
    for (const [seasonId, season] of source.seasons.entries()) {
      const nextSeason = nextSource.seasons[seasonId];
      if (!nextSeason) continue;
      if (
        season.to_season !== nextSeason.to_season ||
        season.dropout !== nextSeason.dropout ||
        season.enabled !== nextSeason.enabled
      ) {
        seasonMappingChanged = true;
      }
      if (
        JSON.stringify(season.only_episodes) !== JSON.stringify(nextSeason.only_episodes) ||
        JSON.stringify(season.remaps) !== JSON.stringify(nextSeason.remaps) ||
        JSON.stringify(season.skip_ids) !== JSON.stringify(nextSeason.skip_ids)
      ) {
        episodeMappingChanged = true;
      }
    }
  }
  if (seasonMappingChanged) changes.add(SeriesChangeType.SeasonMapping);
  if (episodeMappingChanged) changes.add(SeriesChangeType.EpisodeMapping);
  if (!changes.size) changes.add(SeriesChangeType.Presentation);
  return [...changes];
}

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

export async function invalidateAfterMetadataRefresh(
  queryClient: QueryClient,
  items: { platform: SeriesPlatform; slug: string; tvdb_id?: number | null }[],
  part: MetadataRefreshPart = "all",
  options: { sourceId?: number } = {},
): Promise<void> {
  const wantsListings = part === "all" || part === "listings";
  const wantsDisk = part === "all" || part === "disk";
  const wantsSonarr = part === "all" || part === "sonarr";
  const jobs = [queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() })];
  if (wantsListings || wantsDisk) {
    jobs.push(queryClient.invalidateQueries({ queryKey: queryKeys.plan() }));
    jobs.push(queryClient.invalidateQueries({ queryKey: queryKeys.missingBatch([]) }));
  }
  for (const item of items) {
    jobs.push(
      queryClient.invalidateQueries({ queryKey: queryKeys.series(item.platform, item.slug) }),
    );
    if (wantsListings) {
      jobs.push(
        queryClient.invalidateQueries({
          queryKey:
            options.sourceId == null
              ? queryKeys.episodesSeries(item.platform, item.slug)
              : queryKeys.episodesSource(item.platform, item.slug, options.sourceId),
        }),
      );
    }
    if (wantsDisk) {
      jobs.push(
        queryClient.invalidateQueries({ queryKey: queryKeys.disk(item.platform, item.slug) }),
      );
    }
    if (wantsListings || wantsDisk) {
      jobs.push(
        queryClient.invalidateQueries({ queryKey: queryKeys.missing(item.platform, item.slug) }),
      );
    }
    if (wantsListings || wantsDisk || wantsSonarr) {
      jobs.push(queryClient.invalidateQueries({ queryKey: queryKeys.check(item.slug) }));
    }
    if (wantsSonarr && item.tvdb_id != null) {
      jobs.push(
        queryClient.invalidateQueries({ queryKey: queryKeys.sonarrEpisodes(item.tvdb_id) }),
      );
    }
  }
  await Promise.all(jobs);
}

export async function invalidateAfterSourceRefresh(
  queryClient: QueryClient,
  item: { platform: SeriesPlatform; slug: string },
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() }),
    queryClient.invalidateQueries({ queryKey: queryKeys.plan() }),
    queryClient.invalidateQueries({ queryKey: queryKeys.missingBatch([]) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.missing(item.platform, item.slug) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.check(item.slug) }),
  ]);
}

export async function invalidateAfterSeriesChange(
  queryClient: QueryClient,
  previous: SeriesDetail,
  next: SeriesDetail,
  options: { refreshedSourceIds?: number[] } = {},
): Promise<void> {
  const item = { platform: next.platform, slug: next.slug };
  patchSeriesSummary(queryClient, next);
  const changes = classifySeriesChange(previous, next);
  if (needsRefresh(changes, "episode_listings") || options.refreshedSourceIds?.length) {
    const sourceCount = Math.max(previous.sources.length, next.sources.length);
    await withRefresh(next, () =>
      Promise.all(
        Array.from({ length: sourceCount }, (_, sourceId) => {
          const oldSource = previous.sources[sourceId];
          const newSource = next.sources[sourceId];
          const explicitlyRefreshed = options.refreshedSourceIds?.includes(sourceId) ?? false;
          const sourceUrlChanged = oldSource?.url !== newSource?.url;
          const seasonCount = Math.max(
            oldSource?.seasons.length ?? 0,
            newSource?.seasons.length ?? 0,
          );
          const jobs: Promise<void>[] = [];
          for (let seasonId = 0; seasonId < seasonCount; seasonId += 1) {
            const oldSeason = oldSource?.seasons[seasonId];
            const newSeason = newSource?.seasons[seasonId];
            if (
              explicitlyRefreshed ||
              sourceUrlChanged ||
              !oldSeason ||
              !newSeason ||
              oldSeason.url !== newSeason.url
            ) {
              jobs.push(
                queryClient.invalidateQueries({
                  queryKey: queryKeys.episodes(item.platform, item.slug, sourceId, seasonId),
                }),
              );
            }
          }
          return Promise.all(jobs).then(() => undefined);
        }),
      ),
    );
  }
  if (needsRefresh(changes, "disk_inventory")) {
    await withRefresh(next, () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.disk(item.platform, item.slug) }),
    );
  }
  if (needsRefresh(changes, "sonarr")) {
    await withRefresh(next, () =>
      Promise.all([
        ...(previous.tvdb_id == null
          ? []
          : [
              queryClient.invalidateQueries({
                queryKey: queryKeys.sonarrEpisodes(previous.tvdb_id),
              }),
            ]),
        ...(next.tvdb_id == null
          ? []
          : [
              queryClient.invalidateQueries({
                queryKey: queryKeys.sonarrEpisodes(next.tvdb_id),
              }),
            ]),
      ]),
    );
  }
  if (needsRefresh(changes, "disk_slots")) {
    // A mapping edit changes which slots an episode points at, not the source
    // catalog or the rest of the library. Recheck only the old/new target slots.
    await withRefresh(next, () => refreshMappedDiskSlots(queryClient, previous, next));
  }
}

async function withRefresh<T>(detail: SeriesDetail, work: () => Promise<T>): Promise<T> {
  const key = refreshSeriesKey(detail.platform, detail.slug);
  beginRefresh([key]);
  try {
    return await work();
  } finally {
    endRefresh([key]);
  }
}

async function refreshMappedDiskSlots(
  queryClient: QueryClient,
  previous: SeriesDetail,
  next: SeriesDetail,
): Promise<void> {
  const slots = new Map<string, { season: number; episode: number }>();
  const sourceCount = Math.max(previous.sources.length, next.sources.length);
  for (let sourceId = 0; sourceId < sourceCount; sourceId += 1) {
    const oldSource = previous.sources[sourceId];
    const newSource = next.sources[sourceId];
    const seasonCount = Math.max(oldSource?.seasons.length ?? 0, newSource?.seasons.length ?? 0);
    for (let seasonId = 0; seasonId < seasonCount; seasonId += 1) {
      const oldSeason = oldSource?.seasons[seasonId];
      const newSeason = newSource?.seasons[seasonId];
      if (!oldSeason || !newSeason) continue;
      const cache = queryClient.getQueryData<{ episodes: SeriesEpisode[] }>(
        queryKeys.episodes(previous.platform, previous.slug, sourceId, seasonId),
      );
      const episodes = new Map(
        (cache?.episodes ?? []).map((episode) => [episode.source_episode, episode]),
      );
      const remappedEpisodes = new Set([
        ...(oldSeason.remaps ?? []).map((remap) => remap.dropout_episode),
        ...(newSeason.remaps ?? []).map((remap) => remap.dropout_episode),
        ...(oldSeason.only_episodes ?? []),
        ...(newSeason.only_episodes ?? []),
        ...numericEpisodeIds(oldSeason.skip_ids),
        ...numericEpisodeIds(newSeason.skip_ids),
      ]);
      for (const sourceEpisode of remappedEpisodes) {
        if (episodes.has(sourceEpisode)) continue;
        episodes.set(sourceEpisode, {
          id: String(sourceEpisode),
          title: "",
          url: "",
          source_episode: sourceEpisode,
          skipped: false,
          mapped_season: null,
          mapped_episode: null,
          mapped_title: null,
        });
      }
      for (const episode of episodes.values()) {
        const oldTarget = applySeasonToEpisode(oldSeason, episode);
        const newTarget = applySeasonToEpisode(newSeason, episode);
        if (
          oldTarget.mapped_season === newTarget.mapped_season &&
          oldTarget.mapped_episode === newTarget.mapped_episode
        ) {
          continue;
        }
        for (const target of [oldTarget, newTarget]) {
          if (target.mapped_season == null || target.mapped_episode == null) continue;
          const slot = { season: target.mapped_season, episode: target.mapped_episode };
          slots.set(diskSlotKey(slot.season, slot.episode), slot);
        }
      }
    }
  }
  if (!slots.size) return;
  try {
    const result = await apiClient.checkSeriesDiskSlots(next.platform, next.slug, [
      ...slots.values(),
    ]);
    const diskKey = queryKeys.disk(next.platform, next.slug);
    const current = queryClient.getQueryData<{
      on_disk: { season: number; episode: number }[];
    }>(diskKey);
    if (!current) return;
    const onDisk = new Map(
      current.on_disk.map((slot) => [diskSlotKey(slot.season, slot.episode), slot]),
    );
    for (const slot of result.slots) {
      const key = diskSlotKey(slot.season, slot.episode);
      if (slot.on_disk) onDisk.set(key, { season: slot.season, episode: slot.episode });
      else onDisk.delete(key);
    }
    queryClient.setQueryData(diskKey, { on_disk: [...onDisk.values()] });
  } catch {
    // Keep the last inventory cache; a later normal disk refresh can retry.
  }
}

function numericEpisodeIds(ids: string[]): number[] {
  return ids.flatMap((id) => {
    const episode = Number(id);
    return Number.isSafeInteger(episode) && episode > 0 ? [episode] : [];
  });
}

function patchSeriesSummary(queryClient: QueryClient, detail: SeriesDetail): void {
  type SeriesListData = {
    series: SeriesSummary[];
    import_errors: { file: string; error: string }[];
  };
  const current = queryClient.getQueryData<SeriesListData>(queryKeys.seriesList());
  if (!current) return;
  const series = current.series.map((row) =>
    row.platform === detail.platform && row.slug === detail.slug
      ? {
          ...row,
          name: detail.name,
          path: detail.path,
          tvdb_id: detail.tvdb_id,
          source_count: detail.source_count,
          season_count: detail.season_count,
        }
      : row,
  );
  queryClient.setQueryData(queryKeys.seriesList(), { ...current, series });
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
