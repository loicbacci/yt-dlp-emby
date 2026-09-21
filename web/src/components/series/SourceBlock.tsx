import { useState } from "preact/hooks";
import type { SeriesEpisode, SeriesSource, Source } from "../../api";
import { shortUrl } from "../../seriesView";
import { SeasonAccordion } from "./SeasonAccordion";

// Accepted deviation: SourceBlock is intentionally not memo()'d. Its props are
// inline callbacks from SeriesDetail, so a memo wrapper would never hit;
// per-episode derivations are memoized one level down in SeasonAccordion.
export function SourceBlock({
  platform,
  source,
  sourceId,
  episodeMap,
  loadingMap,
  refreshing,
  sourceBusy,
  onDisk,
  destErrors,
  skipErrors,
  seasonOpen,
  onToggleOpen,
  onRemove,
  onSaveUrl,
  onRefresh,
  onToggleEnabled,
  onTitleChange,
  onDestChange,
  onSkip,
  onRemap,
  disabled,
}: {
  platform: Source;
  source: SeriesSource;
  sourceId: number;
  episodeMap: Record<string, SeriesEpisode[]>;
  loadingMap: Record<string, boolean>;
  refreshing?: boolean;
  sourceBusy?: boolean;
  onDisk: ReadonlySet<string>;
  destErrors?: Record<string, string>;
  skipErrors?: Record<string, string>;
  seasonOpen: (seasonId: number) => boolean;
  onToggleOpen: (seasonId: number) => void;
  onRemove: () => void;
  onSaveUrl: (url: string) => void;
  onRefresh?: () => void;
  onToggleEnabled: (seasonId: number) => void;
  onTitleChange: (seasonId: number, value: string) => void;
  onDestChange?: (seasonId: number, value: string) => void;
  onSkip: (seasonId: number, episode: SeriesEpisode) => void;
  onRemap: (seasonId: number, episode: SeriesEpisode) => void;
  disabled?: boolean;
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
            aria-label="Source URL"
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
          disabled={disabled}
          aria-label={editing ? "Save source URL" : "Edit source URL"}
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
        {onRefresh && (
          <button
            type="button"
            class="btn-ghost"
            disabled={disabled || sourceBusy}
            aria-busy={sourceBusy}
            aria-label="Refresh source"
            onClick={onRefresh}
          >
            {sourceBusy ? (
              <>
                <span class="spinner" aria-hidden="true" /> Refreshing…
              </>
            ) : (
              "Refresh"
            )}
          </button>
        )}
        {sourceBusy && !onRefresh && (
          <span class="spinner" aria-hidden="true" role="status" aria-label="Source busy" />
        )}
        <button type="button" class="btn-ghost is-danger" disabled={disabled} onClick={onRemove}>
          Remove
        </button>
      </div>
      {source.error && (
        <div class="validation-error" role="alert">
          {source.error}
        </div>
      )}
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
            destError={destErrors?.[key]}
            skipErrors={skipErrors}
            open={seasonOpen(seasonId)}
            onToggleOpen={() => onToggleOpen(seasonId)}
            onToggleEnabled={() => onToggleEnabled(seasonId)}
            onTitleChange={(value) => onTitleChange(seasonId, value)}
            onDestChange={onDestChange ? (value) => onDestChange(seasonId, value) : undefined}
            onSkip={(ep) => onSkip(seasonId, ep)}
            onRemap={(ep) => onRemap(seasonId, ep)}
          />
        );
      })}
    </section>
  );
}
