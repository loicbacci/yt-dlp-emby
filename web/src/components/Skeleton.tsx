export function Skeleton({
  width,
  height = "0.8em",
  class: className,
}: {
  width?: string;
  height?: string;
  class?: string;
}) {
  return (
    <span
      class={["skeleton", className].filter(Boolean).join(" ")}
      style={{ width: width ?? "100%", height }}
      aria-hidden="true"
    />
  );
}

export function SeriesListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div data-testid="series-list-skeleton">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} class="series-row" aria-hidden="true">
          <div class="series-row-main">
            <Skeleton width="12rem" height="1em" />
            <div class="series-row-meta" style={{ marginTop: "8px" }}>
              <Skeleton width="18rem" height="0.7em" />
            </div>
          </div>
          <div class="series-row-badges">
            <Skeleton width="5rem" height="1em" />
            <Skeleton width="4.5rem" height="1.4em" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SeriesDetailSkeleton() {
  return (
    <div data-testid="series-detail-skeleton">
      <Skeleton width="16rem" height="1.6em" />
      <div class="series-row-meta" style={{ margin: "12px 0 24px" }}>
        <Skeleton width="22rem" height="0.8em" />
      </div>
      {Array.from({ length: 3 }, (_, index) => (
        <div key={index} class="source-block">
          <Skeleton width="9rem" height="1em" />
          <div style={{ marginTop: "12px" }}>
            <Skeleton width="100%" height="2.4em" />
            <div style={{ marginTop: "8px" }}>
              <Skeleton width="100%" height="2.4em" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function EpisodeTableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div class="episode-table-skeleton" role="status" aria-label="Loading episodes">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} class="episode-skeleton-row">
          <Skeleton width="2rem" />
          <Skeleton width="70%" />
          <Skeleton width="4rem" />
          <Skeleton width="5rem" />
        </div>
      ))}
    </div>
  );
}
