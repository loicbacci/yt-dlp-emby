import { useEffect, useRef, useState } from "preact/hooks";
import {
  ApiError,
  type AppConfig,
  type ConfigKey,
  type ConfigValues,
  type CookieJar,
  type CookieKind,
  type CookieStatus,
  type Run,
  apiClient,
  confirmDirtyConfig,
  confirmDirtyCookies,
  confirmDirtySwitch,
  valuesFromConfig,
} from "../api";
import { go } from "../nav";
import { CookieModal } from "../components/CookieModal";
import { Header } from "../components/Header";
import {
  PlatformFields,
  platformDraftFromApi,
  type PlatformDraft,
} from "../components/PlatformFields";
import { AdvancedYamlPanel } from "../components/AdvancedYamlPanel";

const idleRun: Run = {
  status: "idle",
  phase: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
  plan: null,
};

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

const HOST_FIELDS: { key: ConfigKey; label: string; hint: string; password?: boolean }[] =
  [
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

const SONARR_FIELDS: { key: ConfigKey; label: string; hint: string; password?: boolean }[] =
  [
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

function fieldDisplay(
  config: AppConfig | null,
  draft: ConfigValues,
  key: ConfigKey,
): string {
  const meta = config?.fields[key];
  if (meta?.source === "env") return meta.effective ?? "";
  return draft[key];
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
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [saved, setSaved] = useState<ConfigValues>(emptyValues);
  const [draft, setDraft] = useState<ConfigValues>(emptyValues);
  const [error, setError] = useState<string | null>(null);
  const [cookieError, setCookieError] = useState<string | null>(null);
  const [run, setRun] = useState<Run>(idleRun);
  const [revealKey, setRevealKey] = useState(false);
  const [sonarrCheck, setSonarrCheck] = useState<SonarrCheckState>({
    status: "idle",
  });
  const checkGen = useRef(0);
  const [cookies, setCookies] = useState<CookieStatus | null>(null);
  const [cookieModal, setCookieModal] = useState<CookieKind | null>(null);
  const [cookieDraft, setCookieDraft] = useState("");
  const [cookieSaving, setCookieSaving] = useState(false);
  const [tab, setTab] = useState<SettingsTab>("config");
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

  const dirty =
    tab === "config"
      ? JSON.stringify(draft) !== JSON.stringify(saved)
      : tab === "youtube" || tab === "dropout"
        ? JSON.stringify(platformDraft[tab]) !== JSON.stringify(platformSaved[tab])
        : false;
  const dirtyCookies = Boolean(cookieModal && cookieDraft.trim());

  const refreshRun = async () => {
    try {
      setRun(await apiClient.getRun());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const load = async () => {
    const [next, jars, youtube, dropout] = await Promise.all([
      apiClient.getConfig(),
      apiClient.getCookies(),
      apiClient.getPlatform("youtube"),
      apiClient.getPlatform("dropout"),
    ]);
    const values = valuesFromConfig(next);
    setConfig(next);
    setSaved(values);
    setDraft(values);
    setCookies(jars);
    const yt = platformDraftFromApi(youtube);
    const dr = platformDraftFromApi(dropout);
    setPlatformDraft({ youtube: yt, dropout: dr });
    setPlatformSaved({ youtube: yt, dropout: dr });
    setPlatformPaths({ youtube: youtube.paths, dropout: dropout.paths });
    setPlatformJars({
      youtube: youtube.cookie_jar,
      dropout: dropout.cookie_jar,
    });
    setCookieModal(null);
    setCookieDraft("");
    setError(null);
    setCookieError(null);
  };

  useEffect(() => {
    load().catch((err) => {
      setError(err instanceof ApiError ? err.message : "Failed to load config");
      if (err instanceof ApiError && err.status === 401) go("/login");
    });
  }, []);

  useEffect(() => {
    refreshRun();
    const timer = window.setInterval(refreshRun, 2000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") refreshRun();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const navigate = (url: string) => {
    if (url === "/settings") return;
    if (dirty && !confirmDirtyConfig()) return;
    if (yamlDirty && !confirmDirtySwitch()) return;
    if (dirtyCookies && !confirmDirtyCookies()) return;
    go(url);
  };

  const switchTab = (next: SettingsTab) => {
    if (next === tab) return;
    if (dirty && !confirmDirtyConfig()) return;
    if (yamlDirty && !confirmDirtySwitch()) return;
    setTab(next);
    setError(null);
  };

  const sonarrUrl = fieldDisplay(config, draft, "sonarr_url").trim();
  const sonarrKey = fieldDisplay(config, draft, "sonarr_api_key").trim();
  const canCheckSonarr = Boolean(sonarrUrl && sonarrKey);

  useEffect(() => {
    checkGen.current += 1;
    setSonarrCheck({ status: "idle" });
  }, [sonarrUrl, sonarrKey]);

  const checkSonarr = async () => {
    if (!canCheckSonarr || sonarrCheck.status === "checking") return;
    const gen = ++checkGen.current;
    setSonarrCheck({ status: "checking" });
    try {
      const result = await apiClient.pingSonarr({
        sonarr_url: sonarrUrl,
        sonarr_api_key: sonarrKey,
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
        message: err instanceof ApiError ? err.message : "Sonarr check failed",
      });
    }
  };

  const save = async () => {
    setError(null);
    try {
      if (tab === "config") {
        const next = await apiClient.putConfig(draft);
        const values = valuesFromConfig(next);
        setConfig(next);
        setSaved(values);
        setDraft(values);
        return;
      }
      if (tab !== "youtube" && tab !== "dropout") return;
      const body = await apiClient.putPlatform(tab, platformDraft[tab]);
      const values = platformDraftFromApi(body);
      setPlatformDraft((current) => ({ ...current, [tab]: values }));
      setPlatformSaved((current) => ({ ...current, [tab]: values }));
      setPlatformPaths((current) => ({
        ...current,
        [tab]: body.paths,
      }));
      setPlatformJars((current) => ({ ...current, [tab]: body.cookie_jar }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  };

  const openCookieModal = (kind: CookieKind) => {
    if (dirtyCookies && !confirmDirtyCookies()) return;
    setCookieError(null);
    setCookieDraft("");
    setCookieModal(kind);
  };

  const closeCookieModal = () => {
    if (cookieSaving) return;
    if (dirtyCookies && !confirmDirtyCookies()) return;
    setCookieModal(null);
    setCookieDraft("");
    setCookieError(null);
  };

  const saveCookies = async () => {
    if (!cookieModal || !cookieDraft.trim() || cookieSaving) return;
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
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setCookieError(err instanceof ApiError ? err.message : "Cookie save failed");
    } finally {
      setCookieSaving(false);
    }
  };

  const logout = async () => {
    if (dirty && !confirmDirtyConfig()) return;
    if (yamlDirty && !confirmDirtySwitch()) return;
    if (dirtyCookies && !confirmDirtyCookies()) return;
    await apiClient.logout();
    go("/login");
  };

  const cookieField = cookieModal ? COOKIE_FIELDS[cookieModal] : null;
  const filename =
    tab === "config"
      ? config?.path ?? "config.toml"
      : tab === "youtube"
        ? "youtube.yaml"
        : tab === "dropout"
          ? "dropout.yaml"
          : "yaml manifests";

  return (
    <div class="settings-shell">
      <Header
        run={run}
        current="settings"
        onLogout={logout}
        onNavigate={navigate}
      />
      <section class="card settings-card">
        <div class="editor-header">
          <div>
            <h1 class="settings-title">Settings</h1>
            <div class="editor-filename">{filename}</div>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            {(dirty || yamlDirty) && <span class="editor-unsaved">Unsaved</span>}
            {tab !== "advanced" && (
              <button
                type="button"
                class="btn-secondary"
                disabled={!dirty}
                onClick={save}
              >
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
        {tab === "config" && (
          <>
            <p class="settings-lead">
              These values are written to config.toml. Path keys live under{" "}
              <code>[fallback]</code> and are used only when a manifest omits that
              path. Environment variables override both the manifest and this file.
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
                  {sonarrCheck.status === "checking"
                    ? "Checking…"
                    : "Check connection"}
                </button>
                {sonarrCheck.status === "ok" && (
                  <span class="settings-check-ok">
                    {sonarrPingMessage(sonarrCheck)}
                  </span>
                )}
                {sonarrCheck.status === "error" && (
                  <span class="settings-check-error">{sonarrCheck.message}</span>
                )}
              </div>
            </section>
          </>
        )}
        {tab === "youtube" && (
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
        )}
        {tab === "dropout" && (
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
        )}
        {tab === "advanced" && (
          <AdvancedYamlPanel onDirtyChange={setYamlDirty} />
        )}
        {cookies?.env_set && cookies.env_name && tab !== "config" && (
          <div class="banner banner-warn">
            {cookies.env_name} overrides both jars
            {cookies.env_path ? ` (${cookies.env_path})` : ""}. Change it in the
            environment, not here.
          </div>
        )}
        {error && <div class="validation-error">{error}</div>}
      </section>
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
    </div>
  );
}

function ConfigInput({
  field,
  config,
  draft,
  revealKey,
  onRevealKey,
  onChange,
}: {
  field: { key: ConfigKey; label: string; hint: string; password?: boolean };
  config: AppConfig | null;
  draft: ConfigValues;
  revealKey: boolean;
  onRevealKey: (value: boolean) => void;
  onChange: (value: string) => void;
}) {
  const meta = config?.fields[field.key];
  const locked = meta?.source === "env";
  const display = locked ? (meta.effective ?? "") : draft[field.key];
  const inputType =
    field.password && !revealKey && !locked ? "password" : "text";

  return (
    <label class={locked ? "settings-field is-locked" : "settings-field"}>
      <span class="settings-label">{field.label}</span>
      <span class="settings-hint">{field.hint}</span>
      <div class="settings-input-row">
        <input
          type={inputType}
          value={display}
          disabled={locked}
          autoComplete={field.password ? "off" : undefined}
          spellcheck={false}
          onInput={(e) =>
            onChange((e.currentTarget as HTMLInputElement).value)
          }
        />
        {field.password && !locked && (
          <button
            type="button"
            class="btn-ghost"
            onClick={() => onRevealKey(!revealKey)}
          >
            {revealKey ? "Hide" : "Show"}
          </button>
        )}
      </div>
      {locked && meta?.env_name && (
        <div class="banner banner-warn">
          {meta.section === "fallback"
            ? `${meta.env_name} overrides manifests and this fallback${
                meta.effective ? ` (${meta.effective})` : ""
              }. Change it in the environment, not here.`
            : `${meta.env_name} overrides this value${
                meta.effective ? ` (${meta.effective})` : ""
              }. Change it in the environment, not here.`}
          {meta.file ? ` Value stored in config.toml: ${meta.file}` : ""}
        </div>
      )}
    </label>
  );
}
