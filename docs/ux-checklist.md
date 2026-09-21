# UX checklist

Phase 5–7 sign-off. Pages: Dashboard, Shows list, Show detail, Settings, Login, Setup.

Legend: `[x]` = verified in code (logic present; `pnpm --dir web typecheck/test/lint` green).
Manual browser checks live in their own section at the bottom and are NOT signed off.

## Loading
- [x] Dashboard pending plan shows queue skeleton, not "No queue yet"
- [x] Settings shows a skeleton until first load settles (partial render after)
- [x] SessionGate spinner while the session check runs
- [x] Poster loading background while the image loads (plain bg, no shimmer animation)
- [x] RemapModal Sonarr loading indicator, not instant empty
- [x] RefreshSplit spinner while refreshing
- [x] pendingUrl Discovering spinner

## Empty
- [x] Dashboard search miss copy
- [x] Shows list "No series yet" + Add show CTA
- [x] Show detail "No playlists yet"
- [x] Library no seasons
- [x] EpisodeTable empty copy (never silent null)
- [x] LogViewer "No output yet"

## Error
- [x] Retry cards for plan/run/list/detail/config-sections
- [x] refreshItems / refreshMetadata try/catch + per-item errors surfaced
- [x] ManifestEditor clears error on change (stale errors never block Save)
- [x] `role=alert` on async errors; live-while-typing hints stay silent by design
- [x] checkError rendered as error, not hint
- [x] only_episodes guard renders adjacent to its episode row
- [x] dest parse errors render inline under the Emby season input
- [x] TvdbSkip manual Add strictly digits, disabled unless both parse, inline error
- [x] Settings deep link on cookie/path failures

## Success / stop
- [x] Toasts stack, auto-dismiss 4s, status/alert roles
- [x] document.title Downloading n/m / Done
- [x] Optional Notification opt-in wired (delivery needs a manual run, see below)
- [x] Stop always confirms, Stopping… label, errors toast + inline

## Destructive
- [x] Confirm delete / risky remove / large download (25+) / stop
- [x] Immediate + toast for skip/remap/enable/title/dest/tvdb_skip/source-add/non-risky-remove
- [x] ConfirmModal pending + focus Cancel when danger
- [x] Destructive-action decision comments in code (SeriesDetail/SeriesList/Dashboard)

## Forms
- [x] URL validation (http(s) + platform match + duplicate), Enter-to-save form
- [x] dest/remap/tvdb strict digits with inline errors
- [x] YAML root validateManifest before save + live inline syntax hint
- [x] Import saves rely on server-side write_import parsing (validate endpoint is root-schema-only; documented in code)
- [x] Cookies Netscape format + 1MB cap, labeled file input, accept=".txt"
- [x] Path hints on config + platform tabs; Setup 8+ chars / must-match hints
- [x] Env-locked keys omitted from putConfig/putPlatform with lock display
- [x] sonarr_api_key write-only (masked last-4, set/unset states); `?reveal=1` used only to preserve on save and to ping

## Dirty / selection / extra
- [x] beforeunload + unsaved modal (Settings tabs/cookies/logout, Detail, YAML, RemapModal)
- [x] dirtyConfig/dirtyPlatform tracked separately
- [x] SeriesDetail logout/nav guarded
- [x] seriesUiStore LRU 50 + folderView persist, shape-validated, debounced
- [x] Selection tri-state footer + Clear; empty-untouched=all vs explicit-cleared=none
- [x] LibrarySeasons Set open + conflict badge
- [x] CreateSeriesModal real radios, inline slug/tvdb errors
- [x] LogViewer parsed spans stored once, cap 2000
- [x] Poster resets failedSrc/loaded on src change
- [x] Create missing folders toggle next to Force
- [x] Deep-link tab/folderView/query/selection/open folds (sel/open/seasons capped for URL length)
- [x] Dashboard rows clickable to detail (name link; poster/twist still toggles)
- [x] Offline banner on all pages + friendly mutation errors; SSE/polling pause offline
- [x] Password show/hide, autocomplete, busy disable
- [x] Change-password form POST /api/password
- [x] Onboarding checklist banner with deep links; refresh blocked with hint when paths unset
- [x] Listing copy single-sourced (`listingLabel`: "Listing YouTube", bare "Listing…" when unknown)

## Visual / a11y (code present; visual proof is manual, see below)
- [x] Breakpoints 720/480, episode-table scroll wrapper, toolbar wrap
- [x] Compact 2-row phone header (brand+actions row, scrollable nav row)
- [x] run-bar `position: fixed` + safe-area + centered max-width inner
- [x] Modals trap focus + Escape + return focus; menus are button groups with focus return
- [x] Roving tabindex on editor tabs / map-switch; real radios for platform
- [x] Light/dark token values (darker ok/warn/danger, white-on-accent fills)
- [x] color-mix fallbacks for banner/validation/chips/pills/badges/sections/poster/danger-hover
- [x] Skip-to-content, `<main>` landmarks, progressbar semantics, `role=status` skeletons
- [x] prefers-reduced-motion global; `Intl.RelativeTimeFormat`
- [x] PWA chrome only (theme-color, manifest, favicon, apple-touch-icon, noscript); no service worker
- [x] Mockups directional-only; chip order All / YouTube / Dropout; light/360px/empty/error variants
- [x] `.node-version` (root + web) and `tsconfig.node.json` covered by `pnpm typecheck`

## Manual browser sign-off (NOT performed — do not treat the above as visual QA)
- [ ] 360px: no horizontal overflow on Downloads / Shows / Detail / Settings
- [ ] Keyboard-only: full flows for modals, tabs, radios, menus, queue checkboxes
- [ ] Light and dark: badges, buttons, chips, toasts readable (AA spot-check)
- [ ] Notification opt-in actually delivers a "Download done" notification
- [ ] color-mix fallbacks render sanely in a browser without color-mix
- [ ] 44px targets spot-checked by touch; phone header 2-row layout confirmed
- [ ] SSE reconnect + expiry toast observed against a live server
- [ ] Offline banner + paused polling observed with network disabled
