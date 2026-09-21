import { describe, expect, it } from "vitest";
import { shouldPersistQuery } from "./queryKeys";
import { mergeOnDisk, onDiskSet } from "./seriesCatalog";
import { seriesUiKey } from "./seriesUiStore";

describe("shouldPersistQuery", () => {
  it("persists catalog, not derived disk or run snapshots", () => {
    expect(shouldPersistQuery(["episodes", "dropout", "clip", 0, 0])).toBe(true);
    expect(shouldPersistQuery(["disk", "dropout", "clip"])).toBe(false);
    expect(shouldPersistQuery(["series-list"])).toBe(true);
    expect(shouldPersistQuery(["series-missing", "dropout|clip"])).toBe(false);
    expect(shouldPersistQuery(["run"])).toBe(false);
  });
});

describe("onDiskSet", () => {
  it("maps slots to keys and prefers the disk payload", () => {
    expect([...onDiskSet([{ season: 1, episode: 2 }])]).toEqual(["1-2"]);
    const merged = mergeOnDisk(
      [{ season: 4, episode: 11 }],
      [{ on_disk: [{ season: 1, episode: 1 }] }],
    );
    expect([...merged]).toEqual(["4-11"]);
    expect(mergeOnDisk([], [{ on_disk: [{ season: 1, episode: 1 }] }]).size).toBe(0);
    const fallback = mergeOnDisk(undefined, [{ on_disk: [{ season: 1, episode: 1 }] }]);
    expect([...fallback]).toEqual(["1-1"]);
  });
});

describe("seriesUiKey", () => {
  it("scopes fold state per series", () => {
    expect(seriesUiKey("dropout", "game-changer")).toBe("dropout:game-changer");
  });
});
