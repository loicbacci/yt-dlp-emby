import { useEffect, useState } from "preact/hooks";
import type { Source } from "../../api";
import { useModal } from "../../hooks/useModal";
import { slugify, suggestFolder, uniqueNameError } from "../../seriesView";

export function CreateSeriesModal({
  existing,
  onClose,
  onCreate,
  mode = "create",
  initial,
  fileLabel,
}: {
  existing: { name: string; slug?: string }[];
  onClose: () => void;
  onCreate: (body: {
    name: string;
    platform: Source;
    path: string;
    tvdb_id: number | null;
  }) => Promise<void>;
  mode?: "create" | "edit";
  initial?: {
    name: string;
    platform: Source;
    path: string;
    tvdb_id: number | null;
  };
  fileLabel?: string;
}) {
  const [title, setTitle] = useState(initial?.name ?? "");
  const [platform, setPlatform] = useState<Source>(initial?.platform ?? "dropout");
  const [tvdb, setTvdb] = useState(initial?.tvdb_id != null ? String(initial.tvdb_id) : "");
  const [path, setPath] = useState(initial?.path ?? "");
  const [pathTouched, setPathTouched] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tvdbId = tvdb.trim() ? Number.parseInt(tvdb, 10) : null;
  const slug = slugify(title);
  const others =
    mode === "edit"
      ? existing.filter((row) => row.name.toLowerCase() !== (initial?.name ?? "").toLowerCase())
      : existing;
  const nameError = uniqueNameError(title, others);

  useEffect(() => {
    if (!pathTouched) {
      setPath(suggestFolder(title.trim(), Number.isFinite(tvdbId) ? tvdbId : null));
    }
  }, [title, tvdbId, pathTouched]);

  const dialogRef = useModal<HTMLFormElement>(true, () => {
    if (!saving) onClose();
  });

  const ready =
    title.trim() &&
    path.trim() &&
    (mode === "edit" || slug) &&
    !nameError &&
    !saving &&
    (tvdb.trim() === "" || Number.isFinite(tvdbId));

  const submit = async () => {
    if (!ready) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        name: title.trim(),
        platform,
        path: path.trim(),
        tvdb_id: Number.isFinite(tvdbId) ? tvdbId : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
      setSaving(false);
    }
  };

  return (
    <div
      class="modal-backdrop"
      role="presentation"
      onClick={() => {
        if (!saving) onClose();
      }}
    >
      <form
        ref={dialogRef}
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-series-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <h2 id="create-series-title" class="modal-title">
          {mode === "edit" ? "Edit details" : "Add series"}
        </h2>
        <label class="settings-field">
          <span class="settings-label">Title *</span>
          <input
            type="text"
            value={title}
            autoFocus
            onInput={(e) => setTitle((e.currentTarget as HTMLInputElement).value)}
          />
        </label>
        {nameError && <div class="validation-error">{nameError}</div>}
        <div class="settings-field">
          <span class="settings-label">Platform *</span>
          <div role="radiogroup" class="series-toolbar" aria-label="Platform">
            {(["youtube", "dropout"] as Source[]).map((item) => (
              <label key={item} class={platform === item ? "filter-chip active" : "filter-chip"}>
                <input
                  type="radio"
                  name="series-platform"
                  value={item}
                  checked={platform === item}
                  disabled={mode === "edit"}
                  onChange={() => setPlatform(item)}
                />
                {item === "youtube" ? "YouTube" : "Dropout.tv"}
              </label>
            ))}
          </div>
        </div>
        <p class="settings-hint">
          File <code>{fileLabel ?? `shows/${slug || "…"}.yaml`}</code>
        </p>
        <label class="settings-field">
          <span class="settings-label">TVDB id</span>
          <input
            type="text"
            inputMode="numeric"
            value={tvdb}
            onInput={(e) => setTvdb((e.currentTarget as HTMLInputElement).value)}
          />
          {tvdb.trim() && !/^\d+$/.test(tvdb.trim()) && (
            <span class="validation-error" role="alert">
              TVDB id must be digits
            </span>
          )}
        </label>
        <label class="settings-field">
          <span class="settings-label">Folder *</span>
          <input
            type="text"
            value={path}
            onInput={(e) => {
              setPathTouched(true);
              setPath((e.currentTarget as HTMLInputElement).value);
            }}
          />
        </label>
        {error && (
          <div class="validation-error" role="alert">
            {error}
          </div>
        )}
        <div class="modal-actions">
          <button type="button" class="btn-ghost" disabled={saving} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" class="btn-modal-save" disabled={!ready}>
            {saving ? "Saving…" : mode === "edit" ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
