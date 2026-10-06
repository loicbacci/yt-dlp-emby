import { describe, expect, it } from "vitest";
import {
  beginRefresh,
  endRefresh,
  isRefreshing,
  refreshSeriesKey,
  seriesRefreshStore,
  setServerRefreshing,
} from "./seriesRefreshStore";

describe("series refresh state", () => {
  it("keeps a series refreshing until every overlapping operation ends", () => {
    const key = refreshSeriesKey("dropout", "show");
    beginRefresh([key]);
    beginRefresh([key]);
    expect(isRefreshing("dropout", "show")).toBe(true);
    expect([...seriesRefreshStore.state.counts.keys()]).toContain(key);

    endRefresh([key]);
    expect(isRefreshing("dropout", "show")).toBe(true);

    endRefresh([key]);
    expect(isRefreshing("dropout", "show")).toBe(false);
    expect([...seriesRefreshStore.state.counts.keys()]).not.toContain(key);
  });

  it("restores a refresh reported by the server after a page reload", () => {
    setServerRefreshing([refreshSeriesKey("youtube", "show")]);
    expect(isRefreshing("youtube", "show")).toBe(true);

    setServerRefreshing([]);
    expect(isRefreshing("youtube", "show")).toBe(false);
  });
});
