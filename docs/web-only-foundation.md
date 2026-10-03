# Web-only foundation implementation handoff

## Accepted decisions

Keep Preact/Vite/TanStack Query and one Python/FastAPI web backend. Do not add
TanStack Start or a Node web server. Keep yt-dlp, ffmpeg, extraction, naming,
mapping, indexes, and media metadata behavior in Python. Remove public download,
layout, check, doctor, and benchmark CLI commands; retain a server launcher.
YAML/TOML and imported show files remain authoritative; Advanced YAML remains.
Local SQLite holds jobs, item completion, redacted bounded logs, and disposable
series views. Do not put SQLite on the media NAS.

One scoped Refresh replaces refresh modes. Sonarr Check is separate. Use private
Python worker processes with JSON stdin, structured JSONL stdout, and diagnostic
stderr. Browser progress uses one shared polling lifecycle, not SSE. Explicit
retry and interrupted-job recovery are required; automatic resume and partial
file continuation are deferred. Preserve existing URL slugs and media layouts.

## Baseline and workflow

Branch: codex/web-only-foundation. Worktree: .worktrees/web-only-foundation.
The existing seven tracked fixes are preserved separately in commit edd1afa;
the original dirty checkout must remain untouched. Never copy or commit ignored
credentials, cookies, manifests, deployment configuration, runtime state, or media.
Commit coherent milestones; do not automatically merge, deploy, or publish.

## Confirmed initial bugs

Refresh POST returns 202 with job_id/status, while the UI reads final results
immediately. Validate the start response and follow the job to completion on both
Shows and show detail. Preserve specific failures and batch partial success.
Discovery merging currently drops titles and overwrites destination seasons and
URLs. Preserve all existing user fields, keep disappeared configured seasons,
and add newly discovered seasons disabled. Regression: Dropout season 28 maps
to Emby season 27 with a custom title/remaps/exclusions and remains unchanged.

## Services and invariants

Configuration repository owns canonical loading, imports, stable locator/slug
identity, content hashes, validation, and comment-preserving locked atomic writes.
Resolve file-declared relative paths against their declaring file, environment
relative paths against the application data directory. Effective precedence is
environment, applicable manifest, then TOML/default. Read/validation must never
create a library root. Source position identities require a configuration revision.

Provider services return typed discovery/listing/check results without printed
business data. Reuse caches, distinguish cache reads from explicit refresh, and
do not make disk inspection require cookies or ffmpeg. Bound network requests.

Library scans return ready/unavailable, series_exists, episode/file fingerprints,
revision, timestamp, and typed error. Preserve Season 1/Season 01/Specials naming,
temporary exclusions, duplicate handling, .yt-emby.json and metadata cache formats.
Missing NAS, failed scan, and absent show folder are distinct. Unknown disk state
must never become zero files or all episodes missing. Keep symlink/traversal guards.
Record Linux mount identity; a disappeared known NAS mount cannot be replaced
silently by its empty underlying directory. Reset expected identity only through
explicit settings save and a successful health check. Never create library roots.

Pure planner takes configuration, remote listings, disk snapshot, and options;
returns statuses, mapped slots, explicit actions/dependencies, blocked reasons,
and input revision. It must never download, move, rename, delete, repair, clean
staging, migrate library caches, recover rename temporaries, invoke public CLI,
or reconstruct plans from emitted log events.

Executor receives explicit selected action IDs and an operation context (settings,
cancellation, selected actions, logger, progress callback, in-memory credentials).
Remove global event paths/current IDs/selections/sinks. Selection covers downloads,
replacement, rename and removal; unselected actions never run. A dependency that
modifies unrelated items needs explicit selection or the action is blocked.

## Refresh and execution flow

Capture explicit show scope at start (filtered shows, one show, or one source).
Per target: load/validate configuration; check library; discover; fetch enabled
sources; scan; build plan; publish successful view and timestamp. Source-scoped
refresh replaces only its contribution. Refresh may propose controlled disabled
season additions; parent applies them through repository. Otherwise write only
application metadata/caches, never media or staging. Sonarr is never a hidden stage.

Keep last good view stale on failure. Separate last_attempt_at/last_success_at;
success timestamps advance only on success. Batch continues independent targets
and ends failed if any target failed, retaining all outcomes. A stale/failed target
cannot provide executable actions until prerequisites are rebuilt. Mapping saves
replan from cached listings/disk without remote calls, or show Refresh required.
Layout previews use the pure planner instead of a separate command.

Downloads require nonempty IDs from a plan revision. Preserve Force for replacing
Dropout episodes and Create for missing show folders; label Force accurately.
Reload configuration/rescan before execution and reject material plan changes.
Check file preconditions before each mutation; rescan/rebuild after execution.

## Jobs, worker, persistence

States: queued, running, stopping, succeeded, failed, cancelled, interrupted.
queued is admission/startup, not an unattended persistent queue. One active job
globally covers refresh/download/check/diagnostics. Conflicts return 409 with active
ID. Relevant config/cookie/manifest writes are locked during active work; reads
remain available. Workers use immutable input snapshots and parent checks hashes
before writing/publishing. Keep lock until worker and descendants are reaped.

Protocol v1 requests contain operation/target/snapshot/selection/options. Keep stdin
open; EOF means parent loss and worker must stop descendants. stdout is JSONL only
with progress/item_result/result/error, monotonically increasing seq and identities;
stderr carries logs. Parent validates messages, kills malformed workers, owns all
SQLite/canonical writes. Worker owns authorized media writes and existing indexes.
Refresh runs one worker per target sequentially so timed-out targets are killed
before continuing. No detached timed-out work threads may write late results.

Timeouts: refresh 300s/target; download 21600s/job; check/diagnostics 300s; HTTP 30s
with bounded retries. SIGINT process group, wait 5s, SIGTERM wait 2s, then SIGKILL;
reap and drain readers before unlock. Same path handles stop, timeout, malformed
protocol, shutdown, and parent loss.

SQLite tables: schema_migrations; jobs (scope/options/state/times/progress/results/
errors/worker identity/retry parent); job_items (selected identity/action/target/state/
completion); job_logs (ordered redacted lines); series_views (derived inputs/plan/
revisions/freshness/times/error). Validate JSON, enable foreign keys/WAL/busy timeout,
single coordinator writer. Persist item completion immediately; noisy progress at
most 4Hz. Retain 100 terminal jobs plus active; 5000 logs/job, 4KiB/line; latest views
independent of retention. Snapshot returns at most 200 new lines with cursor.

Exclusive data-dir coordinator lock prevents two servers. On startup verify old
worker identity (not PID alone) and death, mark abandoned queued/running/stopping
jobs interrupted. Never auto-resume. Retry creates linked new job, reloads/rescans,
skips verified completed selected items, retries incomplete ones, and rejects changed
mapping/action meaning. Media temporary recovery belongs to download, not refresh.

## API contract

Pydantic models and matching frontend Zod validators:

- POST /api/jobs returns 202 {job_id,status:"queued"}.
- GET /api/jobs returns active job and paginated terminal history.
- GET /api/jobs/{id}?log_after=N returns snapshot and incremental logs.
- POST /api/jobs/{id}/cancel returns snapshot, terminal cancel is idempotent.
- POST /api/jobs/{id}/retry returns new 202 start; active/successful retries are 409.
- GET /api/plans/latest returns cached plan/readiness, never network/disk scans.

Discriminated requests: refresh with items:[{platform,slug}], optional source_index,
expected_revision; download with plan_id, ids, force/create; check with items;
diagnostics with checks. Plan response retains existing generated_at/force/sources
shape while adding plan_id/revision/readiness. Job snapshot: id/kind/status/timestamps/
progress/result/error/logs/log_cursor/logs_truncated/can_cancel/can_retry. Progress:
stage/target/completed/total plus optional item event. Refresh result {ok,results},
per-target platform/slug/error. Logs {n,ts,line}. GET jobs {active,history,total}.

Errors {error,code,request_id}; codes JOB_CONFLICT, CONFIG_CHANGED, PLAN_STALE,
LIBRARY_UNAVAILABLE, SOURCE_TIMEOUT, WORKER_FAILED. Keep auth and path/URL restrictions.
Plan ID hashes relevant config/listing/disk/options, not timestamp alone; IDs use
provider identity separately from target/action. Never interpret bad IDs as all.
Remove final synchronous refresh/parts, legacy run/SSE and refresh-job routes.

## Frontend

TanStack Query owns server state; remove localStorage server-query persistence,
refresh store, SSE/reconnect, competing run/plan polls, redundant detail copies,
and optimistic manifest rewrites. Keep local drafts/selections/folds/UI preferences;
filters/tabs in URL. Failed save preserves draft. Remove obsolete cache keys once.
Shared job poll every 1s online+visible; pause offline/hidden, refetch on return;
reload fetches active job; navigation does not cancel it. Stop terminal polling,
invalidate affected queries once. Transport errors are not job failures. Shared
progress component shows stage/target/time/result/cancel/retry and bounded logs.
Plain Refresh, separate Sonarr Check, last-success/stale/unavailable indications.
Unknown counts render as unknown. Preserve accessibility fixes and keyboard use.

Shared sanitized contract fixtures: queued/running/success/partial failure/cancel/
interrupted/stale plan/unavailable library, validated in backend and frontend CI.

## Cleanup and migration

Remove CLI orchestration, old manager/refresh registry/event-to-plan/global events,
runtime plan.json/events.jsonl/download-only.json, obsolete refresh modes/SSE,
benchmark-only configuration/dependencies. Port meaningful CLI behavior tests to
services before removing compatibility tests. Keep thin host/port/data-dir launcher.
Promote server dependencies to normal dependencies; remove duplicate extra/groups.
One Docker container, Python serves static UI, retain nonroot/tini/ffmpeg/Node yt-dlp
runtime. Update versions to 0.2.0 and lockfiles/docs/CI/installation/Docker examples.

First launch migrates DB, preserves canonical files/cookies/media/indexes, archives
legacy derived state once, marks views Refresh required, never replays selections
or auto-refreshes all shows. Config is authoritative across file/DB crash windows;
store hashes and reject stale views. Document removed commands/replacements,
NAS troubleshooting, interruption/retry, first refresh and rollback.

## Milestones and acceptance

1. Preserve baseline and handoff.
2. Fix async refresh and season merge regression.
3. Explicit repository/provider/library/pure planner/executor boundaries.
4. Structured worker and process-group cancellation/parent-loss.
5. SQLite jobs/progress/completion/recovery/retry.
6. Backend unified refresh/download/check/diagnostics and revision/NAS guards.
7. Shared frontend job lifecycle and simplified refresh.
8. Delete old paths, update packaging/Docker/docs/CI.
9. Full integration verification and final commits.

Required tests: asynchronous refresh pages/batch partial/source-only; preserved
custom mappings/import comments; external hash conflicts; no refresh/planning media
writes; NAS missing/mount disappearance/permissions/absent show/empty show distinct;
season/index/duplicate/path compatibility; cached mapping replan; stale/mixed IDs;
rename/remove selection; multi-tab admission; timeout/cancel kills descendants before
unlock; no late writes; stderr flood/protocol invalidity/parent loss; interruption/
explicit safe retry; retention; no secret leakage; frontend reload/navigation/offline/
visibility/one completion invalidation/transport distinction/unknown counts/drafts/
accessible selection/cancel/retry.

Run ruff lint+format, mypy server/new services, nonnetwork pytest with 70% gate,
frontend typecheck/lint/format/vitest/build, shared contract fixtures, shell/container
health/nonroot/signal checks. Do not weaken coverage or remove valid failing tests.
Fake providers/temp libraries/subprocess fixtures are primary; live NAS/Dropout is
additional and must be reported unverified when unavailable. Final report includes
branch/worktree/commits/check results/interfaces removed/deployment limitations.
