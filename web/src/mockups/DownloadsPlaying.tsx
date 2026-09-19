import { useMemo, useState } from "preact/hooks";
import { downloadQueue } from "./mockCatalog";
import { MockShell, Poster, Twist } from "./Shell";

export function DownloadsPlaying({
  media = "split",
}: {
  media?: "split" | "combined";
}) {
  const queue = useMemo(() => downloadQueue(), []);
  const headShow = queue[0]?.show;
  const headSeason = queue[0]?.seasons[0];
  const now = headSeason?.episodes[0];
  const waiting = queue
    .map((row, showIndex) => ({
      show: row.show,
      seasons: row.seasons
        .map((season, seasonIndex) => ({
          ...season,
          episodes:
            showIndex === 0 && seasonIndex === 0
              ? season.episodes.slice(1)
              : season.episodes,
        }))
        .filter((season) => season.episodes.length > 0),
    }))
    .filter((row) => row.seasons.length > 0);

  const [openShow, setOpenShow] = useState(headShow?.id ?? "");
  const [openSeason, setOpenSeason] = useState(headSeason?.id ?? "");
  const waitingCount = waiting.reduce(
    (n, row) => n + row.seasons.reduce((m, season) => m + season.episodes.length, 0),
    0,
  );
  const total = waitingCount + (now ? 1 : 0);
  const steps =
    media === "combined"
      ? [
          { label: "English subs", state: "done" },
          { label: "Video+Audio", state: "current" },
          { label: "Remux", state: "pending" },
          { label: "Copy to library", state: "pending" },
        ]
      : [
          { label: "English subs", state: "current" },
          { label: "Video", state: "pending" },
          { label: "Audio", state: "pending" },
          { label: "Merge", state: "pending" },
          { label: "Remux", state: "pending" },
          { label: "Copy to library", state: "pending" },
        ];
  const local =
    media === "combined"
      ? {
          label: "Video+Audio",
          detail: "1.12 GB of 1.84 GB · 4.1 MB/s",
          bar: "is-file",
        }
      : {
          label: "English subs",
          detail: "48 KB of 186 KB · 22 KB/s",
          bar: "is-subs",
        };

  return (
    <MockShell current="downloads" playing>
      <section class="mock-now">
        <Poster
          src={headShow?.poster}
          letter={headShow?.letter ?? "D"}
          tone={headShow?.tone ?? "terra"}
          size="now"
        />
        <div>
          <p class="mock-kicker">Downloading now</p>
          <h1>{headShow?.name}</h1>
          <h2>{now?.title}</h2>
          <div class="mock-progress-block">
            <div class="mock-progress-row">
              <span>{local.label}</span>
              <span>{local.detail}</span>
            </div>
            <div class={`mock-progress ${local.bar}`} aria-hidden="true">
              <span />
            </div>
            <ol class="mock-steps">
              {steps.map((step) => (
                <li
                  key={step.label}
                  class={
                    step.state === "done"
                      ? "is-done"
                      : step.state === "current"
                        ? "is-current"
                        : undefined
                  }
                >
                  {step.label}
                </li>
              ))}
            </ol>
          </div>
          <p class="mock-stats">
            1 of {total} · {headSeason?.label} {now?.code}
          </p>
        </div>
        <button type="button" class="mock-stop">
          Stop
        </button>
      </section>

      <h3 class="mock-section-label">Queue · {waitingCount} episodes</h3>
      {waiting.map(({ show, seasons }) => {
        const remaining = seasons.reduce(
          (n, season) => n + season.episodes.length,
          0,
        );
        const expanded = openShow === show.id;
        return (
          <section key={show.id} class="mock-card is-waiting">
            <button
              type="button"
              class="mock-card-head mock-fold"
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
                  {remaining} remaining · {seasons.length}{" "}
                  {seasons.length === 1 ? "season" : "seasons"}
                </span>
              </span>
              <Twist open={expanded} />
            </button>
            {expanded
              ? seasons.map((season) => {
                  const seasonOpen = openSeason === season.id;
                  return (
                    <div key={season.id} class="mock-season-group">
                      <button
                        type="button"
                        class="mock-season-row mock-fold"
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
                        <span class="mock-count">
                          {season.episodes.length} remaining
                        </span>
                        <Twist open={seasonOpen} />
                      </button>
                      {seasonOpen ? (
                        <div class="mock-season-eps">
                          {season.episodes.map((ep) => (
                            <div key={ep.id} class="mock-ep mock-leaf">
                              <span>
                                <span class="mock-ep-title">{ep.title}</span>
                                <span class="mock-ep-code">{ep.code}</span>
                              </span>
                            </div>
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

      <details class="mock-disclosure mock-card" style={{ padding: "12px 16px" }}>
        <summary>
          Details · technical log
          <Twist open={false} />
        </summary>
        <pre class="mock-show-meta" style={{ whiteSpace: "pre-wrap" }}>
          {media === "combined"
            ? `[download] Destination: ${now?.title ?? "episode"}.mkv
[download]  61.0% of 1.84GiB at 4.12MiB/s`
            : `[info] Writing video subtitles to: ${now?.title ?? "episode"}.en.srt
[download]  26.0% of 186.00KiB at 22.10KiB/s`}
        </pre>
      </details>
    </MockShell>
  );
}
