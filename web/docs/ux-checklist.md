# UX checklist

Per-page loading, empty, error, and success states for the yt-dlp-emby web UI.

Legend: `[x]` = verified in code (logic present; `pnpm --dir web typecheck/test/lint` green).
Manual browser checks live in their own section at the bottom and are NOT signed off.

## Downloads (`/`)

- [x] Loading: `QueueSkeleton` while plan is pending (no “No queue yet” flash)
- [x] Empty: search miss copy; idle empty queue copy; `LogViewer` “No output yet”
- [x] Error: plan/run retry cards (`role=alert`); stop errors toast + inline; Settings deep link
- [x] Success: toasts for start/stop/done; `document.title` `Downloading n/m` / `Done`; optional Notification opt-in wired
- [x] Stop always confirms; confirm label becomes `Stopping…`; large download confirm mentions 25+
- [x] Selection footer tri-state (`N of M pending`) + Clear; empty untouched = all, explicit clear = none
- [x] Rows click through to series detail; create-missing-folders toggle; offline banner
- [x] Live events: Connecting when `last==0`, reconnect backoff 1s–8s, doneIds kept, overlay throttled, 401 expiry toast
- [x] Deep-link: q/force/create/selection/open folds in URL (sel/open/seasons length-capped)
- [x] Primary button and RefreshSplit always carry a disabled reason via `title`
- [x] Onboarding checklist banner until paths + cookies + show + refresh are done

## Shows (`/series`)

- [x] Loading: `SeriesListSkeleton` aligned with `.show-row`
- [x] Empty: “No series yet” + Add show CTA; search miss copy
- [x] Error: retry card for list load; refreshItems try/catch + per-item toast
- [x] Success: refresh complete toast; create navigates + toast; delete navigates + toast
- [x] Filter chips All / YouTube / Dropout; query + platform in URL
- [x] Offline banner

## Show detail (`/series/:platform/:slug`)

- [x] Loading: seed from cache; skeleton (`role=status`); SessionGate spinner; unknown `/series/*` redirects to `/series`
- [x] Empty: “No playlists yet”; Library no-seasons; EpisodeTable empty copy
- [x] Error: retry card; modal errors stay in modal; `checkError` as error; `only_episodes` inline at row; dest errors inline at input
- [x] Success: skip/remap/enable/title/dest/tvdb_skip/source-add toasts; Add URL toast
- [x] Dirty: beforeunload + confirm modal (nav/logout/tab); logout guarded; edits blocked while running with reason tooltips
- [x] Server-changed reload prompt; `mutationBusy`; folderView in URL + store (LRU 50)
- [x] TvdbSkip strict digits, Add disabled unless both parse, inline error, shared `addTvdbSkip` util
- [x] RemapModal: debounced suggest, dirty-close confirm, Sonarr loading state
- [x] Sonarr warnings keyed by code-detail-index (no key collisions)

## Settings (`/settings`)

- [x] Loading: skeleton until first load; partial render + per-section retry afterwards (single save-error box)
- [x] Error: per-section retry cards; path/cookie failures deep-link to the matching tab
- [x] Success: Saved / Cookies saved toasts (config + platform tabs)
- [x] Dirty: `dirtyConfig` vs `dirtyPlatform`; tab switch confirm; beforeunload
- [x] Env-locked keys omitted from `putConfig`/`putPlatform`; lock display on both tabs
- [x] Cookies Netscape + 1MB; YAML live parse hint + root `validateManifest` (imports server-validated); path hints; scrollable tabs
- [x] sonarr_api_key write-only with masked last-4 + set/unset states + Remove; `?reveal=1` only to preserve on save and to ping
- [x] Offline banner + friendly mutation errors
- [x] Change-password form (`POST /api/password`); reset documented

## Auth (`/login`, `/setup`)

- [x] SessionGate spinner; error + Retry; return URL after login
- [x] Password show/hide, autocomplete, busy disable, 8+ char / must-match hints
- [x] Setup ↔ Login cross-links

## Shared

- [x] Toasts stack, auto-dismiss 4s, `role=status` / `role=alert`
- [x] ConfirmModal pending + focus Cancel when danger
- [x] Skip-to-content, `<main>` landmarks, progressbar semantics
- [x] 44px tap targets; compact 2-row phone header; run-bar `position: fixed` + safe-area + inner max-width
- [x] Breakpoints 720 / 480; episode-table scroll; toolbar wrap
- [x] Light mode darker `--ok/--warn/--danger`; `header-link.active` white-on-accent; dark `--accent-fill`
- [x] `prefers-reduced-motion` global; `Intl.RelativeTimeFormat`
- [x] PWA chrome only (theme-color, manifest, favicon, apple-touch-icon, noscript); no service worker
- [x] Mockups directional-only; chip order All / YouTube / Dropout; light/360px/empty/error variants
- [x] `.node-version` (root + web) and `tsconfig.node.json` covered by `pnpm typecheck`
- [x] Listing copy single-sourced (`listingLabel`); `accept=".txt"`; memoized SeriesRow + SeasonAccordion derivations

## Manual sign-off (NOT performed — do not treat the above as visual QA)

- [ ] 360px: no horizontal overflow on Downloads / Shows / Detail / Settings
- [ ] Keyboard-only: modals trap + Escape; radios/tabs arrow keys; menus are button groups
- [ ] Light and dark: badges, buttons, chips readable
- [ ] Notification opt-in actually delivers
- [ ] Touch spot-check of 44px targets and the phone header
