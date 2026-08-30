import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * The page is built into the package, not served from a dev server in
 * production: `app/editor/static` is what the authoring role mounts, and
 * what the wheel ships as package data (ADR-0008).
 */
export default defineConfig({
  // `@/…` is what shadcn's components import by, and keeping their
  // canonical shape is the point of copying them in rather than
  // depending on them.
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../app/editor/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
