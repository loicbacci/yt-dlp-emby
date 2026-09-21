import { describe, expect, it } from "vitest";
import { parseSeriesPath } from "./seriesView";
import { sourceIndexKey, tvdbSkipKey } from "./types";

describe("source identity", () => {
  it("keys sources by numeric index", () => {
    expect(sourceIndexKey(0)).toBe("0");
    expect(sourceIndexKey(2)).toBe("2");
  });

  it("stays stable when a source is recreated at the same index", () => {
    const before = [{ id: "old" }, { id: "keep" }].map((_, index) => sourceIndexKey(index));
    const after = [{ id: "new" }, { id: "keep" }].map((_, index) => sourceIndexKey(index));
    expect(before).toEqual(after);
  });
});

describe("tvdbSkipKey", () => {
  it("is stable regardless of episode order", () => {
    expect(tvdbSkipKey([{ season: 1, episodes: [3, 1] }])).toBe("1:1,3");
  });
});

describe("parseSeriesPath encoding", () => {
  it("decodes slugs", () => {
    expect(parseSeriesPath("/series/youtube/my%2Fshow")).toEqual({
      platform: "youtube",
      slug: "my/show",
    });
  });
});
