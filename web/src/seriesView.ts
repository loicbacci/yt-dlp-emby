import type { EpisodeFileStatus, SeriesEpisode, SeriesSeason, SeriesSource } from "./api";
import { slotText } from "./api";
import type { ConfigSlot } from "./api";

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
  poster_url?: string;
  refreshed?: {
    listings: string | null;
    disk: string | null;
    sonarr: string | null;
  };
};

const slugPattern = /[^a-z0-9]+/g;

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(slugPattern, "-")
    .replace(/^-+|-+$/g, "");
}

/** Index show posters by file slug and by slugify(name) so the queue can
 *  join plan rows that still use the apostrophe-preserving pipeline slug. */
export function indexSeriesPosters(
  rows: { platform: string; slug: string; name: string; poster_url?: string | null }[],
): Map<string, string> {
  const map = new Map<string, string>();
  for (const row of rows) {
    if (!row.poster_url) continue;
    map.set(`${row.platform}|${row.slug}`, row.poster_url);
    const fromName = slugify(row.name);
    if (fromName && fromName !== row.slug) {
      map.set(`${row.platform}|${fromName}`, row.poster_url);
    }
  }
  return map;
}

export function seriesPosterUrl(
  posters: Map<string, string>,
  platform: string,
  slug: string,
  name?: string,
): string | undefined {
  return (
    posters.get(`${platform}|${slug}`) ??
    (name ? posters.get(`${platform}|${slugify(name)}`) : undefined)
  );
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
  const raw = parts.slice(2).join("/");
  let slug = raw;
  try {
    slug = decodeURIComponent(raw);
  } catch {
    slug = raw;
  }
  return { platform, slug };
}

export function formatMapsTo(season: number, episode: number): string {
  const s = String(season).padStart(2, "0");
  const e = String(episode).padStart(2, "0");
  return `S${s}E${e}`;
}

export function shortUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname.replace(/\/$/, "")}`;
  } catch {
    return url;
  }
}

export function seasonHeading(toSeason: number): string {
  if (toSeason === 0) return "Specials";
  return `Season ${toSeason}`;
}

export function seasonDisplayName(toSeason: number, title: string | null | undefined): string {
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
  return folds[seasonFoldKey(sourceId, seasonId)] === true;
}

export function countLabel(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function seasonMissingLabel(missing: number | null | undefined): string {
  if (missing == null || missing <= 0) return "";
  return countLabel(missing, "missing", "missing");
}

export function emptyListMessage(total: number, filtered: number): string {
  if (total === 0) return "No series yet"; // CTA is rendered by SeriesList
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
  const remap = season.remaps.find((item) => item.dropout_episode === episode.source_episode);
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

export type RemapKind = "default" | "skip" | "same-season" | "other-season";

export function defaultDestSeason(season: {
  to_season: number | null;
  dropout: number | null;
}): number | null {
  if (season.to_season != null) return season.to_season;
  return season.dropout;
}

export function remapKind(season: SeriesSeason, episode: SeriesEpisode): RemapKind {
  const mapped = applySeasonToEpisode(season, episode);
  if (mapped.skipped) return "skip";
  const remap = season.remaps.find(
    (item) => item.dropout_episode === episode.source_episode && !item.skip,
  );
  if (!remap || remap.to_season == null) return "default";
  const dest = defaultDestSeason(season);
  return remap.to_season === dest ? "same-season" : "other-season";
}

export function originLabel(row: CatalogEpisode): string {
  const dropout = row.season.dropout != null ? `Dropout ${row.season.dropout}` : row.season.label;
  const url = row.sourceUrl ? ` · ${shortUrl(row.sourceUrl)}` : "";
  return `${dropout} · E${row.episode.source_episode}${url}`;
}

export type DestOccupant = {
  row: CatalogEpisode;
  mapped: SeriesEpisode;
  kind: RemapKind;
  status: EpisodeFileStatus;
};

export type DestSlot = {
  destSeason: number;
  destEpisode: number;
  code: string;
  title: string;
  sonarr: boolean;
  skipped: boolean;
  occupants: DestOccupant[];
};

export type DestSeasonGroup = {
  destSeason: number;
  label: string;
  slots: DestSlot[];
  holes: number;
  conflicts: number;
  packable: boolean;
};

export type DestMap = {
  seasons: DestSeasonGroup[];
  leftovers: DestOccupant[];
};

export function isTvdbSkipped(
  skip: { season: number; episodes: number[] }[] | undefined,
  season: number,
  episode: number,
): boolean {
  return Boolean(
    skip?.some((block) => block.season === season && block.episodes.includes(episode)),
  );
}

export function seasonFillStatus(group: {
  slots: DestSlot[];
  holes: number;
}): "ok" | "partial" | "empty" {
  const downloaded = group.slots.filter((slot) =>
    slot.occupants.some((occ) => occ.status === "downloaded"),
  ).length;
  if (downloaded === 0) return "empty";
  if (group.holes > 0) return "partial";
  return "ok";
}

export function missingStatusClass(count: number | null | undefined): string {
  if (count == null) return "";
  return count <= 0 ? "is-ok" : "is-new";
}

export function missingStatusText(count: number | null | undefined): string | null {
  if (count == null) return null;
  return count <= 0 ? "Up to date" : `${count} missing`;
}

export function remapFormDefaults(episode: {
  mapped_season: number | null;
  mapped_episode: number | null;
  mapped_title: string | null;
  title: string;
}): { toSeason: string; toEpisode: string; title: string } {
  return {
    toSeason: episode.mapped_season != null ? String(episode.mapped_season) : "",
    toEpisode: episode.mapped_episode != null ? String(episode.mapped_episode) : "",
    title: episode.mapped_title || episode.title,
  };
}

export function sonarrEpisodeIsOut(
  title: string,
  airDate?: string | null,
  today = new Date().toISOString().slice(0, 10),
): boolean {
  const label = title.trim().toLowerCase();
  if (!label || label === "tba" || label === "tbd" || label === "tbc") return false;
  if (!airDate) return true;
  const day = airDate.trim().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return true;
  return day <= today;
}

export function filterSonarrEpisodes<T extends { season: number; episode: number; title: string }>(
  episodes: T[],
  query: string,
): T[] {
  const raw = query.trim().toLowerCase();
  if (!raw) return episodes;
  const compact = raw.replace(/\s+/g, "");
  const code = /^s?(\d+)e(\d+)$/i.exec(compact);
  return episodes.filter((episode) => {
    if (code) {
      return episode.season === Number(code[1]) && episode.episode === Number(code[2]);
    }
    if (episode.title.toLowerCase().includes(raw)) return true;
    if (formatMapsTo(episode.season, episode.episode).toLowerCase().includes(compact)) {
      return true;
    }
    if (String(episode.episode) === compact || `e${episode.episode}` === compact) {
      return true;
    }
    return false;
  });
}

export function rankSonarrRecommendations<
  T extends { season: number; episode: number; title: string },
>(
  all: T[],
  suggested: T[],
  episode: {
    title: string;
    mapped_season: number | null;
    mapped_episode: number | null;
    source_episode: number;
  },
): T[] {
  const seen = new Set<string>();
  const ranked: T[] = [];
  const add = (item: T | undefined) => {
    if (!item) return;
    const key = `${item.season}-${item.episode}`;
    if (seen.has(key)) return;
    seen.add(key);
    ranked.push(item);
  };
  for (const item of suggested) add(item);
  if (episode.mapped_season != null && episode.mapped_episode != null) {
    add(
      all.find(
        (item) => item.season === episode.mapped_season && item.episode === episode.mapped_episode,
      ),
    );
  }
  for (const item of all) {
    if (item.episode === episode.source_episode) add(item);
  }
  const needle = episode.title.trim().toLowerCase();
  if (needle) {
    for (const item of all) {
      const title = item.title.toLowerCase();
      if (title.includes(needle) || needle.includes(title)) add(item);
    }
  }
  return ranked.slice(0, 12);
}

export function buildDestMap(
  catalog: CatalogEpisode[],
  sonarr:
    | { season: number; episode: number; title: string; air_date?: string | null }[]
    | null
    | undefined,
  onDisk: ReadonlySet<string>,
  tvdbSkip?: { season: number; episodes: number[] }[],
): DestMap {
  const leftovers: DestOccupant[] = [];
  const bySlot = new Map<string, DestOccupant[]>();
  for (const row of catalog) {
    const mapped = applySeasonToEpisode(row.season, row.episode);
    const kind = remapKind(row.season, row.episode);
    const status = fileStatus(mapped, onDisk);
    const occupant: DestOccupant = { row, mapped, kind, status };
    if (mapped.skipped || mapped.mapped_season == null || mapped.mapped_episode == null) {
      leftovers.push(occupant);
      continue;
    }
    const key = diskSlotKey(mapped.mapped_season, mapped.mapped_episode);
    const list = bySlot.get(key);
    if (list) list.push(occupant);
    else bySlot.set(key, [occupant]);
  }

  const sonarrBySeason = new Map<number, { episode: number; title: string }[]>();
  for (const item of sonarr ?? []) {
    if (!sonarrEpisodeIsOut(item.title, item.air_date)) continue;
    const list = sonarrBySeason.get(item.season) ?? [];
    list.push({ episode: item.episode, title: item.title });
    sonarrBySeason.set(item.season, list);
  }

  const destSeasons = new Set<number>();
  for (const key of bySlot.keys()) {
    destSeasons.add(Number(key.split("-")[0]));
  }
  for (const season of sonarrBySeason.keys()) destSeasons.add(season);

  const seasons: DestSeasonGroup[] = [...destSeasons]
    .sort((a, b) => Number(a === 0) - Number(b === 0) || a - b)
    .map((destSeason) => {
      const sonarrEps = (sonarrBySeason.get(destSeason) ?? [])
        .slice()
        .sort((a, b) => a.episode - b.episode);
      const episodeNums = new Set<number>();
      for (const item of sonarrEps) episodeNums.add(item.episode);
      for (const key of bySlot.keys()) {
        const [seasonRaw, episodeRaw] = key.split("-");
        if (Number(seasonRaw) === destSeason) episodeNums.add(Number(episodeRaw));
      }
      const titles = new Map(sonarrEps.map((item) => [item.episode, item.title]));
      const slots: DestSlot[] = [...episodeNums]
        .sort((a, b) => a - b)
        .map((destEpisode) => {
          const occupants = bySlot.get(diskSlotKey(destSeason, destEpisode)) ?? [];
          const title =
            titles.get(destEpisode) ||
            occupants[0]?.mapped.mapped_title ||
            occupants[0]?.row.episode.title ||
            "";
          return {
            destSeason,
            destEpisode,
            code: formatMapsTo(destSeason, destEpisode),
            title,
            sonarr: titles.has(destEpisode),
            skipped: isTvdbSkipped(tvdbSkip, destSeason, destEpisode),
            occupants,
          };
        });
      return {
        destSeason,
        label: seasonHeading(destSeason),
        slots,
        holes: slots.filter((slot) => slot.sonarr && slot.occupants.length === 0 && !slot.skipped)
          .length,
        conflicts: slots.filter((slot) => slot.occupants.length > 1).length,
        packable: false,
      };
    });

  return { seasons, leftovers };
}

export type PackRemap = {
  sourceId: number;
  seasonId: number;
  dropout_episode: number;
  to_season: number;
  to_episode: number;
  title: string;
  clear: boolean;
};

export function packDestSeasonRemaps(destSeason: number, catalog: CatalogEpisode[]): PackRemap[] {
  const native = catalog
    .map((row) => ({ row, mapped: applySeasonToEpisode(row.season, row.episode) }))
    .filter(({ row, mapped }) => {
      if (mapped.skipped) return false;
      if (mapped.mapped_season !== destSeason) return false;
      return defaultDestSeason(row.season) === destSeason;
    })
    .sort(
      (a, b) =>
        a.row.episode.source_episode - b.row.episode.source_episode ||
        a.row.sourceId - b.row.sourceId ||
        a.row.seasonId - b.row.seasonId,
    );

  const changes: PackRemap[] = [];
  native.forEach(({ row, mapped }, index) => {
    const toEpisode = index + 1;
    const dest = defaultDestSeason(row.season);
    const isDefault = dest === destSeason && row.episode.source_episode === toEpisode;
    const already = mapped.mapped_season === destSeason && mapped.mapped_episode === toEpisode;
    const remap = row.season.remaps.find(
      (item) => item.dropout_episode === row.episode.source_episode && !item.skip,
    );
    if (already && isDefault) {
      if (remap) {
        changes.push({
          sourceId: row.sourceId,
          seasonId: row.seasonId,
          dropout_episode: row.episode.source_episode,
          to_season: destSeason,
          to_episode: toEpisode,
          title: mapped.mapped_title || row.episode.title,
          clear: true,
        });
      }
      return;
    }
    if (already) return;
    changes.push({
      sourceId: row.sourceId,
      seasonId: row.seasonId,
      dropout_episode: row.episode.source_episode,
      to_season: destSeason,
      to_episode: toEpisode,
      title: mapped.mapped_title || row.episode.title,
      clear: false,
    });
  });
  return changes;
}

export function applyPackRemapsToSources(
  sources: SeriesSource[],
  changes: PackRemap[],
): SeriesSource[] {
  if (!changes.length) return sources;
  return sources.map((src, sid) => {
    const forSource = changes.filter((change) => change.sourceId === sid);
    if (!forSource.length) return src;
    return {
      ...src,
      seasons: src.seasons.map((season, seasonId) => {
        const forSeason = forSource.filter((change) => change.seasonId === seasonId);
        if (!forSeason.length) return season;
        let remaps = season.remaps;
        for (const change of forSeason) {
          remaps = remaps.filter((item) => item.dropout_episode !== change.dropout_episode);
          if (!change.clear) {
            remaps = [
              ...remaps,
              {
                dropout_episode: change.dropout_episode,
                to_season: change.to_season,
                to_episode: change.to_episode,
                title: change.title || undefined,
              },
            ];
          }
        }
        return { ...season, remaps };
      }),
    };
  });
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
  return rows.sort((a, b) => a.season - b.season || a.episode - b.episode);
}

export function sonarrBadgeLabel(
  check:
    | {
        ok: boolean;
        missing: unknown[];
      }
    | null
    | undefined,
): string | null {
  if (!check) return null;
  if (check.missing.length > 0) {
    const n = check.missing.length;
    return `${n} missing`;
  }
  if (check.ok) return "ok";
  return "warnings";
}

export type CatalogEpisode = {
  sourceId: number;
  seasonId: number;
  season: SeriesSeason;
  episode: SeriesEpisode;
  sourceUrl?: string;
};

export function catalogEpisodes(
  sources: SeriesSource[] | undefined,
  episodeMap: Record<string, SeriesEpisode[]>,
): CatalogEpisode[] {
  const rows: CatalogEpisode[] = [];
  for (const [sourceId, source] of (sources ?? []).entries()) {
    source.seasons.forEach((season, seasonId) => {
      const key = seasonFoldKey(sourceId, seasonId);
      for (const episode of episodeMap[key] ?? []) {
        rows.push({ sourceId, seasonId, season, episode, sourceUrl: source.url });
      }
    });
  }
  return rows;
}

export function findCatalogEpisode(
  catalog: CatalogEpisode[],
  dropoutSeason: number | null | undefined,
  dropoutEpisode: number,
): CatalogEpisode | null {
  const matches = catalog.filter((row) => {
    if (row.episode.source_episode !== dropoutEpisode) return false;
    if (dropoutSeason == null) return true;
    return row.season.dropout === dropoutSeason;
  });
  return matches[0] ?? null;
}

export function catalogEpisodeKey(row: CatalogEpisode): string {
  return `${row.sourceId}-${row.seasonId}-${row.episode.id}`;
}

export function filterCatalogEpisodes(catalog: CatalogEpisode[], query: string): CatalogEpisode[] {
  const q = query.trim().toLowerCase();
  return catalog.filter((row) => {
    if (row.episode.skipped) return false;
    if (!q) return true;
    const mapped = applySeasonToEpisode(row.season, row.episode);
    const maps =
      mapped.mapped_season != null && mapped.mapped_episode != null
        ? formatMapsTo(mapped.mapped_season, mapped.mapped_episode).toLowerCase()
        : "";
    const dropout = row.season.dropout != null ? `season ${row.season.dropout}` : "";
    return (
      row.episode.title.toLowerCase().includes(q) ||
      String(row.episode.source_episode).includes(q) ||
      `e${row.episode.source_episode}`.includes(q) ||
      row.season.label.toLowerCase().includes(q) ||
      dropout.includes(q) ||
      maps.includes(q)
    );
  });
}

export function remapCandidatesForMissing(
  catalog: CatalogEpisode[],
  missing: {
    title: string;
    hints: {
      kind: string;
      dropout_season?: number | null;
      dropout_episode?: number | null;
    }[];
  },
): CatalogEpisode[] {
  const seen = new Set<string>();
  const rows: CatalogEpisode[] = [];
  const add = (item: CatalogEpisode | null | undefined) => {
    if (!item || item.episode.skipped) return;
    const key = `${item.sourceId}-${item.seasonId}-${item.episode.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    rows.push(item);
  };
  for (const hint of missing.hints) {
    if (hint.kind !== "origin" || hint.dropout_episode == null) continue;
    add(findCatalogEpisode(catalog, hint.dropout_season, hint.dropout_episode));
  }
  const needle = missing.title.trim().toLowerCase();
  if (needle) {
    for (const item of catalog) {
      const title = item.episode.title.trim().toLowerCase();
      if (!title) continue;
      if (title.includes(needle) || needle.includes(title)) add(item);
    }
  }
  return rows;
}

export function tvdbSeriesUrl(tvdbId: number): string {
  return `https://thetvdb.com/dereferrer/series/${tvdbId}`;
}

export function sonarrSeriesUrl(
  baseUrl: string,
  titleSlug: string | null | undefined,
  tvdbId: number,
): string {
  const root = baseUrl.replace(/\/+$/, "");
  if (!root) return "";
  if (titleSlug) return `${root}/series/${encodeURIComponent(titleSlug)}`;
  return `${root}/add/new?term=${encodeURIComponent(`tvdb:${tvdbId}`)}`;
}

export function effectiveConfigValue(
  field: { file: ConfigSlot; effective: ConfigSlot } | undefined,
): string {
  // slotText maps masked secret objects to "" so this never throws on
  // `.trim()` and never leaks secrets into hrefs/labels.
  return (slotText(field?.effective) || slotText(field?.file)).trim();
}
