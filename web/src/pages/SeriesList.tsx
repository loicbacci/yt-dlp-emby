import { useEffect, useState } from "preact/hooks";
import { useIsRestoring, useQueries, useQuery, useQueryClient } from "@tanstack/preact-query";
import { ApiError, type Run, apiClient } from "../api";
import { Header } from "../components/Header";
import { Poster, posterLetter } from "../components/Poster";
import { SeriesListSkeleton, Skeleton } from "../components/Skeleton";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { go } from "../nav";
import { EPISODE_STALE_MS } from "../queryClient";
import { queryKeys } from "../queryKeys";
import {
  beginRefresh,
  endRefresh,
  refreshSeriesKey,
  useAnyRefreshing,
} from "../seriesRefreshStore";
import type { SeriesPlatform, SeriesSummary } from "../seriesView";
import { countLabel, emptyListMessage, filterSeries } from "../seriesView";

const idleRun: Run = {
  status: "idle",
  phase: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
  plan: null,
};

export function SeriesList() {
  const restoring = useIsRestoring();
  const queryClient = useQueryClient();
  const refreshingKeys = useAnyRefreshing();
  const [run, setRun] = useState<Run>(idleRun);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<SeriesPlatform | "all">("all");
  const [modal, setModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);

  const listQuery = useQuery({
    queryKey: queryKeys.seriesList(),
    queryFn: () => apiClient.listSeries(),
    staleTime: 60 * 1000,
  });
  const rows = listQuery.data?.series ?? [];
  const dropoutRows = rows.filter((row) => row.platform === "dropout");
  const missingQueries = useQueries({
    queries: dropoutRows.map((row) => ({
      queryKey: queryKeys.missing("dropout", row.slug),
      queryFn: () => apiClient.getSeriesMissing("dropout", row.slug),
      staleTime: EPISODE_STALE_MS,
    })),
  });
  const missingBySlug: Record<
    string,
    (typeof missingQueries)[number] | undefined
  > = {};
  dropoutRows.forEach((row, index) => {
    missingBySlug[row.slug] = missingQueries[index];
  });

  const listError =
    listQuery.error instanceof ApiError && listQuery.error.status === 401
      ? null
      : listQuery.error instanceof Error
        ? listQuery.error.message
        : null;
  const listLoading = Boolean(
    (listQuery.isPending && !listQuery.data) || (restoring && !listQuery.data),
  );

  useEffect(() => {
    if (listQuery.error instanceof ApiError && listQuery.error.status === 401) {
      go("/login");
    }
  }, [listQuery.error]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      apiClient.getRun().then(setRun).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  const filtered = filterSeries(rows, { query, platform });
  const listingsPending = filtered.some(
    (row) => row.platform === "dropout" && row.listings_complete === false,
  );

  const invalidateSeries = async (
    items: { platform: SeriesPlatform; slug: string; tvdb_id?: number | null }[],
  ) => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() });
    for (const item of items) {
      const jobs = [
        queryClient.invalidateQueries({
          queryKey: queryKeys.series(item.platform, item.slug),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.episodesSeries(item.platform, item.slug),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.disk(item.platform, item.slug),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.missing(item.platform, item.slug),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.check(item.slug) }),
      ];
      if (item.tvdb_id != null) {
        jobs.push(
          queryClient.invalidateQueries({
            queryKey: queryKeys.sonarrEpisodes(item.tvdb_id),
          }),
        );
      }
      await Promise.all(jobs);
    }
  };

  const refreshItems = async (items: { platform: SeriesPlatform; slug: string }[]) => {
    if (!items.length) return;
    const keys = items.map((item) => refreshSeriesKey(item.platform, item.slug));
    beginRefresh(keys);
    setRefreshBusy(true);
    try {
      await apiClient.refreshSeries(items);
      await invalidateSeries(items);
    } finally {
      endRefresh(keys);
      setRefreshBusy(false);
    }
  };

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  const onCreate = async (body: {
    name: string;
    platform: import("../api").Source;
    path: string;
    tvdb_id: number | null;
  }) => {
    const detail = await apiClient.createSeries(body);
    setModal(false);
    go(`/series/${detail.platform}/${detail.slug}`);
  };

  return (
    <div class="series-shell">
      <Header run={run} current="series" onLogout={() => void logout()} />
      <section class="card series-card">
        <div class="series-toolbar">
          <h1 class="settings-title">Shows</h1>
          <div class="series-toolbar-end">
            <button
              type="button"
              class="btn-secondary"
              disabled={refreshBusy || !filtered.length}
              onClick={() => void refreshItems(filtered)}
            >
              Refresh
            </button>
            <button
              type="button"
              class="btn-secondary"
              data-testid="series-add"
              onClick={() => setModal(true)}
            >
              Add show
            </button>
          </div>
        </div>
        <div class="series-toolbar">
          <label class="series-search">
            <input
              type="search"
              placeholder="Search shows"
              value={query}
              onInput={(e) =>
                setQuery((e.currentTarget as HTMLInputElement).value)
              }
            />
          </label>
          {(["all", "youtube", "dropout"] as const).map((chip) => (
            <button
              key={chip}
              type="button"
              class={platform === chip ? "filter-chip active" : "filter-chip"}
              aria-pressed={platform === chip}
              onClick={() => setPlatform(chip)}
            >
              {chip === "all"
                ? "All"
                : chip === "youtube"
                  ? "YouTube"
                  : "Dropout"}
            </button>
          ))}
        </div>
        {listError && <div class="validation-error">{listError}</div>}
        {listLoading ? (
          <SeriesListSkeleton />
        ) : !filtered.length ? (
          <div class="empty-state">{emptyListMessage(rows.length, filtered.length)}</div>
        ) : (
          filtered.map((row) => (
            <SeriesRow
              key={`${row.platform}-${row.slug}`}
              row={row}
              missingQuery={missingBySlug[row.slug]}
              restoring={restoring}
              refreshing={refreshingKeys.has(refreshSeriesKey(row.platform, row.slug))}
              menuOpen={menuOpen === `${row.platform}-${row.slug}`}
              onToggleMenu={() =>
                setMenuOpen((current) =>
                  current === `${row.platform}-${row.slug}`
                    ? null
                    : `${row.platform}-${row.slug}`,
                )
              }
              onRefresh={() => void refreshItems([{ platform: row.platform, slug: row.slug }])}
              onDelete={async () => {
                if (!window.confirm(`Delete ${row.name}?`)) return;
                await apiClient.deleteSeries(row.platform, row.slug);
                await queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() });
              }}
            />
          ))
        )}
        {listingsPending && !listLoading && (
          <div class="listings-spinner" aria-live="polite">
            <span class="spinner" aria-hidden="true" />
            Reading remaining listings…
          </div>
        )}
      </section>
      {modal && (
        <CreateSeriesModal
          existing={rows}
          onClose={() => setModal(false)}
          onCreate={onCreate}
        />
      )}
    </div>
  );
}

function SeriesRow({
  row,
  missingQuery,
  restoring,
  refreshing,
  menuOpen,
  onToggleMenu,
  onRefresh,
  onDelete,
}: {
  row: SeriesSummary;
  missingQuery?: {
    data?: { missing_count: number | null; complete: boolean };
    isPending: boolean;
  };
  restoring: boolean;
  refreshing: boolean;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onRefresh: () => void;
  onDelete: () => void | Promise<void>;
}) {
  const count =
    missingQuery?.data !== undefined
      ? missingQuery.data.missing_count
      : row.missing_count;
  const missingLoading =
    (row.platform === "dropout" &&
      count == null &&
      Boolean(missingQuery?.isPending || restoring)) ||
    refreshing;
  const statusText =
    count != null && count > 0 ? `${count} new` : count === 0 ? "Up to date" : null;

  return (
    <div
      class={`show-row${refreshing ? " is-disabled" : ""}`}
      data-testid={`series-row-${row.slug}`}
      aria-disabled={refreshing}
    >
      <a
        href={`/series/${row.platform}/${row.slug}`}
        class="show-row-link"
        onClick={(event) => {
          if (refreshing) {
            event.preventDefault();
            return;
          }
          if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          ) {
            return;
          }
          event.preventDefault();
          go(`/series/${row.platform}/${row.slug}`);
        }}
      >
        <Poster
          src={row.poster_url}
          letter={posterLetter(row.name)}
          size="md"
          alt={row.name}
        />
        <div class="show-row-main">
          <div class="show-row-title">{row.name}</div>
          <div class="series-row-meta">
            <span>
              {row.platform === "youtube" ? "YouTube" : "Dropout"}
              {" · "}
              {countLabel(row.season_count, "season", "seasons")}
              {" · "}
              {missingLoading ? (
                <Skeleton width="6rem" height="0.85em" />
              ) : count != null ? (
                count === 0 ? "Up to date" : `${count} not in library`
              ) : (
                "—"
              )}
            </span>
            <span>{row.path}</span>
          </div>
        </div>
      </a>
      <div class="show-row-actions">
        {missingLoading ? (
          <Skeleton width="4rem" height="0.9em" />
        ) : (
          statusText && <span class="season-missing-count">{statusText}</span>
        )}
        <div class="overflow-menu">
          <button
            type="button"
            class="btn-ghost overflow-trigger"
            aria-expanded={menuOpen}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleMenu();
            }}
          >
            ⋯
          </button>
          {menuOpen && (
            <div class="overflow-panel" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onToggleMenu();
                  go(`/series/${row.platform}/${row.slug}`);
                }}
              >
                Edit
              </button>
              <button type="button" role="menuitem" onClick={() => { onToggleMenu(); onRefresh(); }}>
                Refresh
              </button>
              <button
                type="button"
                role="menuitem"
                class="is-danger"
                onClick={() => {
                  onToggleMenu();
                  void onDelete();
                }}
              >
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
