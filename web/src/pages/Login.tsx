import { useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { returnToFromLocation } from "../auth";
import { PasswordField } from "../components/PasswordField";
import { go } from "../nav";
import { queryClient } from "../queryClient";
import { queryKeys } from "../queryKeys";

export function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await apiClient.login(password);
      queryClient.setQueryData(queryKeys.session(), {
        setup_required: false,
        authenticated: true,
      });
      go(returnToFromLocation());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
      setBusy(false);
    }
  };

  return (
    <div class="auth-page">
      <div class="auth-card">
        <div class="brand" style={{ marginBottom: "16px" }}>
          <span>yt-dlp-emby</span>
        </div>
        <h1>Sign in</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <PasswordField
            label="Password"
            value={password}
            autoComplete="current-password"
            onChange={setPassword}
          />
          <button type="submit" class="btn-primary auth-submit" disabled={busy} aria-busy={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {error && (
          <div class="error-text" role="alert">
            {error}
          </div>
        )}
        <div class="auth-footer">
          Local admin only. There are no accounts. <a href="/setup">First-time setup</a>
        </div>
      </div>
    </div>
  );
}
