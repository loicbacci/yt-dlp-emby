import { LocationProvider, Route, Router, useLocation } from "preact-iso";
import { useEffect, useState } from "preact/hooks";
import { apiClient, routeForSession } from "./api";
import { logoutAndClear } from "./auth";
import { Header } from "./components/Header";
import { ToastHost } from "./components/Toast";
import { setNavigator } from "./nav";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { SeriesDetail } from "./pages/SeriesDetail";
import { SeriesList } from "./pages/SeriesList";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { queryClient } from "./queryClient";
import { queryKeys } from "./queryKeys";

function NavigatorBridge() {
  const { route } = useLocation();
  useEffect(() => {
    setNavigator((url, options) => route(url, options?.replace));
    return () => setNavigator(null);
  }, [route]);
  return null;
}

function NotFound() {
  return (
    <>
      <Header current="dashboard" onLogout={() => void logoutAndClear()} />
      <div class="shell">
        <main>
          <h1>Not found</h1>
          <p class="run-hint">That page does not exist.</p>
          <a href="/">Go to downloads</a>
        </main>
      </div>
    </>
  );
}

function RedirectSeries() {
  const { route } = useLocation();
  useEffect(() => {
    route("/series", true);
  }, [route]);
  return <div class="shell" />;
}

function SessionGate() {
  const { path, route } = useLocation();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    apiClient
      .session()
      .then((session) => {
        if (cancelled) return;
        queryClient.setQueryData(queryKeys.session(), session);
        const next = routeForSession(session, path);
        if (path !== next) route(next, true);
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Session check failed");
      });
    return () => {
      cancelled = true;
    };
  }, [path, route]);

  if (error && !ready) {
    return (
      <div class="shell">
        <div class="error-card" role="alert">
          <p>{error}</p>
          <button
            type="button"
            class="btn-secondary"
            onClick={() => {
              setError(null);
              setReady(false);
              apiClient
                .session()
                .then((session) => {
                  queryClient.setQueryData(queryKeys.session(), session);
                  const next = routeForSession(session, path);
                  if (path !== next) route(next, true);
                  setReady(true);
                })
                .catch((err) => {
                  setError(err instanceof Error ? err.message : "Session check failed");
                });
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div class="shell session-loading" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true" />
        Checking session…
      </div>
    );
  }

  return (
    <Router>
      <Route path="/setup" component={Setup} />
      <Route path="/login" component={Login} />
      <Route path="/settings" component={Settings} />
      <Route path="/series/:platform/:slug" component={SeriesDetail} />
      <Route path="/series" component={SeriesList} />
      <Route path="/series/*" component={RedirectSeries} />
      <Route path="/" component={Dashboard} />
      <Route default component={NotFound} />
    </Router>
  );
}

export function App() {
  return (
    <LocationProvider>
      <a class="skip-link" href="#main">
        Skip to content
      </a>
      <NavigatorBridge />
      <SessionGate />
      <ToastHost />
    </LocationProvider>
  );
}
