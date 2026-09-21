import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UnauthorizedError,
  apiClient,
  messageFromErrorBody,
  omitLockedConfig,
  omitLockedPlatform,
  pathNotices,
  routeForSession,
  runKeyFor,
  slotDisplay,
  slotIsSet,
  slotText,
  valuesFromConfig,
} from "./api";
import type { AppConfig } from "./api";

describe("routeForSession", () => {
  it("routes to setup when required", () => {
    expect(routeForSession({ setup_required: true, authenticated: false }, "/")).toBe("/setup");
  });

  it("routes to login when not authenticated", () => {
    expect(routeForSession({ setup_required: false, authenticated: false }, "/settings")).toBe(
      "/login?next=%2Fsettings",
    );
  });

  it("keeps the dashboard when authenticated", () => {
    expect(routeForSession({ setup_required: false, authenticated: true }, "/")).toBe("/");
  });

  it("keeps settings when authenticated", () => {
    expect(routeForSession({ setup_required: false, authenticated: true }, "/settings")).toBe(
      "/settings",
    );
  });

  it("keeps series routes when authenticated", () => {
    expect(
      routeForSession(
        { setup_required: false, authenticated: true },
        "/series/dropout/game-changer",
      ),
    ).toBe("/series/dropout/game-changer");
  });

  it("sends authenticated users away from login", () => {
    expect(routeForSession({ setup_required: false, authenticated: true }, "/login")).toBe("/");
  });
});

describe("pathNotices", () => {
  it("explains fallback and unset library", () => {
    const notices = pathNotices({
      library: {
        manifest: null,
        effective: "/from/file",
        source: "fallback",
        env_name: null,
      },
      old_dir: {
        manifest: null,
        effective: null,
        source: "unset",
        env_name: null,
      },
      staging: {
        manifest: null,
        effective: null,
        source: "unset",
        env_name: null,
      },
    });
    expect(notices.some((item) => item.includes("fallback from config.toml"))).toBe(true);
    expect(notices.some((item) => item.includes("old_dir is not set"))).toBe(true);
    expect(notices.some((item) => item.includes("staging is not set"))).toBe(false);
  });
});

describe("runKeyFor", () => {
  it("uses started_at so a new run resets the log viewer", () => {
    expect(
      runKeyFor({
        status: "running",
        phase: "downloading",
        source: "youtube",
        dry_run: false,
        verbose: false,
        force: false,
        started_at: "2026-01-01T00:00:00+00:00",
        finished_at: null,
        exit_code: null,
        plan: null,
      }),
    ).toBe("2026-01-01T00:00:00+00:00");
  });

  it("uses idle when never started", () => {
    expect(
      runKeyFor({
        status: "idle",
        phase: "idle",
        source: null,
        dry_run: false,
        verbose: false,
        force: false,
        started_at: null,
        finished_at: null,
        exit_code: null,
        plan: null,
      }),
    ).toBe("idle");
  });
});

describe("messageFromErrorBody", () => {
  it("reads both envelopes", () => {
    expect(messageFromErrorBody({ error: "plain" }, "x")).toBe("plain");
    expect(messageFromErrorBody({ detail: { error: "nested" } }, "x")).toBe("nested");
  });
});

describe("masked config slots", () => {
  const strField = (file: string | null) => ({
    file,
    effective: file,
    source: "file" as const,
    env_name: null,
    section: "root" as const,
  });
  const maskedConfig = {
    path: "config.toml",
    exists: true,
    fields: {
      library: strField("/lib"),
      old_dir: strField("/old"),
      staging: strField(null),
      bench_dest: strField(null),
      shows_dir: strField("shows"),
      sonarr_url: strField("http://localhost:8989"),
      sonarr_api_key: {
        file: { set: true, masked: "****1234" },
        effective: { set: true, masked: "****1234" },
        source: "file",
        env_name: "YT_DLP_EMBY_SONARR_API_KEY",
        section: "root",
      },
    },
  } as unknown as AppConfig;

  it("keeps masked secrets out of editable drafts", () => {
    const values = valuesFromConfig(maskedConfig);
    expect(values.sonarr_api_key).toBe("");
    expect(values.sonarr_url).toBe("http://localhost:8989");
  });

  it("reads set-state and last-4 without throwing", () => {
    const file = maskedConfig.fields.sonarr_api_key.file;
    expect(slotIsSet(file)).toBe(true);
    expect(slotText(file)).toBe("");
    expect(slotDisplay(file)).toBe("****1234");
    expect(slotIsSet({ set: false, masked: null })).toBe(false);
    expect(slotDisplay({ set: false, masked: null })).toBe("");
  });

  it("omits env-locked platform keys like omitLockedConfig", () => {
    const draft = { library: "/m", old_dir: "/o", cookies: "c.txt" };
    const paths = {
      library: { manifest: "/m", effective: "/env", source: "env", env_name: "X" },
      old_dir: { manifest: "/o", effective: "/o", source: "manifest", env_name: null },
      staging: { manifest: null, effective: null, source: "unset", env_name: null },
    } as never;
    expect(omitLockedPlatform(draft, paths)).toEqual({ old_dir: "/o", cookies: "c.txt" });
    expect(omitLockedConfig({ ...valuesFromConfig(maskedConfig) }, maskedConfig)).toEqual(
      valuesFromConfig(maskedConfig),
    );
  });
});

describe("apiClient errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws UnauthorizedError on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: "nope" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    await expect(apiClient.session()).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("reads detail.error from 400", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: { error: "bad yaml" } }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    await expect(apiClient.getConfig()).rejects.toMatchObject({
      status: 400,
      message: "bad yaml",
    });
  });

  it("propagates TypeError when offline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(apiClient.session()).rejects.toBeInstanceOf(TypeError);
    await expect(apiClient.getConfig()).rejects.toMatchObject({
      name: "TypeError",
    });
  });
});
