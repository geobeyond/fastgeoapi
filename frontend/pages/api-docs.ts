import "swagger-ui-dist/swagger-ui.css";
import swaggerBundle from "swagger-ui-dist/swagger-ui-bundle.js?url";
import redocBundle from "redoc/bundles/redoc.standalone.js?url";

import { readConfig } from "./config";

export interface ApiDocsConfig {
  ui: "swagger" | "redoc";
  url: string;
}

/** The global Swagger UI's bundle defines once loaded. */
export interface Viewers {
  SwaggerUIBundle?: (options: { url: string; domNode: HTMLElement }) => unknown;
}

/** What ReDoc's bundle exports: it is an ES module, not a classic script. */
export interface RedocModule {
  init: (url: string, options: object, element: HTMLElement) => unknown;
}

export type Load = (src: string) => Promise<void>;
export type ImportModule = (src: string) => Promise<RedocModule>;

/** Imports a module from the URL the build gives its bundle. */
export function importModule(src: string): Promise<RedocModule> {
  return import(/* @vite-ignore */ src) as Promise<RedocModule>;
}

/** Adds a classic script to the page and waits for it to run. */
export function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.append(script);
  });
}

/** Shows the OpenAPI document in the viewer the page asks for. */
export async function showDocs(
  element: HTMLElement,
  config: ApiDocsConfig,
  load: Load = loadScript,
  viewers: Viewers = window as unknown as Viewers,
  importRedoc: ImportModule = importModule,
): Promise<void> {
  const target = document.createElement("div");
  element.append(target);
  if (config.ui === "redoc") {
    const redoc = await importRedoc(redocBundle);
    // ReDoc 3 reports usage to Redocly unless told not to.
    redoc.init(config.url, { disableTelemetry: true }, target);
    return;
  }
  await load(swaggerBundle);
  viewers.SwaggerUIBundle?.({ url: config.url, domNode: target });
}

class ApiDocs extends HTMLElement {
  connectedCallback(): void {
    void showDocs(this, readConfig<ApiDocsConfig>(this));
  }
}

if (!customElements.get("fga-api-docs")) {
  customElements.define("fga-api-docs", ApiDocs);
}
