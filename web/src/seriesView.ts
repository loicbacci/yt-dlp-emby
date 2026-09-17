import type { EpisodeFileStatus } from "./api";

export type SeriesPlatform = "youtube" | "dropout";

export type SeriesSummary = {
  platform: SeriesPlatform;
  slug: string;
  file: string;
  inline: boolean;
  name: string;
  path: string;
  tvdb_id: number | null;
  source_count: number;
  season_count: number;
  missing_count?: number | null;
  listings_complete?: boolean;
};

const slugPattern = /[^a-z0-9]+/g;

export function slugify(name: string): string {
  return name.toLowerCase().replace(slugPattern, "-").replace(/^-+|-+$/g, "");
}

export function suggestFolder(name: string, tvdbId: number | null): string {
  if (tvdbId !== null && tvdbId >= 1) {
    return `${name} [tvdbid=${tvdbId}]`;
  }
  return name;
}

export function uniqueNameError(
  name: string,
  existing: { name: string; slug?: string }[],
): string | null {
  const folded = name.trim().toLowerCase();
  if (!folded) return null;
  const hit = existing.find((row) => row.name.toLowerCase() === folded);
  if (!hit) return null;
  return `A series named ${hit.name} already exists`;
}

export function parseSeriesPath(path: string): {
  platform: SeriesPlatform;
  slug: string;
} | null {
  const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] !== "series" || parts.length < 3) return null;
  const platform = parts[1];
  if (platform !== "youtube" && platform !== "dropout") return null;
  return { platform, slug: parts.slice(2).join("/") };
}

export function formatMapsTo(season: number, episode: number): string {
  const s = String(season).padStart(2, "0");
  const e = String(episode).padStart(2, "0");
  return `S${s}E${e}`;
}

export function seasonHeading(toSeason: number): string {
  if (toSeason === 0) return "Specials";
  return `Season ${toSeason}`;
}

export function seasonDisplayName(
  toSeason: number,
  title: string | null | undefined,
): string {
  if (title && title.trim()) return title.trim();
  return seasonHeading(toSeason);
}

export function filterSeries(
  list: SeriesSummary[],
  options: { query?: string; platform?: SeriesPlatform | "all" },
): SeriesSummary[] {
  const query = (options.query ?? "").trim().toLowerCase();
  const platform = options.platform ?? "all";
  return list
    .filter((row) => platform === "all" || row.platform === platform)
    .filter((row) => {
      if (!query) return true;
      return (
        row.name.toLowerCase().includes(query) ||
        row.path.toLowerCase().includes(query) ||
        row.slug.toLowerCase().includes(query)
      );
    })
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}

export function seasonFoldKey(sourceId: number, seasonId: number): string {
  return `${sourceId}-${seasonId}`;
}

export function seasonFoldMap(
  sources: { seasons: unknown[] }[],
  open: boolean,
): Record<string, boolean> {
  const next: Record<string, boolean> = {};
  sources.forEach((source, sourceId) => {
    source.seasons.forEach((_season, seasonId) => {
      next[seasonFoldKey(sourceId, seasonId)] = open;
    });
  });
  return next;
}

export function isSeasonOpen(
  folds: Record<string, boolean>,
  sourceId: number,
  seasonId: number,
): boolean {
  return folds[seasonFoldKey(sourceId, seasonId)] !== false;
}

export function countLabel(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function seasonMissingLabel(missing: number | null | undefined): string {
  if (missing == null || missing <= 0) return "";
  return countLabel(missing, "missing", "missing");
}

export function emptyListMessage(total: number, filtered: number): string {
  if (total === 0) return "No series yet.";
  if (filtered === 0) return "No matching series.";
  return "";
}

export function applySeasonToEpisode(
  season: {
    only_episodes: number[] | null;
    remaps: {
      dropout_episode: number;
      to_season?: number;
      to_episode?: number;
      title?: string;
      skip?: boolean;
    }[];
    skip_ids: string[];
  },
  episode: {
    id: string;
    title: string;
    url: string;
    source_episode: number;
    skipped: boolean;
    mapped_season: number | null;
    mapped_episode: number | null;
    mapped_title: string | null;
  },
): typeof episode {
  const remap = season.remaps.find(
    (item) => item.dropout_episode === episode.source_episode,
  );
  if (season.skip_ids.includes(episode.id) || remap?.skip) {
    return {
      ...episode,
      skipped: true,
      mapped_season: null,
      mapped_episode: null,
    };
  }
  let skipped = false;
  if (season.only_episodes && season.only_episodes.length) {
    skipped = !season.only_episodes.includes(episode.source_episode);
  }
  if (remap && remap.to_season != null && remap.to_episode != null) {
    return {
      ...episode,
      skipped,
      mapped_season: remap.to_season,
      mapped_episode: remap.to_episode,
      mapped_title: remap.title ?? episode.title,
    };
  }
  return { ...episode, skipped };
}

export function diskSlotKey(season: number, episode: number): string {
  return `${season}-${episode}`;
}

export function fileStatus(
  episode: {
    skipped: boolean;
    mapped_season: number | null;
    mapped_episode: number | null;
  },
  onDisk: ReadonlySet<string>,
): EpisodeFileStatus {
  if (episode.skipped) return "skipped";
  if (episode.mapped_season == null || episode.mapped_episode == null) {
    return "unmapped";
  }
  return onDisk.has(diskSlotKey(episode.mapped_season, episode.mapped_episode))
    ? "downloaded"
    : "missing";
}

export function episodeStatusLabel(status: EpisodeFileStatus): string {
  if (status === "downloaded") return "downloaded";
  if (status === "missing") return "missing";
  if (status === "unmapped") return "unmapped";
  return "skipped";
}

export type TvdbSkipBlock = { season: number; episodes: number[] };

export function addTvdbSkip(
  skip: TvdbSkipBlock[],
  season: number,
  episode: number,
): TvdbSkipBlock[] {
  const next = skip.map((block) => ({
    ...block,
    episodes: [...block.episodes],
  }));
  const block = next.find((item) => item.season === season);
  if (block) {
    if (!block.episodes.includes(episode)) {
      block.episodes.push(episode);
      block.episodes.sort((a, b) => a - b);
    }
    return next;
  }
  next.push({ season, episodes: [episode] });
  return next;
}

export function removeTvdbSkip(
  skip: TvdbSkipBlock[],
  season: number,
  episode: number,
): TvdbSkipBlock[] {
  return skip
    .map((block) =>
      block.season !== season
        ? block
        : {
            ...block,
            episodes: block.episodes.filter((item) => item !== episode),
          },
    )
    .filter((block) => block.episodes.length > 0);
}

export function skippedTvdbRows(
  skip: TvdbSkipBlock[],
  episodes: { season: number; episode: number; title?: string }[],
): { season: number; episode: number; title?: string }[] {
  const titles = new Map(
    episodes.map((item) => [diskSlotKey(item.season, item.episode), item.title]),
  );
  const rows: { season: number; episode: number; title?: string }[] = [];
  for (const block of skip) {
    for (const episode of block.episodes) {
      rows.push({
        season: block.season,
        episode,
        title: titles.get(diskSlotKey(block.season, episode)),
      });
    }
  }
  return rows.sort(
    (a, b) => a.season - b.season || a.episode - b.episode,
  );
}

export function sonarrBadgeLabel(check: {
  ok: boolean;
  missing: unknown[];
} | null | undefined): string | null {
  if (!check) return null;
  if (check.missing.length > 0) {
    const n = check.missing.length;
    return `${n} missing`;
  }
  if (check.ok) return "ok";
  return "warnings";
}
