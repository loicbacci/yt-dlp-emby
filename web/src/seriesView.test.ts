import { describe, expect, it } from "vitest";
import { addTvdbSkip, applySeasonToEpisode, countLabel, emptyListMessage, filterSeries, formatMapsTo, parseSeriesPath, seasonDisplayName, seasonHeading, slugify, sonarrBadgeLabel, suggestFolder, uniqueNameError } from "./seriesView";

describe("slugify", () => {
  it("matches python examples", () => {
    expect(slugify("Game Changer")).toBe("game-changer");
    expect(slugify("Dimension 20")).toBe("dimension-20");
    expect(slugify("  A/B  C!! ")).toBe("a-b-c");
    expect(slugify("---")).toBe("");
  });
});

describe("suggestFolder", () => {
  it("adds tvdb suffix when set", () => {
    expect(suggestFolder("Dimension 20", null)).toBe("Dimension 20");
    expect(suggestFolder("Dimension 20", 354216)).toBe(
      "Dimension 20 [tvdbid=354216]",
    );
  });
});

describe("uniqueNameError", () => {
  it("detects case-insensitive duplicates", () => {
    expect(
      uniqueNameError("game changer", [{ name: "Game Changer", slug: "x" }]),
    ).toBe("A series named Game Changer already exists");
    expect(uniqueNameError("New", [{ name: "Other" }])).toBeNull();
  });
});

describe("parseSeriesPath", () => {
  it("parses detail routes", () => {
    expect(parseSeriesPath("/series/dropout/dimension-20")).toEqual({
      platform: "dropout",
      slug: "dimension-20",
    });
    expect(parseSeriesPath("/")).toBeNull();
  });
});

describe("formatMapsTo", () => {
  it("formats season and episode", () => {
    expect(formatMapsTo(7, 1)).toBe("S07E01");
    expect(formatMapsTo(0, 12)).toBe("S00E12");
  });
});

describe("seasonHeading", () => {
  it("labels specials", () => {
    expect(seasonHeading(0)).toBe("Specials");
    expect(seasonHeading(3)).toBe("Season 3");
  });
});

describe("seasonDisplayName", () => {
  it("prefers title", () => {
    expect(seasonDisplayName(21, "Junior Year")).toBe("Junior Year");
    expect(seasonDisplayName(0, null)).toBe("Specials");
    expect(seasonDisplayName(5, "  ")).toBe("Season 5");
  });
});

describe("filterSeries", () => {
  const rows = [
    {
      platform: "dropout" as const,
      slug: "a",
      file: "shows/a.yaml",
      inline: false,
      name: "Alpha",
      path: "Alpha",
      tvdb_id: null,
      source_count: 1,
      season_count: 1,
    },
    {
      platform: "youtube" as const,
      slug: "b",
      file: "shows/b.yaml",
      inline: false,
      name: "Beta Channel",
      path: "Beta",
      tvdb_id: null,
      source_count: 2,
      season_count: 2,
    },
  ];

  it("filters by platform and query", () => {
    expect(filterSeries(rows, { platform: "youtube" })).toHaveLength(1);
    expect(filterSeries(rows, { query: "alpha" })[0].slug).toBe("a");
  });
});

describe("countLabel", () => {
  it("pluralizes", () => {
    expect(countLabel(1, "url", "urls")).toBe("1 url");
    expect(countLabel(2, "url", "urls")).toBe("2 urls");
    expect(countLabel(0, "season", "seasons")).toBe("0 seasons");
  });
});

describe("emptyListMessage", () => {
  it("distinguishes empty catalog from a failed filter", () => {
    expect(emptyListMessage(0, 0)).toBe("No series yet.");
    expect(emptyListMessage(3, 0)).toBe("No matching series.");
    expect(emptyListMessage(3, 2)).toBe("");
  });
});

describe("applySeasonToEpisode", () => {
  const base = {
    id: "12",
    title: "Cut",
    url: "https://example",
    source_episode: 12,
    skipped: false,
    mapped_season: 1,
    mapped_episode: 12,
    mapped_title: "Cut",
  };

  it("marks only_episodes gaps as skipped", () => {
    const next = applySeasonToEpisode(
      { only_episodes: [1], remaps: [], skip_ids: [] },
      base,
    );
    expect(next.skipped).toBe(true);
  });

  it("applies remap skip", () => {
    const next = applySeasonToEpisode(
      {
        only_episodes: null,
        remaps: [{ dropout_episode: 12, skip: true }],
        skip_ids: [],
      },
      base,
    );
    expect(next.skipped).toBe(true);
  });

  it("overlays remap maps-to when only_episodes lists the episode", () => {
    const next = applySeasonToEpisode(
      {
        only_episodes: [12],
        remaps: [
          {
            dropout_episode: 12,
            to_season: 4,
            to_episode: 11,
            title: "Cut for Time",
          },
        ],
        skip_ids: [],
      },
      base,
    );
    expect(next.skipped).toBe(false);
    expect(next.mapped_season).toBe(4);
    expect(next.mapped_episode).toBe(11);
    expect(next.mapped_title).toBe("Cut for Time");
  });
});

describe("addTvdbSkip", () => {
  it("adds a new season block or appends an episode", () => {
    const first = addTvdbSkip([], 0, 12);
    expect(first).toEqual([{ season: 0, episodes: [12] }]);
    const second = addTvdbSkip(first, 0, 3);
    expect(second[0].episodes).toEqual([3, 12]);
  });
});

describe("sonarrBadgeLabel", () => {
  it("prefers missing counts", () => {
    expect(sonarrBadgeLabel(null)).toBeNull();
    expect(sonarrBadgeLabel({ ok: true, missing: [] })).toBe("ok");
    expect(sonarrBadgeLabel({ ok: false, missing: [1, 2, 3] })).toBe("3 missing");
    expect(sonarrBadgeLabel({ ok: false, missing: [] })).toBe("warnings");
  });
});
