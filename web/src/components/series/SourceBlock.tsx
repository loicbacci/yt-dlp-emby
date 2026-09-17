import type { SeriesEpisode, SeriesSource, Source } from "../../api";
import { SeasonAccordion } from "./SeasonAccordion";

export function SourceBlock({
  platform,
  source,
  sourceId,
  runActive,
  episodeMap,
  loadingMap,
  onDisk,
  seasonOpen,
  onToggleOpen,
  onRefresh,
  onRemove,
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
  onDisk: ReadonlySet<string>;
  seasonOpen: (seasonId: number) => boolean;
  onToggleOpen: (seasonId: number) => void;
  onRefresh: () => void;
  onRemove: () => void;
  onToggleEnabled: (seasonId: number) => void;
  onTitleChange: (seasonId: number, value: string) => void;
  onSkip: (seasonId: number, episode: SeriesEpisode) => void;
  onRemap: (seasonId: number, episode: SeriesEpisode) => void;
}) {
  return (
    <div class="source-block">
      <div class="source-head">
        <span class="source-kicker">From</span>
        <a
          class="source-url"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          {source.url}
        </a>
        <button
          type="button"
          class="btn-ghost"
          disabled={runActive}
          onClick={onRefresh}
        >
          Refresh
        </button>
        <button type="button" class="btn-ghost" onClick={onRemove}>
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
    </div>
  );
}
