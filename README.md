# yt-emby

**This project was vibe-coded using Cursor.**

Download YouTube playlists with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and write Emby-compatible NFO files and artwork so the result can be added as a TV library without TMDB or TVDB.

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
```

## Configuration

There are **no default media paths**. `library` and `old_dir` must be set via a CLI flag, environment variable, or config file.

Resolution order (highest wins): **CLI flag → environment variable → config file**.

| Setting | CLI | Environment | Config key |
| --- | --- | --- | --- |
| Library root | `--library` | `YT_EMBY_LIBRARY` | `library` |
| Old/replaced files | `--old-dir` | `YT_EMBY_OLD_DIR` | `old_dir` |
| Config file | `--config` | `YT_EMBY_CONFIG` | — |
| ffmpeg binary | `--ffmpeg-location` | `YT_EMBY_FFMPEG` | — |

If `--config` / `YT_EMBY_CONFIG` is unset, `config.toml` in the current working directory is loaded when that file exists.

Copy [`config.toml.example`](config.toml.example):

```toml
library = "/path/to/library"
old_dir = "/path/to/old"
```

## Usage

```bash
uv run yt-emby download "https://www.youtube.com/playlist?list=PLAYLIST_ID"
uv run yt-emby download URL --library /path/to/library --old-dir /path/to/old
uv run yt-emby download URL --season 1 --dry-run
uv run yt-emby download URL --cookies-from-browser firefox
```

Defaults:

- Best video up to 1080p, remuxed to **mkv**
- English subtitles as sidecar `.srt` when available (not burned in)
- Series poster from the channel avatar; fanart from the channel banner when present; season and episode thumbs from playlist/video thumbnails

## Emby library setup

1. Create a **TV** library pointing at your `library` path.
2. Set metadata downloaders to **NFO only** (disable TMDB/TVDB for this library).
3. Scan the library.

NFO files include `<lockdata>true</lockdata>` and YouTube IDs only. Do not add TMDB/TVDB IDs in folder names.

Layout:

```text
{library}/
  {Channel Name}/
    tvshow.nfo
    poster.jpg
    fanart.jpg
    season01-poster.jpg
    Season 01/
      season.nfo
      poster.jpg
      {Channel Name} - S01E01 - Episode Title.mkv
      {Channel Name} - S01E01 - Episode Title.nfo
      {Channel Name} - S01E01 - Episode Title-thumb.jpg
    .yt-emby.json
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
- FFmpeg — **not distributed**; install separately (LGPL/GPL)
