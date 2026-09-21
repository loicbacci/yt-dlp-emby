import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    host: true,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        // Infinite timeout is intentional so SSE (/api/runs/log, /api/runs/events) is not cut off.
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
  test: {
    environment: "jsdom",
    coverage: {
      provider: "v8",
      thresholds: { lines: 70 },
    },
  },
});
