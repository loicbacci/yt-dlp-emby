import { useRef, useState } from "preact/hooks";
import type { CookieKind } from "../api";
import { COOKIE_MAX_BYTES, netscapeCookieError } from "../formValidation";
import { useModal } from "../hooks/useModal";

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
  const [fileError, setFileError] = useState<string | null>(null);
  const ready = Boolean(draft.trim()) && !saving;
  const shownError = fileError || error;
  const dialogRef = useModal<HTMLDivElement>(true, onClose, {
    initialRef: textRef as unknown as import("preact").RefObject<HTMLElement | null>,
  });

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > COOKIE_MAX_BYTES) {
      setFileError("Cookie file must be 1MB or smaller");
      onChange("");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    const text = await file.text();
    const sizeErr = netscapeCookieError(text);
    setFileError(sizeErr && sizeErr.includes("1MB") ? sizeErr : null);
    onChange(text);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div class="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        ref={dialogRef}
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
          Paste a Netscape export or choose a file. Current cookies are never shown.
        </p>
        <textarea
          ref={textRef}
          class="settings-cookie-input"
          value={draft}
          placeholder="Paste Netscape cookies here"
          aria-label={field.label}
          autoComplete="off"
          autoCorrect="off"
          spellcheck={false}
          rows={10}
          onInput={(e) => {
            setFileError(null);
            onChange((e.currentTarget as HTMLTextAreaElement).value);
          }}
        />
        <div class="settings-input-row">
          <input
            ref={fileRef}
            type="file"
            accept=".txt"
            aria-label="Choose cookies.txt file"
            onChange={(e) => void pickFile((e.currentTarget as HTMLInputElement).files?.[0])}
          />
        </div>
        {shownError && (
          <div class="validation-error" role="alert">
            {shownError}
          </div>
        )}
        <div class="modal-actions">
          <button type="button" class="btn-ghost" disabled={saving} onClick={onClose}>
            Cancel
          </button>
          <button type="button" class="btn-modal-save" disabled={!ready} onClick={onSave}>
            {saving ? "Saving…" : "Save cookies"}
          </button>
        </div>
      </div>
    </div>
  );
}
