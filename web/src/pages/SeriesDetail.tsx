// Accepted deviation: SeriesDetail stays single-file. Dirty tracking, catalog,
// and UI-store hooks were extracted (no behavior change); splitting the page
// component itself was skipped as churn with no user-facing gain.
import { useMutation, useQuery, useQueryClient } from "@tanstack/preact-query";
import { useSelector } from "@tanstack/preact-store";
import { useLocation } from "preact-iso";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  ApiError,
  type DropoutCheck,
  type SeriesDetail as SeriesDetailModel,
  type SeriesEpisode,
  type SeriesSeason,
  apiClient,
} from "../api";
import { logoutAndClear } from "../auth";
import { ConfirmModal } from "../components/ConfirmModal";
import { Header } from "../components/Header";
import { Poster, posterLetter } from "../components/Poster";
import { type RefreshPart, RefreshSplit } from "../components/RefreshSplit";
import { SeriesDetailSkeleton, Skeleton } from "../components/Skeleton";
import { pushToast } from "../components/Toast";
import { UrlField } from "../components/UrlField";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { FindSourceModal } from "../components/series/FindSourceModal";
import { LibrarySeasons } from "../components/series/LibrarySeasons";
import { RemapModal } from "../components/series/RemapModal";
import { SeriesYamlPanel } from "../components/series/SeriesYamlPanel";
import { SonarrCheckPanel } from "../components/series/SonarrCheckPanel";
import { SourceBlock } from "../components/series/SourceBlock";
import { TvdbSkipPanel } from "../components/series/TvdbSkipPanel";
import { isHttpUrl, parseOptionalInt, urlMatchesPlatform } from "../formValidation";
import { useOnline } from "../hooks/useOnline";
import { moveRovingIndex } from "../hooks/useRoving";
import { go } from "../nav";
import { queryKeys } from "../queryKeys";
import { formatRelativeTime } from "../relativeTime";
import { useSeriesCatalog } from "../seriesCatalog";
import { invalidateSeriesState } from "../seriesInvalidate";
import {
  beginRefresh,
  endRefresh,
  refreshSeriesKey,
  useSeriesRefreshing,
} from "../seriesRefreshStore";
import {
  type SeriesTab,
  patchSeriesFold,
  seriesUiKey,
  seriesUiStore,
  setFolderViewPref,
  setSeriesFolds,
} from "../seriesUiStore";
import {
  addTvdbSkip,
  buildDestMap,
  catalogEpisodes,
  defaultDestSeason,
  effectiveConfigValue,
  isSeasonOpen,
  parseSeriesPath,
  remapCandidatesForMissing,
  seasonFoldKey,
  seasonFoldMap,
  sonarrSeriesUrl,
  tvdbSeriesUrl,
} from "../seriesView";
import { tvdbSkipKey } from "../types";
import { writeSearch } from "../urlState";
import { useAppRun } from "../useAppQueries";

const EMPTY_FOLDS: Record<string, boolean> = {};

function seasonAt(
  detail: SeriesDetailModel,
  sourceId: number,
  seasonId: number,
): SeriesSeason | undefined {
  return detail.sources[sourceId]?.seasons[seasonId];
}

export function SeriesDetail() {
  const { path } = useLocation();
  const parsed = parseSeriesPath(path);
  const platform = parsed?.platform ?? "dropout";
  const slug = parsed?.slug ?? "";
  const queryClient = useQueryClient();
  const online = useOnline();
  const runQuery = useAppRun();
  const run = runQuery.data;
  const seriesKey = queryKeys.series(platform, slug);

  const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  const viewParam = params.get("view");
  const [folderView, setFolderView] = useState<SeriesTab>(
    viewParam === "sources" || viewParam === "yaml" ? viewParam : "emby",
  );
  const refreshing = useSeriesRefreshing(platform, slug);
  const cached = queryClient.getQueryData<SeriesDetailModel>(seriesKey) ?? null;
  const [detail, setDetail] = useState<SeriesDetailModel | null>(cached);
  const [saved, setSaved] = useState<SeriesDetailModel | null>(cached);
  const [dirtyTick, setDirtyTick] = useState(0);
  const [serverChanged, setServerChanged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Inline (non-global) errors: dest parse failures keyed by season, and the
  // only_episodes guard keyed by episode id so it renders next to its row.
  const [destErrors, setDestErrors] = useState<Record<string, string>>({});
  const [skipErrors, setSkipErrors] = useState<Record<string, string>>({});
  const [modalError, setModalError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [refreshingSourceId, setRefreshingSourceId] = useState<number | null>(null);
  const [removingSourceId, setRemovingSourceId] = useState<number | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [pendingRemoveSource, setPendingRemoveSource] = useState<number | null>(null);
  const [unsavedTo, setUnsavedTo] = useState<string | null>(null);
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
  const seasonFolds = useSelector(seriesUiStore, (state) => state.folds[uiKey] ?? EMPTY_FOLDS);
  const { episodeMap, loadingMap, onDisk } = useSeriesCatalog(
    platform,
    slug,
    seriesQuery.data?.sources,
  );
  const checkQuery = useQuery({
    queryKey: queryKeys.check(slug, tvdbSkipKey(detail?.tvdb_skip)),
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
  const checkError = checkQuery.error instanceof Error ? checkQuery.error.message : null;
  const checkLoading =
    Boolean(detail?.tvdb_id) &&
    platform === "dropout" &&
    (checkQuery.isPending || (checkQuery.isFetching && !checkQuery.data));
  const catalog = useMemo(
    () => catalogEpisodes(detail?.sources, episodeMap),
    [detail?.sources, episodeMap],
  );
  const destMap = useMemo(
    () => buildDestMap(catalog, sonarrMetaQuery.data?.episodes, onDisk, detail?.tvdb_skip),
    [catalog, sonarrMetaQuery.data?.episodes, onDisk, detail?.tvdb_skip],
  );
  const sonarrUrl = effectiveConfigValue(configQuery.data?.fields.sonarr_url);
  const sonarrHref =
    detail?.tvdb_id != null && sonarrUrl
      ? sonarrSeriesUrl(sonarrUrl, sonarrMetaQuery.data?.title_slug, detail.tvdb_id)
      : "";

  // Counter-based dirty tracking: incremented on local edit, reset on save/load.
  // Avoids JSON.stringify per render; server-changed check still compares on refetch.
  const dirty = dirtyTick > 0;
  const markDirty = () => setDirtyTick((tick) => tick + 1);
  const runActive = run?.status === "running" || run?.status === "stopping";
  const prevRunStatus = useRef(run?.status);

  useEffect(() => {
    if (!parsed) go("/series", { replace: true });
  }, [parsed]);

  useEffect(() => {
    writeSearch({ view: folderView === "emby" ? null : folderView });
    setFolderViewPref(uiKey, folderView);
  }, [folderView, uiKey]);

  useEffect(() => {
    if (!seriesQuery.data) return;
    if (dirty) {
      if (JSON.stringify(seriesQuery.data) !== JSON.stringify(saved)) {
        setServerChanged(true);
      }
      return;
    }
    setDetail(seriesQuery.data);
    setSaved(seriesQuery.data);
    setDirtyTick(0);
  }, [seriesQuery.data, dirty, saved]);

  useEffect(() => {
    if (seriesQuery.data) setError(null);
    if (seriesQuery.error instanceof Error) {
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
    if (
      prevRunStatus.current === "running" &&
      (run?.status === "exited" || run?.status === "idle")
    ) {
      void invalidateSeriesState(queryClient, [{ platform, slug, tvdb_id: detail?.tvdb_id }]);
    }
    prevRunStatus.current = run?.status;
  }, [run?.status, platform, slug, queryClient]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (window.location.hash !== "#sonarr-check") return;
    document.getElementById("sonarr-check")?.scrollIntoView({ behavior: "smooth" });
  }, [check, checkError, detail]);

  const flashSaved = (message = "Saved") => {
    setFlash(true);
    pushToast(message);
    window.setTimeout(() => setFlash(false), 1600);
  };

  const persistMut = useMutation({
    mutationFn: (next: SeriesDetailModel) => apiClient.putSeries(platform, slug, next),
    onMutate: async (next) => {
      const prev = queryClient.getQueryData<SeriesDetailModel>(seriesKey);
      queryClient.setQueryData(seriesKey, next);
      setDetail(next);
      markDirty();
      return { prev };
    },
    onError: (err, _next, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(seriesKey, ctx.prev);
        setDetail(ctx.prev);
      }
      setDirtyTick(0);
      const message = err instanceof ApiError ? err.message : "Save failed";
      setError(message);
      pushToast(message, "alert");
    },
    onSuccess: (body) => {
      queryClient.setQueryData(seriesKey, body);
      setDetail(body);
      setSaved(body);
      setDirtyTick(0);
      void invalidateSeriesState(queryClient, [{ platform, slug, tvdb_id: body.tvdb_id }]);
    },
  });

  const persist = async (next: SeriesDetailModel) => {
    const body = await persistMut.mutateAsync(next);
    return body;
  };

  const addUrlMut = useMutation({
    mutationFn: (url: string) => apiClient.addSeriesSource(platform, slug, url),
    onMutate: async (url) => {
      await queryClient.cancelQueries({ queryKey: seriesKey });
      const prev = queryClient.getQueryData<SeriesDetailModel>(seriesKey);
      const prevDetail = detail;
      setPendingUrl(url);
      setPendingError(null);
      setError(null);
      markDirty();
      return { prev, prevDetail };
    },
    onError: (err, _url, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(seriesKey, ctx.prev);
        if (ctx.prevDetail) setDetail(ctx.prevDetail);
      }
      setDirtyTick(0);
      const message = err instanceof ApiError ? err.message : "Add URL failed";
      setPendingError(message);
      pushToast(message, "alert");
    },
    onSuccess: (body) => {
      queryClient.setQueryData(seriesKey, body);
      setDetail(body);
      setSaved(body);
      setDirtyTick(0);
      setUrlDraft("");
      setPendingUrl(null);
      setPendingError(null);
      flashSaved("Source added");
    },
    onSettled: (_body, _err, _url, ctx) => {
      void invalidateSeriesState(queryClient, [
        { platform, slug, tvdb_id: ctx?.prevDetail?.tvdb_id ?? detail?.tvdb_id },
      ]);
    },
  });

  const removeSourceMut = useMutation({
    mutationFn: (sourceId: number) => apiClient.deleteSeriesSource(platform, slug, sourceId),
    onMutate: async (sourceId) => {
      await queryClient.cancelQueries({ queryKey: seriesKey });
      const prev = queryClient.getQueryData<SeriesDetailModel>(seriesKey);
      const prevDetail = detail;
      setRemovingSourceId(sourceId);
      // Optimistic removal.
      if (detail) {
        const next: SeriesDetailModel = {
          ...detail,
          sources: detail.sources.filter((_, idx) => idx !== sourceId),
        };
        queryClient.setQueryData(seriesKey, next);
        setDetail(next);
      }
      markDirty();
      return { prev, prevDetail };
    },
    onError: (err, _sourceId, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(seriesKey, ctx.prev);
        if (ctx.prevDetail) setDetail(ctx.prevDetail);
      }
      setDirtyTick(0);
      const message = err instanceof ApiError ? err.message : "Remove failed";
      setError(message);
      pushToast(message, "alert");
    },
    onSuccess: (body) => {
      queryClient.setQueryData(seriesKey, body);
      setDetail(body);
      setSaved(body);
      setDirtyTick(0);
      pushToast("Source removed");
    },
    onSettled: (_body, _err, _sourceId, ctx) => {
      setRemovingSourceId(null);
      void invalidateSeriesState(queryClient, [
        { platform, slug, tvdb_id: ctx?.prevDetail?.tvdb_id ?? detail?.tvdb_id },
      ]);
    },
  });

  const refreshSourceMut = useMutation({
    mutationFn: (sourceId: number) => apiClient.refreshSeriesSource(platform, slug, sourceId),
    onMutate: async (sourceId) => {
      await queryClient.cancelQueries({ queryKey: seriesKey });
      const prev = queryClient.getQueryData<SeriesDetailModel>(seriesKey);
      const prevDetail = detail;
      setRefreshingSourceId(sourceId);
      setError(null);
      markDirty();
      return { prev, prevDetail };
    },
    onError: (err, sourceId, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(seriesKey, ctx.prev);
      }
      const message = err instanceof ApiError ? err.message : "Refresh failed";
      const base = ctx?.prevDetail ?? detail;
      if (base) {
        const next: SeriesDetailModel = {
          ...base,
          sources: base.sources.map((src, idx) =>
            idx === sourceId ? { ...src, error: message } : src,
          ),
        };
        setDetail(next);
      }
      // Error display is not a dirty edit; clear the in-flight mark.
      setDirtyTick(0);
      pushToast(message, "alert");
    },
    onSuccess: (body) => {
      queryClient.setQueryData(seriesKey, body);
      setDetail(body);
      setSaved(body);
      setDirtyTick(0);
      pushToast("Source refreshed");
    },
    onSettled: (_body, _err, _sourceId, ctx) => {
      setRefreshingSourceId(null);
      void invalidateSeriesState(queryClient, [
        { platform, slug, tvdb_id: ctx?.prevDetail?.tvdb_id ?? detail?.tvdb_id },
      ]);
    },
  });

  const addingUrl = addUrlMut.isPending;
  // Covers add/remove/refresh plus skip/toggle/remap/title/dest (all via persistMut).
  const mutationBusy =
    addingUrl || persistMut.isPending || removeSourceMut.isPending || refreshSourceMut.isPending;

  const save = async () => {
    if (!detail || runActive) return;
    setError(null);
    try {
      await persist(detail);
      flashSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  };

  const addUrl = () => {
    const url = urlDraft.trim();
    if (!url || runActive || addUrlMut.isPending) return;
    setUrlError(null);
    if (!isHttpUrl(url)) {
      setUrlError("Enter a valid http(s) URL");
      return;
    }
    if (!urlMatchesPlatform(url, platform)) {
      setUrlError(`That URL does not look like a ${platform} link`);
      return;
    }
    if (detail?.sources.some((src) => src.url === url)) {
      setUrlError("That source is already attached");
      return;
    }
    addUrlMut.mutate(url);
  };

  const removeSource = (sourceId: number) => {
    if (!detail || removeSourceMut.isPending) return;
    removeSourceMut.mutate(sourceId);
  };

  // Destructive-action policy (Phase 6 decision): skip/remap/enable/title/
  // dest/tvdb_skip/source-add apply immediately with a toast (no undo);
  // delete series and risky source removal are confirm-only modals
  // (no type-to-confirm, no undo). Non-risky source removal stays immediate
  // with a "Source removed" toast from removeSourceMut.onSuccess.
  const askRemoveSource = (sourceId: number) => {
    if (!detail) return;
    const src = detail.sources[sourceId];
    if (!src) return;
    const risky = src.seasons.some(
      (se) =>
        se.remaps.length || (se.only_episodes && se.only_episodes.length) || se.skip_ids.length,
    );
    if (risky) {
      setPendingRemoveSource(sourceId);
      return;
    }
    removeSource(sourceId);
  };

  const refreshSource = (sourceId: number) => {
    if (runActive || !detail || refreshSourceMut.isPending) return;
    refreshSourceMut.mutate(sourceId);
  };

  const saveSourceUrl = async (sourceId: number, url: string) => {
    if (!detail) return;
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, idx) => (idx === sourceId ? { ...src, url } : src)),
    };
    try {
      await persist(next);
      refreshSource(sourceId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update URL failed");
    }
  };

  const updateSeasonTitle = async (sourceId: number, seasonId: number, value: string) => {
    if (!detail) return;
    const season = seasonAt(detail, sourceId, seasonId);
    if (!season) return;
    const title = value.trim() || null;
    if ((season.title ?? null) === title) return;
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) => (seid !== seasonId ? se : { ...se, title })),
            },
      ),
    };
    try {
      await persist(next);
      flashSaved("Title updated");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const updateSeasonDest = async (sourceId: number, seasonId: number, value: string) => {
    if (!detail) return;
    const trimmed = value.trim();
    const parsedDest = parseOptionalInt(trimmed);
    const destKey = `${sourceId}-${seasonId}`;
    if (!parsedDest.ok) {
      setDestErrors((current) => ({
        ...current,
        [destKey]: "Destination season must be a number",
      }));
      return;
    }
    const parsed = parsedDest.value;
    const season = seasonAt(detail, sourceId, seasonId);
    if (!season) return;
    const prev = defaultDestSeason(season);
    if (parsed === season.to_season) return;
    if (parsed == null && season.to_season == null) return;
    const remaps = season.remaps.map((remap) => {
      if (remap.skip) return remap;
      if (remap.to_season == null || remap.to_season === prev) {
        return parsed == null ? remap : { ...remap, to_season: parsed };
      }
      return remap;
    });
    const next: SeriesDetailModel = {
      ...detail,
      sources: detail.sources.map((src, sid) =>
        sid !== sourceId
          ? src
          : {
              ...src,
              seasons: src.seasons.map((se, seid) =>
                seid !== seasonId ? se : { ...se, to_season: parsed, remaps },
              ),
            },
      ),
    };
    try {
      await persist(next);
      flashSaved("Destination updated");
      setDestErrors((current) => {
        if (!(destKey in current)) return current;
        const rest = { ...current };
        delete rest[destKey];
        return rest;
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const toggleSeasonEnabled = async (sourceId: number, seasonId: number) => {
    if (!detail) return;
    const season = seasonAt(detail, sourceId, seasonId);
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
      flashSaved(season?.enabled ? "Season disabled" : "Season enabled");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  };

  const toggleSkip = async (sourceId: number, seasonId: number, episode: SeriesEpisode) => {
    if (!detail) return;
    const season = seasonAt(detail, sourceId, seasonId);
    if (!season) return;
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
          setSkipErrors((current) => ({
            ...current,
            [episode.id]: "only_episodes cannot be empty",
          }));
          return;
        }
        list.delete(num);
      }
      nextSeason = { ...season, only_episodes: [...list].sort((a, b) => a - b) };
    } else {
      const remaps = season.remaps.filter((r) => r.dropout_episode !== episode.source_episode);
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
              seasons: src.seasons.map((se, seid) => (seid === seasonId ? nextSeason : se)),
            },
      ),
    };
    try {
      await persist(next);
      flashSaved("Updated skip");
      setSkipErrors((current) => {
        if (!(episode.id in current)) return current;
        const rest = { ...current };
        delete rest[episode.id];
        return rest;
      });
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
    const season = seasonAt(detail, sourceId, seasonId);
    if (!season) return;
    const remaps = season.remaps.filter((r) => r.dropout_episode !== episode.source_episode);
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
              seasons: src.seasons.map((se, seid) => (seid === seasonId ? { ...se, remaps } : se)),
            },
      ),
    };
    try {
      await persist(next);
      setRemap(null);
      setModalError(null);
      flashSaved("Remap saved");
      void queryClient.invalidateQueries({ queryKey: queryKeys.check(slug) });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Remap failed";
      setModalError(message);
    }
  };

  const deleteSeries = async () => {
    if (!detail || runActive) return;
    try {
      await apiClient.deleteSeries(platform, slug);
      pushToast(`Deleted ${detail.name}`);
      go("/series");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Delete failed";
      setModalError(message);
    }
  };

  const logout = async () => {
    if (dirty) {
      setUnsavedTo("logout");
      return;
    }
    await logoutAndClear();
  };

  const navigate = (url: string) => {
    if (dirty) {
      setUnsavedTo(url);
      return;
    }
    go(url);
  };

  const refreshMetadata = async (part: RefreshPart = "all") => {
    if (runActive) return;
    const key = refreshSeriesKey(platform, slug);
    beginRefresh([key]);
    try {
      const body = await apiClient.refreshSeries(
        [{ platform, slug }],
        part === "all" ? undefined : [part],
      );
      const failed = body.results.find((row) => row.error);
      if (failed?.error) {
        setError(failed.error);
        pushToast(failed.error, "alert");
      } else {
        pushToast("Refresh complete");
      }
      await invalidateSeriesState(queryClient, [{ platform, slug, tvdb_id: detail?.tvdb_id }]);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Refresh failed";
      setError(message);
      pushToast(message, "alert");
    } finally {
      endRefresh([key]);
    }
  };

  if (!detail) {
    return (
      <>
        <Header current="series" onLogout={() => void logout()} onNavigate={navigate} />
        <div class="series-shell">
          <main class="series-page" id="main">
            <a
              href="/series"
              class="header-link"
              onClick={(e) => {
                e.preventDefault();
                navigate("/series");
              }}
            >
              ← Shows
            </a>
            {error ? (
              <div class="error-card" role="alert">
                <p>{error}</p>
                <button
                  type="button"
                  class="btn-secondary"
                  onClick={() => void seriesQuery.refetch()}
                >
                  Retry
                </button>
              </div>
            ) : (
              <section class="settings-section" role="status">
                <h1 class="settings-title">Loading show</h1>
                <SeriesDetailSkeleton />
              </section>
            )}
          </main>
        </div>
      </>
    );
  }

  const mappingView = folderView === "sources";
  const tvdbHref = detail.tvdb_id != null ? tvdbSeriesUrl(detail.tvdb_id) : "";

  return (
    <>
      <Header current="series" onLogout={() => void logout()} onNavigate={navigate} />
      <div class="series-shell">
        <main class="series-page" id="main">
          {!online && (
            <div class="banner banner-warn" role="status">
              You appear offline.
            </div>
          )}
          {serverChanged && (
            <div class="banner banner-warn" role="status">
              Server data changed.{" "}
              <button
                type="button"
                class="btn-ghost"
                onClick={() => {
                  if (seriesQuery.data) {
                    setDetail(seriesQuery.data);
                    setSaved(seriesQuery.data);
                    setDirtyTick(0);
                    setServerChanged(false);
                  }
                }}
              >
                Reload
              </button>
            </div>
          )}
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
                ← Shows
              </a>
              <div class="series-hero-links">
                {tvdbHref && (
                  <a class="ext-link" href={tvdbHref} target="_blank" rel="noreferrer">
                    TVDB
                  </a>
                )}
                {sonarrHref && (
                  <a class="ext-link" href={sonarrHref} target="_blank" rel="noreferrer">
                    Sonarr
                  </a>
                )}
              </div>
            </div>
            <div class="series-hero-row">
              <Poster
                src={detail.poster_url}
                letter={posterLetter(detail.name)}
                size="lg"
                alt={detail.name}
              />
              <div class="series-hero-copy">
                <h1 class="settings-title">{detail.name}</h1>
                <p class="series-map-lead">{platform === "youtube" ? "YouTube" : "Dropout"}</p>
                {refreshing ? (
                  <div class="skel-meta">
                    <Skeleton width="6.5rem" />
                    <Skeleton width="7rem" />
                    <Skeleton width="6rem" />
                  </div>
                ) : (
                  <p class="series-row-meta">
                    <span>
                      {detail.season_count} {detail.season_count === 1 ? "season" : "seasons"}
                    </span>
                    {detail.path ? <span>{detail.path}</span> : null}
                  </p>
                )}
                <div class="series-hero-badges">
                  <span class={detail.platform === "youtube" ? "badge-youtube" : "badge-dropout"}>
                    {detail.platform === "youtube" ? "YouTube" : "Dropout.tv"}
                  </span>
                  {dirty && <span class="editor-unsaved">Unsaved</span>}
                  {flash && !dirty && <span class="saved-flash">Saved</span>}
                </div>
              </div>
              <div class="series-hero-actions">
                <RefreshSplit
                  disabled={refreshing || runActive}
                  busy={refreshing}
                  showSonarr={detail.tvdb_id != null}
                  title={runActive ? "Blocked while a run is in progress" : undefined}
                  onRefresh={(part) => void refreshMetadata(part)}
                />
                <p class="refresh-stamps">
                  {[
                    detail.refreshed?.listings &&
                      `Listings ${formatRelativeTime(detail.refreshed.listings)}`,
                    detail.refreshed?.disk && `Disk ${formatRelativeTime(detail.refreshed.disk)}`,
                    detail.refreshed?.sonarr &&
                      `Sonarr ${formatRelativeTime(detail.refreshed.sonarr)}`,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "Not refreshed yet"}
                </p>
                <div class="series-hero-buttons">
                  <button
                    type="button"
                    class="btn-ghost"
                    disabled={runActive || persistMut.isPending}
                    title={runActive ? "Blocked while a run is in progress" : undefined}
                    onClick={() => setEditOpen(true)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    class="btn-danger"
                    disabled={runActive}
                    title={runActive ? "Blocked while a run is in progress" : undefined}
                    onClick={() => setDeleteOpen(true)}
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    class="btn-secondary"
                    disabled={!dirty || runActive || persistMut.isPending}
                    title={runActive ? "Blocked while a run is in progress" : undefined}
                    onClick={() => void save()}
                  >
                    Save
                  </button>
                </div>
              </div>
            </div>
          </section>
          <div class="map-switch" role="tablist" aria-label="Show view">
            {(
              [
                { key: "emby", label: "Library" },
                { key: "sources", label: "Mapping" },
                { key: "yaml", label: "YAML" },
              ] as const
            ).map((tab, index) => {
              const selected = folderView === tab.key;
              const tabs = ["emby", "sources", "yaml"] as const;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  id={`map-tab-${tab.key}`}
                  aria-selected={selected}
                  aria-controls={`map-panel-${tab.key}`}
                  tabIndex={selected ? 0 : -1}
                  class={selected ? "filter-chip active" : "filter-chip"}
                  onClick={() => setFolderView(tab.key)}
                  onKeyDown={(e) => {
                    const next = moveRovingIndex(e as unknown as KeyboardEvent, 3, index);
                    if (next != null) {
                      e.preventDefault();
                      const target = tabs[next];
                      if (!target) return;
                      setFolderView(target);
                      requestAnimationFrame(() =>
                        document.getElementById(`map-tab-${target}`)?.focus(),
                      );
                    }
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
          {folderView === "emby" && (
            <div id="map-panel-emby" role="tabpanel" aria-labelledby="map-tab-emby">
              <LibrarySeasons
                destMap={destMap}
                loading={
                  Object.values(loadingMap).some(Boolean) ||
                  (detail.tvdb_id != null && sonarrMetaQuery.isPending)
                }
                refreshing={refreshing}
                onFind={(slot) => {
                  const fromCheck = check?.missing.find(
                    (row) => row.season === slot.destSeason && row.episode === slot.destEpisode,
                  );
                  if (typeof window !== "undefined") {
                    window.location.hash = "sonarr-check";
                  }
                  setRemap({
                    missing: fromCheck ?? {
                      season: slot.destSeason,
                      episode: slot.destEpisode,
                      code: slot.code,
                      title: slot.title,
                      hints: [],
                    },
                  });
                }}
              />
            </div>
          )}
          {mappingView && (
            <div id="map-panel-sources" role="tabpanel" aria-labelledby="map-tab-sources">
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
                    onChange={(value) => {
                      setUrlDraft(value);
                      setUrlError(null);
                    }}
                  />
                  <button
                    type="submit"
                    class="btn-secondary"
                    disabled={addingUrl || runActive || !urlDraft.trim()}
                    title={runActive ? "Blocked while a run is in progress" : undefined}
                  >
                    {addingUrl ? (
                      <>
                        <span class="spinner" aria-hidden="true" /> Adding…
                      </>
                    ) : (
                      "Add"
                    )}
                  </button>
                </form>
                {urlError && (
                  <div class="validation-error" role="alert">
                    {urlError}
                  </div>
                )}
                {runActive && <div class="banner banner-warn">a run is in progress</div>}
                {error && (
                  <div class="validation-error" role="alert">
                    {error}
                  </div>
                )}
                {detail.sources.length === 0 && !pendingUrl && (
                  <p class="empty-state">No playlists yet. Paste a URL above to add one.</p>
                )}
                {detail.sources.map((source, sourceId) => (
                  <SourceBlock
                    key={sourceId}
                    platform={platform}
                    source={source}
                    sourceId={sourceId}
                    episodeMap={episodeMap}
                    loadingMap={loadingMap}
                    refreshing={refreshing}
                    sourceBusy={refreshingSourceId === sourceId || removingSourceId === sourceId}
                    onDisk={onDisk}
                    disabled={runActive || mutationBusy}
                    destErrors={destErrors}
                    skipErrors={skipErrors}
                    seasonOpen={(seasonId) => isSeasonOpen(seasonFolds, sourceId, seasonId)}
                    onToggleOpen={(seasonId) => {
                      const key = seasonFoldKey(sourceId, seasonId);
                      patchSeriesFold(uiKey, key, !isSeasonOpen(seasonFolds, sourceId, seasonId));
                    }}
                    onRemove={() => askRemoveSource(sourceId)}
                    onSaveUrl={(url) => void saveSourceUrl(sourceId, url)}
                    onRefresh={() => refreshSource(sourceId)}
                    onToggleEnabled={(seasonId) => void toggleSeasonEnabled(sourceId, seasonId)}
                    onTitleChange={(seasonId, value) =>
                      void updateSeasonTitle(sourceId, seasonId, value)
                    }
                    onDestChange={(seasonId, value) =>
                      void updateSeasonDest(sourceId, seasonId, value)
                    }
                    onSkip={(seasonId, ep) => void toggleSkip(sourceId, seasonId, ep)}
                    onRemap={(seasonId, ep) => setRemap({ sourceId, seasonId, episode: ep })}
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
                      {addingUrl ? (
                        <>
                          <span class="spinner" aria-hidden="true" /> Discovering seasons…
                        </>
                      ) : (
                        (pendingError ?? "")
                      )}
                    </p>
                  </div>
                )}
              </section>
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
                    })
                      .then(() => flashSaved("Exceptions updated"))
                      .catch((err) => {
                        setError(err instanceof ApiError ? err.message : "Skip update failed");
                      });
                  }}
                  onRemap={(row) => setRemap({ missing: row })}
                />
              )}
              {platform === "dropout" && (
                <section class="settings-section">
                  <TvdbSkipPanel
                    detail={detail}
                    onChange={(tvdb_skip) => {
                      void persist({ ...detail, tvdb_skip })
                        .then(() => flashSaved("Exceptions updated"))
                        .catch((err) => {
                          setError(err instanceof ApiError ? err.message : "Update failed");
                        });
                    }}
                  />
                </section>
              )}
            </div>
          )}
          {folderView === "yaml" && (
            <div id="map-panel-yaml" role="tabpanel" aria-labelledby="map-tab-yaml">
              <p class="settings-section-lead">
                Edit this show&apos;s YAML directly. Saving reloads the rest of the page from the
                file.
              </p>
              <SeriesYamlPanel
                platform={platform}
                slug={slug}
                onSaved={(body) => {
                  queryClient.setQueryData(seriesKey, body);
                  setDetail(body);
                  setSaved(body);
                  setDirtyTick(0);
                  setServerChanged(false);
                  flashSaved("YAML saved");
                  void invalidateSeriesState(queryClient, [
                    { platform: body.platform, slug: body.slug, tvdb_id: body.tvdb_id },
                  ]);
                  if (body.slug !== slug) {
                    go(`/series/${body.platform}/${encodeURIComponent(body.slug)}`);
                  }
                }}
              />
            </div>
          )}
        </main>
        {remap && "episode" in remap && (
          <RemapModal
            tvdbId={detail.tvdb_id}
            episode={remap.episode}
            onClose={() => {
              setRemap(null);
              setModalError(null);
            }}
            error={modalError}
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
              void applyRemap(source.sourceId, source.seasonId, source.episode, {
                to_season: remap.missing.season,
                to_episode: remap.missing.episode,
                title: remap.missing.title,
              })
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
        {deleteOpen && (
          // Confirm-only delete (Phase 6 decision): no type-to-confirm, no undo.
          <ConfirmModal
            title={`Delete ${detail.name}?`}
            message={`This removes ${detail.inline ? `the ${detail.file} entry` : detail.file}. Library files are not deleted.`}
            confirmLabel="Delete"
            danger
            error={modalError}
            pending={false}
            onCancel={() => {
              setDeleteOpen(false);
              setModalError(null);
            }}
            onConfirm={() => {
              setDeleteOpen(false);
              void deleteSeries();
            }}
          />
        )}
        {pendingRemoveSource != null && (
          <ConfirmModal
            title="Remove this source?"
            message="This also drops its season remaps, filters, and skip lists."
            confirmLabel="Remove"
            danger
            pending={removeSourceMut.isPending}
            onCancel={() => setPendingRemoveSource(null)}
            onConfirm={() => {
              const sourceId = pendingRemoveSource;
              setPendingRemoveSource(null);
              removeSource(sourceId);
            }}
          />
        )}
        {unsavedTo && (
          <ConfirmModal
            title="Unsaved changes"
            message="Discard unsaved series changes?"
            confirmLabel="Discard"
            danger
            onCancel={() => setUnsavedTo(null)}
            onConfirm={() => {
              const next = unsavedTo;
              setUnsavedTo(null);
              if (next === "logout") {
                void logoutAndClear();
                return;
              }
              go(next);
            }}
          />
        )}
      </div>
    </>
  );
}
