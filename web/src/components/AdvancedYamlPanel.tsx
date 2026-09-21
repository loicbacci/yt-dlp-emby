import { useEffect, useState } from "preact/hooks";
import {
  ApiError,
  type ManifestImport,
  type ManifestPaths,
  type Source,
  apiClient,
  pathNotices,
} from "../api";
import { go } from "../nav";
import { ConfirmModal } from "./ConfirmModal";
import { ManifestEditor } from "./ManifestEditor";

const ROOT = "";

function tabLabel(path: string, source: Source): string {
  if (!path) return source === "youtube" ? "youtube.yaml" : "dropout.yaml";
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

type TabState = { text: string; savedText: string; exists: boolean };

export function AdvancedYamlPanel({
  onDirtyChange,
}: {
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [source, setSource] = useState<Source>("dropout");
  const [tabs, setTabs] = useState<Record<string, TabState>>({
    [ROOT]: { text: "", savedText: "", exists: false },
  });
  const [importPaths, setImportPaths] = useState<string[]>([]);
  const [activePath, setActivePath] = useState(ROOT);
  const [error, setError] = useState<string | null>(null);
  const [paths, setPaths] = useState<ManifestPaths | null>(null);
  const [pendingSwitch, setPendingSwitch] = useState<
    { kind: "source"; value: Source } | { kind: "tab"; value: string } | null
  >(null);

  const active = tabs[activePath] ?? tabs[ROOT];
  const text = active?.text ?? "";
  const savedText = active?.savedText ?? "";
  const anyDirty = Object.values(tabs).some((tab) => tab.text !== tab.savedText);

  useEffect(() => {
    onDirtyChange?.(anyDirty);
    return () => onDirtyChange?.(false);
  }, [anyDirty, onDirtyChange]);

  useEffect(() => {
    if (!anyDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [anyDirty]);

  const load = async (kind: Source) => {
    const manifest = await apiClient.getManifest(kind);
    const imports: ManifestImport[] = manifest.imports ?? [];
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
    setPaths(manifest.paths ?? null);
    setError(null);
  };

  useEffect(() => {
    load(source).catch((err) => {
      setError(err instanceof ApiError ? err.message : "Failed to load manifest");
      if (err instanceof ApiError && err.status === 401) go("/login");
    });
  }, [source]);

  const save = async () => {
    setError(null);
    try {
      if (activePath === ROOT) {
        const check = await apiClient.validateManifest(source, text);
        if (check.ok === false) {
          setError(check.error || "Manifest is invalid");
          return;
        }
        const manifest = await apiClient.putManifest(source, text);
        const imports: ManifestImport[] = manifest.imports ?? [];
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
        setPaths(manifest.paths ?? null);
      } else {
        // Accepted deviation: no pre-save validateManifest call for imports.
        // POST /api/manifests/{kind}/validate parses text against the ROOT
        // manifest schema, so it would wrongly reject valid series files.
        // Import saves rely on server-side write_import parsing (same 400
        // error path) plus the live yamlLooksBroken hint in ManifestEditor.
        const saved = await apiClient.putImport(source, activePath, text);
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
      setError(err instanceof ApiError ? err.message : "Save failed");
      if (err instanceof ApiError && err.status === 401) go("/login");
    }
  };

  const editorTabs =
    importPaths.length > 0
      ? [
          { path: ROOT, label: tabLabel(ROOT, source) },
          ...importPaths.map((path) => ({ path, label: tabLabel(path, source) })),
        ]
      : undefined;

  return (
    <div>
      <p class="settings-hint">
        Edit root manifests and imports. Series catalog lives under Series; downloads use the Run
        page queue.
      </p>
      <div class="run-toolbar" style={{ marginBottom: "12px" }}>
        <label>
          Manifest{" "}
          <select
            value={source}
            onChange={(e) => {
              const next = (e.target as HTMLSelectElement).value as Source;
              if (next === source) return;
              if (anyDirty) {
                setPendingSwitch({ kind: "source", value: next });
                return;
              }
              setSource(next);
            }}
          >
            <option value="dropout">dropout.yaml</option>
            <option value="youtube">youtube.yaml</option>
          </select>
        </label>
      </div>
      <ManifestEditor
        source={source}
        text={text}
        savedText={savedText}
        exists={active?.exists ?? false}
        error={error}
        notices={activePath === ROOT ? pathNotices(paths) : []}
        tabs={editorTabs}
        activePath={activePath}
        onTabChange={(next) => {
          if (next === activePath) return;
          if (text !== savedText) {
            setPendingSwitch({ kind: "tab", value: next });
            return;
          }
          setActivePath(next);
          setError(null);
        }}
        onChange={(value) => {
          setError(null);
          setTabs((current) => ({
            ...current,
            [activePath]: {
              text: value,
              savedText: current[activePath]?.savedText ?? "",
              exists: current[activePath]?.exists ?? false,
            },
          }));
        }}
        onSave={save}
      />
      {pendingSwitch && (
        <ConfirmModal
          title="Unsaved changes"
          message="Discard unsaved yaml changes?"
          confirmLabel="Discard"
          danger
          onCancel={() => setPendingSwitch(null)}
          onConfirm={() => {
            const pending = pendingSwitch;
            setPendingSwitch(null);
            if (pending.kind === "source") {
              setSource(pending.value);
            } else {
              setActivePath(pending.value);
              setError(null);
            }
          }}
        />
      )}
    </div>
  );
}
