import { useState } from "preact/hooks";
import type { SeriesEpisode, SeriesSource, Source } from "../../api";
import { shortUrl } from "../../seriesView";
import { SeasonAccordion } from "./SeasonAccordion";

export function SourceBlock({
  platform,
  source,
  sourceId,
  runActive,
  episodeMap,
  loadingMap,
  refreshing,
  onDisk,
  seasonOpen,
  onToggleOpen,
  onRefresh,
  onRemove,
  onSaveUrl,
  onToggleEnabled,
  onTitleChange,
  onSkip,
  onRemap,
}: {
  platform: Source;
  source: SeriesSource;
  sourceId: number;
  runActive: boolean;
  episodeMap: Record<string, SeriesEpisode[]>;
  loadingMap: Record<string, boolean>;
  refreshing?: boolean;
  onDisk: ReadonlySet<string>;
  seasonOpen: (seasonId: number) => boolean;
  onToggleOpen: (seasonId: number) => void;
  onRefresh: () => void;
  onRemove: () => void;
  onSaveUrl: (url: string) => void;
  onToggleEnabled: (seasonId: number) => void;
  onTitleChange: (seasonId: number, value: string) => void;
  onSkip: (seasonId: number, episode: SeriesEpisode) => void;
  onRemap: (seasonId: number, episode: SeriesEpisode) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(source.url);

  const save = () => {
    const url = draft.trim();
    setEditing(false);
    if (!url || url === source.url) return;
    onSaveUrl(url);
  };

  return (
    <section class="fold-card">
      <div class="source-toolbar">
        {editing ? (
          <input
            class="url-edit"
            value={draft}
            onInput={(e) => setDraft((e.currentTarget as HTMLInputElement).value)}
          />
        ) : (
          <a class="source-url" href={source.url} target="_blank" rel="noreferrer">
            {shortUrl(source.url) || source.url}
          </a>
        )}
        <button
          type="button"
          class="btn-ghost"
          onClick={() => {
            if (editing) save();
            else {
              setDraft(source.url);
              setEditing(true);
            }
          }}
        >
          {editing ? "Save" : "Edit"}
        </button>
        <button
          type="button"
          class="btn-ghost"
          disabled={runActive}
          onClick={onRefresh}
        >
          Refresh
        </button>
        <button type="button" class="btn-ghost is-danger" onClick={onRemove}>
          Remove
        </button>
      </div>
      {source.error && <div class="validation-error">{source.error}</div>}
      {source.seasons.map((season, seasonId) => {
        const key = `${sourceId}-${seasonId}`;
        return (
          <SeasonAccordion
            key={season.id}
            platform={platform}
            sourceId={sourceId}
            seasonId={seasonId}
            season={season}
            episodes={episodeMap[key] ?? null}
            loading={Boolean(loadingMap[key])}
            refreshing={refreshing}
            onDisk={onDisk}
            open={seasonOpen(seasonId)}
            onToggleOpen={() => onToggleOpen(seasonId)}
            onToggleEnabled={() => onToggleEnabled(seasonId)}
            onTitleChange={(value) => onTitleChange(seasonId, value)}
            onSkip={(ep) => onSkip(seasonId, ep)}
            onRemap={(ep) => onRemap(seasonId, ep)}
          />
        );
      })}
    </section>
  );
}
