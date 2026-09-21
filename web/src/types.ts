import { z } from "zod";

export type Source = "youtube" | "dropout";
export type RunPhase = "idle" | "planning" | "downloading" | "stopping" | "exited";
export type RunStatus = "idle" | "running" | "stopping" | "exited";
export type PathSource = "env" | "manifest" | "fallback" | "unset";
export type CookieKind = Source;
export type ConfigKey =
  | "library"
  | "old_dir"
  | "staging"
  | "bench_dest"
  | "shows_dir"
  | "sonarr_url"
  | "sonarr_api_key";
export type EpisodeFileStatus = "downloaded" | "missing" | "skipped" | "unmapped";

export type Session = { setup_required: boolean; authenticated: boolean };
export type ManifestImport = { path: string; text: string; exists: boolean };
export type ManifestPathInfo = {
  manifest: string | null;
  effective: string | null;
  source: PathSource;
  env_name: string | null;
};
export type ManifestPaths = {
  library: ManifestPathInfo;
  old_dir: ManifestPathInfo;
  staging: ManifestPathInfo;
};
export type Manifest = {
  kind: Source;
  text: string;
  exists: boolean;
  imports?: ManifestImport[];
  paths?: ManifestPaths | null;
};
export type ManifestValidate = {
  ok: boolean;
  paths?: ManifestPaths | null;
  error?: string | null;
};

export type PlanSeason = {
  platform: Source;
  slug: string;
  series: string;
  dest_season: number;
  season_title: string | null;
  folder: string;
  download: number;
  skip: number;
  unmapped: number;
  replace: number;
  rename?: number;
  remove?: number;
};

export type PlanItem = {
  id: string;
  action: string;
  code: string;
  title: string;
  dest_season: number;
  season_title: string | null;
  folder: string;
  size: number | null;
  series: string;
  slug: string;
  platform: Source;
  url?: string | null;
};

export type PlanSourceBlock = {
  ok: boolean;
  error: string | null;
  seasons: PlanSeason[];
  items: PlanItem[];
};

export type PlanFile = {
  generated_at: string | null;
  force: boolean;
  sources: Record<string, PlanSourceBlock>;
};

export type RunProgressEvent =
  | { event: "series"; name?: string }
  | { event: "item_steps"; id?: string; steps?: unknown }
  | {
      event: "progress";
      id?: string;
      percent?: unknown;
      phase?: string;
      step?: unknown;
      steps?: unknown;
      speed?: unknown;
      eta?: unknown;
      bytes?: unknown;
      total?: unknown;
    }
  | { event: "item_done"; id?: string; action?: string };

export type Run = {
  status: RunStatus;
  phase: RunPhase;
  source: Source | null;
  dry_run: boolean;
  verbose: boolean;
  force: boolean;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  plan: { generated_at: string | null; force: boolean; pending: number } | null;
  progress?: RunProgressEvent | null;
};

export type DownloadOptions = {
  ids: string[] | null;
  force?: boolean;
  create?: boolean;
};

export type DropoutCheckHint = {
  text: string;
  kind: string;
  sure?: boolean;
  dropout_season?: number | null;
  dropout_episode?: number | null;
  series_name?: string | null;
};

export type DropoutCheck = {
  ok: boolean;
  missing: {
    season: number;
    episode: number;
    code: string;
    title: string;
    hints: DropoutCheckHint[];
  }[];
  warnings: { code: string; detail: string }[];
  title_mismatches: { code: string; file_title: string; sonarr_title: string }[];
};

export type DropoutLayout = {
  folders: {
    dest_season: number | null;
    label: string;
    folder?: string;
    episodes: {
      code: string | null;
      title: string;
      status: string;
      origin: string | null;
    }[];
  }[];
};

export type ConfigField = {
  file: ConfigSlot;
  effective: ConfigSlot;
  source: "env" | "file" | "unset";
  env_name: string | null;
  section: "fallback" | "root";
};

/**
 * Masked secret slot shape returned by GET/PUT /api/config for sonarr_api_key
 * (Phase 2). Raw values are only available via GET /api/config?reveal=1.
 */
export type MaskedSecret = { set: boolean; masked: string | null };
export type ConfigSlot = string | MaskedSecret | null;

export function isMaskedSecret(value: unknown): value is MaskedSecret {
  if (!value || typeof value !== "object") return false;
  const rec = value as Record<string, unknown>;
  return typeof rec.set === "boolean" && (typeof rec.masked === "string" || rec.masked == null);
}

/** Raw text of a config slot. Masked secrets never leak here: they map to "". */
export function slotText(slot: ConfigSlot | undefined): string {
  return typeof slot === "string" ? slot : "";
}

export function slotIsSet(slot: ConfigSlot | undefined): boolean {
  if (typeof slot === "string") return slot.trim() !== "";
  if (isMaskedSecret(slot)) return slot.set;
  return false;
}

/** Display text: raw strings pass through, masked secrets show the last-4 hint. */
export function slotDisplay(slot: ConfigSlot | undefined): string {
  if (typeof slot === "string") return slot;
  if (isMaskedSecret(slot)) return slot.masked ?? "";
  return "";
}
export type AppConfig = {
  path: string;
  exists: boolean;
  fields: Record<ConfigKey, ConfigField>;
};
export type ConfigValues = Record<ConfigKey, string>;

export type CookieJar = {
  filename: string;
  path: string;
  exists: boolean;
  usable: boolean;
};
export type CookieStatus = {
  env_name: string | null;
  env_set: boolean;
  env_path: string | null;
  jars: Record<CookieKind, CookieJar>;
};

export type PlatformSettings = {
  library: string;
  old_dir: string;
  cookies: string;
  paths: ManifestPaths | null;
  cookie_jar: CookieJar;
};

export type SeriesSeason = {
  id: string;
  dropout: number | null;
  url: string;
  to_season: number | null;
  enabled: boolean;
  only_episodes: number[] | null;
  remaps: {
    dropout_episode: number;
    to_season?: number;
    to_episode?: number;
    title?: string;
    skip?: boolean;
  }[];
  skip_ids: string[];
  label: string;
  sublabel: string;
  title: string | null;
};

export type SeriesSource = {
  id: string;
  url: string;
  error: string | null;
  seasons: SeriesSeason[];
};

export type SeriesDetail = {
  platform: Source;
  slug: string;
  file: string;
  inline: boolean;
  name: string;
  path: string;
  tvdb_id: number | null;
  source_count: number;
  season_count: number;
  tvdb_skip: { season: number; episodes: number[] }[];
  sources: SeriesSource[];
  poster_url?: string;
  refreshed?: {
    listings: string | null;
    disk: string | null;
    sonarr: string | null;
  };
};

export type SeriesEpisode = {
  id: string;
  title: string;
  url: string;
  source_episode: number;
  skipped: boolean;
  mapped_season: number | null;
  mapped_episode: number | null;
  mapped_title: string | null;
  status?: EpisodeFileStatus;
};

export type SonarrEpisode = {
  season: number;
  episode: number;
  title: string;
  air_date: string | null;
};

export type SonarrPing = {
  ok: boolean;
  version: string | null;
  instance: string | null;
};

export type MissingRow = { missing_count: number | null; complete: boolean };

const sourceSchema = z.enum(["youtube", "dropout"]);

// Accepted deviation: response schemas stay shallow (top-level shape + passthrough).
// Deep per-field zod schemas for PlanFile/SeriesDetail were skipped as low-ROI:
// the server owns validation and the UI reads narrow slices plus runtime guards.
const runProgressSchema: z.ZodType<RunProgressEvent> = z.union([
  z.object({ event: z.literal("series") }).passthrough(),
  z.object({ event: z.literal("item_steps") }).passthrough(),
  z.object({ event: z.literal("progress") }).passthrough(),
  z.object({ event: z.literal("item_done") }).passthrough(),
]) as z.ZodType<RunProgressEvent>;

export const runSchema = z
  .object({
    status: z.enum(["idle", "running", "stopping", "exited"]),
    phase: z.enum(["idle", "planning", "downloading", "stopping", "exited"]),
    source: sourceSchema.nullable(),
    dry_run: z.boolean(),
    verbose: z.boolean(),
    force: z.boolean(),
    started_at: z.string().nullable(),
    finished_at: z.string().nullable(),
    exit_code: z.number().nullable(),
    plan: z
      .object({
        generated_at: z.string().nullable(),
        force: z.boolean(),
        pending: z.number(),
      })
      .nullable(),
    progress: runProgressSchema.nullable().optional(),
  })
  .passthrough();

export const planFileSchema = z
  .object({
    generated_at: z.string().nullable(),
    force: z.boolean(),
    sources: z.record(z.string(), z.unknown()),
  })
  .passthrough();

export const seriesDetailSchema = z
  .object({
    platform: sourceSchema,
    slug: z.string(),
    file: z.string(),
    inline: z.boolean(),
    name: z.string(),
    path: z.string(),
    tvdb_id: z.number().nullable(),
    source_count: z.number(),
    season_count: z.number(),
    tvdb_skip: z.array(
      z.object({
        season: z.number(),
        episodes: z.array(z.number()),
      }),
    ),
    sources: z.array(z.unknown()),
  })
  .passthrough();

export function parseWith<T>(schema: z.ZodTypeAny, data: unknown, label: string): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new Error(`${label} response was not the expected shape`);
  }
  return result.data as T;
}

/** Stable source identity is the numeric array index returned by the API. */
export function sourceIndexKey(sourceIndex: number): string {
  return String(sourceIndex);
}

export function tvdbSkipKey(
  skip: { season: number; episodes: number[] }[] | null | undefined,
): string {
  if (!skip?.length) return "";
  return skip
    .map((block) => `${block.season}:${[...block.episodes].sort((a, b) => a - b).join(",")}`)
    .join("|");
}
