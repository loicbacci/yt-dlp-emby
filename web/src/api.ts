export type Source = "youtube" | "dropout";
export type RunStatus = "idle" | "running" | "stopping" | "exited";
export type Session = { setup_required: boolean; authenticated: boolean };
export type Manifest = { kind: Source; text: string; exists: boolean };
export type Run = {
  status: RunStatus;
  source: Source | null;
  dry_run: boolean;
  verbose: boolean;
  force: boolean;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
};

export type StartOptions = {
  source: Source;
  dry_run: boolean;
  verbose: boolean;
  force: boolean;
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

export function startPayload(options: StartOptions): StartOptions {
  if (options.source === "youtube") {
    return { ...options, force: false };
  }
  return options;
}

export function routeForSession(session: Session): "/" | "/setup" | "/login" {
  if (session.setup_required) return "/setup";
  if (!session.authenticated) return "/login";
  return "/";
}

export function confirmDirtySwitch(): boolean {
  return window.confirm("Discard unsaved yaml changes?");
}

export function confirmDirtyStart(): boolean {
  return window.confirm(
    "Start uses the last saved file, not the editor. Continue?",
  );
}

export function runKeyFor(run: Run): string {
  return run.started_at ?? "idle";
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
  validateManifest: (kind: Source, text: string) =>
    api<{ ok: boolean }>(`/api/manifests/${kind}/validate`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  getRun: () => api<Run>("/api/runs"),
  startRun: (options: StartOptions) =>
    api<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify(startPayload(options)),
    }),
  stopRun: () => api<Run>("/api/runs/stop", { method: "POST" }),
};
