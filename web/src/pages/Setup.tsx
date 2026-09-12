import { useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { go } from "../nav";

export function Setup() {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const valid =
    password.length >= 8 && confirm.length >= 8 && password === confirm;

  const submit = async () => {
    setError(null);
    try {
      await apiClient.setup(password);
      go("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Setup failed");
    }
  };

  return (
    <div class="auth-page">
      <div class="auth-card">
        <div class="brand" style={{ marginBottom: "16px" }}>
          <span class="brand-bar" />
          <span>yt-dlp-emby</span>
        </div>
        <h1>Set admin password</h1>
        <label>
          Password
          <input
            type="password"
            value={password}
            onInput={(e) =>
              setPassword((e.currentTarget as HTMLInputElement).value)
            }
          />
        </label>
        <label>
          Confirm password
          <input
            type="password"
            value={confirm}
            onInput={(e) =>
              setConfirm((e.currentTarget as HTMLInputElement).value)
            }
          />
        </label>
        <button
          type="button"
          class="btn-primary"
          disabled={!valid}
          onClick={submit}
        >
          Save password
        </button>
        {error && <div class="error-text">{error}</div>}
        <div class="auth-footer">Local admin only. There are no accounts.</div>
      </div>
    </div>
  );
}
