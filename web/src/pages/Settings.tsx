import { useEffect, useRef, useState } from "preact/hooks";
import {
  ApiError,
  type AppConfig,
  type ConfigKey,
  type ConfigValues,
  type CookieJar,
  type CookieKind,
  type CookieStatus,
  apiClient,
  omitLockedConfig,
  omitLockedPlatform,
  slotDisplay,
  slotIsSet,
  slotText,
  valuesFromConfig,
} from "../api";
import { logoutAndClear } from "../auth";
import { AdvancedYamlPanel } from "../components/AdvancedYamlPanel";
import { ConfirmModal } from "../components/ConfirmModal";
import { CookieModal } from "../components/CookieModal";
import { Header } from "../components/Header";
import { PasswordField } from "../components/PasswordField";
import {
  type PlatformDraft,
  PlatformFields,
  platformDraftFromApi,
} from "../components/PlatformFields";
import { SettingsSkeleton } from "../components/Skeleton";
import { pushToast } from "../components/Toast";
import { netscapeCookieError, pathHint } from "../formValidation";
import { isBrowserOnline, useOnline } from "../hooks/useOnline";
import { go } from "../nav";
import { writeSearch } from "../urlState";

const emptyValues: ConfigValues = {
  library: "",
  old_dir: "",
  staging: "",
  bench_dest: "",
  shows_dir: "",
  sonarr_url: "",
  sonarr_api_key: "",
};

type SettingsTab = "config" | "youtube" | "dropout" | "advanced";

const emptyPlatform: PlatformDraft = { library: "", old_dir: "", cookies: "" };

const FALLBACK_FIELDS: { key: ConfigKey; label: string; hint: string }[] = [
  {
    key: "library",
    label: "Library",
    hint: "Emby library root. Used when a manifest omits library.",
  },
  {
    key: "old_dir",
    label: "Old / replaced files",
    hint: "Where replaced or removed files are moved. Used when a manifest omits old_dir.",
  },
  {
    key: "staging",
    label: "Staging",
    hint: "Local disk for in-progress downloads. Used when a manifest omits staging.",
  },
];

const HOST_FIELDS: { key: ConfigKey; label: string; hint: string; password?: boolean }[] = [
  {
    key: "bench_dest",
    label: "Bench destination",
    hint: "Destination for `yt-dlp-emby bench` (defaults to library).",
  },
  {
    key: "shows_dir",
    label: "Shows folder",
    hint: "Relative to the data directory. Series import files live here.",
  },
];

const SONARR_FIELDS: { key: ConfigKey; label: string; hint: string; password?: boolean }[] = [
  {
    key: "sonarr_url",
    label: "URL",
    hint: "Base URL, including port. Example: http://localhost:8989",
  },
  {
    key: "sonarr_api_key",
    label: "API key",
    hint: "Settings → General → Security in Sonarr. Do not put this in dropout.yaml.",
    password: true,
  },
];

type SonarrCheckState =
  | { status: "idle" }
  | { status: "checking" }
  | { status: "ok"; version: string | null; instance: string | null }
  | { status: "error"; message: string };

function fieldDisplay(config: AppConfig | null, draft: ConfigValues, key: ConfigKey): string {
  const meta = config?.fields[key];
  // slotDisplay keeps masked {set, masked} secret objects renderable; the
  // sonarr_api_key draft itself stays write-only (see valuesFromConfig).
  if (meta?.source === "env") return slotDisplay(meta.effective);
  return draft[key];
}

function friendlyMessage(err: unknown, fallback: string): string {
  if (!isBrowserOnline() || err instanceof TypeError) {
    return "You appear offline. Reconnect and try again.";
  }
  return err instanceof ApiError ? err.message : fallback;
}

function sonarrPingMessage(result: {
  version: string | null;
  instance: string | null;
}): string {
  const name = result.instance?.trim() || "Sonarr";
  return result.version ? `Connected to ${name} ${result.version}` : `Connected to ${name}`;
}

const COOKIE_FIELDS: Record<
  "youtube" | "dropout",
  { kind: CookieKind; label: string; hint: string }
> = {
  youtube: {
    kind: "youtube",
    label: "YouTube cookies",
    hint: "Netscape cookies.txt export. Contents are write-only.",
  },
  dropout: {
    kind: "dropout",
    label: "Dropout cookies",
    hint: "Netscape cookies.txt export. Contents are write-only.",
  },
};

export function Settings() {
  const online = useOnline();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [saved, setSaved] = useState<ConfigValues>(emptyValues);
  const [draft, setDraft] = useState<ConfigValues>(emptyValues);
  const [error, setError] = useState<string | null>(null);
  const [loadErrors, setLoadErrors] = useState<{
    config: string | null;
    cookies: string | null;
    youtube: string | null;
    dropout: string | null;
  }>({ config: null, cookies: null, youtube: null, dropout: null });
  const [cookieError, setCookieError] = useState<string | null>(null);
  const [revealKey, setRevealKey] = useState(false);
  const [clearKey, setClearKey] = useState(false);
  const [sonarrCheck, setSonarrCheck] = useState<SonarrCheckState>({
    status: "idle",
  });
  const checkGen = useRef(0);
  const [cookies, setCookies] = useState<CookieStatus | null>(null);
  const [cookieModal, setCookieModal] = useState<CookieKind | null>(null);
  const [cookieDraft, setCookieDraft] = useState("");
  const [cookieSaving, setCookieSaving] = useState(false);
  const [tab, setTab] = useState<SettingsTab>(
    (["config", "youtube", "dropout", "advanced"] as const).includes(
      (typeof window === "undefined"
        ? ""
        : new URLSearchParams(window.location.search).get("tab")) as SettingsTab,
    )
      ? (new URLSearchParams(window.location.search).get("tab") as SettingsTab)
      : "config",
  );
  const [loaded, setLoaded] = useState(false);
  const [unsavedTo, setUnsavedTo] = useState<string | null>(null);
  const [pwCurrent, setPwCurrent] = useState("");
  const [pwNext, setPwNext] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [yamlDirty, setYamlDirty] = useState(false);
  const [platformDraft, setPlatformDraft] = useState<{
    youtube: PlatformDraft;
    dropout: PlatformDraft;
  }>({ youtube: emptyPlatform, dropout: emptyPlatform });
  const [platformSaved, setPlatformSaved] = useState<{
    youtube: PlatformDraft;
    dropout: PlatformDraft;
  }>({ youtube: emptyPlatform, dropout: emptyPlatform });
  const [platformPaths, setPlatformPaths] = useState<{
    youtube: import("../api").ManifestPaths | null;
    dropout: import("../api").ManifestPaths | null;
  }>({ youtube: null, dropout: null });
  const [platformJars, setPlatformJars] = useState<{
    youtube: CookieJar | null;
    dropout: CookieJar | null;
  }>({ youtube: null, dropout: null });

  const dirtyConfig = JSON.stringify(draft) !== JSON.stringify(saved) || clearKey;
  const dirtyPlatform =
    tab === "youtube" || tab === "dropout"
      ? JSON.stringify(platformDraft[tab]) !== JSON.stringify(platformSaved[tab])
      : JSON.stringify(platformDraft) !== JSON.stringify(platformSaved);
  const dirty =
    tab === "config"
      ? dirtyConfig
      : tab === "youtube" || tab === "dropout"
        ? JSON.stringify(platformDraft[tab]) !== JSON.stringify(platformSaved[tab])
        : false;
  const dirtyCookies = Boolean(cookieModal && cookieDraft.trim());
  const anyDirty = dirtyConfig || dirtyPlatform || yamlDirty || dirtyCookies;

  // Masked sonarr_api_key state. The draft never holds the stored secret, so
  // "edited" is simply "typed something"; clearing needs an explicit flag.
  const keyField = config?.fields.sonarr_api_key;
  const keyLocked = keyField?.source === "env";
  const keyFileSet = slotIsSet(keyField?.file);
  const keyEffectiveSet = slotIsSet(keyField?.effective);
  const keyMasked = slotDisplay(keyField?.file) || slotDisplay(keyField?.effective);
  const keyEdited = draft.sonarr_api_key !== "";

  type LoadSection = "config" | "cookies" | "youtube" | "dropout";

  const loadSection = async (section: LoadSection): Promise<void> => {
    // Partial render: each section loads independently so one failure never
    // blanks the whole page; failures surface as per-section retry cards.
    try {
      if (section === "config") {
        const next = await apiClient.getConfig();
        const values = valuesFromConfig(next);
        setConfig(next);
        setSaved(values);
        setDraft(values);
        setClearKey(false);
      } else if (section === "cookies") {
        setCookies(await apiClient.getCookies());
        setCookieModal(null);
        setCookieDraft("");
        setCookieError(null);
      } else {
        const body = await apiClient.getPlatform(section);
        const values = platformDraftFromApi(body);
        setPlatformDraft((current) => ({ ...current, [section]: values }));
        setPlatformSaved((current) => ({ ...current, [section]: values }));
        setPlatformPaths((current) => ({ ...current, [section]: body.paths }));
        setPlatformJars((current) => ({ ...current, [section]: body.cookie_jar }));
      }
      setLoadErrors((current) => ({ ...current, [section]: null }));
    } catch (err) {
      setLoadErrors((current) => ({
        ...current,
        [section]: friendlyMessage(err, `Failed to load ${section}`),
      }));
    }
  };

  const load = async () => {
    setError(null);
    await Promise.all([
      loadSection("config"),
      loadSection("cookies"),
      loadSection("youtube"),
      loadSection("dropout"),
    ]);
    setLoaded(true);
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    writeSearch({ tab: tab === "config" ? null : tab });
  }, [tab]);

  useEffect(() => {
    if (!anyDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [anyDirty]);

  const navigate = (url: string) => {
    if (url === "/settings") return;
    if (anyDirty) {
      setUnsavedTo(url);
      return;
    }
    go(url);
  };

  const switchTab = (next: SettingsTab) => {
    if (next === tab) return;
    if (anyDirty) {
      setUnsavedTo(`tab:${next}`);
      return;
    }
    setTab(next);
    setError(null);
  };

  const sonarrUrl = fieldDisplay(config, draft, "sonarr_url").trim();
  const draftKey = draft.sonarr_api_key.trim();
  // Ping needs a raw key: use the typed draft, else the stored key via ?reveal=1.
  const canCheckSonarr = Boolean(sonarrUrl && (draftKey || keyEffectiveSet));

  useEffect(() => {
    checkGen.current += 1;
    setSonarrCheck({ status: "idle" });
  }, [sonarrUrl, draftKey, keyEffectiveSet]);

  const checkSonarr = async () => {
    if (!canCheckSonarr || sonarrCheck.status === "checking") return;
    const gen = ++checkGen.current;
    setSonarrCheck({ status: "checking" });
    try {
      let key = draftKey;
      if (!key) {
        const revealed = await apiClient.getConfig(true);
        const field = revealed.fields.sonarr_api_key;
        key = slotText(field?.effective) || slotText(field?.file);
      }
      if (gen !== checkGen.current) return;
      if (!key) {
        setSonarrCheck({ status: "error", message: "API key is not set" });
        return;
      }
      const result = await apiClient.pingSonarr({
        sonarr_url: sonarrUrl,
        sonarr_api_key: key,
      });
      if (gen !== checkGen.current) return;
      setSonarrCheck({
        status: "ok",
        version: result.version,
        instance: result.instance,
      });
    } catch (err) {
      if (gen !== checkGen.current) return;
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setSonarrCheck({
        status: "error",
        message: friendlyMessage(err, "Sonarr check failed"),
      });
    }
  };

  const save = async () => {
    setError(null);
    try {
      if (tab === "config") {
        const payload = omitLockedConfig(draft, config);
        if (!keyLocked) {
          if (clearKey) {
            payload.sonarr_api_key = "";
          } else if (!keyEdited && keyFileSet) {
            // PUT replaces the whole file, so an untouched-but-set key must be
            // re-sent from ?reveal=1 or the save would wipe it. Abort loudly
            // rather than risk wiping when the reveal fetch fails.
            try {
              const revealed = await apiClient.getConfig(true);
              payload.sonarr_api_key = slotText(revealed.fields.sonarr_api_key.file);
            } catch {
              setError("Could not preserve the stored API key; save aborted. Retry to try again.");
              return;
            }
          }
        }
        const next = await apiClient.putConfig(payload);
        const values = valuesFromConfig(next);
        setConfig(next);
        setSaved(values);
        setDraft(values);
        setClearKey(false);
        pushToast("Saved");
        return;
      }
      if (tab !== "youtube" && tab !== "dropout") return;
      const body = await apiClient.putPlatform(
        tab,
        omitLockedPlatform(platformDraft[tab], platformPaths[tab]),
      );
      const values = platformDraftFromApi(body);
      setPlatformDraft((current) => ({ ...current, [tab]: values }));
      setPlatformSaved((current) => ({ ...current, [tab]: values }));
      setPlatformPaths((current) => ({
        ...current,
        [tab]: body.paths,
      }));
      setPlatformJars((current) => ({ ...current, [tab]: body.cookie_jar }));
      pushToast("Saved");
    } catch (err) {
      setError(friendlyMessage(err, "Save failed"));
    }
  };

  const changePassword = async () => {
    if (!pwCurrent || pwNext.length < 8 || pwBusy) return;
    setPwBusy(true);
    try {
      await apiClient.changePassword(pwCurrent, pwNext);
      setPwCurrent("");
      setPwNext("");
      pushToast("Password updated");
    } catch (err) {
      setError(friendlyMessage(err, "Password change failed"));
    } finally {
      setPwBusy(false);
    }
  };

  const openCookieModal = (kind: CookieKind) => {
    if (dirtyCookies) {
      setUnsavedTo(`cookies-open:${kind}`);
      return;
    }
    setCookieError(null);
    setCookieDraft("");
    setCookieModal(kind);
  };

  const closeCookieModal = () => {
    if (cookieSaving) return;
    if (dirtyCookies) {
      setUnsavedTo("cookies-close");
      return;
    }
    setCookieModal(null);
    setCookieDraft("");
    setCookieError(null);
  };

  const saveCookies = async () => {
    if (!cookieModal || !cookieDraft.trim() || cookieSaving) return;
    const cookieErr = netscapeCookieError(cookieDraft);
    if (cookieErr) {
      setCookieError(cookieErr);
      return;
    }
    setCookieError(null);
    setCookieSaving(true);
    try {
      const next = await apiClient.putCookies(cookieModal, cookieDraft);
      setCookies(next);
      const platform = await apiClient.getPlatform(cookieModal);
      const values = platformDraftFromApi(platform);
      setPlatformDraft((current) => ({ ...current, [cookieModal]: values }));
      setPlatformSaved((current) => ({ ...current, [cookieModal]: values }));
      setPlatformPaths((current) => ({
        ...current,
        [cookieModal]: platform.paths,
      }));
      setPlatformJars((current) => ({
        ...current,
        [cookieModal]: platform.cookie_jar,
      }));
      setCookieModal(null);
      setCookieDraft("");
      pushToast("Cookies saved");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setCookieError(friendlyMessage(err, "Cookie save failed"));
    } finally {
      setCookieSaving(false);
    }
  };

  const logout = async () => {
    if (anyDirty) {
      setUnsavedTo("logout");
      return;
    }
    await logoutAndClear();
  };

  const cookieField = cookieModal ? COOKIE_FIELDS[cookieModal] : null;
  const filename =
    tab === "config"
      ? (config?.path ?? "config.toml")
      : tab === "youtube"
        ? "youtube.yaml"
        : tab === "dropout"
          ? "dropout.yaml"
          : "yaml manifests";

  return (
    <>
      <Header current="settings" onLogout={logout} onNavigate={navigate} />
      <div class="settings-shell">
        <main class="card settings-card" id="main">
          <div class="editor-header">
            <div>
              <h1 class="settings-title">Settings</h1>
              <div class="editor-filename">{filename}</div>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              {(dirty || yamlDirty) && <span class="editor-unsaved">Unsaved</span>}
              {tab !== "advanced" && (
                <button type="button" class="btn-secondary" disabled={!dirty} onClick={save}>
                  Save
                </button>
              )}
            </div>
          </div>
          <div class="settings-tabs">
            <button
              type="button"
              class={tab === "config" ? "settings-tab active" : "settings-tab"}
              data-testid="settings-tab-config"
              onClick={() => switchTab("config")}
            >
              Config
            </button>
            <button
              type="button"
              class={tab === "youtube" ? "settings-tab active" : "settings-tab"}
              data-testid="settings-tab-youtube"
              onClick={() => switchTab("youtube")}
            >
              YouTube
            </button>
            <button
              type="button"
              class={tab === "dropout" ? "settings-tab active" : "settings-tab"}
              data-testid="settings-tab-dropout"
              onClick={() => switchTab("dropout")}
            >
              Dropout.tv
            </button>
            <button
              type="button"
              class={tab === "advanced" ? "settings-tab active" : "settings-tab"}
              data-testid="settings-tab-advanced"
              onClick={() => switchTab("advanced")}
            >
              Advanced
            </button>
          </div>
          {error && (
            <div class="validation-error" role="alert">
              {error}
              <button type="button" class="btn-secondary" onClick={() => void load()}>
                Retry
              </button>
            </div>
          )}
          {!online && (
            <div class="banner banner-warn" role="status">
              You appear offline. Changes can't be saved until you reconnect.
            </div>
          )}
          {!loaded ? (
            <SettingsSkeleton />
          ) : (
            <>
              {tab === "config" &&
                (loadErrors.config ? (
                  <SectionRetry
                    label="Config"
                    message={loadErrors.config}
                    onRetry={() => loadSection("config")}
                  />
                ) : (
                  <>
                    <p class="settings-lead">
                      These values are written to config.toml. Path keys live under{" "}
                      <code>[fallback]</code> and are used only when a manifest omits that path.
                      Environment variables override both the manifest and this file.
                    </p>
                    <section class="settings-section">
                      <h2 class="settings-heading">Path fallbacks</h2>
                      {FALLBACK_FIELDS.map((field) => (
                        <ConfigInput
                          key={field.key}
                          field={field}
                          config={config}
                          draft={draft}
                          revealKey={revealKey}
                          onRevealKey={setRevealKey}
                          onChange={(value) =>
                            setDraft((current) => ({ ...current, [field.key]: value }))
                          }
                        />
                      ))}
                    </section>
                    <section class="settings-section">
                      <h2 class="settings-heading">This host</h2>
                      {HOST_FIELDS.map((field) => (
                        <ConfigInput
                          key={field.key}
                          field={field}
                          config={config}
                          draft={draft}
                          revealKey={revealKey}
                          onRevealKey={setRevealKey}
                          onChange={(value) =>
                            setDraft((current) => ({ ...current, [field.key]: value }))
                          }
                        />
                      ))}
                    </section>
                    <section class="settings-section">
                      <h2 class="settings-heading">Sonarr</h2>
                      <p class="settings-section-lead">
                        Used by Dropout check to match episodes and suggest remaps.
                      </p>
                      {SONARR_FIELDS.map((field) => (
                        <ConfigInput
                          key={field.key}
                          field={field}
                          config={config}
                          draft={draft}
                          revealKey={revealKey}
                          onRevealKey={setRevealKey}
                          secret={
                            field.key === "sonarr_api_key" && !keyLocked
                              ? {
                                  set: keyFileSet || keyEffectiveSet,
                                  masked: keyMasked,
                                  edited: keyEdited,
                                  clearing: clearKey,
                                  onClear: () => setClearKey(true),
                                  onUndoClear: () => setClearKey(false),
                                }
                              : undefined
                          }
                          onChange={(value) =>
                            setDraft((current) => ({ ...current, [field.key]: value }))
                          }
                        />
                      ))}
                      <div class="settings-sonarr-check">
                        <button
                          type="button"
                          class="btn-secondary"
                          disabled={!canCheckSonarr || sonarrCheck.status === "checking"}
                          onClick={() => void checkSonarr()}
                        >
                          {sonarrCheck.status === "checking" ? "Checking…" : "Check connection"}
                        </button>
                        {sonarrCheck.status === "ok" && (
                          <span class="settings-check-ok">{sonarrPingMessage(sonarrCheck)}</span>
                        )}
                        {sonarrCheck.status === "error" && (
                          <span class="settings-check-error">{sonarrCheck.message}</span>
                        )}
                      </div>
                    </section>
                    <section class="settings-section">
                      <h2 class="settings-heading">Admin password</h2>
                      <p class="settings-section-lead">
                        Change the local admin password. Reset by removing{" "}
                        <code>/data/.yt-dlp-emby-auth.json</code>.
                      </p>
                      <PasswordField
                        label="Current password"
                        value={pwCurrent}
                        autoComplete="current-password"
                        id="settings-pw-current"
                        onChange={setPwCurrent}
                      />
                      <PasswordField
                        label="New password"
                        value={pwNext}
                        autoComplete="new-password"
                        id="settings-pw-next"
                        onChange={setPwNext}
                      />
                      {pwNext && pwNext.length < 8 && (
                        <p class="settings-hint">Use 8+ characters</p>
                      )}
                      <button
                        type="button"
                        class="btn-secondary"
                        disabled={pwBusy || !pwCurrent || pwNext.length < 8}
                        onClick={() => void changePassword()}
                      >
                        {pwBusy ? "Updating…" : "Update password"}
                      </button>
                    </section>
                  </>
                ))}
              {tab === "youtube" &&
                (loadErrors.youtube ? (
                  <SectionRetry
                    label="YouTube manifest"
                    message={loadErrors.youtube}
                    onRetry={() => loadSection("youtube")}
                  />
                ) : (
                  <PlatformFields
                    kind="youtube"
                    draft={platformDraft.youtube}
                    paths={platformPaths.youtube}
                    cookieJar={platformJars.youtube}
                    defaultCookieName="cookies.txt"
                    onChange={(next) =>
                      setPlatformDraft((current) => ({ ...current, youtube: next }))
                    }
                    onOpenCookies={() => openCookieModal("youtube")}
                  />
                ))}
              {tab === "dropout" &&
                (loadErrors.dropout ? (
                  <SectionRetry
                    label="Dropout manifest"
                    message={loadErrors.dropout}
                    onRetry={() => loadSection("dropout")}
                  />
                ) : (
                  <PlatformFields
                    kind="dropout"
                    draft={platformDraft.dropout}
                    paths={platformPaths.dropout}
                    cookieJar={platformJars.dropout}
                    defaultCookieName="dropout-cookies.txt"
                    onChange={(next) =>
                      setPlatformDraft((current) => ({ ...current, dropout: next }))
                    }
                    onOpenCookies={() => openCookieModal("dropout")}
                  />
                ))}
              {tab === "advanced" && <AdvancedYamlPanel onDirtyChange={setYamlDirty} />}
              {loadErrors.cookies && (
                <SectionRetry
                  label="Cookie status"
                  message={loadErrors.cookies}
                  onRetry={() => loadSection("cookies")}
                />
              )}
              {cookies?.env_set && cookies.env_name && tab !== "config" && (
                <div class="banner banner-warn">
                  {cookies.env_name} overrides both jars
                  {cookies.env_path ? ` (${cookies.env_path})` : ""}. Change it in the environment,
                  not here.
                </div>
              )}
            </>
          )}
        </main>
        {cookieField && (
          <CookieModal
            field={cookieField}
            draft={cookieDraft}
            error={cookieError}
            saving={cookieSaving}
            onChange={setCookieDraft}
            onSave={saveCookies}
            onClose={closeCookieModal}
          />
        )}
        {unsavedTo && (
          <ConfirmModal
            title="Unsaved changes"
            message="Discard unsaved changes?"
            confirmLabel="Discard"
            danger
            onCancel={() => setUnsavedTo(null)}
            onConfirm={() => {
              const next = unsavedTo;
              setUnsavedTo(null);
              if (next === "logout") {
                void logoutAndClear();
                return;
              }
              if (next === "cookies-close") {
                setCookieModal(null);
                setCookieDraft("");
                setCookieError(null);
                return;
              }
              if (next.startsWith("cookies-open:")) {
                setCookieModal(next.slice("cookies-open:".length) as CookieKind);
                setCookieDraft("");
                setCookieError(null);
                return;
              }
              if (next.startsWith("tab:")) {
                setTab(next.slice(4) as SettingsTab);
                setError(null);
                return;
              }
              go(next);
            }}
          />
        )}
      </div>
    </>
  );
}

function SectionRetry({
  label,
  message,
  onRetry,
}: {
  label: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div class="error-card" role="alert">
      <p>
        {label}: {message}
      </p>
      <button type="button" class="btn-secondary" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

function ConfigInput({
  field,
  config,
  draft,
  revealKey,
  onRevealKey,
  secret,
  onChange,
}: {
  field: { key: ConfigKey; label: string; hint: string; password?: boolean };
  config: AppConfig | null;
  draft: ConfigValues;
  revealKey: boolean;
  onRevealKey: (value: boolean) => void;
  secret?: {
    set: boolean;
    masked: string;
    edited: boolean;
    clearing: boolean;
    onClear: () => void;
    onUndoClear: () => void;
  };
  onChange: (value: string) => void;
}) {
  const meta = config?.fields[field.key];
  const locked = meta?.source === "env";
  const display = locked ? slotDisplay(meta?.effective) : draft[field.key];
  const inputType = field.password && !revealKey && !locked ? "password" : "text";

  return (
    <label class={locked ? "settings-field is-locked" : "settings-field"}>
      <span class="settings-label">{field.label}</span>
      <span class="settings-hint">{field.hint}</span>
      {secret && !locked && (
        <span class="settings-hint" role="status">
          {secret.clearing
            ? "Key will be removed on save."
            : secret.set
              ? `Key is set${secret.masked ? ` (${secret.masked})` : ""}. Type a new key to replace it.`
              : "No key stored. Type one to add it."}
        </span>
      )}
      <div class="settings-input-row">
        <input
          type={inputType}
          value={secret?.clearing ? "" : display}
          disabled={locked || secret?.clearing}
          autoComplete={field.password ? "off" : undefined}
          spellcheck={false}
          placeholder={
            secret && !locked ? (secret.masked || secret.set ? "••••" : "Not set") : undefined
          }
          onInput={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
        />
        {field.password && !locked && (
          <button type="button" class="btn-ghost" onClick={() => onRevealKey(!revealKey)}>
            {revealKey ? "Hide" : "Show"}
          </button>
        )}
        {secret && !locked && !secret.edited && !secret.clearing && secret.set && (
          <button type="button" class="btn-ghost" onClick={secret.onClear}>
            Remove
          </button>
        )}
        {secret?.clearing && (
          <button type="button" class="btn-ghost" onClick={secret.onUndoClear}>
            Undo
          </button>
        )}
      </div>
      {pathHint(display) && !locked && <span class="settings-hint">{pathHint(display)}</span>}
      {locked && meta?.env_name && (
        <div class="banner banner-warn">
          {meta.section === "fallback"
            ? `${meta.env_name} overrides manifests and this fallback${
                slotDisplay(meta.effective) ? ` (${slotDisplay(meta.effective)})` : ""
              }. Change it in the environment, not here.`
            : `${meta.env_name} overrides this value${
                slotDisplay(meta.effective) ? ` (${slotDisplay(meta.effective)})` : ""
              }. Change it in the environment, not here.`}
          {slotDisplay(meta.file) ? ` Value stored in config.toml: ${slotDisplay(meta.file)}` : ""}
        </div>
      )}
    </label>
  );
}
