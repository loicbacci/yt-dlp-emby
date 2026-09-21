import { useState } from "preact/hooks";

export function PasswordField({
  value,
  onChange,
  label,
  autoComplete,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  autoComplete: "current-password" | "new-password";
  id?: string;
}) {
  const [show, setShow] = useState(false);
  const inputId = id ?? `pw-${autoComplete}`;
  return (
    <label class="settings-field">
      <span class="settings-label">{label}</span>
      <div class="settings-input-row">
        <input
          id={inputId}
          type={show ? "text" : "password"}
          value={value}
          autoComplete={autoComplete}
          onInput={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
        />
        <button type="button" class="btn-ghost" onClick={() => setShow((v) => !v)}>
          {show ? "Hide" : "Show"}
        </button>
      </div>
    </label>
  );
}
