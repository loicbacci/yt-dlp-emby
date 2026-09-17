export const queryKeys = {
  seriesList: () => ["series-list"] as const,
  series: (platform: string, slug: string) => ["series", platform, slug] as const,
  episodes: (
    platform: string,
    slug: string,
    sourceId: number,
    seasonId: number,
  ) => ["episodes", platform, slug, sourceId, seasonId] as const,
  episodesSource: (platform: string, slug: string, sourceId: number) =>
    ["episodes", platform, slug, sourceId] as const,
  episodesSeries: (platform: string, slug: string) =>
    ["episodes", platform, slug] as const,
  disk: (platform: string, slug: string) => ["disk", platform, slug] as const,
  missing: (platform: string, slug: string) =>
    ["series-missing", platform, slug] as const,
  sonarrEpisodes: (tvdbId: number) => ["sonarr-episodes", tvdbId] as const,
  check: (slug: string) => ["series-check", slug] as const,
  layout: (slug: string) => ["series-layout", slug] as const,
  config: () => ["app-config"] as const,
};

export const persistQueryRoots = new Set([
  "series-list",
  "series",
  "episodes",
  "disk",
  "series-missing",
  "sonarr-episodes",
  "series-check",
]);

export function shouldPersistQuery(queryKey: readonly unknown[]): boolean {
  return typeof queryKey[0] === "string" && persistQueryRoots.has(queryKey[0]);
}
