import type { ComponentChildren } from "preact";
import type { EpisodeFileStatus } from "../../api";
import { episodeStatusLabel } from "../../seriesView";

export type EpisodeTableRow = {
  id: string;
  index: string | number;
  title: string;
  from?: ComponentChildren;
  mapsTo?: string;
  status?: EpisodeFileStatus;
  skipped?: boolean;
  rowClass?: string;
  actions?: ComponentChildren;
};

export function EpisodeTable({
  rows,
  indexLabel = "#",
  showMapsTo = true,
  showFrom = false,
  empty,
}: {
  rows: EpisodeTableRow[];
  indexLabel?: string;
  showMapsTo?: boolean;
  showFrom?: boolean;
  empty?: string;
}) {
  if (rows.length === 0) {
    return empty ? <p class="settings-hint">{empty}</p> : null;
  }

  return (
    <table class="episode-table">
      <thead>
        <tr>
          <th>{indexLabel}</th>
          <th>Title</th>
          {showFrom && <th>From</th>}
          {showMapsTo && <th>Maps to</th>}
          <th>Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const status = row.status ?? (row.skipped ? "skipped" : undefined);
          return (
            <tr
              key={row.id}
              class={[row.skipped && "is-skipped", row.rowClass]
                .filter(Boolean)
                .join(" ")}
            >
              <td class="maps-to">{row.index}</td>
              <td>{row.title}</td>
              {showFrom && <td class="run-meta">{row.from ?? "—"}</td>}
              {showMapsTo && (
                <td class="maps-to">{row.mapsTo ?? "—"}</td>
              )}
              <td>
                {status ? (
                  <span class={`episode-status is-${status}`}>
                    {episodeStatusLabel(status)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td>{row.actions}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
