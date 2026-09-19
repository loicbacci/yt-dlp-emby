import catalog from "./catalog.json";

export type TileTone = "terra" | "teal" | "rose" | "gold" | "blue";
export type EpStatus = "library" | "missing" | "skipped";
export type RemapKind = "default" | "skip" | "same" | "other";

export type MockEpisode = {
  n: number;
  title: string;
  status: EpStatus;
};

export type MockSeason = {
  n: number;
  id: string;
  label: string;
  folder: string;
  episodes: MockEpisode[];
};

export type MockMapEpisode = {
  n: number;
  title: string;
  skip?: boolean;
  toSeason?: number;
  toEpisode?: number;
  remapTitle?: string;
};

export type MockMapSeason = {
  dropout: number | null;
  title: string;
  toSeason: number | null;
  enabled: boolean;
  episodes: MockMapEpisode[];
};

export type MockMapSource = {
  url: string;
  seasons: MockMapSeason[];
};

export type MockShow = {
  id: string;
  name: string;
  letter: string;
  tone: TileTone;
  platform: "dropout" | "youtube";
  path: string;
  poster?: string;
  tvdbId?: number | null;
  sourceCount: number;
  yamlSeasons: number;
  seasons: MockSeason[];
  sources: MockMapSource[];
  tvdbSkip: { season: number; episodes: number[] }[];
};

export const MOCK_SHOWS = catalog as MockShow[];

export function showById(id: string): MockShow {
  const match = MOCK_SHOWS.find((show) => show.id === id);
  if (!match) throw new Error(`Unknown show ${id}`);
  return match;
}

export function episodeCode(season: number, episode: number): string {
  return `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
}

export function embyCode(season: number, episode: number): string {
  if (season === 0) return `Specials E${String(episode).padStart(2, "0")}`;
  return episodeCode(season, episode);
}

export function missingCount(show: MockShow): number {
  return show.seasons.reduce(
    (n, season) =>
      n + season.episodes.filter((ep) => ep.status === "missing").length,
    0,
  );
}

export function statusCounts(show: MockShow) {
  const episodes = show.seasons.flatMap((season) => season.episodes);
  return {
    library: episodes.filter((ep) => ep.status === "library").length,
    missing: episodes.filter((ep) => ep.status === "missing").length,
    skipped: episodes.filter((ep) => ep.status === "skipped").length,
    total: episodes.length,
  };
}

export function seasonCounts(season: MockSeason) {
  const library = season.episodes.filter((ep) => ep.status === "library").length;
  const missing = season.episodes.filter((ep) => ep.status === "missing").length;
  const skipped = season.episodes.filter((ep) => ep.status === "skipped").length;
  return { library, missing, skipped, total: season.episodes.length };
}

export function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, "");
}

export function mapsToLabel(season: MockMapSeason, ep: MockMapEpisode): string {
  if (ep.skip) return "Skip";
  const destSeason = ep.toSeason ?? season.toSeason;
  const destEpisode = ep.toEpisode ?? ep.n;
  if (destSeason == null) return "—";
  return embyCode(destSeason, destEpisode);
}

export function remapKind(season: MockMapSeason, ep: MockMapEpisode): RemapKind {
  if (ep.skip) return "skip";
  const destSeason = ep.toSeason ?? season.toSeason;
  if (ep.toSeason == null && ep.toEpisode == null && !ep.remapTitle) {
    return "default";
  }
  if (destSeason != null && season.toSeason != null && destSeason !== season.toSeason) {
    return "other";
  }
  return "same";
}

export type QueueSeason = {
  id: string;
  n: number;
  label: string;
  folder: string;
  episodes: { id: string; title: string; code: string; size: string }[];
};

export function missingSeasons(show: MockShow): QueueSeason[] {
  const size = show.platform === "youtube" ? "180 MB" : "1.1 GB";
  return show.seasons
    .map((season) => ({
      id: season.id,
      n: season.n,
      label: season.n === 0 ? "Specials" : season.label,
      folder: season.folder,
      episodes: season.episodes
        .filter((ep) => ep.status === "missing")
        .map((ep) => ({
          id: `${show.id}-${season.n}-${ep.n}`,
          title: ep.title,
          code: episodeCode(season.n, ep.n),
          size,
        })),
    }))
    .filter((season) => season.episodes.length > 0);
}

export function downloadQueue(): { show: MockShow; seasons: QueueSeason[] }[] {
  const rows = MOCK_SHOWS.map((show) => ({
    show,
    seasons: missingSeasons(show),
  })).filter((row) => row.seasons.length > 0);
  const d20 = rows.filter((row) => row.show.id === "dimension-20");
  const rest = rows
    .filter((row) => row.show.id !== "dimension-20")
    .sort((a, b) => missingCount(b.show) - missingCount(a.show));
  return [...d20, ...rest];
}
