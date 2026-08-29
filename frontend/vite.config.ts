import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * The page is built into the package, not served from a dev server in
 * production: `app/editor/static` is what the authoring role mounts, and
 * what the wheel ships as package data (ADR-0008).
 */
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../app/editor/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
