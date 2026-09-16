# yt-dlp-emby

**This project was vibe-coded using Cursor.**

Download YouTube playlists or Dropout.tv seasons with [yt-dlp](https://github.com/yt-dlp/yt-dlp). YouTube gets Emby NFO and artwork (no TMDB/TVDB). Dropout writes into an existing TVDB/TMDB library with no NFO.

## Mapping

| YouTube | Emby |
| --- | --- |
| Channel | Series |
| Playlist | Season |
| Video | Episode (numbered by current playlist order) |

Each refresh diffs the live playlist against a local index: new videos are downloaded, removed or replaced files are moved to an old-files directory (not deleted), reorders are renames, and episode numbers follow the current playlist.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- **ffmpeg on `PATH`** (not bundled; install it from your OS)
- **Node.js 22+** on `PATH` (YouTube JS challenges; nvm installs are detected)

```text
Debian/Ubuntu:  sudo apt install ffmpeg
Fedora:         sudo dnf install ffmpeg
Arch:           sudo pacman -S ffmpeg
macOS:          brew install ffmpeg
Windows:        winget install Gyan.FFmpeg
```

FFmpeg is an external program invoked by yt-dlp to merge and remux. It is **not** included in this repository. Official FFmpeg builds are LGPL/GPL; this project’s MIT license covers only the source in this repo.

## Install

```bash
uv sync
uv run yt-dlp-emby doctor
uv run yt-dlp-emby doctor --cookies cookies.txt --staging /var/tmp/yt-dlp-emby --library /path/to/library
uv run yt-dlp-emby bench
uv run yt-dlp-emby bench --size 64M --dest /path/to/old
```

`doctor` checks ffmpeg, Node (for YouTube JS), cookies, that staging is writable, and free space on staging/library/temp.

## Configuration

There are **no default media paths**. `library` and `old_dir` must be set via a CLI flag, environment variable, a manifest, or `[fallback]` in a config file.

Resolution order (highest wins): **CLI flag → environment variable → manifest → config `[fallback]`**.

| Setting | CLI | Environment | Manifest | Config key |
| --- | --- | --- | --- | --- |
| Library root | `--library` | `YT_DLP_EMBY_LIBRARY` | `library` | `[fallback].library` |
| Old/replaced files | `--old-dir` | `YT_DLP_EMBY_OLD_DIR` | `old_dir` | `[fallback].old_dir` |
| Bench copy destination | `--dest` | `YT_DLP_EMBY_BENCH_DEST` | — | `bench_dest` |
| Local download staging | `--staging` | `YT_DLP_EMBY_STAGING` | `staging` | `[fallback].staging` |
| Config file | `--config` | `YT_DLP_EMBY_CONFIG` | — | — |
| ffmpeg binary | `--ffmpeg-location` | `YT_DLP_EMBY_FFMPEG` | — | — |
| Netscape cookies | `--cookies` | `YT_DLP_EMBY_COOKIES` | `cookies` | `cookies` (CLI URL mode only) |
| Force metadata refetch | `--force-refetch` | `YT_DLP_EMBY_FORCE_REFETCH` | — | — |
| Dropout listing timings | `-vv` / `--debug` | `YT_DLP_EMBY_DEBUG` | — | — |

If `--config` / `YT_DLP_EMBY_CONFIG` is unset, `config.toml` in the current working directory is loaded when that file exists. `YT_EMBY_*` environment variables still work as a fallback. Top-level `library` / `old_dir` / `staging` in older config files still load as fallbacks.

Copy [`config.toml.example`](config.toml.example):

```toml
# sonarr_url = "http://localhost:8989"
# sonarr_api_key = "your-sonarr-api-key"

[fallback]
library = "/path/to/library"
old_dir = "/path/to/old"
# staging = "/path/to/local/tmp"
```

Downloads always happen on **local disk** first (system temp, or `staging` if you set it), then the finished `.mkv` and subtitle `.srt` files are copied to `library` and the staged files are deleted. Merge temps (`.temp.mkv`) and stream fragments (`.mp4` / `.m4a`) stay in staging and are never copied, so Emby does not pick them up. Point `staging` at a local SSD if `/tmp` is small. Leftover `yt-dlp-emby-*` folders in temp/staging from a killed run cannot be resumed (each run uses a new directory) and are deleted the next time you launch, unless another `yt-dlp-emby` process is still using that folder.

## Usage

Copy [`youtube.yaml.example`](youtube.yaml.example) to `youtube.yaml` (gitignored). Add playlists there, then re-run the command whenever you want the library checked against YouTube:

```bash
uv run yt-dlp-emby youtube
uv run yt-dlp-emby youtube --manifest youtube.yaml --dry-run
uv run yt-dlp-emby youtube --series "Example Channel"
```

Each playlist is listed, compared to the local series folder (`.yt-emby.json` plus the `.mkv` files), and only missing or changed episodes are downloaded. Season numbers come from `season:` in the manifest, or from the existing index if omitted. A manifest run prints the same job UI as Dropout: the series name, one compact line per playlist (`skip` / `download`, plus `rename` / `remove` when those apply), a dim `listed` timing, and indented download rows on dry-run. Skip rows only appear with `-v`. The whole yaml is one job, so you get a single `Done` at the end. `-vv` / `--debug` splits listing vs disk time (`listed 1.4s  disk 12ms`). YouTube still lists the live playlist every time so reorders and removals show up.

```yaml
library: /path/to/library
old_dir: /path/to/old
cookies: cookies.txt

series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLxxxxxxxx
        season: 1
      - url: https://www.youtube.com/playlist?list=PLyyyyyyyy
```

`name` is the Emby series folder. A one-off URL still works without a manifest (paths then come from `config.toml` or flags):

```bash
uv run yt-dlp-emby youtube "https://www.youtube.com/playlist?list=PLAYLIST_ID"
uv run yt-dlp-emby youtube URL --library /path/to/library --old-dir /path/to/old
uv run yt-dlp-emby youtube URL --season 1 --dry-run
uv run yt-dlp-emby youtube URL --cookies-from-browser firefox
uv run yt-dlp-emby youtube URL --cookies cookies.txt
uv run yt-dlp-emby youtube URL --quiet
uv run yt-dlp-emby youtube URL --silent
uv run yt-dlp-emby youtube URL --verbose
uv run yt-dlp-emby youtube URL --debug
uv run yt-dlp-emby youtube URL --force-refetch
uv run yt-dlp-emby bench
uv run yt-dlp-emby bench --size 64M
```

Progress: by default the CLI prints a series name, compact per-season/playlist counts, and draws its own bars while listing and downloading. Bars are TTY-only (piped output gets occasional one-line updates). Download bars are labeled by stream (`video`, `audio`, `en.srt`, `remux`); large library copies show a `copy` bar. yt-dlp's own output is silenced.

- `--quiet` hides bars and step logs; still prints warnings, the compact plan, and a `Done` summary.
- `--silent` prints errors only.
- `-v` / `--verbose` (or `YT_DLP_EMBY_VERBOSE=1`) prints skip rows and every yt-dlp message instead of our bars.
- `-vv` / `--debug` (or `YT_DLP_EMBY_DEBUG=1`) splits listing vs disk timings and does **not** hide progress or dump yt-dlp HTTP.

A run with any failed download exits `1`.

Playlist listing is a fast ID/title/order pass. Full per-video metadata (description, dates, duration) is filled from `{series}/.yt-emby-cache.json` when present, or from the download itself for new episodes. Existing episodes are not re-extracted unless you pass `--force-refetch` (or `YT_DLP_EMBY_FORCE_REFETCH=1`). That flag still lists the playlist first; it does not wait to fetch every video before the first download.

Defaults:

- Best video up to 1080p, remuxed to **mkv**
- English **user-uploaded** subtitles as sidecar `.srt` when available (not burned in). YouTube auto-generated captions are not downloaded.
- Series poster from the channel avatar; fanart from the channel banner when present; season and episode thumbs from playlist/video thumbnails

## Emby library setup

1. Create a **TV** library pointing at your `library` path.
2. Set metadata downloaders to **NFO only** (disable TMDB/TVDB for this library).
3. Scan the library.

NFO files include `<lockdata>true</lockdata>` and YouTube IDs only. Do not add TMDB/TVDB IDs in folder names.

## Dropout

Dropout shows already have TVDB/TMDB entries, so this command does **not** write NFO or artwork. Copy [`dropout.yaml.example`](dropout.yaml.example) to `dropout.yaml` (gitignored). A `# yaml-language-server: $schema=schemas/dropout.schema.json` comment at the top of the file enables IDE errors if you have the YAML extension in Cursor/VS Code.

`dropout` requires a verb: `download`, `layout`, or `check`. Bare `yt-dlp-emby dropout` prints help and exits.

List each Dropout season you want; yt-dlp lists the episodes. A series URL is only a base slug — yt-dlp treats it as season 1 if you omit `/season:N`. The existing `url` + `seasons` shorthand is still valid. Use `urls` when several Dropout catalog pages belong in one Emby/Sonarr folder:

```yaml
# yaml-language-server: $schema=schemas/dropout.schema.json
library: /path/to/dropout-library
old_dir: /path/to/old
cookies: dropout-cookies.txt
imports:
  - shows/dimension-20.yaml

series:
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_id: 361151
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
    tvdb_skip:
      - season: 0
        episodes: [12, 13, 14]
```

`imports` is optional. Keep a single file if you prefer. When you split, put **one file per TVDB/Emby series**; imported files contain only `series:` (no `library` / `cookies` / nested `imports`). Same `path` across files is merged (catalogs are appended). Schema for fragments: [`schemas/dropout-series.schema.json`](schemas/dropout-series.schema.json).

```yaml
# yaml-language-server: $schema=../schemas/dropout-series.schema.json
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_id: 354216
    urls:
      - url: https://watch.dropout.tv/dimension-20-the-complete-series
        seasons:
          - dropout: 28
            to_season: 27
      - url: https://watch.dropout.tv/dimension-20-live-complete-collection
        seasons:
          - dropout: 1
            remap:
              - dropout_episode: 1
                to_season: 0
                to_episode: 48
```

If `to_season` is omitted, remaining episodes keep the Dropout season number (`dropout: 26` → Emby `Season 26`). `remap` still overrides listed episodes (for example a finale into `Specials/`). Optional `title` on a remap sets the Emby filename title (and is what “title differs” compares against). Set `skip: true` on a remap entry to ignore that Dropout episode number entirely (`tvdb_skip` is separate: it only affects `check`). `only_episodes` limits a season to those Dropout episode numbers (the rest of the page is ignored); omit it to keep downloading every episode on the page.

```yaml
      - url: https://watch.dropout.tv/dimension-20-fantasy-high/season:2
        to_season: 7
        only_episodes: [18, 19]
```

Use a **Dropout** Netscape cookies file (`_session` on watch.dropout.tv), not the YouTube cookies file. yt-dlp is given a temp copy and that jar is never written back, so a failed or logged-out request cannot empty your file. `to_season: 0` writes to `Specials/` with `S00E70` in the filename.

```bash
uv run yt-dlp-emby dropout download --manifest dropout.yaml --dry-run
uv run yt-dlp-emby dropout layout
uv run yt-dlp-emby dropout check
uv run yt-dlp-emby dropout download --force
uv run yt-dlp-emby dropout download --series "Dimension 20" --season 28
uv run yt-dlp-emby dropout download --create
uv run yt-dlp-emby dropout download --quiet
uv run yt-dlp-emby dropout download --debug
uv run yt-dlp-emby dropout download --force-refetch
```

`layout` is a dry-run that regroups planned files by Emby folder (`Season 17`, then `Specials`) so you can verify remaps. It does not download. `check` compares local `.mkv` files to Sonarr for series that set `tvdb_id`: **missing** Sonarr episodes that the yaml never maps (not planned downloads), with suggestions when a cached Dropout listing title matches (including other series in the same manifest) or another Sonarr episode looks like a duplicate (exact title and air date; if that copy is already on disk the hint is **add to skip list**). Weaker title or date-only hits are prefixed **maybe** and shown in yellow.; **warning** yaml dests that are not in Sonarr, or remap titles that do not match; and filename titles that do not match. Planned `SxxExx` destinations are left to `download` / `layout`. It does not download and does not need Dropout cookies (Dropout suggestions use `{manifest}/cache/dropout.json` from a previous listing). Point it at Sonarr with `sonarr_url` / `sonarr_api_key` in gitignored `config.toml` (or `--sonarr-url` / `--sonarr-api-key` / `YT_DLP_EMBY_SONARR_URL` / `YT_DLP_EMBY_SONARR_API_KEY`). Do not put the API key in `dropout.yaml`. `tvdb_skip` blacklists Sonarr slots (for example Game Changer cut-for-time specials). `--force-refetch` on `check` refreshes the Sonarr cache in `{manifest}/cache/sonarr.json`.

Existing destination `.mkv` files are skipped (including the same `SxxExx` under a different title). `--force` redownloads them and moves the old title to `old_dir`. Sidecar `.srt` files are written for **all** subtitle languages (not embedded). Season listings (episode URLs and titles) are cached in `{manifest}/cache/dropout.json` (next to `dropout.yaml`, not on the library share) so later dry-runs skip Dropout; pass `--force-refetch` (or `YT_DLP_EMBY_FORCE_REFETCH=1`) to list again. A leftover `{library}/.yt-emby-dropout.json` is moved there on the next run. Listing prints the series name, per-season skip/download counts with a `~size` estimate for queued files (yt-dlp `filesize` when present, otherwise duration at about 5 Mbit/s for the default 1080p mkv), a dim `cached`/`fetch` timing (listing plus one folder scan), and indented download (and unmapped) rows; skip rows and per-file title notes only appear with `-v`. Origin is shown in parentheses only when it differs. Manifest series entries with the same name or path are combined into one layout block. `-vv` / `--debug` (or `YT_DLP_EMBY_DEBUG=1`) adds the listing-cache path and splits those times (`cached 4ms  disk 1.4s`); it does not dump yt-dlp HTTP and does not hide progress bars. Title Case vs slug filenames are treated as the same title. The run ends with elapsed time and a failure recap, and exits `1` if any download failed (or `130` on Ctrl-C).

Missing Emby series folders are refused unless you pass `--create` (dry-run warns instead). `--series` / `--season` limit the manifest. Expired Dropout cookies abort the run instead of failing every episode.

## YouTube library layout

```text
{library}/
  {Channel Name}/
    tvshow.nfo
    poster.jpg
    fanart.jpg
    season01-poster.jpg
    Season 1/
      season.nfo
      poster.jpg
      {Channel Name} - S01E01 - Episode Title.mkv
      {Channel Name} - S01E01 - Episode Title.nfo
      {Channel Name} - S01E01 - Episode Title-thumb.jpg
    .yt-emby.json
    .yt-emby-cache.json
```

## Web UI / Docker (optional)

The CLI is the primary interface. The web UI is an **optional addon** for managing manifests and runs from a phone or browser without tmux.

Install the server extra:

```bash
uv sync --extra server
uv run yt-dlp-emby server --port 8080
```

Development (API + Vite dev server with `/api` proxy):

```bash
uv run yt-dlp-emby server --port 8080
cd web && pnpm install && pnpm dev
```

Docker:

```bash
cp compose.yaml.example compose.yaml
docker compose up --build
```

Open `http://localhost:8080`, set an admin password on first visit, then use **Run** to refresh the download queue and start Dropout then YouTube jobs, **Series** to add shows and remap seasons, and **Settings** for path fallbacks, cookies, and the Advanced yaml editor. Layout and Sonarr check live on Dropout series detail, not on Run. If a manifest lists `imports:`, the Advanced editor shows tabs for the root file and each listed import; there is no UI to add or remove those files (edit the `imports:` list in the root tab and save). Run compose from the same directory as the CLI so both use those files. Bind `library` / `old_dir` at the same absolute paths inside the container. Do not run a host CLI download and a UI job against the same library at the same time.

| Variable | Role |
| --- | --- |
| `YT_DLP_EMBY_DATA` | Data dir (default `/data` in Docker, else cwd) |
| `YT_DLP_EMBY_LIBRARY` | `--library` on each UI-started job |
| `YT_DLP_EMBY_OLD_DIR` | `--old-dir` on each job |
| `YT_DLP_EMBY_STAGING` | `--staging` on each job |
| `YT_DLP_EMBY_PASSWORD` | Optional first-boot admin password (does not auto-login) |
| `YT_DLP_EMBY_HTTPS` | Set `Secure` on session cookies (use behind TLS) |

`--create`, `--force-refetch`, and `doctor` / `bench` remain CLI-only for now.

## Tests

```bash
uv run pytest            # unit tests only (no network)
uv run pytest -m network  # live metadata for two playlist items, plus one low-res download
cd web && pnpm test      # frontend unit tests
```

## License

MIT. See [LICENSE](LICENSE).

Third-party:

- yt-dlp — Unlicense
- Pillow — HPND
- PyYAML — MIT
- FFmpeg — **not distributed**; install separately (LGPL/GPL)
