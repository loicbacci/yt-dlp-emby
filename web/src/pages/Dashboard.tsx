import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { ApiError, type PlanFile, type Run, apiClient, runKeyFor } from "../api";
import { go } from "../nav";
import { Header } from "../components/Header";
import { LogViewer } from "../components/LogViewer";
import {
  applyCheck,
  applyProgress,
  buildTree,
  downloadLabel,
  effectiveDownloadIds,
  formatItemSize,
  heroFrom,
  needsConfirm,
  pendingIds,
  platformLabel,
  runStatsLine,
  searchOpen,
  triState,
  upToDateSeries,
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
  const [progress, setProgress] = useState<ProgressState>({
    currentId: null,
    percent: null,
    phase: null,
    doneIds: new Set(),
    failedIds: new Set(),
  });
  const [openSeries, setOpenSeries] = useState<Set<string>>(new Set());
  const [openSeasons, setOpenSeasons] = useState<Set<string>>(new Set());
  const [eventsReconnecting, setEventsReconnecting] = useState(false);
  const [downloadTotal, setDownloadTotal] = useState(0);

  const tree = useMemo(
    () => (plan ? buildTree(plan as QueuePlanFile) : []),
    [plan],
  );
  const treeRef = useRef(tree);
  treeRef.current = tree;
  const visible = useMemo(() => visibleSeries(tree, query), [tree, query]);
  const upToDate = useMemo(() => upToDateSeries(tree, query), [tree, query]);
  const allPending = useMemo(() => pendingIds(tree), [tree]);
  const effective = useMemo(
    () => effectiveDownloadIds(selected, allPending),
    [selected, allPending],
  );
  const busy = run.status === "running" || run.status === "stopping";
  const planning = run.phase === "planning";
  const downloading = run.phase === "downloading";

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
      applyRun(await apiClient.getRun());
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
    let source: EventSource | null = null;
    let last = 0;
    let closed = false;

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
          if (ev.event === "progress" || ev.event === "item_done") {
            const { progress: next } = applyProgress(treeRef.current, ev);
            setProgress((current) => ({
              ...current,
              currentId: next.currentId ?? current.currentId,
              percent: next.percent ?? current.percent,
              phase: next.phase ?? current.phase,
              doneIds: new Set([...current.doneIds, ...next.doneIds]),
              failedIds: new Set([...current.failedIds, ...next.failedIds]),
            }));
            if (ev.event === "item_done" && typeof ev.id === "string") {
              setPlan((current) => {
                if (!current) return current;
                const nextPlan = JSON.parse(JSON.stringify(current)) as PlanFile;
                for (const block of Object.values(nextPlan.sources)) {
                  block.items = block.items.filter((item) => item.id !== ev.id);
                }
                return nextPlan;
              });
            }
          }
        } catch {
          /* ignore malformed events */
        }
      };
      source.onerror = () => {
        if (last > 0) setEventsReconnecting(true);
        source?.close();
        window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      source?.close();
    };
  }, []);

  useEffect(() => {
    if (downloading && progress.currentId) {
      for (const series of tree) {
        for (const season of series.seasons) {
          for (const ep of season.pending) {
            if (ep.id === progress.currentId) {
              setOpenSeries((s) => new Set(s).add(series.key));
              setOpenSeasons((s) => new Set(s).add(season.key));
            }
          }
        }
      }
    }
  }, [downloading, progress.currentId, tree]);

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

  const onDownload = async () => {
    if (!plan) {
      setError("Refresh the queue first");
      return;
    }
    const count = effective.length;
    if (needsConfirm(count) && !window.confirm(`Download ${count} episodes?`)) return;
    setError(null);
    try {
      setDownloadTotal(effective.length);
      setProgress({
        currentId: null,
        percent: null,
        phase: null,
        doneIds: new Set(),
        failedIds: new Set(),
      });
      const ids = selected.size === 0 ? null : effective;
      applyRun(await apiClient.startDownload({ ids, force }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Download failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
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
  const hero = heroFrom(run, tree, progress, listingSeries, allPending.length);
  const hasManifest = plan !== null;
  const statsLine = runStatsLine(
    run,
    progress,
    downloading ? downloadTotal : allPending.length,
  );
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
    return keys;
  }, [query, visible, openSeasons]);

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
              Series
            </a>
            , then Refresh queue.
          </p>
        )}
        <section class="run-hero">
          <div>
            <h1>{hero.heading}</h1>
            <p class="run-hero-sub">{hero.sub}</p>
          </div>
          {downloading && (
            <button type="button" class="btn-danger" onClick={onStop}>
              Stop
            </button>
          )}
          {progress.percent != null && downloading && (
            <div class="run-hero-bar">
              <div class="run-hero-fill" style={{ width: `${progress.percent}%` }} />
            </div>
          )}
        </section>
        <section class="run-stats" aria-live="polite">{statsLine}</section>
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
              open={openSeries.has(series.key) || Boolean(query.trim())}
              openSeasons={expandedSeasons}
              selected={selected}
              busy={busy}
              downloading={downloading}
              listing={planning && listingSeries === series.name}
              currentId={progress.currentId}
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
            />
          ))}
          {upToDate.length > 0 && (
            <details class="run-complete">
              <summary>Up to date ({upToDate.length})</summary>
              <ul>
                {upToDate.map((s) => (
                  <li key={s.key}>{s.name}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
        <details class="yt-log">
          <summary>Technical log</summary>
          <LogViewer runKey={runKey} />
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
    </div>
  );
}

function SeriesRow({
  series,
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
  open: boolean;
  openSeasons: Set<string>;
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
}) {
  const childIds = series.seasons.flatMap((s) => s.pending.map((e) => e.id));
  const state = triState(selected, childIds);
  if (series.error) {
    return (
      <div class="run-row run-row-series">
        <span class="run-error">{series.name}: {series.error}</span>
      </div>
    );
  }
  return (
    <div class="run-row run-row-series">
      <div class="run-series-head">
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
          class="run-twist"
          aria-expanded={open}
          onClick={onToggleOpen}
        >
          {open ? "▾" : "▸"}
        </button>
        <button type="button" class="run-series-name" onClick={onToggleOpen}>
          {series.name}
        </button>
        <span class="run-meta">{platformLabel(series.platform)}</span>
        {listing && <span class="run-meta">Listing…</span>}
        {series.pendingCount > 0 && (
          <span class="run-meta">{series.pendingCount} new</span>
        )}
      </div>
      {open && (
        <div class="run-series-body">
          {series.seasons.map((season) => {
            const seasonOpen = openSeasons.has(season.key);
            const seasonIds = season.pending.map((e) => e.id);
            return (
              <div key={season.key} class="run-row run-row-season">
                <div class="run-series-head">
                  {!downloading && seasonIds.length > 0 && (
                    <input
                      type="checkbox"
                      class="run-check"
                      checked={triState(selected, seasonIds) === "all"}
                      onChange={(e) =>
                        onToggleSeason(season, (e.target as HTMLInputElement).checked)
                      }
                      disabled={busy}
                      aria-label={`Select season ${season.folderLabel}`}
                    />
                  )}
                  <button
                    type="button"
                    class="run-twist"
                    aria-expanded={seasonOpen}
                    onClick={() => onToggleSeasonOpen(season.key)}
                  >
                    {seasonOpen ? "▾" : "▸"}
                  </button>
                  <button
                    type="button"
                    class="run-series-name"
                    onClick={() => onToggleSeasonOpen(season.key)}
                  >
                    {season.seasonTitle ?? season.folderLabel}
                  </button>
                  <span class="run-meta muted">{season.folderLabel} on disk</span>
                  <span class="run-meta">{season.pending.length} new</span>
                </div>
                {seasonOpen &&
                  season.pending.map((ep) => (
                    <div
                      key={ep.id}
                      class={`run-row run-row-ep${currentId === ep.id ? " is-now" : ""}`}
                    >
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
                      <span class="run-code">{ep.code}</span>
                      <span class="run-ep-title">{ep.title}</span>
                      {formatItemSize(ep.size) && (
                        <span class="run-meta ep-size">{formatItemSize(ep.size)}</span>
                      )}
                    </div>
                  ))}
              </div>
            );
          })}
          {series.completeSeasons.length > 0 && (
            <details class="run-complete queue-complete">
              <summary>
                Already on disk ({series.completeSeasons.length} seasons)
              </summary>
              <ul>
                {series.completeSeasons.map((s) => (
                  <li key={s.folderLabel}>
                    {s.seasonTitle ?? s.folderLabel}
                    <span class="run-meta muted"> · {s.skip} skipped</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {series.unmapped.length > 0 && (
            <details class="run-row run-row-season">
              <summary>Unmapped ({series.unmapped.length})</summary>
              {series.unmapped.map((ep) => (
                <div key={ep.id} class="run-row run-row-ep">
                  <span class="run-code">{ep.code}</span>
                  <span class="run-ep-title">{ep.title}</span>
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </div>
  );
}
