import { describe, expect, it } from "vitest";
import { routeForSession, runKeyFor, startPayload } from "./api";

describe("startPayload", () => {
  it("omits force for youtube", () => {
    const payload = startPayload({
      source: "youtube",
      dry_run: true,
      verbose: false,
      force: true,
    });
    expect(payload.force).toBe(false);
  });

  it("keeps force for dropout", () => {
    const payload = startPayload({
      source: "dropout",
      dry_run: false,
      verbose: true,
      force: true,
    });
    expect(payload.force).toBe(true);
  });
});

describe("routeForSession", () => {
  it("routes to setup when required", () => {
    expect(
      routeForSession({ setup_required: true, authenticated: false }),
    ).toBe("/setup");
  });

  it("routes to login when not authenticated", () => {
    expect(
      routeForSession({ setup_required: false, authenticated: false }),
    ).toBe("/login");
  });

  it("routes to dashboard when authenticated", () => {
    expect(
      routeForSession({ setup_required: false, authenticated: true }),
    ).toBe("/");
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
