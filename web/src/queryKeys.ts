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
  check: (slug: string, skipKey = "") => ["series-check", slug, skipKey] as const,
  layout: (slug: string) => ["series-layout", slug] as const,
  config: () => ["app-config"] as const,
  cookies: () => ["cookies"] as const,
  plan: () => ["plan"] as const,
  run: () => ["run"] as const,
  session: () => ["session"] as const,
};

export const persistQueryRoots = new Set(["series-list", "series", "episodes", "sonarr-episodes"]);

export function shouldPersistQuery(queryKey: readonly unknown[]): boolean {
  return typeof queryKey[0] === "string" && persistQueryRoots.has(queryKey[0]);
}
