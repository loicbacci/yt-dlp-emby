import { useQuery } from "@tanstack/preact-query";
import type { ComponentChildren } from "preact";
import { LocationProvider, Route, Router, useLocation } from "preact-iso";
import { Component } from "preact/compat";
import { useEffect, useState } from "preact/hooks";
import { apiClient, routeForSession } from "./api";
import { logoutAndClear } from "./auth";
import { Header } from "./components/Header";
import { ToastHost } from "./components/Toast";
import { isBrowserOnline, isPageVisible } from "./hooks/useOnline";
import { setNavigator } from "./nav";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { SeriesDetail } from "./pages/SeriesDetail";
import { SeriesList } from "./pages/SeriesList";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { queryClient } from "./queryClient";
import { queryKeys } from "./queryKeys";
import { refreshSeriesKey, setServerRefreshing } from "./seriesRefreshStore";
import { useSession } from "./useAppQueries";

function RefreshRecovery() {
  const session = useSession();
  const active = useQuery({
    queryKey: queryKeys.activeRefreshes(),
    queryFn: () => apiClient.getActiveSeriesRefreshes(),
    enabled: session.data?.authenticated === true,
    staleTime: 0,
    refetchInterval: () => (isBrowserOnline() && isPageVisible() ? 3000 : false),
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const keys = (active.data?.jobs ?? []).flatMap((job) =>
      job.items.map((item) => refreshSeriesKey(item.platform, item.slug)),
    );
    setServerRefreshing(keys);
  }, [active.data]);

  useEffect(() => {
    if (session.data?.authenticated !== true) setServerRefreshing([]);
  }, [session.data?.authenticated]);

  return null;
}

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

type AppErrorBoundaryState = { error: Error | null };

class AppErrorBoundary extends Component<{ children: ComponentChildren }, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): AppErrorBoundaryState {
    return {
      error: error instanceof Error ? error : new Error(String(error)),
    };
  }

  componentDidCatch(error: Error, info: { componentStack?: string }) {
    console.error("App render failed", error, info.componentStack);
  }

  render(props: { children: ComponentChildren }, state: AppErrorBoundaryState) {
    if (state.error) {
      return (
        <div class="shell">
          <main id="main" class="error-card" role="alert">
            <h1>This page couldn’t load</h1>
            <p>{state.error.message || "An unexpected interface error occurred."}</p>
            <button type="button" class="btn-secondary" onClick={() => window.location.reload()}>
              Reload page
            </button>
          </main>
        </div>
      );
    }
    return props.children;
  }
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
    <>
      {/* A pathless child inside preact-iso's Router matches `/` and shadows Dashboard. */}
      <RefreshRecovery />
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
    </>
  );
}

export function App() {
  return (
    <LocationProvider>
      <a class="skip-link" href="#main">
        Skip to content
      </a>
      <AppErrorBoundary>
        <NavigatorBridge />
        <SessionGate />
        <ToastHost />
      </AppErrorBoundary>
    </LocationProvider>
  );
}
