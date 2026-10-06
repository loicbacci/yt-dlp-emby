# Web application acceptance checklist

Use this checklist for browser verification after automated checks pass. Empty
boxes indicate checks still to perform; implementation or a passing unit test is
not a claim of visual/browser sign-off.

## Refresh and availability

- [ ] Shows, show detail, and individual source offer a plain Refresh action.
- [ ] Starting Refresh shows progress rather than immediately reading a final result.
- [ ] Show filtering/selection captures the intended batch when the job starts.
- [ ] A batch failure shows successful and unsuccessful targets individually.
- [ ] Sonarr Check is a separate action.
- [ ] Last-success time remains unchanged after a failed attempt.
- [ ] Unavailable NAS and failed scans show unknown counts and actionable errors.
- [ ] Missing show folder is distinct from missing library root.
- [ ] Newly discovered seasons are disabled and custom mappings survive refresh.

## Jobs and Downloads

- [ ] Navigation and reload rediscover the active job and its progress.
- [ ] Offline/hidden polling pauses and resumes on return.
- [ ] A browser polling failure does not claim the server job failed.
- [ ] Cancel shows Stopping until descendants have exited.
- [ ] Interrupted/failed work offers explicit Retry and preserves history/logs.
- [ ] Completed items are not inadvertently downloaded again by Retry.
- [ ] Empty selection cannot start execution.
- [ ] Stale selection/plan asks for review rather than executing changed actions.
- [ ] Replacement option accurately describes Dropout semantics.
- [ ] Progress/result/log views remain readable during batch work.

## Forms and configuration

- [ ] Mapping saves show pending state and use confirmed server results.
- [ ] Failed saves preserve drafts and show inline errors.
- [ ] Advanced YAML remains available and comments/import boundaries survive saves.
- [ ] Relevant edits are blocked while their inputs are in use by a job.
- [ ] Cookie/path/dependency failures provide useful settings or diagnostics links.
- [ ] Password fields retain autocomplete and show/hide controls.
- [ ] Setup/login/logout and password changes continue to work.

## Layout and accessibility

- [ ] 360px: no horizontal page overflow on Downloads, Shows, Detail, or Settings.
- [ ] Episode tables scroll inside their container on small screens.
- [ ] Keyboard-only: selection, cancel/retry, modals, tabs, and source controls work.
- [ ] Inputs and episode controls have associated accessible labels.
- [ ] Modals trap focus, close with Escape, and return focus appropriately.
- [ ] Light/dark badges, buttons, errors, and toasts are readable.
- [ ] Loading, empty, error, stale, unavailable, and complete states are distinguishable.
- [ ] Reduced motion and live progress/error announcements remain appropriate.
- [ ] Touch targets are usable and navigation wraps/scrolls predictably.
