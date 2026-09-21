import { describe, expect, it } from "vitest";
import { posterLetter, posterShowsImage } from "./Poster";

describe("posterShowsImage", () => {
  it("hides a failed src and retries when the cache-bust changes", () => {
    expect(posterShowsImage("/api/series/dropout/x/poster", null)).toBe(true);
    expect(posterShowsImage("/api/series/dropout/x/poster", "/api/series/dropout/x/poster")).toBe(
      false,
    );
    expect(
      posterShowsImage(
        "/api/series/dropout/x/poster?t=2026-09-20T12:00:00Z",
        "/api/series/dropout/x/poster",
      ),
    ).toBe(true);
    expect(posterShowsImage(null, "/old")).toBe(false);
  });
});

describe("posterLetter", () => {
  it("uses the first letter", () => {
    expect(posterLetter("Game Changer")).toBe("G");
    expect(posterLetter("  ")).toBe("?");
  });
});
