import { render } from "preact";
import { PersistQueryClientProvider } from "@tanstack/preact-query-persist-client";
import { App } from "./App";
import { persistQueryOptions, queryClient } from "./queryClient";
import "./styles.css";

render(
  <PersistQueryClientProvider
    client={queryClient}
    persistOptions={persistQueryOptions}
  >
    <App />
  </PersistQueryClientProvider>,
  document.getElementById("app")!,
);
