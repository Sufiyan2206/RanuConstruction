/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
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
});
