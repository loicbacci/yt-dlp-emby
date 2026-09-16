import { useEffect, useRef } from "preact/hooks";
import type { CookieKind } from "../api";

export function CookieModal({
  field,
  draft,
  error,
  saving,
  onChange,
  onSave,
  onClose,
}: {
  field: { kind: CookieKind; label: string; hint: string };
  draft: string;
  error: string | null;
  saving: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const ready = Boolean(draft.trim()) && !saving;

  useEffect(() => {
    textRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    onChange(await file.text());
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div class="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        class="modal cookie-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cookie-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="cookie-modal-title" class="modal-title">
          {field.label}
        </h2>
        <p class="settings-hint">
          Paste a Netscape export or choose a file. Current cookies are never
          shown.
        </p>
        <textarea
          ref={textRef}
          class="settings-cookie-input"
          value={draft}
          placeholder="Paste Netscape cookies here"
          autoComplete="off"
          autoCorrect="off"
          spellcheck={false}
          rows={10}
          onInput={(e) =>
            onChange((e.currentTarget as HTMLTextAreaElement).value)
          }
        />
        <div class="settings-input-row">
          <input
            ref={fileRef}
            type="file"
            accept=".txt,text/plain"
            onChange={(e) =>
              void pickFile((e.currentTarget as HTMLInputElement).files?.[0])
            }
          />
        </div>
        {error && <div class="validation-error">{error}</div>}
        <div class="modal-actions">
          <button
            type="button"
            class="btn-ghost"
            disabled={saving}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            class="btn-modal-save"
            disabled={!ready}
            onClick={onSave}
          >
            {saving ? "Saving…" : "Save cookies"}
          </button>
        </div>
      </div>
    </div>
  );
}
