# yt-dlp-emby

Manage YouTube and Dropout.tv downloads for an Emby library from a web UI.
Python serves the UI and API, and runs yt-dlp/ffmpeg work in private worker
processes. There is one application to deploy; a Node web server is not required.

Configuration stays in YAML/TOML, including imported show files. The web UI
provides mapping controls and an Advanced YAML editor. Existing library filenames,
NFO/artwork, season folders, and `.yt-emby.json` indexes remain supported.

## Run locally

Requirements: Python 3.11+, uv, Node 22+, pnpm 10.6.5, and ffmpeg. Node is also
used by yt-dlp for YouTube extraction. Install ffmpeg through your operating
system's package manager.

```bash
uv sync --frozen --group dev
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
uv run yt-dlp-emby --host 127.0.0.1 --port 8080 --data /path/to/app-data
```

Open `http://127.0.0.1:8080`, create the admin password, configure provider paths
and cookies, and add your shows. The data directory contains manifests, settings,
authentication, provider caches, and the local job database. Keep it on local disk.

For frontend development, run `pnpm --dir web dev` with the Python application
running. The Vite proxy forwards API calls to Python.

The launcher supports `--host`, `--port`, `--data`, and `--proxy-headers`. `PORT`
sets the default port. Media operations are managed in the web UI.

## Run with Docker

```bash
docker build -t yt-dlp-emby:0.2.0 .
```

Copy `compose.yaml.example` to the ignored `compose.yaml` and configure volumes.
Use a dedicated data directory, for example `/docker/yt-dlp-emby:/data`, rather
than mounting the repository. `scripts/setup-docker-data.sh --dry-run` previews
copying existing configuration into that directory.

Mount library and old/replaced-file directories at the same absolute paths used
in the manifests. Mount local staging separately if `/tmp` is too small. Ensure
the configured UID/GID can read and write application data and media directories.
The image runs as a non-root user, includes ffmpeg and Node, and uses tini to
reap child processes. Python serves the built frontend.

The example publishes localhost only. Set an initial password or complete setup
locally before exposing the application to a LAN. Behind a TLS reverse proxy,
configure HTTPS cookies and trusted proxy addresses.

## Everyday workflow

1. **Refresh** a show, one of its sources, or the shows selected in the Shows view.
   The job validates configuration, fetches listings, scans the library, and
   builds an updated action plan.
2. Review newly discovered seasons and their mappings. New seasons are disabled
   until enabled; existing mappings, custom titles, URLs, and exclusions survive
   discovery. Previously configured seasons are not deleted when discovery omits them.
3. Select the actions to execute on Downloads. Downloads, replacements, renames,
   and removals require an explicit selection from the current plan.
4. Follow the shared job progress, results, and bounded logs. Browser navigation
   or reload does not stop the worker. Cancel explicitly to stop it.

Refresh never downloads, renames, deletes, repairs media, or cleans staging.
**Sonarr Check** is separate; a Sonarr problem does not block listing refresh.
Diagnostics report paths, dependencies, and cookie availability without exposing
cookie contents.

Mapping edits rebuild the plan from cached data. If those inputs are unavailable,
the UI asks for Refresh. Plans have revisions: changed configuration or library
prerequisites require reviewing a new plan before executing old selections.

**Replace existing Dropout episodes** enables replacement even when the target
file exists. It does not change YouTube playlist synchronization rules.
**Create missing show folders** permits creating a show directory within an
available library; it never creates a missing library root.

Downloads stage on local disk before finished media is transferred to the library.
English user-uploaded subtitles are kept as sidecars when available. YouTube
metadata and artwork are generated from source metadata. Dropout can use an
existing Sonarr/TVDB folder layout and configured remaps.

## Configuration

Effective path precedence is environment override, applicable root manifest,
then TOML fallback. File-declared relative paths resolve against the declaring
file's directory; environment-declared relative paths resolve against the app data
directory. Imported show fragments contain show definitions, not platform paths.

Copy `config.toml.example`, `youtube.yaml.example`, and `dropout.yaml.example` as
needed into the data directory. The web UI can manage these files. The examples
and JSON schemas document supported fields; `shows/dimension-20.yaml.example`
demonstrates an imported Dropout show with a destination-season override.

```toml
# config.toml
# sonarr_url = "http://localhost:8989"
# sonarr_api_key = "your-sonarr-api-key"

[fallback]
library = "/mnt/emby/library"
old_dir = "/mnt/emby/old"
staging = "/var/tmp/yt-dlp-emby"
```

```yaml
# dropout.yaml
library: /mnt/emby/Dropout
old_dir: /mnt/emby/old
cookies: dropout-cookies.txt
imports:
  - shows/dimension-20.yaml
```

```yaml
# shows/dimension-20.yaml
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=351537]
    tvdb_id: 351537
    url: https://watch.dropout.tv/dimension-20
    seasons:
      - dropout: 28
        to_season: 27
        enabled: true
```

| Environment variable | Purpose |
| --- | --- |
| `YT_DLP_EMBY_DATA` | Application data directory. |
| `YT_DLP_EMBY_LIBRARY` | Override library root. |
| `YT_DLP_EMBY_OLD_DIR` | Override replaced/removed-file directory. |
| `YT_DLP_EMBY_STAGING` | Override local staging directory. |
| `YT_DLP_EMBY_CONFIG` | Select TOML configuration file. |
| `YT_DLP_EMBY_SHOWS_DIR` | Imported-show directory. |
| `YT_DLP_EMBY_FFMPEG` | ffmpeg binary or directory. |
| `YT_DLP_EMBY_SONARR_URL` / `YT_DLP_EMBY_SONARR_API_KEY` | Sonarr connection settings. |
| `YT_DLP_EMBY_PASSWORD` | Optional first-boot password. |
| `YT_DLP_EMBY_HTTPS` | Secure session cookies behind HTTPS. |
| `YT_DLP_EMBY_PROXY_HEADERS` / `TRUSTED_PROXY_IPS` | Reverse-proxy header trust. |
| `YT_DLP_EMBY_WEB_DIST` | Built frontend directory override. |

Legacy `YT_EMBY_*` setting aliases remain supported. Keep real manifests, cookies,
keys, runtime data, and deployment files out of Git. Cookie uploads use Netscape
cookie files; authenticated cookie contents are never returned by the status API.

## Jobs, failures, and recovery

One application job runs at a time. Conflicting starts and edits to active inputs
return a conflict with the active job identifier. Jobs retain per-target/item
results and redacted logs in local SQLite.

States are queued, running, stopping, succeeded, failed, cancelled, and interrupted.
If the server restarts during work, the job becomes interrupted. It does not resume
automatically. Explicit Retry reloads configuration, checks library state, and
skips verified completed items. Changed mappings require a new plan. Partial
staged download bytes are not automatically resumed.

An unsuccessful refresh retains the previous successful view and marks it stale.
The last-success time advances only after success. A batch can contain successful
shows and failed shows; the results identify both. A polling/network failure in
the browser is distinct from a failed server job.

If a NAS root is missing, inaccessible, or a known backing mount disappears,
the library is unavailable. Counts become unknown, and execution is blocked.
This is different from an available root with an absent show folder or an empty
existing folder. Restore the mount and Refresh; do not create replacement empty
folders to bypass the availability check.

## API

Authenticated clients use `POST /api/jobs` to start refresh, download, check, or
diagnostics work. A start returns HTTP 202 with `{job_id,status}`; obtain the result
from `GET /api/jobs/{id}`. `GET /api/jobs` lists active work and history. Jobs also
have `/cancel` and `/retry` POST endpoints. `GET /api/plans/latest` returns cached
plans and readiness. Inspect `/openapi.json` for models.

GET views do not trigger refresh work. Refresh is an explicit job. Errors contain
a readable `error`, stable `code`, and `request_id`.

## Upgrade from 0.1

Version 0.2 removes the public `youtube`, `dropout`, `doctor`, and `bench` CLI
commands, the `server` subcommand, and old run/SSE/refresh-mode API routes.
Launch with `yt-dlp-emby --host ... --data ...`; use the web UI for operations.
The server dependency extra is no longer needed: use `uv sync --frozen`.

Canonical configuration, cookies, media, and library indexes are preserved.
Legacy derived plans/events/selection state are archived once; refresh the shows
before downloading. No old selection is replayed, and startup does not refresh
every show automatically. Keep a backup of application configuration/data before
upgrading. Code rollback does not require restoring media or deleting new indexes;
old derived plans should be rebuilt by the version being run.

## Development checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/yt_dlp_emby/server
uv run pytest -m 'not network' --cov=src --cov-fail-under=70
pnpm --dir web typecheck
pnpm --dir web lint
pnpm --dir web format:check
pnpm --dir web test
pnpm --dir web build
```

Network-marked tests are opt-in. Automated tests use fake providers, temporary
libraries, and worker subprocesses. Live NAS/provider checks supplement these.

MIT licensed application source. External tools and downloaded media retain their
own licenses and terms.
