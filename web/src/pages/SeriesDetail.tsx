import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { useLocation } from "preact-iso";
import { useQuery } from "@tanstack/preact-query";
import { useSelector } from "@tanstack/preact-store";
import {
  ApiError,
  type Run,
  type SeriesDetail as SeriesDetailModel,
  type SeriesEpisode,
  type SeriesSeason,
  apiClient,
} from "../api";
import { Header } from "../components/Header";
import { SeriesDetailSkeleton, Skeleton } from "../components/Skeleton";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { RemapModal } from "../components/series/RemapModal";
import { SourceBlock } from "../components/series/SourceBlock";
import { TvdbSkipPanel } from "../components/series/TvdbSkipPanel";
import { go } from "../nav";
import { queryClient } from "../queryClient";
import { queryKeys } from "../queryKeys";
import { useSeriesCatalog } from "../seriesCatalog";
import {
  patchSeriesFold,
  seriesUiKey,
  seriesUiStore,
  setSeriesFolds,
} from "../seriesUiStore";
import { addTvdbSkip, isSeasonOpen, parseSeriesPath, seasonFoldKey, seasonFoldMap } from "../seriesView";

const EMPTY_FOLDS: Record<string, boolean> = {};

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

export function SeriesDetail() {
  const { path } = useLocation();
  const parsed = parseSeriesPath(path) ?? { platform: "dropout" as const, slug: "" };
  const { platform, slug } = parsed;

  const [run, setRun] = useState<Run>(idleRun);
  const [folderView, setFolderView] = useState<"sources" | "emby">("sources");
  const [detail, setDetail] = useState<SeriesDetailModel | null>(null);
  const [saved, setSaved] = useState<SeriesDetailModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [addingUrl, setAddingUrl] = useState(false);
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [existing, setExisting] = useState<{ name: string; slug?: string }[]>([]);
  const [remap, setRemap] = useState<{
    sourceId: number;
    seasonId: number;
    episode: SeriesEpisode;
  } | null>(null);

  const seriesQuery = useQuery({
    queryKey: queryKeys.series(platform, slug),
    queryFn: () => apiClient.getSeries(platform, slug),
    enabled: Boolean(slug),
    staleTime: 60 * 1000,
  });
  const uiKey = seriesUiKey(platform, slug);
  const seasonFolds = useSelector(
    seriesUiStore,
    (state) => state.folds[uiKey] ?? EMPTY_FOLDS,
  );
  const { episodeMap, loadingMap, onDisk } = useSeriesCatalog(
    platform,
    slug,
    seriesQuery.data?.sources,
  );
  const layoutQuery = useQuery({
    queryKey: queryKeys.layout(slug),
    queryFn: () => apiClient.getDropoutLayout(slug),
    enabled: platform === "dropout" && folderView === "emby" && Boolean(slug),
  });
  const checkQuery = useQuery({
    queryKey: [...queryKeys.check(slug), JSON.stringify(detail?.tvdb_skip ?? [])],
    queryFn: () => apiClient.getDropoutCheck(slug),
    enabled: platform === "dropout" && Boolean(slug) && detail?.tvdb_id != null,
    staleTime: 5 * 60 * 1000,
  });
  const layout = layoutQuery.data ?? null;
  const layoutError =
    layoutQuery.error instanceof Error ? layoutQuery.error.message : null;
  const check = checkQuery.data ?? null;
  const checkError =
    checkQuery.error instanceof Error ? checkQuery.error.message : null;

  const dirty = useMemo(
    () => JSON.stringify(detail) !== JSON.stringify(saved),
    [detail, saved],
  );
  const runActive = run.status === "running" || run.status === "stopping";
  const prevRunStatus = useRef(run.status);

  useEffect(() => {
    if (!seriesQuery.data || dirty) return;
    setDetail(seriesQuery.data);
    setSaved(seriesQuery.data);
  }, [seriesQuery.data, dirty]);

  useEffect(() => {
    if (seriesQuery.data) setError(null);
    if (seriesQuery.error instanceof ApiError && seriesQuery.error.status === 401) {
      go("/login");
    } else if (seriesQuery.error instanceof Error) {
      setError(seriesQuery.error.message);
    }
  }, [seriesQuery.error, seriesQuery.data]);

  useEffect(() => {
    apiClient
      .listSeries()
      .then((body) => setExisting(body.series))
      .catch(() => {});
  }, [platform, slug]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      apiClient.getRun().then(setRun).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (
      prevRunStatus.current === "running" &&
      (run.status === "exited" || run.status === "idle")
    ) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.disk(platform, slug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.check(slug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.missing(platform, slug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() });
    }
    prevRunStatus.current = run.status;
  }, [run.status, platform, slug]);

  useEffect(() => {
    if (window.location.hash !== "#sonarr-check") return;
    document.getElementById("sonarr-check")?.scrollIntoView({ behavior: "smooth" });
  }, [check, checkError, detail]);

  const persist = async (next: SeriesDetailModel) => {
    const body = await apiClient.putSeries(platform, slug, next);
    queryClient.setQueryData(queryKeys.series(platform, slug), body);
    setDetail(body);
    setSaved(body);
    return body;
  };

  const flashSaved = () => {
    setFlash(true);
    window.setTimeout(() => setFlash(false), 1600);
  };

  const save = async () => {
    if (!detail) return;
    setError(null);
    try {
      await persist(detail);
      flashSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  };

  const addUrl = async () => {
    const url = urlDraft.trim();
    if (!url || runActive) return;
    setAddingUrl(true);
    setPendingUrl(url);
    setPendingError(null);
    setError(null);
    try {
      const body = await apiClient.addSeriesSource(platform, slug, url);
      queryClient.setQueryData(queryKeys.series(platform, slug), body);
      setDetail(body);
      setSaved(body);
      setUrlDraft("");
      setPendingUrl(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.episodesSeries(platform, slug),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.disk(platform, slug) });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Add URL failed";
      setPendingError(message);
    } finally {
      setAddingUrl(false);
    }
  };

  const removeSource = async (sourceId: number) => {
    if (!detail) return;
    const src = detail.sources[sourceId];
    const risky = src.seasons.some(
      (se) =>
        se.remaps.length ||
        (se.only_episodes && se.only_episodes.length) ||
        se.skip_ids.length,
    );
    if (risky && !window.confirm("Remove this source and its season settings?")) {
      return;
    }
    try {
      const body = await apiClient.deleteSeriesSource(platform, slug, sourceId);
      queryClient.setQueryData(queryKeys.series(platform, slug), body);
      setDetail(body);
      setSaved(body);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.episodesSeries(platform, slug),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.disk(platform, slug) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remove failed");
    }
  };

  const refreshSource = async (sourceId: number) => {
    if (runActive || !detail) return;
    try {
      const body = await apiClient.refreshSeriesSource(platform, slug, sourceId);
      queryClient.setQueryData(queryKeys.series(platform, slug), body);
      setDetail(body);
      setSaved(body);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.episodesSource(platform, slug, sourceId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.disk(platform, slug) });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Refresh failed";
      setDetail({
        ...detail,
        sources: detail.sources.map((src, idx) =>
          idx === sourceId ? { ...src, error: message } : src,
        ),
      });
    }
  };

  const updateSeasonTitle = async (
    sourceId: number,
    seasonId: number,
    value: string,
  ) => {
    if (!detail) return;
    const title = value.trim() || null;
    const season = detail.sources[sourceId].seasons[seasonId];
    if ((season.title ?? null) === title) return;
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) =>
                seid !== seasonId ? se : { ...se, title },
              ),
            },
      ),
    };
    try {
      await persist(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const toggleSeasonEnabled = async (sourceId: number, seasonId: number) => {
    if (!detail) return;
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) =>
                seid !== seasonId ? se : { ...se, enabled: !se.enabled },
              ),
            },
      ),
    };
    try {
      await persist(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const toggleSkip = async (
    sourceId: number,
    seasonId: number,
    episode: SeriesEpisode,
  ) => {
    if (!detail) return;
    const season = detail.sources[sourceId].seasons[seasonId];
    let nextSeason: SeriesSeason;
    if (platform === "youtube") {
      const skip = new Set(season.skip_ids);
      if (skip.has(episode.id)) skip.delete(episode.id);
      else skip.add(episode.id);
      nextSeason = { ...season, skip_ids: [...skip] };
    } else if (season.only_episodes && season.only_episodes.length) {
      const list = new Set(season.only_episodes);
      const num = episode.source_episode;
      if (episode.skipped) {
        list.add(num);
      } else {
        if (list.size <= 1) {
          setError("only_episodes cannot be empty");
          return;
        }
        list.delete(num);
      }
      nextSeason = { ...season, only_episodes: [...list].sort((a, b) => a - b) };
    } else {
      const remaps = season.remaps.filter(
        (r) => r.dropout_episode !== episode.source_episode,
      );
      if (!episode.skipped) {
        remaps.push({ dropout_episode: episode.source_episode, skip: true });
      }
      nextSeason = { ...season, remaps };
    }
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) =>
                seid === seasonId ? nextSeason : se,
              ),
            },
      ),
    };
    try {
      await persist(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Skip update failed");
    }
  };

  const applyRemap = async (
    sourceId: number,
    seasonId: number,
    episode: SeriesEpisode,
    fields: { to_season: number; to_episode: number; title: string },
  ) => {
    if (!detail) return;
    const season = detail.sources[sourceId].seasons[seasonId];
    const remaps = season.remaps.filter(
      (r) => r.dropout_episode !== episode.source_episode,
    );
    remaps.push({
      dropout_episode: episode.source_episode,
      to_season: fields.to_season,
      to_episode: fields.to_episode,
      title: fields.title || undefined,
    });
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) =>
                seid === seasonId ? { ...se, remaps } : se,
              ),
            },
      ),
    };
    try {
      await persist(next);
      setRemap(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remap failed");
    }
  };

  const deleteSeries = async () => {
    if (!detail) return;
    const target = detail.inline ? `the ${detail.file} entry` : detail.file;
    if (!window.confirm(`Delete ${detail.name}? This removes ${target}.`)) {
      return;
    }
    try {
      await apiClient.deleteSeries(platform, slug);
      go("/series");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  };

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  const navigate = (url: string) => {
    if (dirty && !window.confirm("Discard unsaved series changes?")) return;
    go(url);
  };

  if (!detail) {
    return (
      <div class="series-shell">
        <Header
          run={run}
          current="series"
          onLogout={() => void logout()}
          onNavigate={navigate}
        />
        <section class="card series-card">
          <a
            href="/series"
            class="header-link"
            onClick={(e) => {
              e.preventDefault();
              go("/series");
            }}
          >
            ← Series
          </a>
          {error ? (
            <div class="validation-error">{error}</div>
          ) : (
            <SeriesDetailSkeleton />
          )}
        </section>
      </div>
    );
  }

  return (
    <div class="series-shell">
      <Header
        run={run}
        current="series"
        onLogout={() => void logout()}
        onNavigate={navigate}
      />
      <section class="card series-card">
        <div class="series-toolbar">
          <div>
            <a
              href="/series"
              class="header-link"
              onClick={(e) => {
                e.preventDefault();
                navigate("/series");
              }}
            >
              ← Series
            </a>
            <h1 class="settings-title">{detail.name}</h1>
            <div class="series-row-meta">
              <span>{detail.path}</span>
              <span>{detail.file}</span>
              {detail.tvdb_id != null && <span>tvdb {detail.tvdb_id}</span>}
              {detail.inline && <span>inline</span>}
            </div>
            <div class="series-toolbar">
              <button type="button" class="btn-ghost" onClick={() => setEditOpen(true)}>
                Edit details
              </button>
              <button
                type="button"
                class="btn-danger"
                onClick={() => void deleteSeries()}
              >
                Delete
              </button>
            </div>
          </div>
          <div class="series-toolbar-end">
            <span
              class={
                detail.platform === "youtube" ? "badge-youtube" : "badge-dropout"
              }
            >
              {detail.platform === "youtube" ? "YouTube" : "Dropout.tv"}
            </span>
            {dirty && <span class="editor-unsaved">Unsaved</span>}
            {flash && !dirty && <span class="saved-flash">Saved</span>}
            <button
              type="button"
              class="btn-secondary"
              disabled={!dirty}
              onClick={() => void save()}
            >
              Save
            </button>
          </div>
        </div>
        {platform === "dropout" && (
          <div class="series-toolbar">
            <button
              type="button"
              class={folderView === "sources" ? "filter-chip active" : "filter-chip"}
              onClick={() => setFolderView("sources")}
            >
              Dropout seasons
            </button>
            <button
              type="button"
              class={folderView === "emby" ? "filter-chip active" : "filter-chip"}
              onClick={() => setFolderView("emby")}
            >
              Emby folders
            </button>
          </div>
        )}
        {platform === "dropout" && folderView === "emby" && layoutError && (
          <p class="settings-hint">{layoutError}</p>
        )}
        {platform === "dropout" && folderView === "emby" && !layout && !layoutError && (
          <div class="layout-folders" aria-busy="true">
            <Skeleton width="9rem" height="1em" />
            <div style={{ marginTop: "10px" }}>
              <Skeleton width="100%" height="2.2em" />
            </div>
            <div style={{ marginTop: "8px" }}>
              <Skeleton width="80%" height="2.2em" />
            </div>
          </div>
        )}
        {platform === "dropout" && folderView === "emby" && layout && (
          <div class="layout-folders">
            {layout.folders.map((folder) => (
              <details key={folder.label} open>
                <summary>{folder.folder ?? folder.label}</summary>
                <ul>
                  {folder.episodes.map((ep) => (
                    <li key={`${ep.code}-${ep.title}`}>
                      {ep.code ?? "—"} {ep.title}{" "}
                      <span class="run-meta">{ep.status}</span>
                      {ep.origin && <span class="run-meta">({ep.origin})</span>}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        )}
        {!(platform === "dropout" && folderView === "emby") && (
        <>
        <h2 class="settings-heading">
          {platform === "youtube" ? "Playlists" : "Catalog URLs"}
        </h2>
        {detail.sources.some((src) => src.seasons.length > 0) && (
          <div class="series-toolbar">
            <button
              type="button"
              class="btn-ghost"
              onClick={() => setSeriesFolds(uiKey, seasonFoldMap(detail.sources, true))}
            >
              Expand all
            </button>
            <button
              type="button"
              class="btn-ghost"
              onClick={() => setSeriesFolds(uiKey, seasonFoldMap(detail.sources, false))}
            >
              Collapse all
            </button>
          </div>
        )}
        <form
          class="series-toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            void addUrl();
          }}
        >
          <input
            type="url"
            class="series-search"
            placeholder="https://…"
            value={urlDraft}
            disabled={addingUrl || runActive}
            data-testid="source-add"
            onInput={(e) =>
              setUrlDraft((e.currentTarget as HTMLInputElement).value)
            }
          />
          <button
            type="submit"
            class="btn-secondary"
            disabled={addingUrl || runActive || !urlDraft.trim()}
          >
            Add URL
          </button>
        </form>
        {runActive && (
          <div class="banner banner-warn">a run is in progress</div>
        )}
        {error && <div class="validation-error">{error}</div>}
        {detail.sources.map((source, sourceId) => (
          <SourceBlock
            key={source.id}
            platform={platform}
            source={source}
            sourceId={sourceId}
            runActive={runActive}
            episodeMap={episodeMap}
            loadingMap={loadingMap}
            onDisk={onDisk}
            seasonOpen={(seasonId) => isSeasonOpen(seasonFolds, sourceId, seasonId)}
            onToggleOpen={(seasonId) => {
              const key = seasonFoldKey(sourceId, seasonId);
              patchSeriesFold(
                uiKey,
                key,
                !isSeasonOpen(seasonFolds, sourceId, seasonId),
              );
            }}
            onRefresh={() => void refreshSource(sourceId)}
            onRemove={() => void removeSource(sourceId)}
            onToggleEnabled={(seasonId) =>
              void toggleSeasonEnabled(sourceId, seasonId)
            }
            onTitleChange={(seasonId, value) =>
              void updateSeasonTitle(sourceId, seasonId, value)
            }
            onSkip={(seasonId, ep) => void toggleSkip(sourceId, seasonId, ep)}
            onRemap={(seasonId, ep) =>
              setRemap({ sourceId, seasonId, episode: ep })
            }
          />
        ))}
        {pendingUrl && (
          <div class="source-block">
            <div class="source-head">
              <span class="editor-filename">{pendingUrl}</span>
              {pendingError && (
                <button
                  type="button"
                  class="btn-ghost"
                  onClick={() => {
                    setPendingUrl(null);
                    setPendingError(null);
                  }}
                >
                  Dismiss
                </button>
              )}
            </div>
            <p class="settings-hint">
              {addingUrl ? "Discovering seasons…" : pendingError ?? ""}
            </p>
          </div>
        )}
        {platform === "dropout" && (
          <TvdbSkipPanel
            detail={detail}
            onChange={(tvdb_skip) => {
              void persist({ ...detail, tvdb_skip }).catch((err) => {
                setError(
                  err instanceof ApiError ? err.message : "Update failed",
                );
              });
            }}
          />
        )}
        </>
        )}
        {platform === "dropout" && detail.tvdb_id != null && (
          <section class="sonarr-check" id="sonarr-check">
            <h2 class="settings-heading">Sonarr check</h2>
            {checkError && <p class="settings-hint">{checkError}</p>}
            {check && (
              <>
                {check.ok && <p class="saved-flash">ok</p>}
                {check.missing.length > 0 && (
                  <>
                    <h3>Missing</h3>
                    <ul>
                      {check.missing.map((row) => (
                        <li key={row.code} class="sonarr-check-row">
                          <span>
                            {row.code} {row.title}
                            {row.hints?.length
                              ? ` — ${row.hints.map((h) => h.text).join("; ")}`
                              : ""}
                          </span>
                          <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => {
                              void persist({
                                ...detail,
                                tvdb_skip: addTvdbSkip(
                                  detail.tvdb_skip,
                                  row.season,
                                  row.episode,
                                ),
                              }).catch((err) => {
                                setError(
                                  err instanceof ApiError
                                    ? err.message
                                    : "Skip update failed",
                                );
                              });
                            }}
                          >
                            Add to skip list
                          </button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {check.warnings.length > 0 && (
                  <>
                    <h3>Warnings</h3>
                    <ul>
                      {check.warnings.map((row) => (
                        <li key={row.code}>{row.code} {row.detail}</li>
                      ))}
                    </ul>
                  </>
                )}
                {check.title_mismatches?.length > 0 && (
                  <>
                    <h3>On disk title differs</h3>
                    <ul>
                      {check.title_mismatches.map((row) => (
                        <li key={row.code}>
                          {row.code} {row.file_title} (Sonarr: {row.sonarr_title})
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            )}
          </section>
        )}
      </section>
      {remap && (
        <RemapModal
          tvdbId={detail.tvdb_id}
          episode={remap.episode}
          onClose={() => setRemap(null)}
          onSave={(fields) =>
            void applyRemap(remap.sourceId, remap.seasonId, remap.episode, fields)
          }
        />
      )}
      {editOpen && (
        <CreateSeriesModal
          mode="edit"
          existing={existing}
          initial={{
            name: detail.name,
            platform,
            path: detail.path,
            tvdb_id: detail.tvdb_id,
          }}
          fileLabel={detail.file}
          onClose={() => setEditOpen(false)}
          onCreate={async (body) => {
            await persist({
              ...detail,
              name: body.name,
              path: body.path,
              tvdb_id: body.tvdb_id,
            });
            setEditOpen(false);
            flashSaved();
          }}
        />
      )}
    </div>
  );
}
