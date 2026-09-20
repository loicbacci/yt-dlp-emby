import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { useQuery } from "@tanstack/preact-query";
import { ApiError, type PlanFile, type Run, apiClient, runKeyFor } from "../api";
import { go } from "../nav";
import { Header } from "../components/Header";
import { LogViewer } from "../components/LogViewer";
import { ConfirmModal } from "../components/ConfirmModal";
import { Poster, posterLetter } from "../components/Poster";
import { queryKeys } from "../queryKeys";
import {
  applyCheck,
  applyProgress,
  buildTree,
  downloadLabel,
  effectiveDownloadIds,
  episodeForId,
  formatBinaryBytes,
  formatItemSize,
  formatProgressStats,
  heroFrom,
  emptyProgress,
  mergeProgress,
  needsConfirm,
  overlayProgress,
  pendingIds,
  platformLabel,
  remainingEpisodes,
  runStatsLine,
  searchOpen,
  triState,
  upToDateSeries,
  seriesInActiveDownload,
  visibleSeries,
  type PlanFile as QueuePlanFile,
  type ProgressState,
  type QueueSeason,
  type QueueSeries,
} from "../runQueue";

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

export function Dashboard() {
  const [run, setRun] = useState<Run>(idleRun);
  const [runKey, setRunKey] = useState("idle");
  const [plan, setPlan] = useState<PlanFile | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [force, setForce] = useState(false);
  const [showForce, setShowForce] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listingSeries, setListingSeries] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressState>(emptyProgress());
  const [openSeries, setOpenSeries] = useState<Set<string>>(new Set());
  const [openSeasons, setOpenSeasons] = useState<Set<string>>(new Set());
  const [openUpcoming, setOpenUpcoming] = useState<Set<string>>(new Set());
  const [eventsReconnecting, setEventsReconnecting] = useState(false);
  const [downloadTotal, setDownloadTotal] = useState(0);
  const [pendingDownload, setPendingDownload] = useState<{
    count: number;
    ids: string[] | null;
  } | null>(null);
  const [activeDownloadIds, setActiveDownloadIds] = useState<Set<string> | null>(
    null,
  );

  const tree = useMemo(
    () => (plan ? buildTree(plan as QueuePlanFile) : []),
    [plan],
  );
  const treeRef = useRef(tree);
  treeRef.current = tree;
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
    () => effectiveDownloadIds(selected, allPending),
    [selected, allPending],
  );

  const applyRun = (next: Run) => {
    setRun(next);
    setRunKey(runKeyFor(next));
  };

  const loadPlan = async () => {
    try {
      const next = await apiClient.getPlan();
      setPlan(next);
      if (next.force) setForce(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlan(null);
        return;
      }
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const refreshRun = async () => {
    try {
      const next = await apiClient.getRun();
      applyRun(next);
      if (next.progress && typeof next.progress.event === "string") {
        if (next.progress.event === "series" && typeof next.progress.name === "string") {
          setListingSeries(next.progress.name);
        }
        if (
          next.progress.event === "item_steps" ||
          next.progress.event === "progress" ||
          next.progress.event === "item_done"
        ) {
          const { progress: patch } = applyProgress(treeRef.current, next.progress);
          setProgress((current) => mergeProgress(current, patch));
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  useEffect(() => {
    loadPlan();
    refreshRun();
    const timer = window.setInterval(refreshRun, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setProgress(emptyProgress());
    setListingSeries(null);
    setEventsReconnecting(false);
    let source: EventSource | null = null;
    let last = 0;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      if (closed) return;
      source = new EventSource(`/api/runs/events?after=${last}`);
      source.onmessage = (message) => {
        setEventsReconnecting(false);
        try {
          const payload = JSON.parse(message.data) as {
            n: number;
            event: Record<string, unknown>;
          };
          last = payload.n;
          const ev = payload.event;
          if (ev.event === "series" && typeof ev.name === "string") {
            setListingSeries(ev.name);
          }
          if (
            ev.event === "item_steps" ||
            ev.event === "progress" ||
            ev.event === "item_done"
          ) {
            const { progress: next } = applyProgress(treeRef.current, ev);
            setProgress((current) => mergeProgress(current, next));
          }
        } catch {
          /* ignore malformed events */
        }
      };
      source.onerror = () => {
        source?.close();
        if (closed) return;
        if (last > 0) setEventsReconnecting(true);
        timer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      source?.close();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runKey]);

  useEffect(() => {
    if (downloading && progress.currentId) {
      for (const series of displayTree) {
        for (const season of series.seasons) {
          for (const ep of season.pending) {
            if (ep.id === progress.currentId) {
              setOpenSeries((s) => new Set(s).add(series.key));
              setOpenUpcoming((s) => new Set(s).add(series.key));
              setOpenSeasons(new Set([season.key]));
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
    if (!first) return;
    didOpenDefault.current = true;
    setOpenSeries(new Set([first.key]));
    setOpenSeasons(new Set([first.seasons[0].key]));
  }, [visible, downloading]);

  const onRefresh = async () => {
    setError(null);
    setListingSeries(null);
    try {
      applyRun(await apiClient.startPlan(force));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Refresh failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const startDownload = async (ids: string[] | null, count: number) => {
    setError(null);
    try {
      setDownloadTotal(count);
      setProgress(emptyProgress());
      setActiveDownloadIds(new Set(ids ?? allPending));
      applyRun(await apiClient.startDownload({ ids, force }));
    } catch (err) {
      setActiveDownloadIds(null);
      setError(err instanceof ApiError ? err.message : "Download failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const onDownload = () => {
    if (!plan) {
      setError("Refresh the queue first");
      return;
    }
    const count = effective.length;
    const ids = selected.size === 0 ? null : effective;
    if (needsConfirm(count)) {
      setPendingDownload({ count, ids });
      return;
    }
    void startDownload(ids, count);
  };

  const onStop = async () => {
    try {
      applyRun(await apiClient.stopRun());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  useEffect(() => {
    if (run.status === "exited" && run.dry_run) {
      loadPlan();
    }
  }, [run.status, run.dry_run, run.finished_at]);

  const downloadCount = effective.length || allPending.length;
  const hero = heroFrom(run, displayTree, progress, listingSeries, allPending.length);
  const hasManifest = plan !== null;
  const statsLine = runStatsLine(
    run,
    progress,
    downloading ? downloadTotal || allPending.length : allPending.length,
  );
  const progressStats = downloading ? formatProgressStats(progress) : null;
  const posterQuery = useQuery({
    queryKey: queryKeys.seriesList(),
    queryFn: () => apiClient.listSeries(),
    staleTime: 60_000,
  });
  const posterMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of posterQuery.data?.series ?? []) {
      if (row.poster_url) map.set(`${row.platform}|${row.slug}`, row.poster_url);
    }
    return map;
  }, [posterQuery.data]);
  const nowHit = progress.currentId
    ? episodeForId(displayTree, progress.currentId)
    : null;
  const nowPoster = nowHit
    ? posterMap.get(`${nowHit.series.platform}|${nowHit.series.slug}`)
    : null;
  const localDetail =
    progress.total != null && progress.total > 0
      ? `${formatBinaryBytes(progress.bytes ?? 0)} of ${formatBinaryBytes(progress.total)}${
          progress.speed != null && Number.isFinite(progress.speed)
            ? ` · ${formatBinaryBytes(progress.speed)}/s`
            : ""
        }`
      : progressStats;
  const expandedSeasons = useMemo(() => {
    const keys = new Set(openSeasons);
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
  }, [query, visible, openSeasons, downloading, progress.currentId, displayTree]);

  const expandedUpcoming = useMemo(() => {
    const keys = new Set(openUpcoming);
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
          series.seasons.some((season) =>
            season.pending.some((ep) => ep.id === progress.currentId),
          )
        ) {
          keys.add(series.key);
        }
      }
    }
    return keys;
  }, [
    openUpcoming,
    query,
    visible,
    downloading,
    progress.currentId,
    displayTree,
  ]);

  const toggleSeries = (series: QueueSeries, checked: boolean) => {
    const ids = series.seasons.flatMap((s) => s.pending.map((e) => e.id));
    setSelected(applyCheck(selected, ids, checked));
  };

  const toggleSeason = (season: QueueSeason, checked: boolean) => {
    setSelected(applyCheck(selected, season.pending.map((e) => e.id), checked));
  };

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  return (
    <div class="run-shell">
      <Header run={run} current="dashboard" onLogout={logout} />
      <main class="run-main">
        <div class="run-toolbar">
          <input
            class="run-search"
            type="search"
            placeholder="Search queue…"
            value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          />
          {!downloading && (
            <>
              <button
                type="button"
                class="btn-secondary"
                disabled={busy}
                onClick={onRefresh}
              >
                Refresh queue
              </button>
              <button
                type="button"
                class="btn-ghost"
                onClick={() => setShowForce((v) => !v)}
                disabled={busy}
              >
                Force
              </button>
            </>
          )}
        </div>
        {eventsReconnecting && (
          <p class="run-hint">Reconnecting live events…</p>
        )}
        {showForce && (
          <p class="run-hint">
            <label>
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce((e.target as HTMLInputElement).checked)}
                disabled={busy}
              />
              Re-download files already on disk (Dropout). Refresh the queue after turning
              this on.
            </label>
          </p>
        )}
        {error && <div class="validation-error">{error}</div>}
        {!hasManifest && !busy && (
          <p class="run-hint">
            No queue yet. Add series under{" "}
            <a href="/series" onClick={(e) => { e.preventDefault(); go("/series"); }}>
              Shows
            </a>
            , then Refresh queue.
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
              <p class="download-kicker">Downloading now</p>
              <h1>{nowHit.series.name}</h1>
              <h2>{nowHit.ep.title}</h2>
              <div class="progress-row">
                <span>{progress.phase ?? "Working…"}</span>
                <span>{localDetail}</span>
              </div>
              <div
                class={`progress-track${progress.percent == null ? " is-indeterminate" : ""}`}
              >
                <div
                  class="progress-fill"
                  style={
                    progress.percent != null
                      ? { width: `${progress.percent}%` }
                      : undefined
                  }
                />
              </div>
              {progress.steps.length > 0 && (
                <ol class="step-chips">
                  {progress.steps.map((label, index) => (
                    <li
                      key={label}
                      data-testid={`step-chip-${label}`}
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
              <button
                type="button"
                class="btn-danger"
                style={{ marginTop: "12px" }}
                onClick={onStop}
              >
                Stop
              </button>
            </div>
          </section>
        ) : (
          <section class="dl-hero">
            <div>
              <h1>
                {planning || run.phase === "stopping"
                  ? hero.heading
                  : `${allPending.length} new episodes`}
              </h1>
              <p class="run-hero-sub">{hero.sub}</p>
            </div>
            {downloading && (
              <button type="button" class="btn-danger run-hero-stop" onClick={onStop}>
                Stop
              </button>
            )}
          </section>
        )}
        <section class="run-stats" aria-live="polite">{statsLine}</section>
        {downloading && (
          <h3 class="queue-label">
            Queue · {Math.max(0, (downloadTotal || allPending.length) - progress.doneIds.size - (nowHit ? 1 : 0))} episodes
          </h3>
        )}
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
              posterUrl={posterMap.get(`${series.platform}|${series.slug}`)}
              open={openSeries.has(series.key) || Boolean(query.trim())}
              openSeasons={expandedSeasons}
              upcomingOpen={expandedUpcoming.has(series.key)}
              selected={selected}
              busy={busy}
              downloading={downloading}
              listing={planning && listingSeries === series.name}
              currentId={progress.currentId}
              currentPercent={progress.percent}
              onToggleOpen={() =>
                setOpenSeries((s) => {
                  const next = new Set(s);
                  if (next.has(series.key)) next.delete(series.key);
                  else next.add(series.key);
                  return next;
                })
              }
              onToggleSeries={(checked) => toggleSeries(series, checked)}
              onToggleSeason={toggleSeason}
              onToggleEpisode={(id, checked) =>
                setSelected(applyCheck(selected, [id], checked))
              }
              onToggleSeasonOpen={(key) =>
                setOpenSeasons((s) => {
                  const next = new Set(s);
                  if (next.has(key)) next.delete(key);
                  else next.add(key);
                  return next;
                })
              }
              onToggleUpcoming={(open) =>
                setOpenUpcoming((s) => {
                  const next = new Set(s);
                  if (open) next.add(series.key);
                  else next.delete(series.key);
                  return next;
                })
              }
            />
          ))}
          {upToDate.length > 0 && (
            <details class="fold-card disclosure">
              <summary>Already in library ({upToDate.length})</summary>
              <ul>
                {upToDate.map((s) => (
                  <li key={s.key}>{s.name}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
        <details class="run-log-details">
          <summary>Details · technical log</summary>
          <LogViewer runKey={runKey} compact />
        </details>
      </main>
      {!downloading && (
        <footer class="run-bar">
          <span>
            {planning
              ? "Listing…"
              : selected.size > 0
                ? `${downloadCount} selected`
                : `${downloadCount} pending`}
          </span>
          <button
            type="button"
            class="btn-primary"
            disabled={busy || planning || !hasManifest || downloadCount === 0}
            onClick={onDownload}
          >
            {downloadLabel(downloadCount)}
          </button>
        </footer>
      )}
      {pendingDownload && (
        <ConfirmModal
          title={`Download ${pendingDownload.count} episodes?`}
          message="This starts a large download. You can stop it from the run bar."
          confirmLabel={downloadLabel(pendingDownload.count)}
          onCancel={() => setPendingDownload(null)}
          onConfirm={() => {
            const { ids, count } = pendingDownload;
            setPendingDownload(null);
            void startDownload(ids, count);
          }}
        />
      )}
    </div>
  );
}

function SeriesRow({
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
}: {
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
  currentPercent: number | null;
  onToggleOpen: () => void;
  onToggleSeries: (checked: boolean) => void;
  onToggleSeason: (season: QueueSeason, checked: boolean) => void;
  onToggleEpisode: (id: string, checked: boolean) => void;
  onToggleSeasonOpen: (key: string) => void;
  onToggleUpcoming: (open: boolean) => void;
}) {
  const childIds = series.seasons.flatMap((s) => s.pending.map((e) => e.id));
  const state = triState(selected, childIds);
  const hideDone = downloading;
  const upcoming = series.seasons
    .map((season) => ({
      season,
      remaining: remainingEpisodes(season, hideDone).filter(
        (ep) => ep.id !== currentId,
      ),
    }))
    .filter((row) => row.remaining.length > 0);
  const upcomingCount = upcoming.reduce((n, row) => n + row.remaining.length, 0);
  if (series.error) {
    return (
      <section class="fold-card">
        <span class="run-error">{series.name}: {series.error}</span>
      </section>
    );
  }
  if (downloading && upcomingCount === 0) return null;
  return (
    <section class="fold-card">
      <div class="fold-head">
        {!downloading && childIds.length > 0 && (
          <input
            type="checkbox"
            class="run-check"
            checked={state === "all"}
            ref={(el) => {
              if (el) el.indeterminate = state === "some";
            }}
            onChange={(e) =>
              onToggleSeries((e.target as HTMLInputElement).checked)
            }
            disabled={busy}
            aria-label={`Select all in ${series.name}`}
          />
        )}
        <button
          type="button"
          class="fold-main"
          aria-expanded={open}
          onClick={onToggleOpen}
        >
          <Poster
            src={posterUrl}
            letter={posterLetter(series.name)}
            size="md"
            alt={series.name}
          />
          <span class="show-copy">
            <span class="show-name">{series.name}</span>
            <span class="show-meta">
              {listing
                ? "Listing…"
                : downloading
                  ? `${upcomingCount} remaining · ${upcoming.length} ${upcoming.length === 1 ? "season" : "seasons"}`
                  : `${series.pendingCount} new · ${series.seasons.length} ${series.seasons.length === 1 ? "season" : "seasons"} · ${platformLabel(series.platform)}`}
            </span>
          </span>
          <span class={`twist${open ? " is-open" : ""}`} aria-hidden="true" />
        </button>
      </div>
      {open &&
        upcoming.map(({ season, remaining }) => {
          const seasonOpen = openSeasons.has(season.key);
          const seasonIds = remaining.map((e) => e.id);
          return (
            <div key={season.key} class="season-group">
              <div class="fold-head season-head">
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
                      onToggleSeason(
                        season,
                        (e.target as HTMLInputElement).checked,
                      )
                    }
                    disabled={busy}
                    aria-label={`Select ${season.folderLabel}`}
                  />
                )}
                <button
                  type="button"
                  class="fold-main"
                  aria-expanded={seasonOpen}
                  onClick={() => onToggleSeasonOpen(season.key)}
                >
                  <span class="show-copy">
                    <span class="show-name">
                      {season.seasonTitle ?? season.folderLabel}
                    </span>
                    <span class="show-meta">{season.folderLabel}</span>
                  </span>
                  <span class={`count-chip${downloading ? "" : " is-new"}`}>
                    {remaining.length} {downloading ? "remaining" : "new"}
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
                      {!downloading && (
                        <input
                          type="checkbox"
                          class="run-check"
                          checked={selected.has(ep.id)}
                          onChange={(e) =>
                            onToggleEpisode(
                              ep.id,
                              (e.target as HTMLInputElement).checked,
                            )
                          }
                          disabled={busy}
                        />
                      )}
                      <span class="ep-copy">
                        <span class="ep-title">{ep.title}</span>
                        <span class="ep-code">{ep.code}</span>
                      </span>
                      {ep.status === "failed" && (
                        <span class="run-error">failed</span>
                      )}
                      {formatItemSize(ep.size) && (
                        <span class="ep-size">{formatItemSize(ep.size)}</span>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      {open && series.unmapped.length > 0 && (
        <div class="season-group">
          <div class="show-meta" style={{ padding: "8px 16px" }}>
            Unmapped ({series.unmapped.length})
          </div>
          <div class="season-eps">
            {series.unmapped.map((ep) => (
              <div key={ep.id} class="ep-row">
                <span class="ep-copy">
                  <span class="ep-title">{ep.title}</span>
                  <span class="ep-code">{ep.code}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
