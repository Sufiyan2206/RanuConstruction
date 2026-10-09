/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// VITE_BASE=/snookers/ builds the app to live under that path (used for the single-domain deployment).
export default defineConfig(({ mode }) => ({
  base: loadEnv(mode, ".", "VITE_").VITE_BASE || "/",
  plugins: [react(), tailwindcss()],
  // Decode %20 etc. and drop the leading "/" before a Windows drive letter ("/D:/..." -> "D:/...").
  resolve: { alias: { "@": decodeURIComponent(new URL("./src", import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, "$1") } },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
      "/health": "http://localhost:8000",
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], globals: true, css: false },
}));
