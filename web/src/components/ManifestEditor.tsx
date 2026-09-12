import { useEffect, useRef } from "preact/hooks";
import type { Source } from "../api";
import { highlightYaml } from "../yamlHighlight";

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
  const preRef = useRef<HTMLPreElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const pre = preRef.current;
    const area = textRef.current;
    if (!pre || !area) return;
    pre.scrollTop = area.scrollTop;
    pre.scrollLeft = area.scrollLeft;
  }, [text]);

  const syncScroll = () => {
    const pre = preRef.current;
    const area = textRef.current;
    if (!pre || !area) return;
    pre.scrollTop = area.scrollTop;
    pre.scrollLeft = area.scrollLeft;
  };

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
            disabled={!dirty || Boolean(error)}
            onClick={onSave}
          >
            Save
          </button>
        </div>
      </div>
      <div class="editor-frame">
        <pre ref={preRef} class="editor-highlight" aria-hidden="true">
          {highlightYaml(text).map((token, index) => (
            <span key={index} class={`tok-${token.kind}`}>
              {token.text}
            </span>
          ))}
        </pre>
        <textarea
          ref={textRef}
          class="editor-textarea"
          spellcheck={false}
          value={text}
          onScroll={syncScroll}
          onInput={(e) =>
            onChange((e.currentTarget as HTMLTextAreaElement).value)
          }
        />
      </div>
      {error && <div class="validation-error">{error}</div>}
    </section>
  );
}
