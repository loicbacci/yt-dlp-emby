import { describe, expect, it } from "vitest";
import {
  applyCheck,
  applyProgress,
  buildTree,
  downloadLabel,
  effectiveDownloadIds,
  emptyProgress,
  formatBinaryBytes,
  formatEta,
  formatItemSize,
  formatProgressStats,
  heroFrom,
  itemId,
  mergeProgress,
  overlayProgress,
  platformLabel,
  needsConfirm,
  partitionSeasons,
  pendingIds,
  remainingEpisodes,
  finishedEpisodes,
  groupByDestSeason,
  runStatsLine,
  seriesInActiveDownload,
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

  it("does not copy dropout seasons from a youtube plan block", () => {
    const tree = buildTree({
      ...d20Plan,
      sources: {
        dropout: d20Plan.sources.dropout,
        youtube: {
          ok: true,
          error: null,
          seasons: [
            ...d20Plan.sources.dropout.seasons,
            ...d20Plan.sources.youtube.seasons,
          ],
          items: [
            ...d20Plan.sources.dropout.items,
            ...d20Plan.sources.youtube.items,
          ],
        },
      },
    });
    const d20 = tree.filter((s) => s.slug === "dimension-20");
    expect(d20).toHaveLength(1);
    expect(d20[0].platform).toBe("dropout");
    expect(d20[0].seasons).toHaveLength(1);
    expect(d20[0].seasons[0].seasonTitle).toBe("Fantasy High Junior Year");
    const yt = tree.find((s) => s.slug === "professor-messer");
    expect(yt?.seasons).toHaveLength(1);
  });

  it("orders dest seasons like Sonarr (specials last)", () => {
    const tree = buildTree({
      generated_at: null,
      force: false,
      sources: {
        dropout: {
          ok: true,
          error: null,
          seasons: [
            {
              platform: "dropout",
              slug: "dimension-20",
              series: "Dimension 20",
              dest_season: 0,
              season_title: null,
              folder: "Specials",
              download: 2,
              skip: 0,
              unmapped: 0,
              replace: 0,
            },
            {
              platform: "dropout",
              slug: "dimension-20",
              series: "Dimension 20",
              dest_season: 12,
              season_title: "Shriek Week",
              folder: "Season 12",
              download: 1,
              skip: 0,
              unmapped: 0,
              replace: 0,
            },
            {
              platform: "dropout",
              slug: "dimension-20",
              series: "Dimension 20",
              dest_season: 11,
              season_title: "The Seven",
              folder: "Season 11",
              download: 2,
              skip: 0,
              unmapped: 0,
              replace: 0,
            },
          ],
          items: [
            {
              id: "dropout|dimension-20|S00E02",
              action: "download",
              code: "S00E02",
              title: "Special 2",
              dest_season: 0,
              season_title: null,
              folder: "Specials",
              size: null,
              series: "Dimension 20",
              slug: "dimension-20",
              platform: "dropout",
            },
            {
              id: "dropout|dimension-20|S11E02",
              action: "download",
              code: "S11E02",
              title: "Seven 2",
              dest_season: 11,
              season_title: "The Seven",
              folder: "Season 11",
              size: null,
              series: "Dimension 20",
              slug: "dimension-20",
              platform: "dropout",
            },
            {
              id: "dropout|dimension-20|S12E01",
              action: "download",
              code: "S12E01",
              title: "Shriek 1",
              dest_season: 12,
              season_title: "Shriek Week",
              folder: "Season 12",
              size: null,
              series: "Dimension 20",
              slug: "dimension-20",
              platform: "dropout",
            },
            {
              id: "dropout|dimension-20|S11E01",
              action: "download",
              code: "S11E01",
              title: "Seven 1",
              dest_season: 11,
              season_title: "The Seven",
              folder: "Season 11",
              size: null,
              series: "Dimension 20",
              slug: "dimension-20",
              platform: "dropout",
            },
            {
              id: "dropout|dimension-20|S00E01",
              action: "download",
              code: "S00E01",
              title: "Special 1",
              dest_season: 0,
              season_title: null,
              folder: "Specials",
              size: null,
              series: "Dimension 20",
              slug: "dimension-20",
              platform: "dropout",
            },
          ],
        },
      },
    });
    const d20 = tree.find((s) => s.slug === "dimension-20");
    expect(d20?.seasons.map((s) => s.destSeason)).toEqual([11, 12, 0]);
    expect(d20?.seasons[0].pending.map((e) => e.code)).toEqual(["S11E01", "S11E02"]);
    expect(pendingIds(tree)).toEqual([
      "dropout|dimension-20|S11E01",
      "dropout|dimension-20|S11E02",
      "dropout|dimension-20|S12E01",
      "dropout|dimension-20|S00E01",
      "dropout|dimension-20|S00E02",
    ]);
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
    expect(downloadLabel(294)).toBe("Download 294 episodes");
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

describe("remainingEpisodes", () => {
  it("hides finished rows during a download", () => {
    const tree = buildTree(d20Plan);
    const season = tree.find((s) => s.slug === "dimension-20")!.seasons[0];
    const overlay = overlayProgress(tree, {
      ...emptyProgress(),
      currentId: season.pending[1].id,
      percent: 40,
      phase: "video",
      doneIds: new Set([season.pending[0].id]),
    });
    const live = overlay.find((s) => s.slug === "dimension-20")!.seasons[0];
    expect(remainingEpisodes(live, true).map((e) => e.code)).toEqual([
      "S21E02",
      "S21E03",
    ]);
    expect(finishedEpisodes(live).map((e) => e.code)).toEqual(["S21E01"]);
  });
});

describe("seriesInActiveDownload", () => {
  it("hides series that are not in the current download set", () => {
    const tree = buildTree(d20Plan);
    const d20 = tree.find((s) => s.slug === "dimension-20")!;
    const youtube = tree.find((s) => s.platform === "youtube");
    const ids = new Set(d20.seasons.flatMap((season) => season.pending.map((ep) => ep.id)));
    expect(seriesInActiveDownload(d20, ids)).toBe(true);
    if (youtube) expect(seriesInActiveDownload(youtube, ids)).toBe(false);
  });

  it("hides a series after its selected episodes finish", () => {
    const tree = buildTree(d20Plan);
    const overlay = overlayProgress(tree, {
      ...emptyProgress(),
      doneIds: new Set(pendingIds(tree).filter((id) => id.includes("dimension-20"))),
    });
    const d20 = overlay.find((s) => s.slug === "dimension-20")!;
    const ids = new Set(pendingIds(tree).filter((id) => id.includes("dimension-20")));
    expect(seriesInActiveDownload(d20, ids)).toBe(false);
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

describe("applyProgress", () => {
  it("parses ANSI percent strings from yt-dlp", () => {
    const { progress } = applyProgress([], {
      event: "progress",
      id: "dropout|dimension-20|S21E01",
      percent: "\u001b[0;94m 12.5%\u001b[0m",
      phase: "video",
    });
    expect(progress.percent).toBe(12.5);
    expect(progress.currentId).toBe("dropout|dimension-20|S21E01");
  });

  it("keeps speed and eta from the event", () => {
    const { progress } = applyProgress([], {
      event: "progress",
      id: "dropout|x|S01E01",
      percent: 20,
      phase: "video",
      speed: 51009899.8,
      eta: 60.1,
      bytes: 769206961,
      total: 3671230871,
    });
    expect(progress.speed).toBeCloseTo(51009899.8);
    expect(progress.eta).toBeCloseTo(60.1);
    expect(progress.bytes).toBe(769206961);
    expect(progress.total).toBe(3671230871);
  });

  it("uses bytes when percent is missing", () => {
    const { progress } = applyProgress([], {
      event: "progress",
      id: "dropout|x|S01E01",
      bytes: 25,
      total: 100,
    });
    expect(progress.percent).toBe(25);
  });
});

describe("overlayProgress", () => {
  it("marks the current and finished episodes", () => {
    const tree = buildTree(d20Plan);
    const overlay = overlayProgress(tree, {
      ...emptyProgress(),
      currentId: "dropout|dimension-20|S21E02",
      percent: 40,
      phase: "video",
      doneIds: new Set(["dropout|dimension-20|S21E01"]),
    });
    const eps = overlay[0].seasons[0].pending;
    expect(eps.find((e) => e.id.endsWith("E01"))?.status).toBe("done");
    expect(eps.find((e) => e.id.endsWith("E02"))?.status).toBe("downloading");
  });
});

describe("heroFrom", () => {
  it("shows the current episode while downloading", () => {
    const tree = buildTree(d20Plan);
    const hero = heroFrom(
      { phase: "downloading", source: "dropout" },
      tree,
      {
        ...emptyProgress(),
        currentId: "dropout|dimension-20|S21E01",
        percent: 12.5,
        phase: "video",
      },
      null,
      3,
    );
    expect(hero.heading).toContain("Dimension 20");
    expect(hero.sub).toContain("S21E01");
    expect(hero.sub).not.toContain("%");
  });
});

describe("formatProgressStats", () => {
  it("matches the terminal download line fields", () => {
    expect(formatBinaryBytes(48.7 * 1024 * 1024)).toBe("48.7MiB");
    expect(formatEta(61)).toBe("01:01");
    expect(formatEta(null)).toBe("--:--");
    expect(
      formatProgressStats({
        ...emptyProgress(),
        percent: 12.5,
        phase: "video",
        speed: 48.7 * 1024 * 1024,
        eta: 60,
        bytes: 769.2 * 1024 * 1024,
        total: 3.4 * 1024 * 1024 * 1024,
      }),
    ).toBe("video · 769.2MiB/3.4GiB · 48.7MiB/s");
  });
});

describe("mergeProgress steps", () => {
  it("keeps step index when local percent resets", () => {
    const tree = buildTree(d20Plan);
    const first = applyProgress(tree, {
      event: "item_steps",
      id: "dropout|dimension-20|S21E01",
      steps: ["English subs", "Video"],
    }).progress;
    const second = applyProgress(tree, {
      event: "progress",
      id: "dropout|dimension-20|S21E01",
      step: 0,
      steps: ["English subs", "Video"],
      percent: 100,
    }).progress;
    const third = applyProgress(tree, {
      event: "progress",
      id: "dropout|dimension-20|S21E01",
      step: 1,
      steps: ["English subs", "Video"],
      percent: 5,
    }).progress;
    const merged = mergeProgress(mergeProgress(emptyProgress(), first), third);
    const withSecond = mergeProgress(mergeProgress(merged, second), third);
    expect(withSecond.step).toBe(1);
    expect(withSecond.currentId).toBe("dropout|dimension-20|S21E01");
    expect(withSecond.steps).toHaveLength(2);
  });
});

describe("runStatsLine", () => {
  it("counts done against the original queue size", () => {
    expect(
      runStatsLine(
        { phase: "downloading", source: "dropout" },
        {
          ...emptyProgress(),
          currentId: "a",
          percent: 10,
          phase: "video",
          doneIds: new Set(["a"]),
        },
        4,
      ),
    ).toBe("1/4 done · 0 failed · Dropout");
  });
});
