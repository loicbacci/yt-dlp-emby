import { describe, expect, it } from "vitest";
import { formatRelativeTime, newestRefreshIso } from "./relativeTime";

describe("formatRelativeTime", () => {
  const now = Date.parse("2026-09-20T12:00:00Z");

  it("returns null for empty values", () => {
    expect(formatRelativeTime(null, now)).toBeNull();
    expect(formatRelativeTime("not-a-date", now)).toBeNull();
  });

  it("formats recent stamps", () => {
    expect(formatRelativeTime("2026-09-20T11:59:40Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-09-20T11:10:00Z", now)).toMatch(/50.*ago/);
    expect(formatRelativeTime("2026-09-20T09:00:00Z", now)).toMatch(/3.*ago/);
    expect(formatRelativeTime("2026-09-18T12:00:00Z", now)).toMatch(/2.*ago/);
  });
});

describe("newestRefreshIso", () => {
  it("picks the latest stamp among visible rows", () => {
    expect(
      newestRefreshIso([
        {
          refreshed: {
            listings: "2026-09-20T10:00:00Z",
            disk: "2026-09-20T11:00:00Z",
            sonarr: null,
          },
        },
        {
          refreshed: {
            listings: "2026-09-19T12:00:00Z",
            disk: null,
            sonarr: "2026-09-20T12:00:00Z",
          },
        },
      ]),
    ).toBe("2026-09-20T12:00:00Z");
  });
});
