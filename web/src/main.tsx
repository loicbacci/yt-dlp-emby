import { QueryClientProvider } from "@tanstack/preact-query";
import { render } from "preact";
import { App } from "./App";
import { queryClient } from "./queryClient";
import "./styles.css";

render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>,
  document.getElementById("app")!,
);
