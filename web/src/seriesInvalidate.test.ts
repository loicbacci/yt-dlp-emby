import { QueryClient } from "@tanstack/preact-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SeriesDetail } from "./api";
import { queryKeys } from "./queryKeys";
import {
  SeriesChangeType,
  classifySeriesChange,
  invalidateAfterMetadataRefresh,
  invalidateAfterSeriesChange,
} from "./seriesInvalidate";

function detail(): SeriesDetail {
  return {
    platform: "dropout",
    slug: "show",
    file: "shows/show.yaml",
    inline: false,
    name: "Show",
    path: "Show",
    tvdb_id: 123,
    source_count: 1,
    season_count: 1,
    tvdb_skip: [],
    sources: [
      {
        id: "0",
        url: "https://watch.dropout.tv/show",
        error: null,
        seasons: [
          {
            id: "0",
            dropout: 1,
            url: "https://watch.dropout.tv/show/season-1",
            to_season: 1,
            enabled: true,
            only_episodes: null,
            remaps: [],
            skip_ids: [],
            label: "Season 1",
            sublabel: "",
            title: null,
          },
        ],
      },
    ],
  };
}

describe("series change classification and invalidation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes listing-derived state without rescanning disk or Sonarr", async () => {
    const client = new QueryClient();
    const keys = [
      queryKeys.seriesList(),
      queryKeys.series("dropout", "show"),
      queryKeys.plan(),
      queryKeys.episodes("dropout", "show", 0, 0),
      queryKeys.disk("dropout", "show"),
      queryKeys.missing("dropout", "show"),
      queryKeys.missingBatch(["dropout|show"]),
      queryKeys.check("show"),
      queryKeys.sonarrEpisodes(123),
    ];
    for (const queryKey of keys) client.setQueryData(queryKey, { cached: true });

    await invalidateAfterMetadataRefresh(
      client,
      [{ platform: "dropout", slug: "show", tvdb_id: 123 }],
      "listings",
    );

    for (const queryKey of keys.filter(
      (key) => key[0] !== "disk" && key[0] !== "sonarr-episodes",
    )) {
      expect(client.getQueryState(queryKey)?.isInvalidated).toBe(true);
    }
    expect(client.getQueryState(queryKeys.disk("dropout", "show"))?.isInvalidated).toBe(false);
    expect(client.getQueryState(queryKeys.sonarrEpisodes(123))?.isInvalidated).toBe(false);
  });

  it("refreshes only disk-derived state for a disk refresh", async () => {
    const client = new QueryClient();
    const keys = [
      queryKeys.seriesList(),
      queryKeys.series("dropout", "show"),
      queryKeys.plan(),
      queryKeys.episodes("dropout", "show", 0, 0),
      queryKeys.disk("dropout", "show"),
      queryKeys.missing("dropout", "show"),
      queryKeys.missingBatch(["dropout|show"]),
      queryKeys.check("show"),
      queryKeys.sonarrEpisodes(123),
    ];
    for (const queryKey of keys) client.setQueryData(queryKey, { cached: true });

    await invalidateAfterMetadataRefresh(
      client,
      [{ platform: "dropout", slug: "show", tvdb_id: 123 }],
      "disk",
    );

    for (const queryKey of [
      queryKeys.seriesList(),
      queryKeys.series("dropout", "show"),
      queryKeys.plan(),
      queryKeys.disk("dropout", "show"),
      queryKeys.missing("dropout", "show"),
      queryKeys.missingBatch(["dropout|show"]),
      queryKeys.check("show"),
    ]) {
      expect(client.getQueryState(queryKey)?.isInvalidated).toBe(true);
    }
    expect(client.getQueryState(queryKeys.episodes("dropout", "show", 0, 0))?.isInvalidated).toBe(
      false,
    );
    expect(client.getQueryState(queryKeys.sonarrEpisodes(123))?.isInvalidated).toBe(false);
  });

  it("does no query refresh for a season title edit", async () => {
    const client = new QueryClient();
    const previous = detail();
    const next = detail();
    next.sources[0]!.seasons[0]!.title = "Custom title";
    const keys = [
      queryKeys.plan(),
      queryKeys.episodes("dropout", "show", 0, 0),
      queryKeys.disk("dropout", "show"),
      queryKeys.missing("dropout", "show"),
      queryKeys.check("show"),
    ];
    for (const queryKey of keys) client.setQueryData(queryKey, { cached: true });
    client.setQueryData(queryKeys.seriesList(), { series: [], import_errors: [] });
    const allKeys = [...keys, queryKeys.seriesList()];

    expect(classifySeriesChange(previous, next)).toContain(SeriesChangeType.Presentation);
    await invalidateAfterSeriesChange(client, previous, next);

    for (const queryKey of allKeys) {
      expect(client.getQueryState(queryKey)?.isInvalidated).toBe(false);
    }
  });

  it("rechecks only mapped slots without invalidating catalogs or disk inventory", async () => {
    const client = new QueryClient();
    const previous = detail();
    const next = detail();
    next.sources[0]!.seasons[0]!.remaps = [
      { dropout_episode: 3, to_season: 1, to_episode: 8, title: "Mapped" },
    ];
    const catalogKey = queryKeys.episodes("dropout", "show", 0, 0);
    client.setQueryData(catalogKey, {
      episodes: [
        {
          id: "3",
          title: "Episode 3",
          url: "https://example.test/3",
          source_episode: 3,
          skipped: false,
          mapped_season: 1,
          mapped_episode: 3,
          mapped_title: null,
        },
      ],
    });
    client.setQueryData(queryKeys.disk("dropout", "show"), {
      on_disk: [{ season: 1, episode: 3 }],
    });
    client.setQueryData(queryKeys.plan(), { cached: true });
    client.setQueryData(queryKeys.missing("dropout", "show"), { cached: true });
    client.setQueryData(queryKeys.check("show"), { cached: true });
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        slots: [
          { season: 1, episode: 3 },
          { season: 1, episode: 8 },
        ],
      });
      return new Response(
        JSON.stringify({
          slots: [
            { season: 1, episode: 3, on_disk: false },
            { season: 1, episode: 8, on_disk: true },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetch);

    expect(classifySeriesChange(previous, next)).toContain(SeriesChangeType.EpisodeMapping);
    await invalidateAfterSeriesChange(client, previous, next);

    expect(client.getQueryState(queryKeys.missing("dropout", "show"))?.isInvalidated).toBe(false);
    expect(client.getQueryState(queryKeys.check("show"))?.isInvalidated).toBe(false);
    expect(client.getQueryState(queryKeys.plan())?.isInvalidated).toBe(false);
    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(false);
    expect(client.getQueryState(queryKeys.disk("dropout", "show"))?.isInvalidated).toBe(false);
    expect(client.getQueryData(queryKeys.disk("dropout", "show"))).toEqual({
      on_disk: [{ season: 1, episode: 8 }],
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("finds affected episodes from only_episodes when listings are not cached", async () => {
    const client = new QueryClient();
    const previous = detail();
    const next = detail();
    previous.sources[0]!.seasons[0]!.only_episodes = [1];
    next.sources[0]!.seasons[0]!.only_episodes = [3];
    client.setQueryData(queryKeys.disk("dropout", "show"), { on_disk: [] });
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        slots: [
          { season: 1, episode: 1 },
          { season: 1, episode: 3 },
        ],
      });
      return new Response(
        JSON.stringify({
          slots: [
            { season: 1, episode: 1, on_disk: false },
            { season: 1, episode: 3, on_disk: true },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetch);

    await invalidateAfterSeriesChange(client, previous, next);

    expect(client.getQueryData(queryKeys.disk("dropout", "show"))).toEqual({
      on_disk: [{ season: 1, episode: 3 }],
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rechecks old and new season slots for a season destination change", async () => {
    const client = new QueryClient();
    const previous = detail();
    const next = detail();
    next.sources[0]!.seasons[0]!.to_season = 2;
    const catalogKey = queryKeys.episodes("dropout", "show", 0, 0);
    client.setQueryData(catalogKey, {
      episodes: [
        {
          id: "3",
          title: "Episode 3",
          url: "https://example.test/3",
          source_episode: 3,
          skipped: false,
          mapped_season: 1,
          mapped_episode: 3,
          mapped_title: null,
        },
      ],
    });
    client.setQueryData(queryKeys.disk("dropout", "show"), { on_disk: [] });
    const fetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        slots: [
          { season: 1, episode: 3 },
          { season: 2, episode: 3 },
        ],
      });
      return new Response(
        JSON.stringify({
          slots: [
            { season: 1, episode: 3, on_disk: true },
            { season: 2, episode: 3, on_disk: false },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetch);

    expect(classifySeriesChange(previous, next)).toContain(SeriesChangeType.SeasonMapping);
    await invalidateAfterSeriesChange(client, previous, next);

    expect(client.getQueryData(queryKeys.disk("dropout", "show"))).toEqual({
      on_disk: [{ season: 1, episode: 3 }],
    });
    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("refreshes only that source catalog when its URL changes", async () => {
    const client = new QueryClient();
    const previous = detail();
    const next = detail();
    next.sources[0]!.url = "https://watch.dropout.tv/another-show";
    const catalogKey = queryKeys.episodes("dropout", "show", 0, 0);
    const diskKey = queryKeys.disk("dropout", "show");
    client.setQueryData(catalogKey, { cached: true });
    client.setQueryData(diskKey, { cached: true });

    expect(classifySeriesChange(previous, next)).toContain(SeriesChangeType.Catalog);
    await invalidateAfterSeriesChange(client, previous, next);

    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(diskKey)?.isInvalidated).toBe(false);
  });
});
