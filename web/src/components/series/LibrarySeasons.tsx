import { useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { Skeleton } from "../Skeleton";
import {
  catalogEpisodeKey,
  formatMapsTo,
  type DestMap,
  type DestOccupant,
  type DestSlot,
} from "../../seriesView";

export function LibrarySeasons({
  destMap,
  loading,
  refreshing,
  onFind,
  onPack,
}: {
  destMap: DestMap;
  loading?: boolean;
  refreshing?: boolean;
  onFind: (slot: DestSlot) => void;
  onPack: (destSeason: number) => void;
}) {
  const firstOpen =
    destMap.seasons.find((group) => group.holes > 0)?.destSeason ??
    destMap.seasons[0]?.destSeason ??
    null;
  const [open, setOpen] = useState<number | null>(firstOpen);

  if (loading && destMap.seasons.length === 0) {
    return <p class="settings-hint">Loading listings…</p>;
  }

  return (
    <>
      <p class="lib-legend">
        <span>
          <span class="dot-status library" />
          In library
        </span>
        <span>
          <span class="dot-status missing" />
          Missing
        </span>
        <span>
          <span class="dot-status skipped" />
          Skipped
        </span>
      </p>
      {destMap.seasons.map((group) => {
        const isOpen = open === group.destSeason;
        const inLibrary = group.slots.filter((slot) =>
          slot.occupants.some((occ) => occ.status === "downloaded"),
        ).length;
        const missing = group.holes;
        const skipped = group.slots.filter((slot) =>
          slot.occupants.some((occ) => occ.status === "skipped"),
        ).length;
        return (
          <section key={group.destSeason} class="fold-card">
            <div class="fold-head">
              <button
                type="button"
                class="fold-main"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : group.destSeason)}
              >
                <span class="show-copy">
                  <span class="show-name">{group.label}</span>
                </span>
                {refreshing ? (
                  <Skeleton width="8.5rem" height="0.9em" />
                ) : (
                  <span class={`count-chip${missing ? " is-new" : ""}`}>
                    {missing
                      ? `${missing} missing · ${inLibrary} in library`
                      : skipped
                        ? `${inLibrary} in library · ${skipped} skipped`
                        : `${group.slots.length} in library`}
                  </span>
                )}
                <span class={`twist${isOpen ? " is-open" : ""}`} aria-hidden="true" />
              </button>
              {group.packable && (
                <button
                  type="button"
                  class="btn-ghost"
                  onClick={() => onPack(group.destSeason)}
                >
                  Pack remaining
                </button>
              )}
            </div>
            {isOpen ? (
              refreshing ? (
                <div class="season-eps">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} class="ep-row">
                      <span class="dot-status" />
                      <span class="ep-copy">
                        <Skeleton width={`${58 - index * 4}%`} />
                        <Skeleton width="4.2rem" height="0.7em" />
                      </span>
                      <Skeleton width="4.8rem" height="1.2em" />
                    </div>
                  ))}
                </div>
              ) : (
                <div class="season-eps">
                  {group.slots.flatMap((slot) => {
                    if (slot.occupants.length === 0) {
                      return [
                        <LibraryRow
                          key={slot.code}
                          status="missing"
                          title={slot.title || "Empty slot"}
                          code={slot.code}
                          pill="Missing"
                          action={
                            <button
                              type="button"
                              class="btn-ghost"
                              onClick={() => onFind(slot)}
                            >
                              Find episode
                            </button>
                          }
                        />,
                      ];
                    }
                    return slot.occupants.map((occupant) => (
                      <LibraryRow
                        key={`${slot.code}-${catalogEpisodeKey(occupant.row)}`}
                        status={libraryDot(occupant)}
                        title={
                          occupant.mapped.mapped_title || occupant.row.episode.title
                        }
                        code={slot.code}
                        pill={libraryPill(occupant)}
                        skipped={occupant.status === "skipped"}
                      />
                    ));
                  })}
                </div>
              )
            ) : null}
          </section>
        );
      })}
      {destMap.leftovers.length > 0 && (
        <section class="fold-card">
          <button
            type="button"
            class="fold-head"
            aria-expanded={open === -1}
            onClick={() => setOpen(open === -1 ? null : -1)}
          >
            <span class="show-copy">
              <span class="show-name">Unmapped / skipped</span>
            </span>
            <span class="count-chip">{destMap.leftovers.length}</span>
            <span class={`twist${open === -1 ? " is-open" : ""}`} aria-hidden="true" />
          </button>
          {open === -1 && (
            <div class="season-eps">
              {destMap.leftovers.map((occupant) => (
                <LibraryRow
                  key={catalogEpisodeKey(occupant.row)}
                  status={libraryDot(occupant)}
                  title={occupant.row.episode.title}
                  code={
                    occupant.mapped.mapped_season != null &&
                    occupant.mapped.mapped_episode != null
                      ? formatMapsTo(
                          occupant.mapped.mapped_season,
                          occupant.mapped.mapped_episode,
                        )
                      : `E${String(occupant.row.episode.source_episode).padStart(2, "0")}`
                  }
                  pill={libraryPill(occupant)}
                  skipped={occupant.status === "skipped"}
                />
              ))}
            </div>
          )}
        </section>
      )}
    </>
  );
}

function libraryDot(occupant: DestOccupant): "library" | "missing" | "skipped" {
  if (occupant.status === "skipped") return "skipped";
  if (occupant.status === "downloaded") return "library";
  return "missing";
}

function libraryPill(occupant: DestOccupant): string {
  if (occupant.status === "skipped") return "Skipped";
  if (occupant.status === "downloaded") return "In library";
  return "Missing";
}

function LibraryRow({
  status,
  title,
  code,
  pill,
  skipped,
  action,
}: {
  status: "library" | "missing" | "skipped";
  title: string;
  code: string;
  pill: string;
  skipped?: boolean;
  action?: ComponentChildren;
}) {
  return (
    <div class={skipped ? "ep-row is-skipped" : "ep-row"}>
      <span class={`dot-status ${status}`} />
      <span class="ep-copy">
        <span class="ep-title">{title}</span>
        <span class="ep-code">{code}</span>
      </span>
      <span class={`status-pill ${status}`}>{pill}</span>
      {action}
    </div>
  );
}
