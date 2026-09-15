import { useEffect, useState } from "preact/hooks";
import {
  ApiError,
  type DropoutAction,
  type ManifestImport,
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

const ROOT = "";

type TabState = { text: string; savedText: string; exists: boolean };

function tabLabel(path: string, source: Source): string {
  if (!path) return source === "youtube" ? "youtube.yaml" : "dropout.yaml";
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

export function Dashboard() {
  const [source, setSource] = useState<Source>("youtube");
  const [action, setAction] = useState<DropoutAction>("download");
  const [dryRun, setDryRun] = useState(false);
  const [verbose, setVerbose] = useState(false);
  const [force, setForce] = useState(false);
  const [tabs, setTabs] = useState<Record<string, TabState>>({
    [ROOT]: { text: "", savedText: "", exists: false },
  });
  const [importPaths, setImportPaths] = useState<string[]>([]);
  const [activePath, setActivePath] = useState(ROOT);
  const [loadedSource, setLoadedSource] = useState<Source | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [run, setRun] = useState<Run>(idleRun);
  const [runKey, setRunKey] = useState("idle");

  const active = tabs[activePath] ?? tabs[ROOT];
  const text = active?.text ?? "";
  const savedText = active?.savedText ?? "";
  const rootExists = tabs[ROOT]?.exists ?? false;

  const applyRun = (next: Run) => {
    setRun(next);
    setRunKey(runKeyFor(next));
  };

  const loadManifest = async (kind: Source) => {
    const manifest = await apiClient.getManifest(kind);
    const imports: ManifestImport[] = kind === "dropout" ? (manifest.imports ?? []) : [];
    const nextTabs: Record<string, TabState> = {
      [ROOT]: {
        text: manifest.text,
        savedText: manifest.text,
        exists: manifest.exists,
      },
    };
    for (const item of imports) {
      nextTabs[item.path] = {
        text: item.text,
        savedText: item.text,
        exists: item.exists,
      };
    }
    setTabs(nextTabs);
    setImportPaths(imports.map((item) => item.path));
    setActivePath(ROOT);
    setLoadedSource(kind);
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
    if (loadedSource !== source) return;
    if (activePath !== ROOT) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      apiClient
        .validateManifest(source, text)
        .then(() => {
          if (!cancelled) setManifestError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof ApiError && err.status === 401) {
            go("/login");
            return;
          }
          setManifestError(
            err instanceof ApiError ? err.message : "Validation failed",
          );
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [source, text, loadedSource, activePath]);

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

  const anyDirty = Object.values(tabs).some((tab) => tab.text !== tab.savedText);

  const changeSource = async (next: Source) => {
    if (anyDirty && !confirmDirtySwitch()) return;
    setSource(next);
    if (next === "youtube") setAction("download");
  };

  const changeTab = (next: string) => {
    if (next === activePath) return;
    if (text !== savedText && !confirmDirtySwitch()) return;
    setActivePath(next);
    setManifestError(null);
  };

  const save = async () => {
    setManifestError(null);
    try {
      if (activePath === ROOT) {
        const manifest = await apiClient.putManifest(source, text);
        const imports: ManifestImport[] =
          source === "dropout" ? (manifest.imports ?? []) : [];
        setTabs((current) => {
          const next: Record<string, TabState> = {
            ...current,
            [ROOT]: {
              text: manifest.text,
              savedText: manifest.text,
              exists: manifest.exists,
            },
          };
          for (const item of imports) {
            next[item.path] = current[item.path] ?? {
              text: item.text,
              savedText: item.text,
              exists: item.exists,
            };
          }
          return next;
        });
        setImportPaths(imports.map((item) => item.path));
      } else {
        const saved = await apiClient.putDropoutImport(activePath, text);
        setTabs((current) => ({
          ...current,
          [activePath]: {
            text: saved.text,
            savedText: saved.text,
            exists: saved.exists,
          },
        }));
      }
    } catch (err) {
      setManifestError(err instanceof ApiError ? err.message : "Save failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const start = async () => {
    if (anyDirty && !confirmDirtyStart()) return;
    setRunError(null);
    try {
      applyRun(
        await apiClient.startRun({
          source,
          dry_run: dryRun,
          verbose,
          force,
          action: source === "dropout" ? action : "download",
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

  const editorTabs =
    source === "dropout"
      ? [
          { path: ROOT, label: tabLabel(ROOT, source) },
          ...importPaths.map((path) => ({ path, label: tabLabel(path, source) })),
        ]
      : undefined;

  return (
    <div class="dashboard-shell">
      <Header run={run} onLogout={logout} />
      <div class="dashboard-left">
        <RunControls
          source={source}
          action={action}
          dryRun={dryRun}
          verbose={verbose}
          force={force}
          exists={rootExists}
          run={run}
          onSourceChange={changeSource}
          onActionChange={setAction}
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
          exists={active?.exists ?? false}
          error={manifestError}
          tabs={editorTabs}
          activePath={activePath}
          onTabChange={changeTab}
          onChange={(value) =>
            setTabs((current) => ({
              ...current,
              [activePath]: {
                text: value,
                savedText: current[activePath]?.savedText ?? "",
                exists: current[activePath]?.exists ?? false,
              },
            }))
          }
          onSave={save}
        />
      </div>
      <div class="dashboard-log">
        <LogViewer runKey={runKey} />
      </div>
    </div>
  );
}
