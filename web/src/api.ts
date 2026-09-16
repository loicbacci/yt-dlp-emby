import type { SeriesSummary } from "./seriesView";

export type Source = "youtube" | "dropout";
export type RunPhase = "idle" | "planning" | "downloading" | "stopping" | "exited";
export type RunStatus = "idle" | "running" | "stopping" | "exited";
export type Session = { setup_required: boolean; authenticated: boolean };
export type ManifestImport = { path: string; text: string; exists: boolean };
export type PathSource = "env" | "manifest" | "fallback" | "unset";
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
};
export type PlanSourceBlock = {
  ok: boolean;
  error: string | null;
  seasons: Record<string, unknown>[];
  items: Record<string, unknown>[];
};

export type PlanFile = {
  generated_at: string | null;
  force: boolean;
  sources: Record<string, PlanSourceBlock>;
};

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
};

export type DownloadOptions = {
  ids: string[] | null;
  force?: boolean;
};

export type DropoutCheck = {
  ok: boolean;
  missing: {
    season: number;
    episode: number;
    code: string;
    title: string;
    hints: { text: string; kind: string }[];
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
  file: string | null;
  effective: string | null;
  source: "env" | "file" | "unset";
  env_name: string | null;
  section: "fallback" | "root";
};
export type ConfigKey =
  | "library"
  | "old_dir"
  | "staging"
  | "bench_dest"
  | "shows_dir"
  | "sonarr_url"
  | "sonarr_api_key";
export type AppConfig = {
  path: string;
  exists: boolean;
  fields: Record<ConfigKey, ConfigField>;
};
export type ConfigValues = Record<ConfigKey, string>;
export type CookieKind = Source;
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
  to_season: number;
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
};

export type SonarrEpisode = {
  season: number;
  episode: number;
  title: string;
  air_date: string | null;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
    ...init,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail?.error ?? body.error ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function routeForSession(session: Session, path: string): string {
  if (session.setup_required) return "/setup";
  if (!session.authenticated) return "/login";
  if (path === "/setup" || path === "/login") return "/";
  return path;
}

export function confirmDirtySwitch(): boolean {
  return window.confirm("Discard unsaved yaml changes?");
}

export function confirmDirtyConfig(): boolean {
  return window.confirm("Discard unsaved config changes?");
}

export function confirmDirtyCookies(): boolean {
  return window.confirm("Discard unsaved cookie paste?");
}

export function runKeyFor(run: Run): string {
  return run.started_at ?? "idle";
}

export function valuesFromConfig(config: AppConfig): ConfigValues {
  const value = (key: ConfigKey) => config.fields[key]?.file ?? "";
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

export function pathNotices(paths: ManifestPaths | null | undefined): string[] {
  if (!paths) return [];
  const notices: string[] = [];
  for (const key of ["library", "old_dir", "staging"] as const) {
    const item = paths[key];
    if (!item) continue;
    if (item.source === "env") {
      notices.push(
        `${key} overridden by ${item.env_name ?? "environment"} (${item.effective})`,
      );
    } else if (item.source === "fallback") {
      notices.push(
        `${key} using fallback from config.toml (${item.effective})`,
      );
    } else if (item.source === "unset" && key !== "staging") {
      notices.push(
        `${key} is not set in this file, config.toml [fallback], or environment`,
      );
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
  getConfig: () => api<AppConfig>("/api/config"),
  putConfig: (values: ConfigValues) =>
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
  getRun: () => api<Run>("/api/runs"),
  getPlan: () => api<PlanFile>("/api/runs/plan"),
  startPlan: (force = false) =>
    api<Run>("/api/runs/plan", {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  startDownload: (options: DownloadOptions) =>
    api<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ ids: options.ids, force: options.force ?? false }),
    }),
  stopRun: () => api<Run>("/api/runs/stop", { method: "POST" }),
  getPlatform: (kind: Source) => api<PlatformSettings>(`/api/platform/${kind}`),
  putPlatform: (kind: Source, body: { library: string; old_dir: string; cookies: string }) =>
    api<PlatformSettings>(`/api/platform/${kind}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listSeries: () => api<{ series: SeriesSummary[] }>("/api/series"),
  createSeries: (body: {
    name: string;
    platform: Source;
    path: string;
    tvdb_id: number | null;
  }) => api<SeriesDetail>("/api/series", { method: "POST", body: JSON.stringify(body) }),
  getSeries: (platform: Source, slug: string) =>
    api<SeriesDetail>(`/api/series/${platform}/${slug}`),
  getDropoutCheck: (slug: string) =>
    api<DropoutCheck>(`/api/series/dropout/${slug}/check`),
  getDropoutLayout: (slug: string) =>
    api<DropoutLayout>(`/api/series/dropout/${slug}/layout`),
  putSeries: (platform: Source, slug: string, body: SeriesDetail) =>
    api<SeriesDetail>(`/api/series/${platform}/${slug}`, {
      method: "PUT",
      body: JSON.stringify({
        name: body.name,
        path: body.path,
        tvdb_id: body.tvdb_id,
        tvdb_skip: body.tvdb_skip,
        sources: body.sources,
      }),
    }),
  deleteSeries: (platform: Source, slug: string) =>
    api<void>(`/api/series/${platform}/${slug}`, { method: "DELETE" }),
  addSeriesSource: (platform: Source, slug: string, url: string) =>
    api<SeriesDetail>(`/api/series/${platform}/${slug}/sources`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  deleteSeriesSource: (platform: Source, slug: string, sourceId: number) =>
    api<SeriesDetail>(`/api/series/${platform}/${slug}/sources/${sourceId}`, {
      method: "DELETE",
    }),
  refreshSeriesSource: (platform: Source, slug: string, sourceId: number) =>
    api<SeriesDetail>(`/api/series/${platform}/${slug}/sources/${sourceId}/refresh`, {
      method: "POST",
    }),
  getSeriesEpisodes: (
    platform: Source,
    slug: string,
    sourceId: number,
    seasonId: number,
  ) =>
    api<{ episodes: SeriesEpisode[] }>(
      `/api/series/${platform}/${slug}/sources/${sourceId}/seasons/${seasonId}/episodes`,
    ),
  getSonarrEpisodes: (tvdbId: number) =>
    api<{ title: string; episodes: SonarrEpisode[] }>(
      `/api/sonarr/episodes?tvdb_id=${tvdbId}`,
    ),
  suggestSonarr: (tvdbId: number, title: string) =>
    api<{ suggestions: SonarrEpisode[] }>("/api/sonarr/suggest", {
      method: "POST",
      body: JSON.stringify({ tvdb_id: tvdbId, title }),
    }),
};
