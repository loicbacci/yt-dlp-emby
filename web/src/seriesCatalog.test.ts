import { describe, expect, it } from "vitest";
import { mergeOnDisk, onDiskSet } from "./seriesCatalog";
import { seriesUiKey } from "./seriesUiStore";

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
