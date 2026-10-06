import { useMutation, useQuery, useQueryClient } from "@tanstack/preact-query";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { ApiError, apiClient, refreshJobRequest } from "../api";
import { logoutAndClear } from "../auth";
import { ConfirmModal } from "../components/ConfirmModal";
import { Header } from "../components/Header";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { Poster, posterLetter } from "../components/Poster";
import { RefreshSplit } from "../components/RefreshSplit";
import { SeriesListSkeleton, Skeleton } from "../components/Skeleton";
import { pushToast } from "../components/Toast";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { useDismiss } from "../hooks/useDismiss";
import { useJobs } from "../hooks/useJobs";
import { useOnline } from "../hooks/useOnline";
import { go } from "../nav";
import { queryKeys } from "../queryKeys";
import { formatRelativeTime, newestRefreshIso } from "../relativeTime";
import type { SeriesPlatform, SeriesSummary } from "../seriesView";
import {
  countLabel,
  emptyListMessage,
  filterSeries,
  missingStatusClass,
  missingStatusText,
  seriesFreshness,
} from "../seriesView";
import { writeSearch } from "../urlState";

export function SeriesList() {
  const queryClient = useQueryClient();
  const online = useOnline();
  const jobsQuery = useJobs();
  const activeJob = jobsQuery.data?.active;
  const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [platform, setPlatform] = useState<SeriesPlatform | "all">(() => {
    const value = params.get("platform");
    return value === "youtube" || value === "dropout" ? value : "all";
  });
  const [modal, setModal] = useState(false);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SeriesSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const menuTriggerRef = useRef<HTMLElement | null>(null);
  const triggerRefs = useRef(new Map<string, HTMLButtonElement>());
  useDismiss(Boolean(menuOpen), () => setMenuOpen(null), ".overflow-menu", menuTriggerRef);
  const toggleMenu = (key: string, trigger?: HTMLButtonElement | null) => {
    if (trigger) menuTriggerRef.current = trigger;
    else if (menuOpen === key) menuTriggerRef.current = null;
    setMenuOpen((current) => (current === key ? null : key));
  };
  const closeMenuAndRefocus = () => {
    setMenuOpen(null);
    requestAnimationFrame(() => menuTriggerRef.current?.focus());
  };

  const listQuery = useQuery({
    queryKey: queryKeys.seriesList(),
    queryFn: () => apiClient.listSeries(),
    staleTime: 60 * 1000,
  });
  const rows = listQuery.data?.series ?? [];
  const platforms = [...new Set(rows.map((row) => row.platform))];
  const importErrors = listQuery.data?.import_errors ?? [];
  const needMissing = useMemo(
    () => rows.filter((row) => row.platform === "dropout" && row.missing_count == null),
    [rows],
  );
  const missingKeys = needMissing.map((row) => `${row.platform}|${row.slug}`);
  const missingBatch = useQuery({
    queryKey: queryKeys.missingBatch(missingKeys),
    queryFn: () =>
      apiClient.getSeriesMissingBatch(
        needMissing.map((row) => ({ platform: row.platform, slug: row.slug })),
      ),
    enabled: needMissing.length > 0,
    staleTime: 30 * 1000,
  });

  const configQuery = useQuery({
    queryKey: queryKeys.config(),
    queryFn: () => apiClient.getConfig(),
    staleTime: 0,
  });
  const youtubePlatformQuery = useQuery({
    queryKey: queryKeys.platform("youtube"),
    queryFn: () => apiClient.getPlatform("youtube"),
    enabled: platforms.includes("youtube"),
    staleTime: 0,
  });
  const dropoutPlatformQuery = useQuery({
    queryKey: queryKeys.platform("dropout"),
    queryFn: () => apiClient.getPlatform("dropout"),
    enabled: platforms.includes("dropout"),
    staleTime: 0,
  });
  const platformPathsLoading =
    (platforms.includes("youtube") && youtubePlatformQuery.isFetching) ||
    (platforms.includes("dropout") && dropoutPlatformQuery.isFetching);
  const platformPaths = {
    youtube: youtubePlatformQuery.data?.paths,
    dropout: dropoutPlatformQuery.data?.paths,
  };
  const cookiesQuery = useQuery({
    queryKey: queryKeys.cookies(),
    queryFn: () => apiClient.getCookies(),
    staleTime: 0,
  });
  const planQuery = useQuery({
    queryKey: queryKeys.plan(),
    queryFn: async () => {
      try {
        return await apiClient.getPlan();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    staleTime: 5_000,
  });

  const listError = listQuery.error instanceof Error ? listQuery.error.message : null;
  const listLoading = Boolean(listQuery.isPending && !listQuery.data);

  useEffect(() => {
    writeSearch({
      q: query.trim() || null,
      platform: platform === "all" ? null : platform,
    });
  }, [query, platform]);

  const filtered = filterSeries(rows, { query, platform });
  const sonarrItems = filtered
    .filter((row) => row.platform === "dropout" && row.tvdb_id != null)
    .map(({ platform, slug }) => ({ platform, slug }));
  const listingsPending = filtered.some(
    (row) => row.platform === "dropout" && row.listings_complete === false,
  );
  const lastRefresh = formatRelativeTime(newestRefreshIso(filtered));

  const refreshMut = useMutation({
    mutationFn: (items: { platform: SeriesPlatform; slug: string }[]) =>
      apiClient.startJob(refreshJobRequest(items)),
    onMutate: () => {
      setActionError(null);
    },
    onError: (err) => {
      const message = err instanceof ApiError ? err.message : "Refresh failed";
      setActionError(message);
      pushToast(message, "alert");
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.jobs() }),
  });
  const refreshItems = (items: { platform: SeriesPlatform; slug: string }[]) => {
    if (!items.length || refreshMut.isPending || activeJob) return;
    refreshMut.mutate(items);
  };
  const refreshInProgress = refreshMut.isPending || Boolean(activeJob);
  const activeTargets = activeJob?.kind === "refresh" ? (activeJob.progress?.target ?? "") : "";

  const deleteMut = useMutation({
    mutationFn: (row: SeriesSummary) => apiClient.deleteSeries(row.platform, row.slug),
    onSuccess: async (_void, row) => {
      setPendingDelete(null);
      pushToast(`Deleted ${row.name}`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.plan() });
    },
    onError: (err) => {
      setActionError(err instanceof ApiError ? err.message : "Delete failed");
    },
  });

  const onCreate = async (body: {
    name: string;
    platform: import("../api").Source;
    path: string;
    tvdb_id: number | null;
  }) => {
    const detail = await apiClient.createSeries(body);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.plan() }),
    ]);
    setModal(false);
    pushToast(`Created ${detail.name}`);
    go(`/series/${detail.platform}/${encodeURIComponent(detail.slug)}`);
  };

  return (
    <>
      <Header current="series" onLogout={() => void logoutAndClear()} />
      <div class="series-shell">
        <main class="card series-card" id="main">
          {!online && (
            <div class="banner banner-warn" role="status">
              You appear offline.
            </div>
          )}
          <OnboardingChecklist
            config={
              configQuery.isFetching || platformPathsLoading
                ? undefined
                : (configQuery.data ?? null)
            }
            cookies={cookiesQuery.isFetching ? undefined : (cookiesQuery.data ?? null)}
            seriesCount={listQuery.isPending ? undefined : rows.length}
            planReady={planQuery.data != null}
            platformPaths={platformPaths}
            platforms={platforms}
            platformPathsLoading={platformPathsLoading}
          />
          <div class="series-toolbar">
            <div>
              <h1 class="settings-title">Shows</h1>
              {lastRefresh && <p class="refresh-stamps">Last refresh {lastRefresh}</p>}
            </div>
            <div class="series-toolbar-end">
              <RefreshSplit
                disabled={refreshInProgress || !filtered.length}
                busy={refreshInProgress}
                title={
                  refreshInProgress
                    ? "Refresh already running"
                    : !filtered.length
                      ? "No shows to refresh"
                      : undefined
                }
                onRefresh={() =>
                  void refreshItems(filtered.map(({ platform, slug }) => ({ platform, slug })))
                }
                onSonarrCheck={
                  sonarrItems.length
                    ? () => {
                        if (activeJob) return;
                        void apiClient
                          .startJob({ kind: "check", items: sonarrItems })
                          .then(() => queryClient.invalidateQueries({ queryKey: queryKeys.jobs() }))
                          .catch((err) =>
                            setActionError(
                              err instanceof Error ? err.message : "Sonarr check failed to start",
                            ),
                          );
                      }
                    : undefined
                }
              />
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
              <span class="sr-only">Search shows</span>
              <input
                type="search"
                placeholder="Search shows"
                value={query}
                onInput={(e) => setQuery((e.currentTarget as HTMLInputElement).value)}
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
                {chip === "all" ? "All" : chip === "youtube" ? "YouTube" : "Dropout"}
              </button>
            ))}
          </div>
          {listError && (
            <div class="error-card" role="alert">
              <p>{listError}</p>
              <button type="button" class="btn-secondary" onClick={() => void listQuery.refetch()}>
                Retry
              </button>
            </div>
          )}
          {actionError && (
            <div class="validation-error" role="alert">
              {actionError}
            </div>
          )}
          {importErrors.length > 0 && (
            <div class="banner banner-warn" role="status">
              <strong>
                Couldn't load{" "}
                {importErrors.length === 1 ? "a show file" : `${importErrors.length} show files`}
              </strong>
              <ul class="banner-list">
                {importErrors.map((item) => (
                  <li key={`${item.file}:${item.error}`}>
                    {item.file}: {item.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {listLoading ? (
            <SeriesListSkeleton />
          ) : !filtered.length ? (
            <div class="empty-state">
              <p>{emptyListMessage(rows.length, filtered.length, { query, platform })}</p>
              {(query.trim() || platform !== "all") && (
                <button
                  type="button"
                  class="btn-ghost"
                  onClick={() => {
                    setQuery("");
                    setPlatform("all");
                  }}
                >
                  Clear filters
                </button>
              )}
              {rows.length === 0 && (
                <button type="button" class="btn-primary" onClick={() => setModal(true)}>
                  Add show
                </button>
              )}
            </div>
          ) : (
            filtered.map((row) => (
              <SeriesRow
                key={`${row.platform}-${row.slug}`}
                row={row}
                missing={
                  row.missing_count ??
                  missingBatch.data?.[`${row.platform}|${row.slug}`]?.missing_count ??
                  null
                }
                missingLoading={
                  row.platform === "dropout" && row.missing_count == null && missingBatch.isPending
                }
                refreshing={Boolean(activeTargets.includes(`${row.platform}|${row.slug}`))}
                menuOpen={menuOpen === `${row.platform}-${row.slug}`}
                registerTrigger={(el) => {
                  const key = `${row.platform}-${row.slug}`;
                  if (el) triggerRefs.current.set(key, el);
                  else triggerRefs.current.delete(key);
                }}
                onToggleMenu={(trigger) => toggleMenu(`${row.platform}-${row.slug}`, trigger)}
                onCloseMenu={() => {
                  const key = `${row.platform}-${row.slug}`;
                  menuTriggerRef.current = triggerRefs.current.get(key) ?? null;
                  closeMenuAndRefocus();
                }}
                onRefresh={() => void refreshItems([{ platform: row.platform, slug: row.slug }])}
                onDelete={() => {
                  setActionError(null);
                  setPendingDelete(row);
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
        </main>
        {modal && (
          <CreateSeriesModal existing={rows} onClose={() => setModal(false)} onCreate={onCreate} />
        )}
        {pendingDelete && (
          // Destructive-action policy (Phase 6 decision): delete is confirm-only
          // (no type-to-confirm, no undo). Library files are never deleted.
          <ConfirmModal
            title={`Delete ${pendingDelete.name}?`}
            message="This removes the show from the config. Library files are not deleted."
            confirmLabel="Delete"
            danger
            pending={deleteMut.isPending}
            onCancel={() => setPendingDelete(null)}
            onConfirm={() => deleteMut.mutate(pendingDelete)}
          />
        )}
      </div>
    </>
  );
}

function SeriesRow({
  row,
  missing,
  missingLoading,
  refreshing,
  menuOpen,
  registerTrigger,
  onToggleMenu,
  onCloseMenu,
  onRefresh,
  onDelete,
}: {
  row: SeriesSummary;
  missing: number | null;
  missingLoading: boolean;
  refreshing: boolean;
  menuOpen: boolean;
  registerTrigger: (el: HTMLButtonElement | null) => void;
  onToggleMenu: (trigger: HTMLButtonElement | null) => void;
  onCloseMenu: () => void;
  onRefresh: () => void;
  onDelete: () => void | Promise<void>;
}) {
  const statusText =
    missing == null && row.platform === "dropout" ? "Unknown" : missingStatusText(missing);
  const statusClass = missingStatusClass(missing);
  const href = `/series/${row.platform}/${encodeURIComponent(row.slug)}`;

  return (
    <div
      class={`show-row${refreshing ? " is-disabled" : ""}`}
      data-testid={`series-row-${row.slug}`}
      aria-disabled={refreshing}
    >
      <a
        href={href}
        class="show-row-link"
        onClick={(event) => {
          if (refreshing) event.preventDefault();
        }}
      >
        <Poster src={row.poster_url} letter={posterLetter(row.name)} size="md" alt={row.name} />
        <div class="show-row-main">
          <div class="show-row-title">{row.name}</div>
          <div class="series-row-meta">
            <span>
              {row.platform === "youtube" ? "YouTube" : "Dropout"}
              {" · "}
              {countLabel(row.season_count, "season", "seasons")}
            </span>
            {row.path ? <span class="show-row-path">{row.path}</span> : null}
            {seriesFreshness(row) === "stale" && <span class="run-meta">Refresh required</span>}
            {seriesFreshness(row) === "unavailable" && (
              <span class="run-meta">Library unavailable{row.error ? `: ${row.error}` : ""}</span>
            )}
            {row.last_success_at && (
              <span class="run-meta">Last success {formatRelativeTime(row.last_success_at)}</span>
            )}
          </div>
        </div>
      </a>
      <div class="show-row-actions">
        {refreshing && (
          <span
            class="spinner"
            aria-hidden="true"
            role="status"
            aria-label={`Refreshing ${row.name}`}
          />
        )}
        {missingLoading ? (
          <Skeleton width="4rem" height="0.9em" />
        ) : (
          statusText && (
            <span class={`season-missing-count ${statusClass}`.trim()}>{statusText}</span>
          )
        )}
        <div class="overflow-menu">
          <button
            ref={(el) => registerTrigger(el)}
            type="button"
            class="btn-ghost overflow-trigger"
            aria-expanded={menuOpen}
            aria-haspopup="true"
            aria-label={`More actions for ${row.name}`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleMenu(e.currentTarget as HTMLButtonElement);
            }}
          >
            ⋯
          </button>
          {menuOpen && (
            <div class="overflow-panel">
              <button
                type="button"
                onClick={() => {
                  onCloseMenu();
                  go(href);
                }}
              >
                Edit
              </button>
              <button
                type="button"
                disabled={refreshing}
                onClick={() => {
                  onCloseMenu();
                  onRefresh();
                }}
              >
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
              <button
                type="button"
                class="is-danger"
                onClick={() => {
                  onCloseMenu();
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
