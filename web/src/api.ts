import type {
  AppConfig,
  ConfigSlot,
  ConfigValues,
  CookieKind,
  CookieStatus,
  DownloadOptions,
  DropoutCheck,
  DropoutLayout,
  Manifest,
  ManifestImport,
  ManifestPaths,
  ManifestValidate,
  MaskedSecret,
  MissingRow,
  PlanFile,
  PlatformSettings,
  Run,
  SeriesDetail,
  SeriesEpisode,
  Session,
  SonarrEpisode,
  SonarrPing,
  Source,
} from "./types";
import {
  isMaskedSecret,
  parseWith,
  planFileSchema,
  runSchema,
  seriesDetailSchema,
  slotDisplay,
  slotIsSet,
  slotText,
} from "./types";

export { isMaskedSecret, slotDisplay, slotIsSet, slotText };
export type { ConfigSlot, MaskedSecret };

export type {
  AppConfig,
  ConfigField,
  ConfigKey,
  ConfigValues,
  CookieJar,
  CookieKind,
  CookieStatus,
  DropoutCheck,
  DropoutCheckHint,
  DropoutLayout,
  DownloadOptions,
  EpisodeFileStatus,
  Manifest,
  ManifestImport,
  ManifestPathInfo,
  ManifestPaths,
  ManifestValidate,
  PathSource,
  PlanFile,
  PlanSourceBlock,
  PlatformSettings,
  Run,
  RunPhase,
  RunProgressEvent,
  RunStatus,
  SeriesDetail,
  SeriesEpisode,
  SeriesSeason,
  SeriesSource,
  Session,
  SonarrEpisode,
  SonarrPing,
  Source,
} from "./types";

const REQUEST_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export class UnauthorizedError extends ApiError {
  constructor(message = "Unauthorized") {
    super(401, message);
    this.name = "UnauthorizedError";
  }
}

export function messageFromErrorBody(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const rec = body as Record<string, unknown>;
  if (typeof rec.error === "string" && rec.error.trim()) return rec.error;
  const detail = rec.detail;
  if (detail && typeof detail === "object") {
    const nested = (detail as { error?: unknown }).error;
    if (typeof nested === "string" && nested.trim()) return nested;
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  try {
    return JSON.stringify(body);
  } catch {
    return fallback;
  }
}

function mergeHeaders(init?: RequestInit): Headers {
  const headers = new Headers();
  headers.set("Accept", "application/json");
  if (init?.body) headers.set("Content-Type", "application/json");
  if (init?.headers) {
    new Headers(init.headers).forEach((value, key) => {
      headers.set(key, value);
    });
  }
  return headers;
}

function mergeSignal(timeout: AbortSignal, extra?: AbortSignal | null): AbortSignal {
  if (!extra) return timeout;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([timeout, extra]);
  return extra;
}

function seriesUrl(platform: Source, slug: string, suffix = ""): string {
  return `/api/series/${platform}/${encodeURIComponent(slug)}${suffix}`;
}

async function api<T>(path: string, init?: RequestInit, parse?: (data: unknown) => T): Promise<T> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const { signal: initSignal, headers: _headers, ...rest } = init ?? {};
  const response = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: mergeHeaders(init),
    signal: mergeSignal(timeout, initSignal),
  });
  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      message = messageFromErrorBody(await response.json(), message);
    } catch {
      /* ignore */
    }
    if (response.status === 401) throw new UnauthorizedError(message);
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const data: unknown = await response.json();
  return parse ? parse(data) : (data as T);
}

export function routeForSession(session: Session, path: string): string {
  if (session.setup_required) return path === "/setup" ? path : "/setup";
  if (!session.authenticated) {
    if (path === "/login" || path === "/setup") return path;
    const next = path && path !== "/" ? `?next=${encodeURIComponent(path)}` : "";
    return `/login${next}`;
  }
  if (path === "/setup" || path === "/login") return "/";
  return path;
}

export function runKeyFor(run: Run): string {
  return run.started_at ?? "idle";
}

export function valuesFromConfig(config: AppConfig): ConfigValues {
  // slotText maps masked secret objects to "": sonarr_api_key is write-only in
  // the UI (masked last-4 shown separately) and must never round-trip into PUT.
  const value = (key: keyof ConfigValues) => slotText(config.fields[key]?.file);
  return {
    library: value("library"),
    old_dir: value("old_dir"),
    staging: value("staging"),
    bench_dest: value("bench_dest"),
    shows_dir: value("shows_dir"),
    sonarr_url: value("sonarr_url"),
    sonarr_api_key: value("sonarr_api_key"),
  };
}

export function omitLockedConfig(
  values: ConfigValues,
  config: AppConfig | null,
): Partial<ConfigValues> {
  if (!config) return { ...values };
  const next: Partial<ConfigValues> = {};
  for (const key of Object.keys(values) as (keyof ConfigValues)[]) {
    if (config.fields[key]?.source === "env") continue;
    next[key] = values[key];
  }
  return next;
}

export type PlatformPayload = { library: string; old_dir: string; cookies: string };

export function omitLockedPlatform(
  values: PlatformPayload,
  paths: ManifestPaths | null | undefined,
): Partial<PlatformPayload> {
  // Mirror of omitLockedConfig: never send manifest values the environment
  // shadows (server drops absent keys, which is neutral while env is set).
  const next: Partial<PlatformPayload> = { cookies: values.cookies };
  if (paths?.library?.source !== "env") next.library = values.library;
  if (paths?.old_dir?.source !== "env") next.old_dir = values.old_dir;
  return next;
}

export function pathNotices(paths: Manifest["paths"]): string[] {
  if (!paths) return [];
  const notices: string[] = [];
  for (const key of ["library", "old_dir", "staging"] as const) {
    const item = paths[key];
    if (!item) continue;
    if (item.source === "env") {
      notices.push(`${key} overridden by ${item.env_name ?? "environment"} (${item.effective})`);
    } else if (item.source === "fallback") {
      notices.push(`${key} using fallback from config.toml (${item.effective})`);
    } else if (item.source === "unset" && key !== "staging") {
      notices.push(`${key} is not set in this file, config.toml [fallback], or environment`);
    }
  }
  return notices;
}

export const apiClient = {
  session: () => api<Session>("/api/session"),
  setup: (password: string) =>
    api<{ ok: boolean }>("/api/setup", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  login: (password: string) =>
    api<{ ok: boolean }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => api<{ ok: boolean }>("/api/logout", { method: "POST" }),
  changePassword: (current: string, next: string) =>
    api<{ ok: boolean }>("/api/password", {
      method: "POST",
      body: JSON.stringify({ current, password: next }),
    }),
  getManifest: (kind: Source) => api<Manifest>(`/api/manifests/${kind}`),
  putManifest: (kind: Source, text: string) =>
    api<Manifest>(`/api/manifests/${kind}`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),
  putDropoutImport: (path: string, text: string) =>
    api<ManifestImport>("/api/manifests/dropout/imports", {
      method: "PUT",
      body: JSON.stringify({ path, text }),
    }),
  putImport: (kind: Source, path: string, text: string) =>
    api<ManifestImport>(`/api/manifests/${kind}/imports`, {
      method: "PUT",
      body: JSON.stringify({ path, text }),
    }),
  validateManifest: (kind: Source, text: string) =>
    api<ManifestValidate>(`/api/manifests/${kind}/validate`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  getConfig: (reveal = false) => api<AppConfig>(reveal ? "/api/config?reveal=1" : "/api/config"),
  putConfig: (values: Partial<ConfigValues>) =>
    api<AppConfig>("/api/config", {
      method: "PUT",
      body: JSON.stringify(values),
    }),
  getCookies: () => api<CookieStatus>("/api/cookies"),
  putCookies: (kind: CookieKind, text: string) =>
    api<CookieStatus>(`/api/cookies/${kind}`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),
  getRun: () => api<Run>("/api/runs", undefined, (data) => parseWith(runSchema, data, "Run")),
  getPlan: () =>
    api<PlanFile>("/api/runs/plan", undefined, (data) => parseWith(planFileSchema, data, "Plan")),
  startPlan: (force = false, create = false) =>
    api<Run>(
      "/api/runs/plan",
      {
        method: "POST",
        body: JSON.stringify({ force, create }),
      },
      (data) => parseWith(runSchema, data, "Run"),
    ),
  startDownload: (options: DownloadOptions) =>
    api<Run>(
      "/api/runs",
      {
        method: "POST",
        body: JSON.stringify({
          ids: options.ids,
          force: options.force ?? false,
          create: options.create ?? false,
        }),
      },
      (data) => parseWith(runSchema, data, "Run"),
    ),
  stopRun: () =>
    api<Run>("/api/runs/stop", { method: "POST" }, (data) => parseWith(runSchema, data, "Run")),
  getPlatform: (kind: Source) => api<PlatformSettings>(`/api/platform/${kind}`),
  putPlatform: (
    kind: Source,
    body: Partial<{ library: string; old_dir: string; cookies: string }>,
  ) =>
    api<PlatformSettings>(`/api/platform/${kind}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listSeries: () =>
    api<{
      series: import("./seriesView").SeriesSummary[];
      import_errors: { file: string; error: string }[];
    }>("/api/series"),
  createSeries: (body: {
    name: string;
    platform: Source;
    path: string;
    tvdb_id: number | null;
  }) =>
    api<SeriesDetail>("/api/series", { method: "POST", body: JSON.stringify(body) }, (data) =>
      parseWith(seriesDetailSchema, data, "Series"),
    ),
  getSeries: (platform: Source, slug: string) =>
    api<SeriesDetail>(seriesUrl(platform, slug), undefined, (data) =>
      parseWith(seriesDetailSchema, data, "Series"),
    ),
  getSeriesYaml: (platform: Source, slug: string) =>
    api<{ text: string; file: string }>(seriesUrl(platform, slug, "/yaml")),
  putSeriesYaml: (platform: Source, slug: string, text: string) =>
    api<SeriesDetail>(
      seriesUrl(platform, slug, "/yaml"),
      { method: "PUT", body: JSON.stringify({ text }) },
      (data) => parseWith(seriesDetailSchema, data, "Series"),
    ),
  getSeriesDisk: (platform: Source, slug: string) =>
    api<{ on_disk: { season: number; episode: number }[] }>(seriesUrl(platform, slug, "/disk")),
  getSeriesMissing: (platform: Source, slug: string) =>
    api<MissingRow>(seriesUrl(platform, slug, "/missing")),
  getSeriesMissingBatch: async (items: { platform: Source; slug: string }[]) => {
    if (!items.length) return {} as Record<string, MissingRow>;
    try {
      const body = await api<{
        missing?: Record<string, MissingRow>;
        results?: {
          platform: string;
          slug: string;
          missing_count: number | null;
          complete: boolean;
        }[];
      }>("/api/series/missing", {
        method: "POST",
        body: JSON.stringify({ items }),
      });
      if (body.missing) return body.missing;
      const map: Record<string, MissingRow> = {};
      for (const row of body.results ?? []) {
        map[`${row.platform}|${row.slug}`] = {
          missing_count: row.missing_count,
          complete: row.complete,
        };
      }
      if (Object.keys(map).length) return map;
    } catch (err) {
      if (!(err instanceof ApiError) || (err.status !== 404 && err.status !== 405)) {
        throw err;
      }
    }
    const entries = await Promise.all(
      items.map(async (item) => {
        const row = await apiClient.getSeriesMissing(item.platform, item.slug);
        return [`${item.platform}|${item.slug}`, row] as const;
      }),
    );
    return Object.fromEntries(entries);
  },
  getDropoutCheck: (slug: string) =>
    api<DropoutCheck>(`/api/series/dropout/${encodeURIComponent(slug)}/check`),
  getDropoutLayout: (slug: string) =>
    api<DropoutLayout>(`/api/series/dropout/${encodeURIComponent(slug)}/layout`),
  putSeries: (platform: Source, slug: string, body: SeriesDetail) =>
    api<SeriesDetail>(
      seriesUrl(platform, slug),
      {
        method: "PUT",
        body: JSON.stringify({
          name: body.name,
          path: body.path,
          tvdb_id: body.tvdb_id,
          tvdb_skip: body.tvdb_skip,
          sources: body.sources,
        }),
      },
      (data) => parseWith(seriesDetailSchema, data, "Series"),
    ),
  deleteSeries: (platform: Source, slug: string) =>
    api<void>(seriesUrl(platform, slug), { method: "DELETE" }),
  addSeriesSource: (platform: Source, slug: string, url: string) =>
    api<SeriesDetail>(
      seriesUrl(platform, slug, "/sources"),
      { method: "POST", body: JSON.stringify({ url }) },
      (data) => parseWith(seriesDetailSchema, data, "Series"),
    ),
  deleteSeriesSource: (platform: Source, slug: string, sourceIndex: number) =>
    api<SeriesDetail>(
      seriesUrl(platform, slug, `/sources/${sourceIndex}`),
      { method: "DELETE" },
      (data) => parseWith(seriesDetailSchema, data, "Series"),
    ),
  refreshSeriesSource: (platform: Source, slug: string, sourceIndex: number) =>
    api<SeriesDetail>(
      seriesUrl(platform, slug, `/sources/${sourceIndex}/refresh`),
      { method: "POST" },
      (data) => parseWith(seriesDetailSchema, data, "Series"),
    ),
  refreshSeries: (items: { platform: Source; slug: string }[], parts?: string[]) =>
    api<{
      ok: boolean;
      results: { platform: string; slug: string; error: string | null }[];
    }>("/api/series/refresh", {
      method: "POST",
      body: JSON.stringify({ items, parts }),
    }),
  getSeriesEpisodes: (platform: Source, slug: string, sourceIndex: number, seasonId: number) =>
    api<{
      episodes: SeriesEpisode[];
      on_disk?: { season: number; episode: number }[];
    }>(seriesUrl(platform, slug, `/sources/${sourceIndex}/seasons/${seasonId}/episodes`)),
  getSonarrEpisodes: (tvdbId: number) =>
    api<{ title: string; title_slug: string | null; episodes: SonarrEpisode[] }>(
      `/api/sonarr/episodes?tvdb_id=${tvdbId}`,
    ),
  suggestSonarr: (tvdbId: number, title: string) =>
    api<{ suggestions: SonarrEpisode[] }>("/api/sonarr/suggest", {
      method: "POST",
      body: JSON.stringify({ tvdb_id: tvdbId, title }),
    }),
  pingSonarr: (values: { sonarr_url: string; sonarr_api_key: string }) =>
    api<SonarrPing>("/api/sonarr/ping", {
      method: "POST",
      body: JSON.stringify(values),
    }),
};
