import { useMemo, useState } from "preact/hooks";
import { downloadQueue } from "./mockCatalog";
import { MockShell, Poster, Twist } from "./Shell";

export function DownloadsIdle() {
  const rows = useMemo(() => downloadQueue(), []);
  const [openShow, setOpenShow] = useState("dimension-20");
  const [openSeason, setOpenSeason] = useState("dimension-20-s28");
  const [selected, setSelected] = useState<Set<string>>(() => {
    return new Set(
      rows.flatMap((row) =>
        row.seasons.flatMap((season) => season.episodes.map((ep) => ep.id)),
      ),
    );
  });

  const allCount = rows.reduce(
    (n, row) => n + row.seasons.reduce((m, season) => m + season.episodes.length, 0),
    0,
  );
  const d20 = rows.find((row) => row.show.id === "dimension-20");
  const d20Count = d20
    ? d20.seasons.reduce((n, season) => n + season.episodes.length, 0)
    : 0;

  const toggleIds = (ids: string[], checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  return (
    <MockShell current="downloads">
      <div class="mock-hero">
        <div>
          <h1>{allCount} new episodes</h1>
          <p>
            {rows.length} shows have something to grab · Dimension 20 alone has{" "}
            {d20Count}
          </p>
        </div>
        <button type="button" class="mock-ghost">
          Check for new episodes
        </button>
      </div>
      {rows.map(({ show, seasons }) => {
        const ids = seasons.flatMap((season) => season.episodes.map((ep) => ep.id));
        const picked = ids.filter((id) => selected.has(id)).length;
        const expanded = openShow === show.id;
        return (
          <section key={show.id} class="mock-card">
            <div class="mock-card-head mock-fold">
              <input
                class="mock-check"
                type="checkbox"
                checked={picked === ids.length && ids.length > 0}
                ref={(el) => {
                  if (el) el.indeterminate = picked > 0 && picked < ids.length;
                }}
                onChange={(e) =>
                  toggleIds(ids, (e.currentTarget as HTMLInputElement).checked)
                }
                aria-label={`Select ${show.name}`}
              />
              <button
                type="button"
                class="mock-card-head mock-fold"
                style={{ padding: 0, minHeight: 0, flex: 1 }}
                aria-expanded={expanded}
                onClick={() => setOpenShow(expanded ? "" : show.id)}
              >
                <Poster
                  src={show.poster}
                  letter={show.letter}
                  tone={show.tone}
                  size="md"
                />
                <span class="mock-show-copy">
                  <span class="mock-show-name">{show.name}</span>
                  <span class="mock-show-meta">
                    {ids.length} new · {seasons.length}{" "}
                    {seasons.length === 1 ? "season" : "seasons"} ·{" "}
                    {show.platform === "youtube" ? "YouTube" : "Dropout"}
                  </span>
                </span>
                <Twist open={expanded} />
              </button>
            </div>
            {expanded
              ? seasons.map((season) => {
                  const seasonIds = season.episodes.map((ep) => ep.id);
                  const seasonPicked = seasonIds.filter((id) =>
                    selected.has(id),
                  ).length;
                  const seasonOpen = openSeason === season.id;
                  return (
                    <div key={season.id} class="mock-season-group">
                      <div class="mock-season-row mock-fold">
                        <input
                          class="mock-check"
                          type="checkbox"
                          checked={seasonPicked === seasonIds.length}
                          ref={(el) => {
                            if (el) {
                              el.indeterminate =
                                seasonPicked > 0 && seasonPicked < seasonIds.length;
                            }
                          }}
                          onChange={(e) =>
                            toggleIds(
                              seasonIds,
                              (e.currentTarget as HTMLInputElement).checked,
                            )
                          }
                          aria-label={`Select ${season.label}`}
                        />
                        <button
                          type="button"
                          class="mock-season-main"
                          aria-expanded={seasonOpen}
                          onClick={() =>
                            setOpenSeason(seasonOpen ? "" : season.id)
                          }
                        >
                          <span class="mock-show-copy">
                            <span class="mock-season-name">{season.label}</span>
                            {season.folder ? (
                              <span class="mock-show-meta">{season.folder}</span>
                            ) : null}
                          </span>
                          <span class="mock-count is-new">
                            {season.episodes.length} new
                          </span>
                          <Twist open={seasonOpen} />
                        </button>
                      </div>
                      {seasonOpen ? (
                        <div class="mock-season-eps">
                          {season.episodes.map((ep) => (
                            <label
                              key={ep.id}
                              class={
                                selected.has(ep.id)
                                  ? "mock-ep mock-leaf is-on"
                                  : "mock-ep mock-leaf"
                              }
                            >
                              <input
                                class="mock-check"
                                type="checkbox"
                                checked={selected.has(ep.id)}
                                onChange={() =>
                                  toggleIds([ep.id], !selected.has(ep.id))
                                }
                              />
                              <span>
                                <span class="mock-ep-title">{ep.title}</span>
                                <span class="mock-ep-code">{ep.code}</span>
                              </span>
                              <span class="mock-ep-size">{ep.size}</span>
                            </label>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })
              : null}
          </section>
        );
      })}
      <details class="mock-disclosure">
        <summary>
          Already in library (earlier Dimension 20 seasons, plus caught-up shows)
          <Twist open={false} />
        </summary>
        <p>
          Fantasy High through Burrow's End are treated as on disk for this mock.
        </p>
      </details>
      <footer class="mock-bar">
        <span>{selected.size} selected</span>
        <button type="button" class="mock-primary">
          Download {selected.size} episodes
        </button>
      </footer>
    </MockShell>
  );
}
