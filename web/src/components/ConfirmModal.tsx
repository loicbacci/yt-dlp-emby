import { useRef } from "preact/hooks";
import { useModal } from "../hooks/useModal";

export function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  pending?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useModal<HTMLDivElement>(true, onCancel, {
    initialRef: danger ? cancelRef : confirmRef,
  });

  return (
    <div class="modal-backdrop" role="presentation" onClick={pending ? undefined : onCancel}>
      <div
        ref={dialogRef}
        class="modal confirm-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        aria-describedby={message ? "confirm-modal-message" : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-modal-title" class="modal-title">
          {title}
        </h2>
        {message && (
          <p id="confirm-modal-message" class="confirm-modal-message">
            {message}
          </p>
        )}
        {error && (
          <div class="validation-error" role="alert">
            {error}
          </div>
        )}
        <div class="modal-actions">
          <button
            ref={cancelRef}
            type="button"
            class="btn-ghost"
            disabled={pending}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            class={danger ? "btn-danger" : "btn-modal-save"}
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
