import type { SeriesSource, Source } from "../../api";
import { SeasonAccordion } from "./SeasonAccordion";
import type { SeriesEpisode } from "../../api";

export function SourceBlock({
  platform,
  slug,
  source,
  sourceId,
  runActive,
  onRefresh,
  onRemove,
  onToggleEnabled,
  onSkip,
  onRemap,
}: {
  platform: Source;
  slug: string;
  source: SeriesSource;
  sourceId: number;
  runActive: boolean;
  onRefresh: () => void;
  onRemove: () => void;
  onToggleEnabled: (seasonId: number) => void;
  onSkip: (seasonId: number, episode: SeriesEpisode) => void;
  onRemap: (seasonId: number, episode: SeriesEpisode) => void;
}) {
  return (
    <div class="source-block">
      <div class="source-head">
        <span class="editor-filename">Source {sourceId + 1}</span>
        <span class="editor-filename" style={{ flex: 1 }}>
          {source.url}
        </span>
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
      {source.seasons.map((season, seasonId) => (
        <SeasonAccordion
          key={season.id}
          platform={platform}
          slug={slug}
          sourceId={sourceId}
          seasonId={seasonId}
          season={season}
          onToggleEnabled={() => onToggleEnabled(seasonId)}
          onSkip={(ep) => onSkip(seasonId, ep)}
          onRemap={(ep) => onRemap(seasonId, ep)}
        />
      ))}
    </div>
  );
}
