import { describe, expect, it } from "vitest";
import {
  applyCheck,
  buildTree,
  downloadLabel,
  effectiveDownloadIds,
  formatItemSize,
  itemId,
  platformLabel,
  needsConfirm,
  partitionSeasons,
  pendingIds,
  groupByDestSeason,
  sourcesFor,
  triState,
  upToDateSeries,
  visibleSeries,
} from "./runQueue";

const d20Plan = {
  generated_at: "2026-01-01T00:00:00+00:00",
  force: false,
  sources: {
    dropout: {
      ok: true,
      error: null,
      seasons: [
        {
          platform: "dropout" as const,
          slug: "dimension-20",
          series: "Dimension 20",
          dest_season: 21,
          season_title: "Fantasy High Junior Year",
          folder: "Season 21",
          download: 3,
          skip: 17,
          unmapped: 0,
          replace: 0,
        },
        {
          platform: "dropout" as const,
          slug: "dimension-20",
          series: "Dimension 20",
          dest_season: 1,
          season_title: null,
          folder: "Season 1",
          download: 0,
          skip: 12,
          unmapped: 0,
          replace: 0,
        },
      ],
      items: [
        {
          id: "dropout|dimension-20|S21E01",
          action: "download",
          code: "S21E01",
          title: "Ep 1",
          dest_season: 21,
          season_title: "Fantasy High Junior Year",
          folder: "Season 21",
          size: 100,
          series: "Dimension 20",
          slug: "dimension-20",
          platform: "dropout" as const,
        },
        {
          id: "dropout|dimension-20|S21E02",
          action: "download",
          code: "S21E02",
          title: "Ep 2",
          dest_season: 21,
          season_title: "Fantasy High Junior Year",
          folder: "Season 21",
          size: 100,
          series: "Dimension 20",
          slug: "dimension-20",
          platform: "dropout" as const,
        },
        {
          id: "dropout|dimension-20|S21E03",
          action: "download",
          code: "S21E03",
          title: "Ep 3",
          dest_season: 21,
          season_title: "Fantasy High Junior Year",
          folder: "Season 21",
          size: 100,
          series: "Dimension 20",
          slug: "dimension-20",
          platform: "dropout" as const,
        },
      ],
    },
    youtube: {
      ok: true,
      error: null,
      seasons: [
        {
          platform: "youtube" as const,
          slug: "professor-messer",
          series: "Professor Messer",
          dest_season: 2,
          season_title: null,
          folder: "Season 2",
          download: 4,
          skip: 0,
          unmapped: 0,
          replace: 0,
        },
      ],
      items: Array.from({ length: 4 }, (_, i) => ({
        id: `youtube|professor-messer|S02E0${i + 1}`,
        action: "download",
        code: `S02E0${i + 1}`,
        title: `Video ${i + 1}`,
        dest_season: 2,
        season_title: null,
        folder: "Season 2",
        size: null,
        series: "Professor Messer",
        slug: "professor-messer",
        platform: "youtube" as const,
      })),
    },
  },
};

describe("itemId", () => {
  it("is stable", () => {
    expect(itemId("dropout", "dimension-20", "S21E04")).toBe(
      "dropout|dimension-20|S21E04",
    );
  });
});

describe("partitionSeasons", () => {
  it("splits complete vs pending", () => {
    const { pending, complete } = partitionSeasons(d20Plan.sources.dropout.seasons);
    expect(pending).toHaveLength(1);
    expect(complete).toHaveLength(1);
    expect(pending[0].dest_season).toBe(21);
  });
});

describe("buildTree", () => {
  it("hides complete seasons from series pending list", () => {
    const tree = buildTree(d20Plan);
    const d20 = tree.find((s) => s.slug === "dimension-20");
    expect(d20?.seasons).toHaveLength(1);
    expect(d20?.seasons[0].seasonTitle).toBe("Fantasy High Junior Year");
    expect(d20?.pendingCount).toBe(3);
  });
});

describe("visibleSeries", () => {
  it("drops zero-pending series without search", () => {
    const tree = buildTree({
      ...d20Plan,
      sources: {
        ...d20Plan.sources,
        dropout: {
          ...d20Plan.sources.dropout,
          seasons: [
            ...d20Plan.sources.dropout.seasons,
            {
              platform: "dropout",
              slug: "game-changer",
              series: "Game Changer",
              dest_season: 1,
              season_title: null,
              folder: "Season 1",
              download: 0,
              skip: 5,
              unmapped: 0,
              replace: 0,
            },
          ],
        },
      },
    });
    const visible = visibleSeries(tree, "");
    expect(visible.some((s) => s.slug === "game-changer")).toBe(false);
    expect(visible.some((s) => s.slug === "dimension-20")).toBe(true);
  });

  it("search reveals completed series", () => {
    const tree = buildTree(d20Plan);
    const hit = visibleSeries(tree, "Junior Year");
    expect(hit.some((s) => s.slug === "dimension-20")).toBe(true);
  });
});

describe("upToDateSeries", () => {
  it("lists fully complete series", () => {
    const plan = {
      ...d20Plan,
      sources: {
        dropout: {
          ok: true,
          error: null,
          seasons: [
            {
              platform: "dropout" as const,
              slug: "game-changer",
              series: "Game Changer",
              dest_season: 1,
              season_title: null,
              folder: "Season 1",
              download: 0,
              skip: 5,
              unmapped: 0,
              replace: 0,
            },
          ],
          items: [],
        },
        youtube: d20Plan.sources.youtube,
      },
    };
    const tree = buildTree(plan);
    const up = upToDateSeries(tree, "");
    expect(up.some((s) => s.slug === "game-changer")).toBe(true);
  });
});

describe("selection helpers", () => {
  const tree = buildTree(d20Plan);
  const all = pendingIds(tree);

  it("triState", () => {
    expect(triState(new Set(), all)).toBe("none");
    expect(triState(new Set(all), all)).toBe("all");
    expect(triState(new Set([all[0]]), all)).toBe("some");
  });

  it("applyCheck", () => {
    const next = applyCheck(new Set(), [all[0], all[1]], true);
    expect(next.size).toBe(2);
  });

  it("effectiveDownloadIds empty selection means all", () => {
    expect(effectiveDownloadIds(new Set(), all)).toEqual(all);
  });

  it("downloadLabel always has a number", () => {
    expect(downloadLabel(294)).toBe("Download 294");
  });

  it("needsConfirm at 25", () => {
    expect(needsConfirm(24)).toBe(false);
    expect(needsConfirm(25)).toBe(true);
  });

  it("sourcesFor", () => {
    expect(sourcesFor([], tree)).toEqual(["dropout", "youtube"]);
    expect(sourcesFor([all[0]], tree)).toEqual(["dropout"]);
  });
});

describe("unmapped-only series", () => {
  it("stays visible in the main tree", () => {
    const plan = {
      generated_at: null,
      force: false,
      sources: {
        dropout: {
          ok: true,
          error: null,
          seasons: [],
          items: [
            {
              id: "dropout|orphan|S00E01",
              action: "unmapped",
              code: "S00E01",
              title: "Lost ep",
              dest_season: 0,
              season_title: null,
              folder: "Specials",
              size: null,
              series: "Orphan Show",
              slug: "orphan",
              platform: "dropout" as const,
            },
          ],
        },
      },
    };
    const tree = buildTree(plan);
    expect(visibleSeries(tree, "")).toHaveLength(1);
    expect(tree[0].unmapped).toHaveLength(1);
  });
});

describe("formatItemSize", () => {
  it("formats bytes", () => {
    expect(formatItemSize(null)).toBeNull();
    expect(formatItemSize(512)).toBe("512 B");
    expect(formatItemSize(12_000_000)).toBe("11 MB");
  });
});

describe("platformLabel", () => {
  it("humanizes slugs", () => {
    expect(platformLabel("dropout")).toBe("Dropout");
    expect(platformLabel("youtube")).toBe("YouTube");
  });
});

describe("groupByDestSeason", () => {
  it("orders specials last", () => {
    const grouped = groupByDestSeason([
      { dest_season: 0, code: "S00E01" },
      { dest_season: 2, code: "S02E01" },
      { dest_season: 1, code: "S01E01" },
    ]);
    expect(grouped.map((g) => g.dest_season)).toEqual([1, 2, 0]);
  });
});
