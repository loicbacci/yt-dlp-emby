# yt-emby

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
uv run yt-emby doctor
uv run yt-emby doctor --cookies cookies.txt --staging /var/tmp/yt-emby --library /mnt/nas-video/Youtube
```

`doctor` checks ffmpeg, Node (for YouTube JS), cookies, that staging is writable, and free space on staging/library/temp.

## Configuration

There are **no default media paths**. `library` and `old_dir` must be set via a CLI flag, environment variable, or config file.

Resolution order (highest wins): **CLI flag → environment variable → config file**.

| Setting | CLI | Environment | Config key |
| --- | --- | --- | --- |
| Library root | `--library` | `YT_EMBY_LIBRARY` | `library` |
| Old/replaced files | `--old-dir` | `YT_EMBY_OLD_DIR` | `old_dir` |
| Local download staging | `--staging` | `YT_EMBY_STAGING` | `staging` |
| Config file | `--config` | `YT_EMBY_CONFIG` | — |
| ffmpeg binary | `--ffmpeg-location` | `YT_EMBY_FFMPEG` | — |
| Netscape cookies | `--cookies` | `YT_EMBY_COOKIES` | `cookies` |
| Force metadata refetch | `--force-refetch` | `YT_EMBY_FORCE_REFETCH` | — |
| Dropout listing timings | `-vv` / `--debug` | `YT_EMBY_DEBUG` | — |

If `--config` / `YT_EMBY_CONFIG` is unset, `config.toml` in the current working directory is loaded when that file exists.

Copy [`config.toml.example`](config.toml.example):

```toml
library = "/path/to/library"
old_dir = "/path/to/old"
# staging = "/path/to/local/tmp"
```

Downloads always happen on **local disk** first (system temp, or `staging` if you set it), then the finished `.mkv` and subtitle `.srt` files are copied to `library` and the staged files are deleted. Merge temps (`.temp.mkv`) and stream fragments (`.mp4` / `.m4a`) stay in staging and are never copied, so Emby does not pick them up. Point `staging` at a local SSD if `/tmp` is small. Leftover `yt-emby-*` folders in temp/staging from a killed run cannot be resumed (each run uses a new directory) and are deleted the next time you launch.

## Usage

```bash
uv run yt-emby youtube "https://www.youtube.com/playlist?list=PLAYLIST_ID"
uv run yt-emby youtube URL --library /path/to/library --old-dir /path/to/old
uv run yt-emby youtube URL --season 1 --dry-run
uv run yt-emby youtube URL --cookies-from-browser firefox
uv run yt-emby youtube URL --cookies cookies.txt
uv run yt-emby youtube URL --quiet
uv run yt-emby youtube URL --silent
uv run yt-emby youtube URL --verbose
uv run yt-emby youtube URL --force-refetch
```

Progress: by default the CLI logs each step, prints a plan summary, and draws its own bars while listing and downloading. Bars are TTY-only (piped output gets occasional one-line updates). Download bars are labeled by stream (`video`, `audio`, `en.srt`, `remux`); large library copies show a `copy` bar. yt-dlp's own output is silenced.

- `--quiet` hides bars and step logs; still prints warnings and a `Done  downloaded=N  skipped=N  failed=N` summary.
- `--silent` prints errors only.
- `-v` / `--verbose` (or `YT_EMBY_VERBOSE=1`) prints every yt-dlp message instead of our bars.
- Dropout `-vv` / `--debug` (or `YT_EMBY_DEBUG=1`) splits listing vs disk timings and does **not** hide progress or dump yt-dlp HTTP.

A run with any failed download exits `1`.

Playlist listing is a fast ID/title/order pass. Full per-video metadata (description, dates, duration) is filled from `{series}/.yt-emby-cache.json` when present, or from the download itself for new episodes. Existing episodes are not re-extracted unless you pass `--force-refetch` (or `YT_EMBY_FORCE_REFETCH=1`). That flag still lists the playlist first; it does not wait to fetch every video before the first download.

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

Dropout shows already have TVDB/TMDB entries, so this command does **not** write NFO or artwork. Copy [`dropout.yaml.example`](dropout.yaml.example) to `dropout.yaml` (gitignored). List each Dropout season you want; yt-dlp lists the episodes. A series URL is only a base slug — yt-dlp treats it as season 1 if you omit `/season:N`.

```yaml
library: /mnt/nas-video/Dropout
old_dir: /mnt/nas-video/_old
cookies: dropout-cookies.txt

series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
      - dropout: 29
        remap:
          - dropout_episode: 1
            to_season: 0
            to_episode: 70
```

If `to_season` is omitted, remaining episodes keep the Dropout season number (`dropout: 26` → Emby `Season 26`). `remap` still overrides listed episodes (for example a finale into `Specials/`).

Use a **Dropout** Netscape cookies file (`_session` on watch.dropout.tv), not the YouTube cookies file. yt-dlp is given a temp copy so it cannot truncate that file. `to_season: 0` writes to `Specials/` with `S00E70` in the filename.

```bash
uv run yt-emby dropout
uv run yt-emby dropout --manifest dropout.yaml --dry-run
uv run yt-emby dropout --force
uv run yt-emby dropout --series "Dimension 20" --season 28
uv run yt-emby dropout --create
uv run yt-emby dropout --quiet
uv run yt-emby dropout --debug
uv run yt-emby dropout --force-refetch
```

Existing destination `.mkv` files are skipped (including the same `SxxExx` under a different title). `--force` redownloads them and moves the old title to `old_dir`. Sidecar `.srt` files are written for **all** subtitle languages (not embedded). Season listings (episode URLs and titles) are cached in `{manifest}/cache/dropout.json` (next to `dropout.yaml`, not on the library share) so later dry-runs skip Dropout; pass `--force-refetch` (or `YT_EMBY_FORCE_REFETCH=1`) to list again. A leftover `{library}/.yt-emby-dropout.json` is moved there on the next run. Listing prints the series name, per-season skip/download counts, a dim `cached`/`fetch` timing (listing plus one folder scan), and indented download (and unmapped) rows; skip rows and per-file title notes only appear with `-v`. `-vv` / `--debug` (or `YT_EMBY_DEBUG=1`) adds the listing-cache path and splits those times (`cached 4ms  disk 1.4s`); it does not dump yt-dlp HTTP and does not hide progress bars. Title Case vs slug filenames are treated as the same title. The run ends with elapsed time and a failure recap, and exits `1` if any download failed (or `130` on Ctrl-C).

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

## Tests

```bash
uv run pytest            # unit tests only (no network)
uv run pytest -m network  # live metadata for two playlist items, plus one low-res download
```

## License

MIT. See [LICENSE](LICENSE).

Third-party:

- yt-dlp — Unlicense
- Pillow — HPND
- PyYAML — MIT
- FFmpeg — **not distributed**; install separately (LGPL/GPL)
