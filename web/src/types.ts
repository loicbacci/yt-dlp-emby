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
  | "shows_dir"
  | "sonarr_url"
  | "sonarr_api_key";
export type EpisodeFileStatus = "downloaded" | "missing" | "skipped" | "unmapped" | "unknown";

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
  execution_id?: string;
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
  plan_id?: string;
  revision?: string;
  readiness?: "ready" | "stale" | "unavailable" | string;
  generated_at: string | null;
  force: boolean;
  stale?: boolean;
  cache_errors?: { platform: string; slug: string; error: string }[];
  sources: Record<string, PlanSourceBlock>;
};

export type JobKind = "refresh" | "download" | "check" | "diagnostics";
export type JobStatus =
  | "queued"
  | "running"
  | "stopping"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";
export type JobProgress = {
  stage: string;
  target: string | null;
  completed: number;
  total: number | null;
  item?: Record<string, unknown> | null;
};
export type JobLog = { n: number; ts: string; line: string };
export type JobSnapshot = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: JobProgress | null;
  result: unknown;
  error: unknown;
  logs: JobLog[];
  log_cursor: number;
  logs_truncated: boolean;
  can_cancel: boolean;
  can_retry: boolean;
};
export type JobStart = { job_id: string; status: "queued" };
export type JobRequest =
  | {
      kind: "refresh";
      items: { platform: Source; slug: string }[];
      parts?: ("listings" | "disk" | "sonarr")[];
      source_index?: number;
      expected_revision?: string;
    }
  | {
      kind: "download";
      ids: string[];
    }
  | { kind: "check"; items: { platform: Source; slug: string }[] }
  | { kind: "diagnostics"; checks: string[] };
export type LibrarySnapshot = {
  status: "ready" | "unavailable";
  series_exists: boolean | null;
  episodes: number | null;
  episode_fingerprints: unknown;
  revision: string | null;
  scanned_at: string | null;
  mount_identity: unknown;
  error: string | null;
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
  config_revision?: string | null;
  source_count: number;
  season_count: number;
  tvdb_skip: { season: number; episodes: number[] }[];
  sources: SeriesSource[];
  poster_url?: string;
  freshness?: "ready" | "stale" | "unavailable";
  last_attempt_at?: string | null;
  last_success_at?: string | null;
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
export const episodeFileStatusSchema = z.enum([
  "downloaded",
  "missing",
  "skipped",
  "unmapped",
  "unknown",
]);

export const dropoutCheckSchema = z
  .object({
    ok: z.boolean(),
    missing: z.array(
      z
        .object({
          season: z.number(),
          episode: z.number(),
          code: z.string(),
          title: z.string(),
          hints: z.array(
            z
              .object({
                text: z.string(),
                kind: z.string(),
                sure: z.boolean().optional(),
                dropout_season: z.number().nullable().optional(),
                dropout_episode: z.number().nullable().optional(),
                series_name: z.string().nullable().optional(),
              })
              .passthrough(),
          ),
        })
        .passthrough(),
    ),
    warnings: z.array(z.object({ code: z.string(), detail: z.string() }).passthrough()),
    title_mismatches: z.array(
      z
        .object({ code: z.string(), file_title: z.string(), sonarr_title: z.string() })
        .passthrough(),
    ),
  })
  .passthrough();

// Plan bodies retain their established tree shape while adding an executable
// revision and a readiness signal for job admission.
export const planFileSchema = z
  .object({
    plan_id: z.string().min(1),
    revision: z.string().min(1),
    readiness: z.string(),
    generated_at: z.string().nullable(),
    force: z.boolean(),
    sources: z.record(z.string(), z.unknown()),
  })
  .passthrough();

export const jobProgressSchema = z.object({
  stage: z.string(),
  target: z
    .union([z.string(), z.object({ platform: z.string(), slug: z.string() }).passthrough()])
    .nullable()
    .optional()
    .transform((target) =>
      typeof target === "string" ? target : target ? `${target.platform}|${target.slug}` : null,
    ),
  completed: z.number().int().nonnegative(),
  total: z.number().int().nonnegative().nullable(),
  item: z.record(z.string(), z.unknown()).nullable().optional(),
});
export const jobLogSchema = z.object({
  n: z.number().int().nonnegative(),
  ts: z.string(),
  line: z.string(),
});
export const jobSnapshotSchema = z
  .object({
    id: z.string().min(1),
    kind: z.enum(["refresh", "download", "check", "diagnostics"]),
    status: z.enum([
      "queued",
      "running",
      "stopping",
      "succeeded",
      "failed",
      "cancelled",
      "interrupted",
    ]),
    created_at: z.string(),
    started_at: z.string().nullable(),
    finished_at: z.string().nullable(),
    progress: jobProgressSchema.nullable(),
    result: z.unknown(),
    error: z.unknown(),
    logs: z.array(jobLogSchema).max(200),
    log_cursor: z.number().int().nonnegative(),
    logs_truncated: z.boolean(),
    can_cancel: z.boolean(),
    can_retry: z.boolean(),
  })
  .passthrough();
export const jobStartSchema = z.object({ job_id: z.string().min(1), status: z.literal("queued") });
export const jobsListSchema = z
  .object({
    active: jobSnapshotSchema.nullable(),
    history: z.array(jobSnapshotSchema),
    total: z.number().int().nonnegative(),
  })
  .passthrough();
export const librarySnapshotSchema = z
  .object({
    status: z.enum(["ready", "unavailable"]),
    series_exists: z.boolean().nullable(),
    episodes: z.number().int().nonnegative().nullable(),
    episode_fingerprints: z.unknown(),
    revision: z.string().nullable(),
    scanned_at: z.string().nullable(),
    mount_identity: z.unknown(),
    error: z.string().nullable(),
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

export const seriesEpisodeSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    url: z.string(),
    source_episode: z.number(),
    skipped: z.boolean(),
    mapped_season: z.number().nullable(),
    mapped_episode: z.number().nullable(),
    mapped_title: z.string().nullable(),
    status: episodeFileStatusSchema.optional(),
  })
  .passthrough();
export const seriesEpisodesResponseSchema = z
  .object({
    episodes: z.array(seriesEpisodeSchema),
    on_disk: z.array(z.object({ season: z.number(), episode: z.number() })).optional(),
    disk_state: z.enum(["ready", "unavailable", "stale"]).optional(),
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
