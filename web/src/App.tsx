import { useEffect, useState } from "preact/hooks";
import { LocationProvider, Router, Route, useLocation } from "preact-iso";
import { apiClient, routeForSession } from "./api";
import { setNavigator } from "./nav";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";

function NavigatorBridge() {
  const { route } = useLocation();
  useEffect(() => {
    setNavigator(route);
    return () => setNavigator(null);
  }, [route]);
  return null;
}

function SessionGate() {
  const { path, route } = useLocation();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    apiClient
      .session()
      .then((session) => {
        const next = routeForSession(session);
        if (path !== next) {
          route(next);
        }
        setReady(true);
      })
      .catch(() => setReady(true));
  }, []);

  if (!ready) {
    return <div class="shell" />;
  }

  return (
    <Router>
      <Route path="/setup" component={Setup} />
      <Route path="/login" component={Login} />
      <Route default component={Dashboard} />
    </Router>
  );
}

export function App() {
  return (
    <LocationProvider>
      <NavigatorBridge />
      <SessionGate />
    </LocationProvider>
  );
}
