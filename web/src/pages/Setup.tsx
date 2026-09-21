import { useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { returnToFromLocation } from "../auth";
import { PasswordField } from "../components/PasswordField";
import { go } from "../nav";
import { queryClient } from "../queryClient";
import { queryKeys } from "../queryKeys";

export function Setup() {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hints: string[] = [];
  if (password && password.length < 8) hints.push("Use 8+ characters");
  if (confirm && password !== confirm) hints.push("Passwords must match");
  const valid = password.length >= 8 && confirm.length >= 8 && password === confirm;

  const submit = async () => {
    if (!valid || busy) return;
    setError(null);
    setBusy(true);
    try {
      await apiClient.setup(password);
      queryClient.setQueryData(queryKeys.session(), {
        setup_required: false,
        authenticated: true,
      });
      go(returnToFromLocation());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Setup failed");
      setBusy(false);
    }
  };

  return (
    <div class="auth-page">
      <div class="auth-card">
        <div class="brand" style={{ marginBottom: "16px" }}>
          <span>yt-dlp-emby</span>
        </div>
        <h1>Set admin password</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <PasswordField
            label="Password"
            value={password}
            autoComplete="new-password"
            onChange={setPassword}
          />
          <PasswordField
            label="Confirm password"
            value={confirm}
            autoComplete="new-password"
            id="pw-confirm"
            onChange={setConfirm}
          />
          {hints.map((hint) => (
            <p key={hint} class="settings-hint">
              {hint}
            </p>
          ))}
          <button
            type="submit"
            class="btn-primary auth-submit"
            disabled={!valid || busy}
            aria-busy={busy}
            title={!valid ? "Use 8+ characters and matching passwords" : undefined}
          >
            {busy ? "Saving…" : "Save password"}
          </button>
        </form>
        {error && (
          <div class="error-text" role="alert">
            {error}
          </div>
        )}
        <div class="auth-footer">
          Local admin only. There are no accounts. Already set up? <a href="/login">Sign in</a>
        </div>
      </div>
    </div>
  );
}
