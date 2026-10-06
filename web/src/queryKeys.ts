export const queryKeys = {
  seriesList: () => ["series-list"] as const,
  series: (platform: string, slug: string) => ["series", platform, slug] as const,
  episodes: (platform: string, slug: string, sourceIndex: number, seasonId: number) =>
    ["episodes", platform, slug, sourceIndex, seasonId] as const,
  episodesSource: (platform: string, slug: string, sourceIndex: number) =>
    ["episodes", platform, slug, sourceIndex] as const,
  episodesSeries: (platform: string, slug: string) => ["episodes", platform, slug] as const,
  disk: (platform: string, slug: string) => ["disk", platform, slug] as const,
  missing: (platform: string, slug: string) => ["series-missing", `${platform}|${slug}`] as const,
  missingBatch: (keys: string[]) => ["series-missing-batch", ...keys] as const,
  sonarrEpisodes: (tvdbId: number) => ["sonarr-episodes", tvdbId] as const,
  config: () => ["app-config"] as const,
  platform: (kind: string) => ["platform-settings", kind] as const,
  cookies: () => ["cookies"] as const,
  queue: () => ["queue"] as const,
  jobs: () => ["jobs"] as const,
  session: () => ["session"] as const,
};
