import { defineConfig } from "vite";

/**
 * The stylesheet and the islands of the HTML pages, compiled into the
 * fastgeoapi-html package. The server reads the manifest to link each
 * page to its files, whose names carry a hash and are cached for good.
 * A relative base keeps the URLs the files load each other by relative,
 * so they work under whatever path the API is mounted at.
 */
export default defineConfig({
  base: "./",
  build: {
    outDir: "../packages/fastgeoapi-html/fastgeoapi_html/static",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: ["pages/style.css", "pages/api-docs.ts", "pages/process-run.ts"],
    },
  },
});
