import type { Source } from "../api";

export function ManifestEditor({
  source,
  text,
  savedText,
  exists,
  error,
  onChange,
  onSave,
}: {
  source: Source;
  text: string;
  savedText: string;
  exists: boolean;
  error: string | null;
  onChange: (text: string) => void;
  onSave: () => void;
}) {
  const dirty = text !== savedText;
  const filename = source === "youtube" ? "youtube.yaml" : "dropout.yaml";

  return (
    <section class="card">
      {!exists && (
        <div class="banner">
          File not on disk yet. Save to create it. Start is disabled until then.
        </div>
      )}
      <div class="editor-header">
        <span class="editor-filename">{filename}</span>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          {dirty && <span class="editor-unsaved">Unsaved</span>}
          <button
            type="button"
            class="btn-secondary"
            disabled={!dirty}
            onClick={onSave}
          >
            Save
          </button>
        </div>
      </div>
      <textarea
        class="editor-textarea"
        spellcheck={false}
        value={text}
        onInput={(e) =>
          onChange((e.currentTarget as HTMLTextAreaElement).value)
        }
      />
      {error && <div class="validation-error">{error}</div>}
    </section>
  );
}
