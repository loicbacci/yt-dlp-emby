import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import {
  type DestMap,
  type DestOccupant,
  type DestSlot,
  catalogEpisodeKey,
  formatMapsTo,
  seasonFillStatus,
} from "../../seriesView";
import { Skeleton } from "../Skeleton";

export function LibrarySeasons({
  destMap,
  loading,
  refreshing,
  onFind,
}: {
  destMap: DestMap;
  loading?: boolean;
  refreshing?: boolean;
  onFind: (slot: DestSlot) => void;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());

  if (loading && destMap.seasons.length === 0) {
    return <p class="settings-hint">Loading listings…</p>;
  }
  if (!loading && destMap.seasons.length === 0) {
    return <p class="empty-state">No seasons yet.</p>;
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
        const isOpen = open.has(group.destSeason);
        const fill = seasonFillStatus(group);
        const fillDot = fill === "ok" ? "library" : fill === "empty" ? "skipped" : "missing";
        const inLibrary = group.slots.filter((slot) =>
          slot.occupants.some((occ) => occ.status === "downloaded"),
        ).length;
        const missing = group.holes;
        const skipped = group.slots.filter(
          (slot) => slot.skipped || slot.occupants.some((occ) => occ.status === "skipped"),
        ).length;
        const chipClass = fill === "empty" ? "is-empty" : missing ? "is-new" : "is-ok";
        return (
          <section key={group.destSeason} class="fold-card">
            <div class="fold-head season-head">
              <button
                type="button"
                class="fold-main"
                aria-expanded={isOpen}
                onClick={() =>
                  setOpen((current) => {
                    const next = new Set(current);
                    if (next.has(group.destSeason)) next.delete(group.destSeason);
                    else next.add(group.destSeason);
                    return next;
                  })
                }
              >
                <span class={`dot-status ${fillDot}`} />
                <span class="show-copy">
                  <span class="season-kicker">Season</span>
                  <span class="show-name">{group.label}</span>
                </span>
                {refreshing ? (
                  <Skeleton width="8.5rem" height="0.9em" />
                ) : (
                  <span class={`count-chip ${chipClass}`}>
                    {missing
                      ? `${missing} missing · ${inLibrary} in library`
                      : skipped
                        ? `${inLibrary} in library · ${skipped} skipped`
                        : `${group.slots.length} in library`}
                  </span>
                )}
                <span class={`twist${isOpen ? " is-open" : ""}`} aria-hidden="true" />
              </button>
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
                      if (slot.skipped) {
                        return [
                          <LibraryRow
                            key={slot.code}
                            status="skipped"
                            title={slot.title || "Skipped slot"}
                            code={slot.code}
                            pill="Skipped"
                            skipped
                          />,
                        ];
                      }
                      return [
                        <LibraryRow
                          key={slot.code}
                          status="missing"
                          title={slot.title || "Empty slot"}
                          code={slot.code}
                          pill="Missing"
                          action={
                            <button type="button" class="btn-ghost" onClick={() => onFind(slot)}>
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
                        title={occupant.mapped.mapped_title || occupant.row.episode.title}
                        code={slot.code}
                        pill={libraryPill(occupant)}
                        skipped={occupant.status === "skipped"}
                        conflict={slot.occupants.length > 1}
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
            aria-expanded={open.has(-1)}
            onClick={() =>
              setOpen((current) => {
                const next = new Set(current);
                if (next.has(-1)) next.delete(-1);
                else next.add(-1);
                return next;
              })
            }
          >
            <span class="show-copy">
              <span class="show-name">Unmapped / skipped</span>
            </span>
            <span class="count-chip">{destMap.leftovers.length}</span>
            <span class={`twist${open.has(-1) ? " is-open" : ""}`} aria-hidden="true" />
          </button>
          {open.has(-1) && (
            <div class="season-eps">
              {destMap.leftovers.map((occupant) => (
                <LibraryRow
                  key={catalogEpisodeKey(occupant.row)}
                  status={libraryDot(occupant)}
                  title={occupant.row.episode.title}
                  code={
                    occupant.mapped.mapped_season != null && occupant.mapped.mapped_episode != null
                      ? formatMapsTo(occupant.mapped.mapped_season, occupant.mapped.mapped_episode)
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
  conflict,
}: {
  status: "library" | "missing" | "skipped";
  title: string;
  code: string;
  pill: string;
  skipped?: boolean;
  action?: ComponentChildren;
  conflict?: boolean;
}) {
  return (
    <div class={skipped ? "ep-row is-skipped" : "ep-row"}>
      <span class={`dot-status ${status}`} />
      <span class="ep-copy">
        <span class="ep-title">{title}</span>
        <span class="ep-code">{code}</span>
      </span>
      {conflict && <span class="count-chip is-empty">Conflict</span>}
      <span class={`status-pill ${status}`}>{pill}</span>
      {action}
    </div>
  );
}
