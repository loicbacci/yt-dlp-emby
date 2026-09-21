import { useIsRestoring, useMutation, useQuery, useQueryClient } from "@tanstack/preact-query";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { logoutAndClear } from "../auth";
import { ConfirmModal } from "../components/ConfirmModal";
import { Header } from "../components/Header";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { Poster, posterLetter } from "../components/Poster";
import { type RefreshPart, RefreshSplit } from "../components/RefreshSplit";
import { SeriesListSkeleton, Skeleton } from "../components/Skeleton";
import { pushToast } from "../components/Toast";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { useDismiss } from "../hooks/useDismiss";
import { useOnline } from "../hooks/useOnline";
import { go } from "../nav";
import { queryKeys } from "../queryKeys";
import { formatRelativeTime, newestRefreshIso } from "../relativeTime";
import { invalidateSeriesState } from "../seriesInvalidate";
import {
  beginRefresh,
  endRefresh,
  refreshSeriesKey,
  useAnyRefreshing,
} from "../seriesRefreshStore";
import type { SeriesPlatform, SeriesSummary } from "../seriesView";
import {
  countLabel,
  emptyListMessage,
  filterSeries,
  missingStatusClass,
  missingStatusText,
} from "../seriesView";
import { writeSearch } from "../urlState";

export function SeriesList() {
  const restoring = useIsRestoring();
  const queryClient = useQueryClient();
  const online = useOnline();
  const refreshingKeys = useAnyRefreshing();
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
    staleTime: 60 * 1000,
  });
  const cookiesQuery = useQuery({
    queryKey: queryKeys.cookies(),
    queryFn: () => apiClient.getCookies(),
    staleTime: 60 * 1000,
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
  const listLoading = Boolean(
    (listQuery.isPending && !listQuery.data) || (restoring && !listQuery.data),
  );

  useEffect(() => {
    writeSearch({
      q: query.trim() || null,
      platform: platform === "all" ? null : platform,
    });
  }, [query, platform]);

  const filtered = filterSeries(rows, { query, platform });
  const listingsPending = filtered.some(
    (row) => row.platform === "dropout" && row.listings_complete === false,
  );
  const lastRefresh = formatRelativeTime(newestRefreshIso(filtered));
  const allRefreshing =
    filtered.length > 0 &&
    filtered.every((row) => refreshingKeys.includes(refreshSeriesKey(row.platform, row.slug)));

  type RefreshItemsArg = {
    items: { platform: SeriesPlatform; slug: string; tvdb_id?: number | null }[];
    part?: RefreshPart;
  };
  const refreshMut = useMutation({
    mutationFn: ({ items, part = "all" }: RefreshItemsArg) =>
      apiClient.refreshSeries(
        items.map((item) => ({ platform: item.platform, slug: item.slug })),
        part === "all" ? undefined : [part],
      ),
    onMutate: async ({ items }: RefreshItemsArg) => {
      const keys = items.map((item) => refreshSeriesKey(item.platform, item.slug));
      await queryClient.cancelQueries({ queryKey: queryKeys.seriesList() });
      const prevList = queryClient.getQueryData(queryKeys.seriesList());
      beginRefresh(keys);
      setActionError(null);
      return { prevList, keys, items };
    },
    onError: (err, _arg, ctx) => {
      if (ctx?.prevList) queryClient.setQueryData(queryKeys.seriesList(), ctx.prevList);
      const message = err instanceof ApiError ? err.message : "Refresh failed";
      setActionError(message);
      pushToast(message, "alert");
    },
    onSuccess: (body) => {
      const failed = body.results.filter((row) => row.error);
      if (failed.length) {
        const message = failed.map((row) => `${row.slug}: ${row.error}`).join("; ");
        setActionError(message);
        pushToast(message, "alert");
      } else {
        pushToast("Refresh complete");
      }
    },
    onSettled: (_body, _err, arg, ctx) => {
      endRefresh(ctx?.keys ?? []);
      void invalidateSeriesState(queryClient, arg?.items ?? ctx?.items ?? []);
    },
  });
  const refreshItems = (
    items: { platform: SeriesPlatform; slug: string; tvdb_id?: number | null }[],
    part: RefreshPart = "all",
  ) => {
    if (!items.length || refreshMut.isPending) return;
    refreshMut.mutate({ items, part });
  };

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
            config={configQuery.isPending ? undefined : (configQuery.data ?? null)}
            cookies={cookiesQuery.isPending ? undefined : (cookiesQuery.data ?? null)}
            seriesCount={listQuery.isPending ? undefined : rows.length}
            planReady={planQuery.data != null}
          />
          <div class="series-toolbar">
            <div>
              <h1 class="settings-title">Shows</h1>
              {lastRefresh && <p class="refresh-stamps">Last refresh {lastRefresh}</p>}
            </div>
            <div class="series-toolbar-end">
              <RefreshSplit
                disabled={allRefreshing || !filtered.length}
                busy={allRefreshing}
                showSonarr={filtered.some((row) => row.tvdb_id != null)}
                title={
                  allRefreshing
                    ? "Refresh already running"
                    : !filtered.length
                      ? "No shows to refresh"
                      : undefined
                }
                onRefresh={(part) => void refreshItems(filtered, part)}
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
              <p>{emptyListMessage(rows.length, filtered.length)}</p>
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
                  row.platform === "dropout" &&
                  row.missing_count == null &&
                  (missingBatch.isPending || restoring)
                }
                refreshing={refreshingKeys.includes(refreshSeriesKey(row.platform, row.slug))}
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
                onRefresh={() =>
                  void refreshItems([
                    {
                      platform: row.platform,
                      slug: row.slug,
                      tvdb_id: row.tvdb_id,
                    },
                  ])
                }
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
  const statusText = missingStatusText(missing);
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
