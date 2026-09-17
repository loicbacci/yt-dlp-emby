import {
  catalogEpisodeKey,
  originLabel,
  type DestMap,
  type DestOccupant,
  type DestSlot,
} from "../../seriesView";
import { EpisodeTable } from "./EpisodeTable";

export function DestMapPanel({
  destMap,
  loading,
  onRemap,
  onFind,
  onPack,
}: {
  destMap: DestMap;
  loading?: boolean;
  onRemap: (occupant: DestOccupant) => void;
  onFind: (slot: DestSlot) => void;
  onPack: (destSeason: number) => void;
}) {
  return (
    <section class="settings-section">
      <h2 class="settings-heading">Emby order</h2>
      <p class="settings-section-lead">
        Slots in remapped dest order. Color marks a remap: gold stays in this
        season, purple leaves it (usually Specials). Pack remaining fills holes
        after specials are pulled out.
      </p>
      {loading && destMap.seasons.length === 0 && (
        <p class="settings-hint">Loading listings…</p>
      )}
      {destMap.seasons.map((group) => (
        <details
          key={group.destSeason}
          class="dest-season"
          open={group.holes > 0 || group.conflicts > 0 || group.packable}
        >
          <summary>
            <span>{group.label}</span>
            {group.holes > 0 && (
              <span class="season-missing-count">{group.holes} empty</span>
            )}
            {group.conflicts > 0 && (
              <span class="season-has-missing">{group.conflicts} conflict</span>
            )}
            {group.packable && (
              <button
                type="button"
                class="btn-ghost"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onPack(group.destSeason);
                }}
              >
                Pack remaining
              </button>
            )}
          </summary>
          <EpisodeTable
            indexLabel="Slot"
            showMapsTo={false}
            showFrom
            rows={group.slots.flatMap((slot) => {
              if (slot.occupants.length === 0) {
                return [
                  {
                    id: slot.code,
                    index: slot.code,
                    title: slot.title || "Empty slot",
                    from: slot.sonarr ? (
                      <span class="origin-chip">Sonarr</span>
                    ) : (
                      <span class="origin-chip">—</span>
                    ),
                    status: "missing" as const,
                    rowClass: "is-dest-hole",
                    actions: (
                      <button
                        type="button"
                        class="btn-ghost"
                        onClick={() => onFind(slot)}
                      >
                        Find episode
                      </button>
                    ),
                  },
                ];
              }
              return slot.occupants.map((occupant) => ({
                id: `${slot.code}-${catalogEpisodeKey(occupant.row)}`,
                index: slot.code,
                title: occupant.mapped.mapped_title || occupant.row.episode.title,
                from: (
                  <span class="origin-chip">{originLabel(occupant.row)}</span>
                ),
                status: occupant.status,
                rowClass:
                  slot.occupants.length > 1
                    ? "is-dest-conflict"
                    : occupant.kind === "other-season"
                      ? "is-remap-other"
                      : occupant.kind === "same-season"
                        ? "is-remap-same"
                        : undefined,
                actions: (
                  <button
                    type="button"
                    class="btn-ghost"
                    onClick={() => onRemap(occupant)}
                  >
                    Remap
                  </button>
                ),
              }));
            })}
          />
        </details>
      ))}
      {destMap.leftovers.length > 0 && (
        <details class="dest-season">
          <summary>Unmapped / skipped ({destMap.leftovers.length})</summary>
          <EpisodeTable
            indexLabel="#"
            showFrom
            rows={destMap.leftovers.map((occupant) => ({
              id: catalogEpisodeKey(occupant.row),
              index: occupant.row.episode.source_episode,
              title: occupant.row.episode.title,
              from: (
                <span class="origin-chip">{originLabel(occupant.row)}</span>
              ),
              mapsTo: occupant.mapped.skipped ? "skipped" : "—",
              status: occupant.status,
              skipped: occupant.mapped.skipped,
              actions: (
                <button
                  type="button"
                  class="btn-ghost"
                  onClick={() => onRemap(occupant)}
                >
                  Remap
                </button>
              ),
            }))}
          />
        </details>
      )}
    </section>
  );
}
