// Accepted deviation: Dashboard stays single-file. Run-event, selection, and
// fold state live in useRunEvents/useQueueSelection hooks (extracted, no
// behavior change); splitting the page component itself was skipped as churn.
import { useMutation, useQuery, useQueryClient } from "@tanstack/preact-query";
import { memo } from "preact/compat";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { ApiError, type Run, apiClient, runKeyFor } from "../api";
import { logoutAndClear } from "../auth";
import { ConfirmModal } from "../components/ConfirmModal";
import { Header } from "../components/Header";
import { LogViewer } from "../components/LogViewer";
import { OnboardingChecklist, pathsUnset } from "../components/OnboardingChecklist";
import { Poster, posterLetter } from "../components/Poster";
import { QueueSkeleton } from "../components/Skeleton";
import { pushToast, useDocumentTitle } from "../components/Toast";
import { useDismiss } from "../hooks/useDismiss";
import { useOnline } from "../hooks/useOnline";
import { useExpandedSeasons, useQueueSelection } from "../hooks/useQueueSelection";
import { useRunEvents } from "../hooks/useRunEvents";
import { queryKeys } from "../queryKeys";
import { formatRelativeTime } from "../relativeTime";
import {
  type QueueSeason,
  type QueueSeries,
  actionLabel,
  actionsForIds,
  applyProgress,
  buildTree,
  countChipText,
  emptyProgress,
  episodeForId,
  formatBinaryBytes,
  formatEta,
  formatItemSize,
  formatProgressStats,
  heroFrom,
  isDownloadHeavy,
  mergeProgress,
  needsConfirm,
  overlayProgress,
  pendingIds,
  platformLabel,
  queueHeading,
  remainingEpisodes,
  runLabel,
  runStatsLine,
  searchOpen,
  seriesInActiveDownload,
  triState,
  upToDateSeries,
  visibleSeries,
} from "../runQueue";
import { invalidateAfterQueueRebuild } from "../seriesInvalidate";
import { indexSeriesPosters, seriesPosterUrl, shortUrl } from "../seriesView";
import { writeSearch } from "../urlState";
import { idleRun, useAppRun, usePlan } from "../useAppQueries";

export function Dashboard() {
  const queryClient = useQueryClient();
  const online = useOnline();
  const runQuery = useAppRun();
  const planQuery = usePlan();
  const run = runQuery.data ?? idleRun;
  const runKey = runKeyFor(run);
  const plan = planQuery.data ?? null;
  const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [force, setForce] = useState(params.get("force") === "1");
  const [createFolders, setCreateFolders] = useState(params.get("create") === "1");
  const [showForce, setShowForce] = useState(false);
  const forceToggleRef = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopOpen, setStopOpen] = useState(false);
  const [notifyOptIn, setNotifyOptIn] = useState(false);
  const selection = useQueueSelection(params.get("sel"));
  const expanded = useExpandedSeasons(params.get("open"), params.get("seasons"));
  const [pendingDownload, setPendingDownload] = useState<{
    count: number;
    ids: string[] | null;
    actions: string[];
  } | null>(null);
  const [activeDownloadIds, setActiveDownloadIds] = useState<Set<string> | null>(null);

  const tree = useMemo(() => (plan ? buildTree(plan) : []), [plan]);
  const treeRef = useRef(tree);
  treeRef.current = tree;
  const events = useRunEvents(runKey, treeRef, online);
  const { progress, listingSeries, eventsReconnecting } = events;
  useDismiss(
    showForce,
    () => setShowForce(false),
    ".queue-refresh",
    forceToggleRef as unknown as import("preact").RefObject<HTMLElement | null>,
  );
  const displayTree = useMemo(() => overlayProgress(tree, progress), [tree, progress]);
  const busy = run.status === "running" || run.status === "stopping";
  const planning = run.phase === "planning";
  const downloading = run.phase === "downloading";
  const visible = useMemo(() => {
    const rows = visibleSeries(displayTree, query);
    if (!downloading || !activeDownloadIds) return rows;
    return rows.filter((series) => seriesInActiveDownload(series, activeDownloadIds));
  }, [displayTree, query, downloading, activeDownloadIds]);
  const upToDate = useMemo(() => {
    if (downloading) return [];
    return upToDateSeries(displayTree, query);
  }, [displayTree, query, downloading]);
  const allPending = useMemo(() => pendingIds(tree), [tree]);
  const effective = useMemo(
    () => selection.effective(allPending),
    [selection.selected, selection.touched, allPending],
  );

  const applyRun = (next: Run) => {
    queryClient.setQueryData(queryKeys.run(), next);
  };

  useEffect(() => {
    // Deep-link query/flags plus selection and open folds. Episode ids are
    // `platform|slug|code` (comma-safe); over-long values are dropped rather
    // than persisted so shared URLs stay usable. openUpcoming stays local
    // (ephemeral downloading-only folds).
    const capped = (ids: string[]): string | null => {
      if (!ids.length) return null;
      const joined = ids.join(",");
      return joined.length > 1800 ? null : joined;
    };
    writeSearch({
      q: query.trim() || null,
      force: force ? "1" : null,
      create: createFolders ? "1" : null,
      sel: !selection.touched
        ? null
        : selection.selected.size === 0
          ? "none"
          : capped([...selection.selected]),
      open: capped([...expanded.openSeries]),
      seasons: capped([...expanded.openSeasons]),
    });
  }, [
    query,
    force,
    createFolders,
    selection.selected,
    selection.touched,
    expanded.openSeries,
    expanded.openSeasons,
  ]);

  useEffect(() => {
    if (planQuery.data?.force) setForce(true);
  }, [planQuery.data?.force]);

  useEffect(() => {
    if (!runQuery.data?.progress || typeof runQuery.data.progress.event !== "string") return;
    const ev = runQuery.data.progress;
    if (ev.event === "series" && "name" in ev && typeof ev.name === "string") {
      events.setListingSeries(ev.name);
    }
    if (ev.event === "item_steps" || ev.event === "progress" || ev.event === "item_done") {
      const { progress: patch } = applyProgress(treeRef.current, ev);
      events.setProgress((current) => mergeProgress(current, patch));
    }
  }, [runQuery.dataUpdatedAt]);

  useEffect(() => {
    if (downloading && progress.currentId) {
      for (const series of displayTree) {
        for (const season of series.seasons) {
          for (const ep of season.pending) {
            if (ep.id === progress.currentId) {
              expanded.setOpenSeries((s) => new Set(s).add(series.key));
              expanded.setOpenUpcoming((s) => new Set(s).add(series.key));
              expanded.setOpenSeasons(new Set([season.key]));
            }
          }
        }
      }
    }
  }, [downloading, progress.currentId, displayTree]);

  const didOpenDefault = useRef(false);
  useEffect(() => {
    if (didOpenDefault.current || downloading || !visible.length) return;
    const first = visible.find((series) => series.seasons.length > 0);
    const firstSeason = first?.seasons[0];
    if (!first || !firstSeason) return;
    didOpenDefault.current = true;
    expanded.setOpenSeries(new Set([first.key]));
    expanded.setOpenSeasons(new Set([firstSeason.key]));
  }, [visible, downloading]);

  const startPlanMut = useMutation({
    mutationFn: () => apiClient.startPlan(force, createFolders),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: queryKeys.run() });
      const prev = queryClient.getQueryData<Run>(queryKeys.run());
      applyRun({ ...(prev ?? idleRun), status: "running", phase: "planning" });
      return { prev };
    },
    onError: (err, _v, ctx) => {
      if (ctx?.prev) applyRun(ctx.prev);
      setError(err instanceof ApiError ? err.message : "Refresh failed");
      pushToast(err instanceof Error ? err.message : "Refresh failed", "alert");
    },
    onSuccess: (next) => applyRun(next),
  });

  const startDownloadMut = useMutation({
    mutationFn: ({ ids }: { ids: string[] | null; count: number }) =>
      apiClient.startDownload({ ids, force, create: createFolders }),
    onMutate: async ({ ids, count }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.run() });
      const prev = queryClient.getQueryData<Run>(queryKeys.run());
      events.setProgress(emptyProgress());
      setActiveDownloadIds(new Set(ids ?? allPending));
      applyRun({ ...(prev ?? idleRun), status: "running", phase: "downloading" });
      return { prev, count };
    },
    onError: (err, _v, ctx) => {
      if (ctx?.prev) applyRun(ctx.prev);
      setActiveDownloadIds(null);
      setError(err instanceof ApiError ? err.message : "Download failed");
      pushToast(err instanceof Error ? err.message : "Download failed", "alert");
    },
    onSuccess: (next) => applyRun(next),
  });

  const stopMut = useMutation({
    mutationFn: () => apiClient.stopRun(),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: queryKeys.run() });
      const prev = queryClient.getQueryData<Run>(queryKeys.run());
      applyRun({ ...(prev ?? idleRun), status: "stopping", phase: "stopping" });
      return { prev };
    },
    onError: (err, _v, ctx) => {
      if (ctx?.prev) applyRun(ctx.prev);
      pushToast(err instanceof Error ? err.message : "Stop failed", "alert");
      setError(err instanceof Error ? err.message : "Stop failed");
    },
    onSuccess: (next) => {
      applyRun(next);
      setStopOpen(false);
      pushToast("Stopping…");
    },
  });

  const onDownload = () => {
    if (!plan) {
      setError("Refresh the queue first");
      return;
    }
    const count = effective.length;
    const ids = selection.selected.size === 0 && !selection.touched ? null : effective;
    if (needsConfirm(count)) {
      setPendingDownload({ count, ids, actions: runActions });
      return;
    }
    startDownloadMut.mutate({ ids, count });
  };

  useEffect(() => {
    if (run.status === "exited") {
      setActiveDownloadIds(null);
      void invalidateAfterQueueRebuild(queryClient);
      if (run.exit_code === 0) {
        pushToast("Download done");
        if (notifyOptIn && "Notification" in window && Notification.permission === "granted") {
          new Notification("Download done");
        }
      }
    }
  }, [run.status, run.finished_at, queryClient, notifyOptIn]);

  const runActions = useMemo(() => actionsForIds(effective, tree), [effective, tree]);
  const allActions = useMemo(() => actionsForIds(allPending, tree), [allPending, tree]);
  const downloadCount = effective.length;
  const primaryLabel = runLabel(downloadCount, runActions);
  const hero = heroFrom(run, displayTree, progress, listingSeries, allPending.length);
  const hasManifest = plan !== null;
  // No silent disables: the primary button always explains why it is disabled.
  const primaryReason = busy
    ? "Blocked while a run is in progress"
    : planning
      ? "Wait for the queue to finish listing"
      : !hasManifest
        ? "Refresh the queue first"
        : downloadCount === 0
          ? "Select at least one episode"
          : startDownloadMut.isPending
            ? "Starting…"
            : undefined;
  const remaining = Math.max(0, allPending.length - progress.doneIds.size);
  const statsLine = runStatsLine(run, progress, downloading ? remaining : allPending.length);
  const idleMeta = [
    plan?.generated_at ? `Queue refreshed ${formatRelativeTime(plan.generated_at)}` : null,
    eventsReconnecting ? "Reconnecting live events…" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const heroSub = planning || run.phase === "stopping" ? hero.sub : idleMeta;
  const progressStats = downloading ? formatProgressStats(progress) : null;
  const posterQuery = useQuery({
    queryKey: queryKeys.seriesList(),
    queryFn: () => apiClient.listSeries(),
    staleTime: 60_000,
  });
  const posterMap = useMemo(
    () => indexSeriesPosters(posterQuery.data?.series ?? []),
    [posterQuery.data],
  );
  const configQuery = useQuery({
    queryKey: queryKeys.config(),
    queryFn: () => apiClient.getConfig(),
    staleTime: 60_000,
  });
  const cookiesQuery = useQuery({
    queryKey: queryKeys.cookies(),
    queryFn: () => apiClient.getCookies(),
    staleTime: 60_000,
  });
  const setupPathsMissing = !configQuery.isPending && pathsUnset(configQuery.data ?? null);
  const nowHit = progress.currentId ? episodeForId(displayTree, progress.currentId) : null;
  const nowPoster = nowHit
    ? seriesPosterUrl(posterMap, nowHit.series.platform, nowHit.series.slug, nowHit.series.name)
    : null;
  const localDetail =
    progress.total != null && progress.total > 0
      ? `${formatBinaryBytes(progress.bytes ?? 0)} of ${formatBinaryBytes(progress.total)}${
          progress.speed != null && Number.isFinite(progress.speed)
            ? ` · ${formatBinaryBytes(progress.speed)}/s`
            : ""
        }${progress.eta != null ? ` · ETA ${formatEta(progress.eta)}` : ""}`
      : progressStats;
  const pageTitle = downloading
    ? `Downloading ${progress.doneIds.size}/${Math.max(allPending.length, progress.doneIds.size)}`
    : run.status === "exited" && run.exit_code === 0
      ? "Done"
      : "yt-dlp-emby";
  useDocumentTitle(pageTitle);

  const expandedSeasons = useMemo(() => {
    const keys = new Set(expanded.openSeasons);
    const q = query.trim();
    if (q) {
      for (const series of visible) {
        for (const season of series.seasons) {
          if (searchOpen(q, series, season)) keys.add(season.key);
        }
      }
    }
    if (downloading && progress.currentId) {
      for (const series of displayTree) {
        for (const season of series.seasons) {
          if (season.pending.some((ep) => ep.id === progress.currentId)) {
            keys.add(season.key);
          }
        }
      }
    }
    return keys;
  }, [query, visible, expanded.openSeasons, downloading, progress.currentId, displayTree]);

  const expandedUpcoming = useMemo(() => {
    const keys = new Set(expanded.openUpcoming);
    const q = query.trim();
    if (q) {
      for (const series of visible) {
        if (series.seasons.some((season) => searchOpen(q, series, season))) {
          keys.add(series.key);
        }
      }
    }
    if (downloading && progress.currentId) {
      for (const series of displayTree) {
        if (
          series.seasons.some((season) => season.pending.some((ep) => ep.id === progress.currentId))
        ) {
          keys.add(series.key);
        }
      }
    }
    return keys;
  }, [expanded.openUpcoming, query, visible, downloading, progress.currentId, displayTree]);

  const planError =
    planQuery.error instanceof ApiError && planQuery.error.status !== 404
      ? planQuery.error.message
      : runQuery.error instanceof Error
        ? runQuery.error.message
        : null;

  const searchMiss =
    Boolean(query.trim()) && visible.length === 0 && upToDate.length === 0 && hasManifest;

  return (
    <>
      <Header current="dashboard" onLogout={() => void logoutAndClear()} />
      <div class="run-shell">
        <main class="run-main" id="main">
          {!online && (
            <div class="banner banner-warn" role="status">
              You appear offline. Polling and live events are paused.
            </div>
          )}
          <OnboardingChecklist
            config={configQuery.isPending ? undefined : (configQuery.data ?? null)}
            cookies={cookiesQuery.isPending ? undefined : (cookiesQuery.data ?? null)}
            seriesCount={posterQuery.isPending ? undefined : (posterQuery.data?.series.length ?? 0)}
            planReady={plan !== null}
          />
          {setupPathsMissing && (
            <p class="run-hint" role="status">
              Set library paths in <a href="/settings">Settings</a> before refreshing.
            </p>
          )}
          {(error || planError) && (
            <div class="error-card" role="alert">
              <p>{error ?? planError}</p>
              <p class="settings-hint">
                Cookie or Sonarr failures? Check <a href="/settings">Settings</a>.
              </p>
              <button
                type="button"
                class="btn-secondary"
                onClick={() => {
                  setError(null);
                  void runQuery.refetch();
                  void planQuery.refetch();
                }}
              >
                Retry
              </button>
            </div>
          )}
          {planQuery.isPending && !plan ? (
            <QueueSkeleton />
          ) : (
            <>
              {!hasManifest && !busy && (
                <p class="run-hint">
                  No queue yet. Add series under <a href="/series">Shows</a>, then Refresh queue.
                </p>
              )}
              {downloading && nowHit ? (
                <section class="download-now" data-testid="download-now">
                  <Poster
                    src={nowPoster}
                    letter={posterLetter(nowHit.series.name)}
                    size="now"
                    alt={nowHit.series.name}
                  />
                  <div class="download-now-copy">
                    <p class="download-kicker">
                      {!nowHit || isDownloadHeavy([nowHit.ep.action])
                        ? "Downloading now"
                        : `${actionLabel(nowHit.ep.action)} now`}
                    </p>
                    <h1>{nowHit.series.name}</h1>
                    <h2>{nowHit.ep.title}</h2>
                    <div class="progress-row">
                      <span>{progress.phase ?? "Working…"}</span>
                      <span>{localDetail}</span>
                    </div>
                    <div
                      class={`progress-track${progress.percent == null ? " is-indeterminate" : ""}`}
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progress.percent ?? undefined}
                      aria-valuetext={
                        progress.percent == null
                          ? "In progress"
                          : `${Math.round(progress.percent)}%`
                      }
                    >
                      <div
                        class="progress-fill"
                        style={
                          progress.percent != null ? { width: `${progress.percent}%` } : undefined
                        }
                      />
                    </div>
                    {progress.steps.length > 0 && (
                      <ol class="step-chips">
                        {progress.steps.map((label, index) => (
                          <li
                            key={label}
                            data-testid={`step-chip-${label}`}
                            aria-current={progress.step === index ? "step" : undefined}
                            class={
                              progress.step != null && index < progress.step
                                ? "is-done"
                                : progress.step === index
                                  ? "is-current"
                                  : undefined
                            }
                          >
                            {label}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                </section>
              ) : (
                <section class="dl-hero">
                  <div>
                    <h1>
                      {planning || run.phase === "stopping"
                        ? hero.heading
                        : queueHeading(allPending.length, allActions)}
                    </h1>
                    {heroSub ? <p class="run-hero-sub">{heroSub}</p> : null}
                  </div>
                </section>
              )}
              {downloading && (
                <section class="run-stats" aria-live="polite" aria-label="Run status">
                  {statsLine}
                </section>
              )}
              {downloading && <h3 class="queue-label">Queue · {remaining} remaining</h3>}
              <div class="run-toolbar">
                <label class="sr-only" for="queue-search">
                  Search queue
                </label>
                <input
                  id="queue-search"
                  class="run-search"
                  type="search"
                  placeholder="Search queue…"
                  value={query}
                  onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
                />
                {!downloading && (
                  <div class="refresh-split queue-refresh">
                    <button
                      type="button"
                      class="btn-secondary"
                      disabled={busy || startPlanMut.isPending || setupPathsMissing}
                      title={setupPathsMissing ? "Set library paths in Settings first" : undefined}
                      onClick={() => {
                        setError(null);
                        events.setListingSeries(null);
                        startPlanMut.mutate();
                      }}
                    >
                      Refresh queue
                    </button>
                    <button
                      ref={forceToggleRef}
                      type="button"
                      class="btn-secondary refresh-split-toggle"
                      disabled={busy}
                      aria-expanded={showForce}
                      aria-haspopup="true"
                      aria-label="Force options"
                      title="Force options"
                      onClick={() => setShowForce((v) => !v)}
                    >
                      ▾
                    </button>
                    {showForce && (
                      <div class="overflow-panel refresh-split-menu force-menu" role="group">
                        <label>
                          <input
                            type="checkbox"
                            checked={force}
                            onChange={(e) => setForce((e.target as HTMLInputElement).checked)}
                            disabled={busy}
                          />
                          Re-download files already on disk
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={createFolders}
                            onChange={(e) =>
                              setCreateFolders((e.target as HTMLInputElement).checked)
                            }
                            disabled={busy}
                          />
                          Create missing folders
                        </label>
                      </div>
                    )}
                  </div>
                )}
              </div>
              {searchMiss && <p class="empty-state">No queue items match “{query.trim()}”.</p>}
              <section class="run-tree">
                {planning && (
                  <p class="run-hint">Building the download queue — listing each series…</p>
                )}
                {hasManifest && !busy && visible.length === 0 && upToDate.length > 0 && (
                  <p class="run-hint">Everything in the queue is already on disk.</p>
                )}
                {visible.map((series) => (
                  <SeriesRow
                    key={series.key}
                    series={series}
                    posterUrl={seriesPosterUrl(
                      posterMap,
                      series.platform,
                      series.slug,
                      series.name,
                    )}
                    open={expanded.openSeries.has(series.key) || Boolean(query.trim())}
                    openSeasons={expandedSeasons}
                    upcomingOpen={expandedUpcoming.has(series.key)}
                    selected={selection.selected}
                    busy={busy}
                    downloading={downloading}
                    listing={planning && listingSeries === series.name}
                    currentId={progress.currentId}
                    onToggleOpen={() => expanded.toggleSeries(series.key)}
                    onToggleSeries={(checked) =>
                      selection.apply(
                        series.seasons.flatMap((s) => s.pending.map((e) => e.id)),
                        checked,
                      )
                    }
                    onToggleSeason={(season, checked) =>
                      selection.apply(
                        season.pending.map((e) => e.id),
                        checked,
                      )
                    }
                    onToggleEpisode={(id, checked) => selection.apply([id], checked)}
                    onToggleSeasonOpen={(key) => expanded.toggleSeason(key)}
                    onToggleUpcoming={(open) => expanded.toggleUpcoming(series.key, open)}
                  />
                ))}
                {upToDate.length > 0 && (
                  <details class="fold-card disclosure">
                    <summary>
                      <span class="count-chip is-ok">Already in library ({upToDate.length})</span>
                    </summary>
                    <ul>
                      {upToDate.map((s) => (
                        <li key={s.key}>
                          <a href={`/series/${s.platform}/${encodeURIComponent(s.slug)}`}>
                            {s.name}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            </>
          )}
          <details class="run-log-details">
            <summary>Details · technical log</summary>
            <LogViewer runKey={runKey} compact />
          </details>
        </main>
        <footer class="run-bar">
          <div class="run-bar-inner">
            <div class="run-bar-start">
              <span>
                {planning
                  ? "Listing…"
                  : downloading || run.phase === "stopping"
                    ? `${remaining} remaining`
                    : selection.touched
                      ? `${downloadCount} of ${allPending.length} pending`
                      : `${downloadCount} pending`}
              </span>
              {selection.touched && !busy && (
                <button type="button" class="btn-ghost" onClick={selection.clear}>
                  Clear
                </button>
              )}
              {"Notification" in window && (
                <label class="run-bar-notify">
                  <input
                    type="checkbox"
                    checked={notifyOptIn}
                    onChange={(e) => {
                      const on = (e.target as HTMLInputElement).checked;
                      setNotifyOptIn(on);
                      if (on && Notification.permission === "default") {
                        void Notification.requestPermission();
                      }
                    }}
                  />
                  Notify when done
                </label>
              )}
            </div>
            {busy ? (
              <button
                type="button"
                class="btn-danger"
                disabled={stopMut.isPending || run.phase === "stopping"}
                onClick={() => setStopOpen(true)}
              >
                {run.phase === "stopping" || stopMut.isPending ? "Stopping…" : "Stop"}
              </button>
            ) : (
              <button
                type="button"
                class="btn-primary"
                disabled={
                  planning || !hasManifest || downloadCount === 0 || startDownloadMut.isPending
                }
                title={primaryReason}
                onClick={onDownload}
              >
                {primaryLabel}
              </button>
            )}
          </div>
        </footer>
        {pendingDownload && (
          <ConfirmModal
            title={
              needsConfirm(pendingDownload.count)
                ? `Large download: 25+ episodes — ${runLabel(pendingDownload.count, pendingDownload.actions)}?`
                : `${runLabel(pendingDownload.count, pendingDownload.actions)}?`
            }
            message={
              isDownloadHeavy(pendingDownload.actions)
                ? "This starts a large download. You can stop it from the run bar."
                : "This applies the selected library changes. You can stop it from the run bar."
            }
            confirmLabel={runLabel(pendingDownload.count, pendingDownload.actions)}
            pending={startDownloadMut.isPending}
            onCancel={() => setPendingDownload(null)}
            onConfirm={() => {
              const { ids, count } = pendingDownload;
              setPendingDownload(null);
              startDownloadMut.mutate({ ids, count });
            }}
          />
        )}
        {stopOpen && (
          <ConfirmModal
            title="Stop this run?"
            message="In-progress work will halt after the current step."
            confirmLabel="Stop"
            danger
            pending={stopMut.isPending}
            onCancel={() => setStopOpen(false)}
            onConfirm={() => stopMut.mutate()}
          />
        )}
      </div>
    </>
  );
}

type SeriesRowProps = {
  series: QueueSeries;
  posterUrl?: string;
  open: boolean;
  openSeasons: Set<string>;
  upcomingOpen: boolean;
  selected: Set<string>;
  busy: boolean;
  downloading: boolean;
  listing: boolean;
  currentId: string | null;
  onToggleOpen: () => void;
  onToggleSeries: (checked: boolean) => void;
  onToggleSeason: (season: QueueSeason, checked: boolean) => void;
  onToggleEpisode: (id: string, checked: boolean) => void;
  onToggleSeasonOpen: (key: string) => void;
  onToggleUpcoming: (open: boolean) => void;
};

function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a === b) return true;
  if (a.size !== b.size) return false;
  for (const key of a) {
    if (!b.has(key)) return false;
  }
  return true;
}

function seasonFolderHint(season: QueueSeason): string | null {
  const title = (season.seasonTitle ?? season.folderLabel).trim();
  const folder = season.folderLabel.trim();
  if (!folder || folder.toLowerCase() === title.toLowerCase()) return null;
  return season.folderLabel;
}

function seriesRowEqual(prev: SeriesRowProps, next: SeriesRowProps): boolean {
  // Callbacks intentionally ignored: they derive from series data (compared by
  // identity, stabilized by overlayProgress) plus stable selection/expanded stores.
  return (
    prev.series === next.series &&
    prev.posterUrl === next.posterUrl &&
    prev.open === next.open &&
    prev.upcomingOpen === next.upcomingOpen &&
    prev.selected === next.selected &&
    prev.busy === next.busy &&
    prev.downloading === next.downloading &&
    prev.listing === next.listing &&
    prev.currentId === next.currentId &&
    setsEqual(prev.openSeasons, next.openSeasons)
  );
}

const SeriesRow = memo(function SeriesRow({
  series,
  posterUrl,
  open,
  openSeasons,
  selected,
  busy,
  downloading,
  listing,
  currentId,
  onToggleOpen,
  onToggleSeries,
  onToggleSeason,
  onToggleEpisode,
  onToggleSeasonOpen,
}: SeriesRowProps) {
  const childIds = series.seasons.flatMap((s) => s.pending.map((e) => e.id));
  const state = triState(selected, childIds);
  const hideDone = downloading;
  const upcoming = series.seasons
    .map((season) => ({
      season,
      remaining: remainingEpisodes(season, hideDone).filter((ep) => ep.id !== currentId),
    }))
    .filter((row) => row.remaining.length > 0);
  const upcomingCount = upcoming.reduce((n, row) => n + row.remaining.length, 0);
  const seriesActions = series.seasons.flatMap((season) => season.pending.map((ep) => ep.action));
  const seriesChip = countChipText(series.pendingCount, false, seriesActions);
  if (series.error) {
    return (
      <section class="fold-card">
        <span class="run-error">
          {series.name}: {series.error}
        </span>
      </section>
    );
  }
  if (downloading && upcomingCount === 0) return null;
  const detailHref = `/series/${series.platform}/${encodeURIComponent(series.slug)}`;
  return (
    <section class="fold-card">
      <div class="fold-head show-head">
        <span class="fold-check">
          {!downloading && childIds.length > 0 && (
            <input
              type="checkbox"
              class="run-check"
              checked={state === "all"}
              ref={(el) => {
                if (el) el.indeterminate = state === "some";
              }}
              onChange={(e) => onToggleSeries((e.target as HTMLInputElement).checked)}
              disabled={busy}
              aria-label={`Select all in ${series.name}`}
            />
          )}
        </span>
        <button
          type="button"
          class="fold-hit"
          aria-expanded={open}
          aria-label={`${open ? "Collapse" : "Expand"} ${series.name}`}
          onClick={onToggleOpen}
        />
        <Poster src={posterUrl} letter={posterLetter(series.name)} size="md" alt="" />
        <a href={detailHref} class="show-copy">
          <span class="show-name">{series.name}</span>
          <span class="show-meta">
            {listing
              ? "Listing…"
              : downloading
                ? `${upcomingCount} remaining · ${upcoming.length} ${upcoming.length === 1 ? "season" : "seasons"}`
                : `${seriesChip} · ${series.seasons.length} ${series.seasons.length === 1 ? "season" : "seasons"} · ${platformLabel(series.platform)}`}
          </span>
        </a>
        <span class={`twist${open ? " is-open" : ""}`} aria-hidden="true" />
      </div>
      {open && (
        <div class="season-stack">
          {upcoming.map(({ season, remaining }) => {
            const seasonOpen = openSeasons.has(season.key);
            const seasonIds = remaining.map((e) => e.id);
            const folderHint = seasonFolderHint(season);
            return (
              <section key={season.key} class="season-card">
                <div class="fold-head season-head">
                  <span class="fold-check">
                    {!downloading && seasonIds.length > 0 && (
                      <input
                        type="checkbox"
                        class="run-check"
                        checked={triState(selected, seasonIds) === "all"}
                        ref={(el) => {
                          if (el) {
                            el.indeterminate = triState(selected, seasonIds) === "some";
                          }
                        }}
                        onChange={(e) =>
                          onToggleSeason(season, (e.target as HTMLInputElement).checked)
                        }
                        disabled={busy}
                        aria-label={`Select ${season.folderLabel}`}
                      />
                    )}
                  </span>
                  <button
                    type="button"
                    class="fold-main"
                    aria-expanded={seasonOpen}
                    onClick={() => onToggleSeasonOpen(season.key)}
                  >
                    <span class="show-copy">
                      <span class="season-kicker">Season</span>
                      <span class="show-name">{season.seasonTitle ?? season.folderLabel}</span>
                      {folderHint && <span class="show-meta">{folderHint}</span>}
                    </span>
                    <span
                      class={`count-chip${
                        downloading
                          ? ""
                          : remaining.length === 0
                            ? " is-ok"
                            : isDownloadHeavy(remaining.map((ep) => ep.action))
                              ? " is-new"
                              : ""
                      }`}
                    >
                      {countChipText(
                        remaining.length,
                        downloading,
                        remaining.map((ep) => ep.action),
                      )}
                    </span>
                    <span class={`twist${seasonOpen ? " is-open" : ""}`} aria-hidden="true" />
                  </button>
                </div>
                {seasonOpen && (
                  <div class="season-eps">
                    {remaining.map((ep) => (
                      <label
                        key={ep.id}
                        class={
                          selected.has(ep.id) && !downloading
                            ? "ep-row is-on"
                            : ep.status === "failed"
                              ? "ep-row is-failed"
                              : "ep-row"
                        }
                      >
                        <span class="fold-check">
                          {!downloading && (
                            <input
                              type="checkbox"
                              class="run-check"
                              checked={selected.has(ep.id)}
                              onChange={(e) =>
                                onToggleEpisode(ep.id, (e.target as HTMLInputElement).checked)
                              }
                              disabled={busy}
                            />
                          )}
                        </span>
                        <span class="ep-copy">
                          <span class="ep-title">{ep.title}</span>
                          <span class="ep-code">{ep.code}</span>
                        </span>
                        {ep.action !== "download" && (
                          <span class={`status-pill action-${ep.action}`}>
                            {actionLabel(ep.action)}
                          </span>
                        )}
                        {ep.status === "failed" && <span class="run-error">failed</span>}
                        {formatItemSize(ep.size) && (
                          <span class="ep-size">{formatItemSize(ep.size)}</span>
                        )}
                      </label>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
          {series.unmapped.length > 0 && (
            <section class="season-card">
              <div class="fold-head season-head">
                <span class="show-copy">
                  <span class="show-name">Unmapped ({series.unmapped.length})</span>
                  <span class="show-meta">
                    <a href={detailHref}>Map on show</a>
                  </span>
                </span>
              </div>
              <div class="season-eps">
                {series.unmapped.map((ep) => (
                  <div key={ep.id} class="ep-row">
                    <span class="fold-check" />
                    <span class="ep-copy">
                      <span class="ep-title">{ep.title}</span>
                      <span class="ep-code">
                        {ep.code}
                        {ep.url ? ` · ${shortUrl(ep.url)}` : ""}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </section>
  );
}, seriesRowEqual);
