import { describe, expect, it } from "vitest";
import type { AppConfig, ManifestPaths } from "../api";
import { pathsUnset } from "./OnboardingChecklist";

function config(library: string | null, oldDir: string | null): AppConfig {
  return {
    fields: {
      library: { effective: library },
      old_dir: { effective: oldDir },
    },
  } as AppConfig;
}

function manifestPaths(library: string | null, oldDir: string | null): ManifestPaths {
  const path = (effective: string | null) => ({
    manifest: effective,
    effective,
    source: effective ? ("manifest" as const) : ("unset" as const),
    env_name: null,
  });
  return { library: path(library), old_dir: path(oldDir), staging: path(null) };
}

describe("pathsUnset", () => {
  it("accepts shared fallback paths", () => {
    expect(pathsUnset(config("/library", "/old"))).toBe(false);
  });

  it("accepts paths declared by every platform with a show", () => {
    expect(
      pathsUnset(config(null, null), { youtube: manifestPaths("/yt", "/old-yt") }, ["youtube"]),
    ).toBe(false);
  });

  it("keeps setup incomplete if any platform path is missing", () => {
    expect(
      pathsUnset(
        config(null, null),
        {
          youtube: manifestPaths("/yt", "/old-yt"),
          dropout: manifestPaths("/dropout", null),
        },
        ["youtube", "dropout"],
      ),
    ).toBe(true);
  });
});
