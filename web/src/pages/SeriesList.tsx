import { useEffect, useState } from "preact/hooks";
import { useIsRestoring, useQueries, useQuery } from "@tanstack/preact-query";
import { ApiError, type Run, apiClient } from "../api";
import { Header } from "../components/Header";
import { SeriesListSkeleton, Skeleton } from "../components/Skeleton";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { go } from "../nav";
import { EPISODE_STALE_MS } from "../queryClient";
import { queryKeys } from "../queryKeys";
import type { SeriesPlatform, SeriesSummary } from "../seriesView";
import { countLabel, emptyListMessage, filterSeries, seasonMissingLabel } from "../seriesView";

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
  const [run, setRun] = useState<Run>(idleRun);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<SeriesPlatform | "all">("all");
  const [modal, setModal] = useState(false);

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
          <h1 class="settings-title">Series</h1>
          <button
            type="button"
            class="btn-secondary"
            data-testid="series-add"
            onClick={() => setModal(true)}
          >
            Add series
          </button>
        </div>
        <div class="series-toolbar">
          <label class="series-search">
            <input
              type="search"
              placeholder="Search series"
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
                  : "Dropout.tv"}
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
            />
          ))
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
}: {
  row: SeriesSummary;
  missingQuery?: {
    data?: { missing_count: number | null; complete: boolean };
    isPending: boolean;
  };
  restoring: boolean;
}) {
  const count =
    missingQuery?.data !== undefined
      ? missingQuery.data.missing_count
      : row.missing_count;
  const missingLoading =
    row.platform === "dropout" &&
    count == null &&
    Boolean(missingQuery?.isPending || restoring);
  const missingLabel = seasonMissingLabel(count);

  return (
    <a
      href={`/series/${row.platform}/${row.slug}`}
      class="series-row"
      data-testid={`series-row-${row.slug}`}
      onClick={(event) => {
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
      <div class="series-row-main">
        <div class={count ? "season-has-missing" : undefined}>{row.name}</div>
        <div class="series-row-meta">
          <span>{row.path}</span>
          {row.tvdb_id != null && <span>tvdb {row.tvdb_id}</span>}
          <span>
            {countLabel(
              row.source_count,
              row.platform === "youtube" ? "playlist" : "url",
              row.platform === "youtube" ? "playlists" : "urls",
            )}
          </span>
          <span>{countLabel(row.season_count, "season", "seasons")}</span>
          {row.inline && <span>inline</span>}
        </div>
      </div>
      <div class="series-row-badges">
        {missingLoading ? (
          <Skeleton width="5.5rem" height="0.9em" class="season-missing-skeleton" />
        ) : (
          missingLabel && <span class="season-missing-count">{missingLabel}</span>
        )}
        <span class={row.platform === "youtube" ? "badge-youtube" : "badge-dropout"}>
          {row.platform === "youtube" ? "YouTube" : "Dropout.tv"}
        </span>
      </div>
    </a>
  );
}
