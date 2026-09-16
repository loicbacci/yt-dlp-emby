import { useEffect, useMemo, useState } from "preact/hooks";
import { useLocation } from "preact-iso";
import {
  ApiError,
  type Run,
  type SeriesDetail as SeriesDetailModel,
  type SeriesEpisode,
  type SeriesSeason,
  apiClient,
} from "../api";
import { Header } from "../components/Header";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { RemapModal } from "../components/series/RemapModal";
import { SourceBlock } from "../components/series/SourceBlock";
import { TvdbSkipPanel } from "../components/series/TvdbSkipPanel";
import { go } from "../nav";
import { parseSeriesPath } from "../seriesView";

const idleRun: Run = {
  status: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
};

export function SeriesDetail() {
  const { path } = useLocation();
  const parsed = parseSeriesPath(path) ?? { platform: "dropout" as const, slug: "" };
  const { platform, slug } = parsed;

  const [run, setRun] = useState<Run>(idleRun);
  const [detail, setDetail] = useState<SeriesDetailModel | null>(null);
  const [saved, setSaved] = useState<SeriesDetailModel | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  const dirty = useMemo(
    () => JSON.stringify(detail) !== JSON.stringify(saved),
    [detail, saved],
  );
  const runActive = run.status === "running" || run.status === "stopping";

  const load = async () => {
    if (!slug) return;
    const next = await apiClient.getSeries(platform, slug);
    setDetail(next);
    setSaved(next);
  };

  useEffect(() => {
    load().catch((err) => {
      if (err instanceof ApiError && err.status === 401) go("/login");
      else setError(err instanceof Error ? err.message : "Failed to load");
    });
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

  const persist = async (next: SeriesDetailModel) => {
    const body = await apiClient.putSeries(platform, slug, next);
    setDetail(body);
    setSaved(body);
    return body;
  };

  const save = async () => {
    if (!detail) return;
    setError(null);
    try {
      await persist(detail);
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
      setDetail(body);
      setSaved(body);
      setUrlDraft("");
      setPendingUrl(null);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Add URL failed";
      setPendingError(message);
      setError(message);
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
    const body = await apiClient.deleteSeriesSource(platform, slug, sourceId);
    setDetail(body);
    setSaved(body);
  };

  const refreshSource = async (sourceId: number) => {
    if (runActive || !detail) return;
    try {
      const body = await apiClient.refreshSeriesSource(platform, slug, sourceId);
      setDetail(body);
      setSaved(body);
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
    await persist(next);
    setRemap(null);
  };

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  if (!detail) {
    return (
      <div class="series-shell">
        <Header run={run} current="series" onLogout={() => void logout()} />
        {error ? <div class="validation-error">{error}</div> : <div class="shell" />}
      </div>
    );
  }

  return (
    <div class="series-shell">
      <Header run={run} current="series" onLogout={() => void logout()} />
      <section class="card series-card">
        <div class="series-toolbar">
          <div>
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
            <h1 class="settings-title">{detail.name}</h1>
            <div class="series-row-meta">
              <span>{detail.path}</span>
              <span>{detail.file}</span>
              {detail.tvdb_id != null && <span>tvdb {detail.tvdb_id}</span>}
            </div>
            <button type="button" class="btn-ghost" onClick={() => setEditOpen(true)}>
              Edit details
            </button>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span
              class={
                detail.platform === "youtube" ? "badge-youtube" : "badge-dropout"
              }
            >
              {detail.platform === "youtube" ? "YouTube" : "Dropout.tv"}
            </span>
            {dirty && <span class="editor-unsaved">Unsaved</span>}
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
        <h2 class="settings-heading">
          {platform === "youtube" ? "Playlists" : "Catalog URLs"}
        </h2>
        <div class="series-toolbar">
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
            type="button"
            class="btn-secondary"
            disabled={addingUrl || runActive || !urlDraft.trim()}
            onClick={() => void addUrl()}
          >
            Add URL
          </button>
        </div>
        {runActive && (
          <div class="banner banner-warn">a run is in progress</div>
        )}
        {error && <div class="validation-error">{error}</div>}
        {detail.sources.map((source, sourceId) => (
          <SourceBlock
            key={source.id}
            platform={platform}
            slug={slug}
            source={source}
            sourceId={sourceId}
            runActive={runActive}
            onRefresh={() => void refreshSource(sourceId)}
            onRemove={() => void removeSource(sourceId)}
            onToggleEnabled={(seasonId) =>
              void toggleSeasonEnabled(sourceId, seasonId)
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
            </div>
            <p class="settings-hint">
              {addingUrl ? "Discovering seasons…" : pendingError ?? ""}
            </p>
            {pendingError && <div class="validation-error">{pendingError}</div>}
          </div>
        )}
        {platform === "dropout" && (
          <TvdbSkipPanel
            detail={detail}
            onChange={(tvdb_skip) => void persist({ ...detail, tvdb_skip })}
          />
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
          }}
        />
      )}
    </div>
  );
}
