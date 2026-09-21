import type { CookieJar, CookieKind, ManifestPaths, Source } from "../api";
import { pathNotices } from "../api";
import { pathHint } from "../formValidation";

const PLATFORM_LABEL: Record<Source, string> = {
  youtube: "YouTube",
  dropout: "Dropout.tv",
};

export type PlatformDraft = {
  library: string;
  old_dir: string;
  cookies: string;
};

export function PlatformFields({
  kind,
  draft,
  paths,
  cookieJar,
  defaultCookieName,
  onChange,
  onOpenCookies,
}: {
  kind: Source;
  draft: PlatformDraft;
  paths: ManifestPaths | null;
  cookieJar: CookieJar | null;
  defaultCookieName: string;
  onChange: (next: PlatformDraft) => void;
  onOpenCookies: () => void;
}) {
  const notices = pathNotices(paths);
  const cookieStatus = cookieJar?.usable ? "On file" : cookieJar?.exists ? "Empty file" : "Not set";
  const cookieClass = cookieJar?.usable ? "status-done" : "";
  // Env-locked manifest keys are omitted from PUT (omitLockedPlatform) and
  // shown read-only, mirroring the config tab's locked fields.
  const libraryLocked = paths?.library?.source === "env";
  const oldDirLocked = paths?.old_dir?.source === "env";
  const libraryDisplay = libraryLocked ? (paths?.library?.effective ?? "") : draft.library;
  const oldDirDisplay = oldDirLocked ? (paths?.old_dir?.effective ?? "") : draft.old_dir;

  return (
    <>
      <p class="settings-lead">
        Library and old_dir in {`${kind}.yaml`}. Empty uses config fallback.
      </p>
      {notices.map((notice) => (
        <div
          key={notice}
          class={notice.includes("overridden by") ? "banner" : "banner banner-warn"}
        >
          {notice}
        </div>
      ))}
      <label class={libraryLocked ? "settings-field is-locked" : "settings-field"}>
        <span class="settings-label">Library</span>
        <input
          type="text"
          value={libraryDisplay}
          disabled={libraryLocked}
          spellcheck={false}
          onInput={(e) =>
            onChange({ ...draft, library: (e.currentTarget as HTMLInputElement).value })
          }
        />
        {pathHint(libraryDisplay) && !libraryLocked && (
          <span class="settings-hint">{pathHint(libraryDisplay)}</span>
        )}
        {libraryLocked && paths?.library?.env_name && (
          <span class="settings-hint">
            {paths.library.env_name} overrides this manifest value. Change it in the environment,
            not here.
          </span>
        )}
      </label>
      <label class={oldDirLocked ? "settings-field is-locked" : "settings-field"}>
        <span class="settings-label">Old / replaced files</span>
        <input
          type="text"
          value={oldDirDisplay}
          disabled={oldDirLocked}
          spellcheck={false}
          onInput={(e) =>
            onChange({ ...draft, old_dir: (e.currentTarget as HTMLInputElement).value })
          }
        />
        {pathHint(oldDirDisplay) && !oldDirLocked && (
          <span class="settings-hint">{pathHint(oldDirDisplay)}</span>
        )}
        {oldDirLocked && paths?.old_dir?.env_name && (
          <span class="settings-hint">
            {paths.old_dir.env_name} overrides this manifest value. Change it in the environment,
            not here.
          </span>
        )}
      </label>
      <label class="settings-field">
        <span class="settings-label">Cookies path</span>
        <input
          type="text"
          value={draft.cookies}
          placeholder={defaultCookieName}
          spellcheck={false}
          onInput={(e) =>
            onChange({ ...draft, cookies: (e.currentTarget as HTMLInputElement).value })
          }
        />
        {pathHint(draft.cookies) && <span class="settings-hint">{pathHint(draft.cookies)}</span>}
      </label>
      <div class="settings-field">
        <div class="settings-cookie-row">
          <span class={`status-chip ${cookieClass}`}>
            <span class="status-dot" />
            {cookieStatus}
          </span>
          <button type="button" class="btn-secondary" onClick={onOpenCookies}>
            {cookieJar?.exists ? "Replace" : "Add"}
          </button>
        </div>
      </div>
      <p class="settings-hint">
        {PLATFORM_LABEL[kind]} tab saves only {`${kind}.yaml`}.
      </p>
    </>
  );
}

export function platformDraftFromApi(body: {
  library: string;
  old_dir: string;
  cookies: string;
}): PlatformDraft {
  return {
    library: body.library ?? "",
    old_dir: body.old_dir ?? "",
    cookies: body.cookies ?? "",
  };
}

export function cookieKindForPlatform(kind: Source): CookieKind {
  return kind;
}
