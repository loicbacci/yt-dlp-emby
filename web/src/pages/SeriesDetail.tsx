import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { useLocation } from "preact-iso";
import { useQuery } from "@tanstack/preact-query";
import { useSelector } from "@tanstack/preact-store";
import {
  ApiError,
  type DropoutCheck,
  type Run,
  type SeriesDetail as SeriesDetailModel,
  type SeriesEpisode,
  type SeriesSeason,
  apiClient,
} from "../api";
import { Header } from "../components/Header";
import { SeriesDetailSkeleton } from "../components/Skeleton";
import { UrlField } from "../components/UrlField";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { DestMapPanel } from "../components/series/DestMapPanel";
import { FindSourceModal } from "../components/series/FindSourceModal";
import { RemapModal } from "../components/series/RemapModal";
import { SonarrCheckPanel } from "../components/series/SonarrCheckPanel";
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
import {
  addTvdbSkip,
  applyPackRemapsToSources,
  buildDestMap,
  catalogEpisodes,
  effectiveConfigValue,
  isSeasonOpen,
  packDestSeasonRemaps,
  parseSeriesPath,
  remapCandidatesForMissing,
  seasonFoldKey,
  seasonFoldMap,
  sonarrSeriesUrl,
  tvdbSeriesUrl,
} from "../seriesView";

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
  const [folderView, setFolderView] = useState<"sources" | "emby">("emby");
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
  const [remap, setRemap] = useState<
    | {
        sourceId: number;
        seasonId: number;
        episode: SeriesEpisode;
      }
    | { missing: DropoutCheck["missing"][number] }
    | null
  >(null);

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
  const checkQuery = useQuery({
    queryKey: [...queryKeys.check(slug), JSON.stringify(detail?.tvdb_skip ?? [])],
    queryFn: () => apiClient.getDropoutCheck(slug),
    enabled: platform === "dropout" && Boolean(slug) && detail?.tvdb_id != null,
    staleTime: 5 * 60 * 1000,
  });
  const configQuery = useQuery({
    queryKey: queryKeys.config(),
    queryFn: () => apiClient.getConfig(),
    staleTime: 60 * 1000,
  });
  const sonarrMetaQuery = useQuery({
    queryKey: queryKeys.sonarrEpisodes(detail?.tvdb_id ?? 0),
    queryFn: () => apiClient.getSonarrEpisodes(detail?.tvdb_id as number),
    enabled: platform === "dropout" && detail?.tvdb_id != null,
    staleTime: 30 * 60 * 1000,
  });
  const check = checkQuery.data ?? null;
  const checkError =
    checkQuery.error instanceof Error ? checkQuery.error.message : null;
  const checkLoading =
    Boolean(detail?.tvdb_id) &&
    platform === "dropout" &&
    (checkQuery.isPending || (checkQuery.isFetching && !checkQuery.data));
  const catalog = useMemo(
    () => catalogEpisodes(detail?.sources, episodeMap),
    [detail?.sources, episodeMap],
  );
  const destMap = useMemo(
    () =>
      buildDestMap(catalog, sonarrMetaQuery.data?.episodes, onDisk),
    [catalog, sonarrMetaQuery.data?.episodes, onDisk],
  );
  const sonarrUrl = effectiveConfigValue(configQuery.data?.fields.sonarr_url);
  const sonarrHref =
    detail?.tvdb_id != null && sonarrUrl
      ? sonarrSeriesUrl(
          sonarrUrl,
          sonarrMetaQuery.data?.title_slug,
          detail.tvdb_id,
        )
      : "";

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
      void queryClient.invalidateQueries({ queryKey: queryKeys.check(slug) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remap failed");
    }
  };

  const applyPack = async (destSeason: number) => {
    if (!detail) return;
    const changes = packDestSeasonRemaps(destSeason, catalog);
    if (!changes.length) return;
    const next: SeriesDetailModel = {
      ...detail,
      sources: applyPackRemapsToSources(detail.sources, changes),
    };
    try {
      await persist(next);
      void queryClient.invalidateQueries({ queryKey: queryKeys.check(slug) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Pack failed");
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
        <div class="series-page">
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
            <section class="settings-section">
              <SeriesDetailSkeleton />
            </section>
          )}
        </div>
      </div>
    );
  }

  const catalogView = !(platform === "dropout" && folderView === "emby");
  const tvdbHref =
    detail.tvdb_id != null ? tvdbSeriesUrl(detail.tvdb_id) : "";

  return (
    <div class="series-shell">
      <Header
        run={run}
        current="series"
        onLogout={() => void logout()}
        onNavigate={navigate}
      />
      <div class="series-page">
        <section class="settings-section series-hero">
          <div class="series-hero-top">
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
            <div class="series-hero-links">
              {tvdbHref && (
                <a
                  class="ext-link"
                  href={tvdbHref}
                  target="_blank"
                  rel="noreferrer"
                >
                  TVDB
                </a>
              )}
              {sonarrHref && (
                <a
                  class="ext-link"
                  href={sonarrHref}
                  target="_blank"
                  rel="noreferrer"
                >
                  Sonarr
                </a>
              )}
            </div>
          </div>
          <div class="series-hero-row">
            <div>
              <h1 class="settings-title">{detail.name}</h1>
              <p class="series-map-lead">
                {platform === "youtube" ? "YouTube" : "Dropout"}
                <span class="map-arrow"> → </span>
                Emby
                {detail.path ? ` · ${detail.path}` : ""}
              </p>
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
                class="btn-ghost"
                onClick={() => setEditOpen(true)}
              >
                Edit
              </button>
              <button
                type="button"
                class="btn-danger"
                onClick={() => void deleteSeries()}
              >
                Delete
              </button>
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
        </section>
        {platform === "dropout" && (
          <div class="map-switch" role="tablist" aria-label="Mapping view">
            <button
              type="button"
              role="tab"
              aria-selected={folderView === "sources"}
              class={folderView === "sources" ? "filter-chip active" : "filter-chip"}
              onClick={() => setFolderView("sources")}
            >
              Dropout catalog
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={folderView === "emby"}
              class={folderView === "emby" ? "filter-chip active" : "filter-chip"}
              onClick={() => setFolderView("emby")}
            >
              Emby library
            </button>
          </div>
        )}
        {platform === "dropout" && folderView === "emby" && (
          <DestMapPanel
            destMap={destMap}
            loading={
              Object.values(loadingMap).some(Boolean) ||
              (detail.tvdb_id != null && sonarrMetaQuery.isPending)
            }
            onRemap={(occupant) =>
              setRemap({
                sourceId: occupant.row.sourceId,
                seasonId: occupant.row.seasonId,
                episode: occupant.row.episode,
              })
            }
            onFind={(slot) =>
              setRemap({
                missing: {
                  season: slot.destSeason,
                  episode: slot.destEpisode,
                  code: slot.code,
                  title: slot.title,
                  hints: [],
                },
              })
            }
            onPack={(destSeason) => void applyPack(destSeason)}
          />
        )}
        {catalogView && (
          <section class="settings-section">
            <div class="series-section-head">
              <div>
                <h2 class="settings-heading">
                  {platform === "youtube" ? "Playlists" : "From Dropout"}
                </h2>
                <p class="settings-section-lead">
                  {platform === "youtube"
                    ? "Playlists downloaded into this series."
                    : "Catalog URLs and how each season maps into Emby."}
                </p>
              </div>
              {detail.sources.some((src) => src.seasons.length > 0) && (
                <div class="series-toolbar">
                  <button
                    type="button"
                    class="btn-ghost"
                    onClick={() =>
                      setSeriesFolds(uiKey, seasonFoldMap(detail.sources, true))
                    }
                  >
                    Expand all
                  </button>
                  <button
                    type="button"
                    class="btn-ghost"
                    onClick={() =>
                      setSeriesFolds(uiKey, seasonFoldMap(detail.sources, false))
                    }
                  >
                    Collapse all
                  </button>
                </div>
              )}
            </div>
            <form
              class="url-add"
              onSubmit={(e) => {
                e.preventDefault();
                void addUrl();
              }}
            >
              <UrlField
                value={urlDraft}
                placeholder={
                  platform === "youtube"
                    ? "Paste a YouTube playlist or channel URL"
                    : "Paste a Dropout series or season URL"
                }
                disabled={addingUrl || runActive}
                testId="source-add"
                onChange={setUrlDraft}
              />
              <button
                type="submit"
                class="btn-secondary"
                disabled={addingUrl || runActive || !urlDraft.trim()}
              >
                Add
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
                seasonOpen={(seasonId) =>
                  isSeasonOpen(seasonFolds, sourceId, seasonId)
                }
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
                  <span class="source-kicker">From</span>
                  <span class="source-url">{pendingUrl}</span>
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
          </section>
        )}
        {platform === "dropout" && detail.tvdb_id != null && (
          <SonarrCheckPanel
            detail={detail}
            check={check}
            checkError={checkError}
            loading={checkLoading}
            onSkip={(season, episode) => {
              void persist({
                ...detail,
                tvdb_skip: addTvdbSkip(detail.tvdb_skip, season, episode),
              }).catch((err) => {
                setError(
                  err instanceof ApiError ? err.message : "Skip update failed",
                );
              });
            }}
            onRemap={(row) => setRemap({ missing: row })}
          />
        )}
        {platform === "dropout" && catalogView && (
          <section class="settings-section">
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
          </section>
        )}
      </div>
      {remap && "episode" in remap && (
        <RemapModal
          tvdbId={detail.tvdb_id}
          episode={remap.episode}
          onClose={() => setRemap(null)}
          onSave={(fields) =>
            void applyRemap(remap.sourceId, remap.seasonId, remap.episode, fields)
          }
        />
      )}
      {remap && "missing" in remap && (
        <FindSourceModal
          target={{
            season: remap.missing.season,
            episode: remap.missing.episode,
            title: remap.missing.title,
          }}
          catalog={catalog}
          suggestions={remapCandidatesForMissing(catalog, remap.missing)}
          hints={remap.missing.hints}
          loading={Object.values(loadingMap).some(Boolean)}
          onClose={() => setRemap(null)}
          onSave={(source) =>
            void applyRemap(
              source.sourceId,
              source.seasonId,
              source.episode,
              {
                to_season: remap.missing.season,
                to_episode: remap.missing.episode,
                title: remap.missing.title,
              },
            )
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
