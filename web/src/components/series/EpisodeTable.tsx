import type { SeriesEpisode } from "../../api";
import { episodeStatusLabel, formatMapsTo } from "../../seriesView";

export function EpisodeTable({
  platform,
  episodes,
  onSkip,
  onRemap,
}: {
  platform: "youtube" | "dropout";
  episodes: SeriesEpisode[];
  onSkip: (episode: SeriesEpisode) => void;
  onRemap: (episode: SeriesEpisode) => void;
}) {
  return (
    <table class="episode-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Title</th>
          <th>Maps to</th>
          <th>Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {episodes.map((ep) => {
          const status = ep.status ?? (ep.skipped ? "skipped" : "unmapped");
          return (
            <tr key={ep.id} class={ep.skipped ? "is-skipped" : ""}>
              <td>{ep.source_episode}</td>
              <td>{ep.title}</td>
              <td class="maps-to">
                {ep.skipped
                  ? "skipped"
                  : ep.mapped_season != null && ep.mapped_episode != null
                    ? formatMapsTo(ep.mapped_season, ep.mapped_episode)
                    : "—"}
              </td>
              <td>
                <span class={`episode-status is-${status}`}>
                  {episodeStatusLabel(status)}
                </span>
              </td>
              <td>
                <button
                  type="button"
                  class="btn-ghost"
                  data-testid={`episode-skip-${ep.id}`}
                  onClick={() => onSkip(ep)}
                >
                  {ep.skipped ? "Unskip" : "Skip"}
                </button>
                {platform === "dropout" && !ep.skipped && (
                  <button
                    type="button"
                    class="btn-ghost"
                    data-testid={`episode-remap-${ep.id}`}
                    onClick={() => onRemap(ep)}
                  >
                    Remap
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
