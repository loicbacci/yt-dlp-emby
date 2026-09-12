import { useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { go } from "../nav";

export function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await apiClient.login(password);
      go("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    }
  };

  return (
    <div class="auth-page">
      <div class="auth-card">
        <div class="brand" style={{ marginBottom: "16px" }}>
          <span class="brand-bar" />
          <span>yt-dlp-emby</span>
        </div>
        <h1>Sign in</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
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
          <button type="submit" class="btn-primary">Sign in</button>
        </form>
        {error && <div class="error-text">{error}</div>}
        <div class="auth-footer">Local admin only. There are no accounts.</div>
      </div>
    </div>
  );
}
