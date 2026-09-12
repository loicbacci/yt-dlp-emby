import { useEffect, useState } from "preact/hooks";
import {
  ApiError,
  type Run,
  type Source,
  apiClient,
  confirmDirtyStart,
  confirmDirtySwitch,
  runKeyFor,
} from "../api";
import { go } from "../nav";
import { Header } from "../components/Header";
import { LogViewer } from "../components/LogViewer";
import { ManifestEditor } from "../components/ManifestEditor";
import { RunControls } from "../components/RunControls";

const idleRun: Run = {
  status: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
};

export function Dashboard() {
  const [source, setSource] = useState<Source>("youtube");
  const [dryRun, setDryRun] = useState(false);
  const [verbose, setVerbose] = useState(false);
  const [force, setForce] = useState(false);
  const [text, setText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [exists, setExists] = useState(false);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [run, setRun] = useState<Run>(idleRun);
  const [runKey, setRunKey] = useState("idle");

  const applyRun = (next: Run) => {
    setRun(next);
    setRunKey(runKeyFor(next));
  };

  const loadManifest = async (kind: Source) => {
    const manifest = await apiClient.getManifest(kind);
    setText(manifest.text);
    setSavedText(manifest.text);
    setExists(manifest.exists);
    setManifestError(null);
  };

  const refreshRun = async () => {
    try {
      applyRun(await apiClient.getRun());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
      }
    }
  };

  useEffect(() => {
    loadManifest(source).catch((err) => {
      setManifestError(
        err instanceof ApiError ? err.message : "Failed to load manifest",
      );
    });
  }, [source]);

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

  const changeSource = async (next: Source) => {
    if (text !== savedText && !confirmDirtySwitch()) return;
    setSource(next);
  };

  const save = async () => {
    setManifestError(null);
    try {
      const manifest = await apiClient.putManifest(source, text);
      setSavedText(manifest.text);
      setExists(manifest.exists);
    } catch (err) {
      setManifestError(err instanceof ApiError ? err.message : "Save failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const start = async () => {
    if (text !== savedText && !confirmDirtyStart()) return;
    setRunError(null);
    try {
      applyRun(
        await apiClient.startRun({
          source,
          dry_run: dryRun,
          verbose,
          force,
        }),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setRunError(err instanceof ApiError ? err.message : "Start failed");
    }
  };

  const stop = async () => {
    setRunError(null);
    try {
      applyRun(await apiClient.stopRun());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        go("/login");
        return;
      }
      setRunError(err instanceof ApiError ? err.message : "Stop failed");
    }
  };

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  return (
    <div class="dashboard-shell">
      <Header run={run} onLogout={logout} />
      <div class="dashboard-left">
        <RunControls
          source={source}
          dryRun={dryRun}
          verbose={verbose}
          force={force}
          exists={exists}
          run={run}
          onSourceChange={changeSource}
          onDryRunChange={setDryRun}
          onVerboseChange={setVerbose}
          onForceChange={setForce}
          onStart={start}
          onStop={stop}
        />
        {runError && <div class="validation-error">{runError}</div>}
        <ManifestEditor
          source={source}
          text={text}
          savedText={savedText}
          exists={exists}
          error={manifestError}
          onChange={setText}
          onSave={save}
        />
      </div>
      <div class="dashboard-log">
        <LogViewer runKey={runKey} />
      </div>
    </div>
  );
}
