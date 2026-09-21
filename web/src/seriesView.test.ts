import { describe, expect, it } from "vitest";
import {
  addTvdbSkip,
  applyPackRemapsToSources,
  applySeasonToEpisode,
  buildDestMap,
  countLabel,
  emptyListMessage,
  fileStatus,
  filterCatalogEpisodes,
  filterSeries,
  filterSonarrEpisodes,
  findCatalogEpisode,
  formatMapsTo,
  isSeasonOpen,
  indexSeriesPosters,
  missingStatusClass,
  missingStatusText,
  originLabel,
  packDestSeasonRemaps,
  parseSeriesPath,
  rankSonarrRecommendations,
  remapCandidatesForMissing,
  remapFormDefaults,
  remapKind,
  removeTvdbSkip,
  seasonDisplayName,
  seasonFillStatus,
  seasonFoldMap,
  seasonHeading,
  seasonMissingLabel,
  skippedTvdbRows,
  slugify,
  seriesPosterUrl,
  sonarrBadgeLabel,
  sonarrEpisodeIsOut,
  sonarrSeriesUrl,
  suggestFolder,
  tvdbSeriesUrl,
  uniqueNameError,
} from "./seriesView";

describe("slugify", () => {
  it("matches python examples", () => {
    expect(slugify("Game Changer")).toBe("game-changer");
    expect(slugify("Dimension 20")).toBe("dimension-20");
    expect(slugify("  A/B  C!! ")).toBe("a-b-c");
    expect(slugify("Dimension 20's Adventuring Party")).toBe("dimension-20-s-adventuring-party");
    expect(slugify("---")).toBe("");
  });
});

describe("indexSeriesPosters", () => {
  it("joins queue slugs that used slugify(name) to file-stem show rows", () => {
    const posters = indexSeriesPosters([
      {
        platform: "dropout",
        slug: "dimension-20-adventuring-party",
        name: "Dimension 20's Adventuring Party",
        poster_url: "/api/series/dropout/dimension-20-adventuring-party/poster",
      },
    ]);
    expect(
      seriesPosterUrl(
        posters,
        "dropout",
        "dimension-20-s-adventuring-party",
        "Dimension 20's Adventuring Party",
      ),
    ).toBe("/api/series/dropout/dimension-20-adventuring-party/poster");
  });
});

describe("suggestFolder", () => {
  it("adds tvdb suffix when set", () => {
    expect(suggestFolder("Dimension 20", null)).toBe("Dimension 20");
    expect(suggestFolder("Dimension 20", 354216)).toBe("Dimension 20 [tvdbid=354216]");
  });
});

describe("uniqueNameError", () => {
  it("detects case-insensitive duplicates", () => {
    expect(uniqueNameError("game changer", [{ name: "Game Changer", slug: "x" }])).toBe(
      "A series named Game Changer already exists",
    );
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
    expect(parseSeriesPath("/series/dropout/game%20changer")).toEqual({
      platform: "dropout",
      slug: "game changer",
    });
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
    expect(filterSeries(rows, { query: "alpha" })[0]?.slug).toBe("a");
  });
});

describe("seasonFoldMap", () => {
  it("sets every season and defaults closed", () => {
    const sources = [{ seasons: [1, 2] }, { seasons: [3] }];
    expect(seasonFoldMap(sources, false)).toEqual({
      "0-0": false,
      "0-1": false,
      "1-0": false,
    });
    expect(isSeasonOpen({}, 0, 0)).toBe(false);
    expect(isSeasonOpen({ "0-0": true }, 0, 0)).toBe(true);
    expect(isSeasonOpen({ "0-0": false }, 0, 0)).toBe(false);
  });
});

describe("countLabel", () => {
  it("pluralizes", () => {
    expect(countLabel(1, "url", "urls")).toBe("1 url");
    expect(countLabel(2, "url", "urls")).toBe("2 urls");
    expect(countLabel(0, "season", "seasons")).toBe("0 seasons");
  });
});

describe("seasonMissingLabel", () => {
  it("hides complete seasons and labels gaps", () => {
    expect(seasonMissingLabel(0)).toBe("");
    expect(seasonMissingLabel(1)).toBe("1 missing");
    expect(seasonMissingLabel(4)).toBe("4 missing");
    expect(seasonMissingLabel(null)).toBe("");
  });
});

describe("missing status copy", () => {
  it("uses one missing label and color class", () => {
    expect(missingStatusText(0)).toBe("Up to date");
    expect(missingStatusText(3)).toBe("3 missing");
    expect(missingStatusClass(0)).toBe("is-ok");
    expect(missingStatusClass(3)).toBe("is-new");
    expect(missingStatusText(null)).toBeNull();
  });
});

describe("sonarrEpisodeIsOut", () => {
  it("ignores TBA titles and future air dates", () => {
    expect(sonarrEpisodeIsOut("TBA", null, "2026-09-21")).toBe(false);
    expect(sonarrEpisodeIsOut("tbd", "2020-01-01", "2026-09-21")).toBe(false);
    expect(sonarrEpisodeIsOut("Pilot", "2026-09-22", "2026-09-21")).toBe(false);
    expect(sonarrEpisodeIsOut("Pilot", "2026-09-21", "2026-09-21")).toBe(true);
    expect(sonarrEpisodeIsOut("Cut for Time", null, "2026-09-21")).toBe(true);
  });
});

describe("sonarr remap search", () => {
  const episodes = [
    { season: 1, episode: 2, title: "Pilot" },
    { season: 3, episode: 11, title: "Slug Eater" },
    { season: 0, episode: 4, title: "TBA" },
  ];

  it("filters by code, number, and title", () => {
    expect(filterSonarrEpisodes(episodes, "S03E11")).toEqual([episodes[1]]);
    expect(filterSonarrEpisodes(episodes, "e2")).toEqual([episodes[0]]);
    expect(filterSonarrEpisodes(episodes, "slug")).toEqual([episodes[1]]);
  });

  it("ranks suggestions, current slot, and episode-number hits", () => {
    const ranked = rankSonarrRecommendations(episodes, [episodes[2]!], {
      title: "Slug",
      mapped_season: 1,
      mapped_episode: 2,
      source_episode: 11,
    });
    expect(ranked.map((row) => `${row.season}-${row.episode}`)).toEqual(["0-4", "1-2", "3-11"]);
  });
});

describe("remapFormDefaults", () => {
  it("prefills Emby season, episode, and title from the applied mapping", () => {
    expect(
      remapFormDefaults({
        title: "Dropout Title",
        mapped_title: "Sonarr Title",
        mapped_season: 7,
        mapped_episode: 3,
      }),
    ).toEqual({ toSeason: "7", toEpisode: "3", title: "Sonarr Title" });
  });

  it("leaves dest fields empty when unmapped", () => {
    expect(
      remapFormDefaults({
        title: "Loose",
        mapped_title: null,
        mapped_season: null,
        mapped_episode: null,
      }),
    ).toEqual({ toSeason: "", toEpisode: "", title: "Loose" });
  });
});

describe("emptyListMessage", () => {
  it("distinguishes empty catalog from a failed filter", () => {
    expect(emptyListMessage(0, 0)).toBe("No series yet");
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
    const next = applySeasonToEpisode({ only_episodes: [1], remaps: [], skip_ids: [] }, base);
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
    expect(second[0]?.episodes).toEqual([3, 12]);
  });
});

describe("removeTvdbSkip", () => {
  it("drops empty season blocks", () => {
    expect(removeTvdbSkip([{ season: 0, episodes: [12, 30] }], 0, 12)).toEqual([
      { season: 0, episodes: [30] },
    ]);
    expect(removeTvdbSkip([{ season: 0, episodes: [12] }], 0, 12)).toEqual([]);
  });
});

describe("skippedTvdbRows", () => {
  it("lists only skipped slots with Sonarr titles when known", () => {
    const rows = skippedTvdbRows(
      [{ season: 0, episodes: [30] }],
      [
        { season: 0, episode: 30, title: "Cut for Time" },
        { season: 1, episode: 1, title: "Pilot" },
      ],
    );
    expect(rows).toEqual([{ season: 0, episode: 30, title: "Cut for Time" }]);
  });
});

describe("fileStatus", () => {
  const disk = new Set(["1-1"]);
  it("prefers skipped then disk presence", () => {
    expect(fileStatus({ skipped: true, mapped_season: 1, mapped_episode: 1 }, disk)).toBe(
      "skipped",
    );
    expect(fileStatus({ skipped: false, mapped_season: 1, mapped_episode: 1 }, disk)).toBe(
      "downloaded",
    );
    expect(fileStatus({ skipped: false, mapped_season: 1, mapped_episode: 2 }, disk)).toBe(
      "missing",
    );
    expect(fileStatus({ skipped: false, mapped_season: null, mapped_episode: null }, disk)).toBe(
      "unmapped",
    );
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

describe("catalog remap helpers", () => {
  const season = {
    id: "0",
    dropout: 4,
    url: "",
    to_season: 4,
    enabled: true,
    only_episodes: null,
    remaps: [],
    skip_ids: [],
    label: "Season 4",
    sublabel: "",
    title: null,
  };
  const episode = {
    id: "11",
    title: "Slug Eater",
    url: "",
    source_episode: 11,
    skipped: false,
    mapped_season: 4,
    mapped_episode: 11,
    mapped_title: "Slug Eater",
  };
  const catalog = [{ sourceId: 0, seasonId: 0, season, episode }];

  it("finds a dropout listing", () => {
    expect(findCatalogEpisode(catalog, 4, 11)?.episode.id).toBe("11");
    expect(findCatalogEpisode(catalog, 1, 11)).toBeNull();
  });

  it("builds missing remap candidates from origin hints", () => {
    const rows = remapCandidatesForMissing(catalog, {
      title: "Slug Eater",
      hints: [
        {
          kind: "origin",
          dropout_season: 4,
          dropout_episode: 11,
        },
      ],
    });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.episode.title).toBe("Slug Eater");
  });

  it("filters the catalog by title and episode number", () => {
    expect(filterCatalogEpisodes(catalog, "slug")).toHaveLength(1);
    expect(filterCatalogEpisodes(catalog, "e11")).toHaveLength(1);
    expect(filterCatalogEpisodes(catalog, "pilot")).toHaveLength(0);
  });
});

describe("external series urls", () => {
  it("builds tvdb and sonarr links", () => {
    expect(tvdbSeriesUrl(361151)).toBe("https://thetvdb.com/dereferrer/series/361151");
    expect(sonarrSeriesUrl("http://sonarr:8989/", "game-changer", 361151)).toBe(
      "http://sonarr:8989/series/game-changer",
    );
    expect(sonarrSeriesUrl("http://sonarr:8989", null, 361151)).toContain("tvdb%3A361151");
  });
});

describe("dest-order map", () => {
  const season = {
    id: "0",
    dropout: 3,
    url: "https://www.dropout.tv/smartypants/season/3",
    to_season: 3,
    enabled: true,
    only_episodes: null,
    remaps: [
      { dropout_episode: 2, to_season: 0, to_episode: 2, title: "Special A" },
      { dropout_episode: 4, to_season: 0, to_episode: 4, title: "Special B" },
    ],
    skip_ids: [],
    label: "Season 3",
    sublabel: "",
    title: null,
  };
  const listing = (n: number, title: string) => ({
    id: String(n),
    title,
    url: "",
    source_episode: n,
    skipped: false,
    mapped_season: 3,
    mapped_episode: n,
    mapped_title: title,
  });
  const catalog = [1, 2, 3, 4, 5].map((n) => ({
    sourceId: 0,
    seasonId: 0,
    season,
    episode: listing(n, `Episode ${n}`),
  }));
  const sonarr = [1, 2, 3, 4, 5].map((n) => ({
    season: 3,
    episode: n,
    title: `Library ${n}`,
  }));

  it("colors remaps and leaves dest holes after specials", () => {
    expect(remapKind(season, catalog[1]!.episode)).toBe("other-season");
    expect(remapKind(season, catalog[2]!.episode)).toBe("default");
    expect(originLabel(catalog[0]!)).toBe("Dropout 3 · E1");
    expect(
      originLabel({
        ...catalog[0]!,
        sourceUrl: "https://www.dropout.tv/smartypants",
      }),
    ).toBe("Dropout 3 · E1 · www.dropout.tv/smartypants");

    const dest = buildDestMap(catalog, sonarr, new Set());
    const s3 = dest.seasons.find((group) => group.destSeason === 3);
    const specials = dest.seasons.find((group) => group.destSeason === 0);
    expect(s3?.holes).toBe(2);
    expect(s3?.packable).toBe(false);
    expect(s3?.slots.map((slot) => [slot.destEpisode, slot.occupants.length])).toEqual([
      [1, 1],
      [2, 0],
      [3, 1],
      [4, 0],
      [5, 1],
    ]);
    expect(specials?.slots.map((slot) => slot.destEpisode)).toEqual([2, 4]);
    expect(specials?.slots.every((slot) => slot.occupants[0]?.kind === "other-season")).toBe(true);
  });

  it("does not treat TBA or unaired Sonarr rows as dest holes", () => {
    const dest = buildDestMap(catalog, [
      ...sonarr,
      { season: 3, episode: 6, title: "TBA" },
      { season: 3, episode: 7, title: "Next Week", air_date: "2099-01-01" },
    ], new Set());
    const s3 = dest.seasons.find((group) => group.destSeason === 3);
    expect(s3?.slots.map((slot) => slot.destEpisode)).toEqual([1, 2, 3, 4, 5]);
    expect(s3?.holes).toBe(2);
  });

  it("packs remaining native listings into consecutive dest numbers", () => {
    const changes = packDestSeasonRemaps(3, catalog);
    expect(changes).toEqual([
      {
        sourceId: 0,
        seasonId: 0,
        dropout_episode: 3,
        to_season: 3,
        to_episode: 2,
        title: "Episode 3",
        clear: false,
      },
      {
        sourceId: 0,
        seasonId: 0,
        dropout_episode: 5,
        to_season: 3,
        to_episode: 3,
        title: "Episode 5",
        clear: false,
      },
    ]);

    const packedSources = applyPackRemapsToSources(
      [
        {
          id: "0",
          url: season.url,
          error: null,
          seasons: [season],
        },
      ],
      changes,
    );
    const packedSeason = packedSources[0]!.seasons[0]!;
    expect(packedSeason.remaps).toEqual([
      { dropout_episode: 2, to_season: 0, to_episode: 2, title: "Special A" },
      { dropout_episode: 4, to_season: 0, to_episode: 4, title: "Special B" },
      {
        dropout_episode: 3,
        to_season: 3,
        to_episode: 2,
        title: "Episode 3",
      },
      {
        dropout_episode: 5,
        to_season: 3,
        to_episode: 3,
        title: "Episode 5",
      },
    ]);
    expect(remapKind(packedSeason, catalog[2]!.episode)).toBe("same-season");

    const packedCatalog = catalog.map((row) => ({ ...row, season: packedSeason }));
    const dest = buildDestMap(packedCatalog, sonarr, new Set());
    const s3 = dest.seasons.find((group) => group.destSeason === 3);
    expect(
      s3?.slots.filter((slot) => slot.occupants.length > 0).map((slot) => slot.destEpisode),
    ).toEqual([1, 2, 3]);
    expect(s3?.packable).toBe(false);
  });

  it("does not count tvdb_skip slots as dest holes", () => {
    const dest = buildDestMap(catalog, sonarr, new Set(), [{ season: 3, episodes: [2, 4] }]);
    const s3 = dest.seasons.find((group) => group.destSeason === 3);
    expect(s3?.holes).toBe(0);
    expect(s3?.slots.find((slot) => slot.destEpisode === 2)?.skipped).toBe(true);
    expect(seasonFillStatus(s3!)).toBe("empty");
  });
});
