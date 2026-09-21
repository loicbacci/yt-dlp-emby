import { useMemo, useState } from "preact/hooks";
import { MOCK_SHOWS, missingCount } from "./mockCatalog";
import { MockShell, OverflowMenu, Poster, Skel, Spinner } from "./Shell";

type Platform = "all" | "dropout" | "youtube";
export type ShowsListLoading = "idle" | "manifests" | "refresh";

export function ShowsList({
  loading = "idle",
  empty = false,
  loadError = null,
}: {
  loading?: ShowsListLoading;
  empty?: boolean;
  loadError?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<Platform>("all");
  const [menu, setMenu] = useState<string | null>(null);
  const refreshing = loading === "refresh";
  const readingManifests = loading === "manifests";
  const rows = useMemo(() => {
    if (empty) return [];
    const filtered = MOCK_SHOWS.filter((row) => {
      if (platform !== "all" && row.platform !== platform) return false;
      if (!query.trim()) return true;
      return row.name.toLowerCase().includes(query.trim().toLowerCase());
    });
    if (readingManifests) return filtered.slice(0, 4);
    return filtered;
  }, [platform, query, readingManifests, empty]);

  return (
    <MockShell current="shows">
      <div class="mock-toolbar">
        <h1>Shows</h1>
        <div class="mock-toolbar-actions">
          <button
            type="button"
            class="mock-ghost"
            disabled={refreshing || readingManifests}
          >
            {refreshing ? (
              <>
                <Spinner />
                Refreshing
              </>
            ) : (
              "Refresh"
            )}
          </button>
          <button type="button" class="mock-primary">
            Add show
          </button>
        </div>
      </div>
      <div class="mock-filters">
        <input
          class="mock-search"
          type="search"
          placeholder="Search shows"
          value={query}
          onInput={(e) => setQuery((e.currentTarget as HTMLInputElement).value)}
        />
        {(["all", "youtube", "dropout"] as const).map((chip) => (
          <button
            key={chip}
            type="button"
            class={platform === chip ? "mock-chip is-active" : "mock-chip"}
            onClick={() => setPlatform(chip)}
          >
            {chip === "all" ? "All" : chip === "youtube" ? "YouTube" : "Dropout"}
          </button>
        ))}
      </div>
      {loadError ? (
        <div class="mock-error-card" role="alert">
          <p>{loadError}</p>
          <button type="button" class="mock-ghost">
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div class="mock-empty">
          <p>No series yet. Add your first show to get started.</p>
          <button type="button" class="mock-primary">
            Add show
          </button>
        </div>
      ) : rows.map((row) => {
        const missing = missingCount(row);
        return (
          <article
            key={row.id}
            class={
              refreshing ? "mock-show-row is-busy" : "mock-show-row"
            }
            aria-disabled={refreshing}
          >
            <Poster src={row.poster} letter={row.letter} tone={row.tone} />
            <div class="mock-show-copy">
              <div class="mock-show-name">{row.name}</div>
              {refreshing ? (
                <div class="mock-skel-meta">
                  <Skel width="9.5rem" />
                  <Skel width="7.5rem" />
                </div>
              ) : (
                <div class="mock-show-meta">
                  {row.platform === "youtube" ? "YouTube" : "Dropout"} ·{" "}
                  {row.seasons.length}{" "}
                  {row.seasons.length === 1 ? "season" : "seasons"}
                  {missing > 0 ? ` · ${missing} not in library` : " · Up to date"}
                </div>
              )}
              <div class="mock-path">{row.path}</div>
            </div>
            {refreshing ? (
              <span class="mock-status">
                <Skel width="4.5rem" height="1.1em" />
              </span>
            ) : (
              <span
                class={`mock-status ${missing ? (missing > 20 ? "is-new" : "is-missing") : "is-ok"}`}
              >
                {missing ? `${missing} new` : "Up to date"}
              </span>
            )}
            <OverflowMenu
              open={menu === row.id}
              onToggle={() => setMenu(menu === row.id ? null : row.id)}
              onClose={() => setMenu(null)}
            />
          </article>
        );
        })}
      {readingManifests && !loadError && rows.length > 0 ? (
        <div class="mock-list-status" role="status">
          <Spinner />
          Reading remaining manifests…
        </div>
      ) : null}
    </MockShell>
  );
}
