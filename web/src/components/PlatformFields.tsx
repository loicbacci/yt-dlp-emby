import type { CookieJar, CookieKind, ManifestPaths, Source } from "../api";
import { pathNotices } from "../api";

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
  const cookieStatus = cookieJar?.usable
    ? "On file"
    : cookieJar?.exists
      ? "Empty file"
      : "Not set";
  const cookieClass = cookieJar?.usable ? "status-done" : "";

  return (
    <>
      <p class="settings-lead">
        Library and old_dir in {`${kind}.yaml`}. Empty uses config fallback.
      </p>
      {notices.map((notice) => (
        <div key={notice} class="banner banner-warn">{notice}</div>
      ))}
      <label class="settings-field">
        <span class="settings-label">Library</span>
        <input
          type="text"
          value={draft.library}
          spellcheck={false}
          onInput={(e) =>
            onChange({ ...draft, library: (e.currentTarget as HTMLInputElement).value })
          }
        />
      </label>
      <label class="settings-field">
        <span class="settings-label">Old / replaced files</span>
        <input
          type="text"
          value={draft.old_dir}
          spellcheck={false}
          onInput={(e) =>
            onChange({ ...draft, old_dir: (e.currentTarget as HTMLInputElement).value })
          }
        />
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
      <p class="settings-hint">{PLATFORM_LABEL[kind]} tab saves only {`${kind}.yaml`}.</p>
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
