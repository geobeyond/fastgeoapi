import "swagger-ui-dist/swagger-ui.css";
import swaggerBundle from "swagger-ui-dist/swagger-ui-bundle.js?url";
import redocBundle from "redoc/bundles/redoc.standalone.js?url";

import { readConfig } from "./config";

export interface ApiDocsConfig {
  ui: "swagger" | "redoc";
  url: string;
}

/** The globals the viewers' bundles define once loaded. */
export interface Viewers {
  SwaggerUIBundle?: (options: { url: string; domNode: HTMLElement }) => unknown;
  Redoc?: {
    init: (url: string, options: object, element: HTMLElement) => void;
  };
}

export type Load = (src: string) => Promise<void>;

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
): Promise<void> {
  const target = document.createElement("div");
  element.append(target);
  if (config.ui === "redoc") {
    await load(redocBundle);
    viewers.Redoc?.init(config.url, {}, target);
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
