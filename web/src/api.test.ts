import { describe, expect, it } from "vitest";
import { pathNotices, routeForSession, runKeyFor, startPayload } from "./api";

describe("startPayload", () => {
  it("forces action download for youtube", () => {
    const payload = startPayload({
      source: "youtube",
      dry_run: true,
      verbose: false,
      force: true,
      action: "layout",
    });
    expect(payload.force).toBe(false);
    expect(payload.action).toBe("download");
  });

  it("keeps force for dropout download", () => {
    const payload = startPayload({
      source: "dropout",
      dry_run: false,
      verbose: true,
      force: true,
      action: "download",
    });
    expect(payload.force).toBe(true);
    expect(payload.action).toBe("download");
  });

  it("clears force for layout and check", () => {
    for (const action of ["layout", "check"] as const) {
      const payload = startPayload({
        source: "dropout",
        dry_run: true,
        verbose: false,
        force: true,
        action,
      });
      expect(payload.force).toBe(false);
      expect(payload.action).toBe(action);
    }
  });
});

describe("routeForSession", () => {
  it("routes to setup when required", () => {
    expect(
      routeForSession({ setup_required: true, authenticated: false }, "/"),
    ).toBe("/setup");
  });

  it("routes to login when not authenticated", () => {
    expect(
      routeForSession({ setup_required: false, authenticated: false }, "/settings"),
    ).toBe("/login");
  });

  it("keeps the dashboard when authenticated", () => {
    expect(
      routeForSession({ setup_required: false, authenticated: true }, "/"),
    ).toBe("/");
  });

  it("keeps settings when authenticated", () => {
    expect(
      routeForSession(
        { setup_required: false, authenticated: true },
        "/settings",
      ),
    ).toBe("/settings");
  });

  it("sends authenticated users away from login", () => {
    expect(
      routeForSession({ setup_required: false, authenticated: true }, "/login"),
    ).toBe("/");
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
    expect(notices.some((item) => item.includes("fallback from config.toml"))).toBe(
      true,
    );
    expect(notices.some((item) => item.includes("old_dir is not set"))).toBe(true);
    expect(notices.some((item) => item.includes("staging is not set"))).toBe(
      false,
    );
  });
});

describe("runKeyFor", () => {
  it("uses started_at so a new run resets the log viewer", () => {
    expect(
      runKeyFor({
        status: "running",
        source: "youtube",
        dry_run: false,
        verbose: false,
        force: false,
        started_at: "2026-01-01T00:00:00+00:00",
        finished_at: null,
        exit_code: null,
      }),
    ).toBe("2026-01-01T00:00:00+00:00");
  });

  it("uses idle when never started", () => {
    expect(
      runKeyFor({
        status: "idle",
        source: null,
        dry_run: false,
        verbose: false,
        force: false,
        started_at: null,
        finished_at: null,
        exit_code: null,
      }),
    ).toBe("idle");
  });
});
