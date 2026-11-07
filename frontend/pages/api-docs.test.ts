import { showDocs } from "./api-docs";

const url = "https://example.org/geoapi/openapi?f=json";

describe("showDocs", () => {
  it("opens Swagger UI on the document by default", async () => {
    const element = document.createElement("fga-api-docs");
    const loaded: string[] = [];
    const swagger = vi.fn();

    await showDocs(
      element,
      { ui: "swagger", url },
      async (src) => {
        loaded.push(src);
      },
      { SwaggerUIBundle: swagger },
    );

    expect(loaded).toEqual([expect.stringContaining("swagger-ui-bundle")]);
    expect(swagger).toHaveBeenCalledWith({
      url,
      domNode: element.firstElementChild,
    });
  });

  it("opens ReDoc from its module bundle when the page asks for it", async () => {
    const element = document.createElement("fga-api-docs");
    const loaded: string[] = [];
    const imported: string[] = [];
    const init = vi.fn();

    await showDocs(
      element,
      { ui: "redoc", url },
      async (src) => {
        loaded.push(src);
      },
      {},
      async (src) => {
        imported.push(src);
        return { init };
      },
    );

    // ReDoc 3 ships its bundle as an ES module: no classic script.
    expect(loaded).toEqual([]);
    expect(imported).toEqual([expect.stringContaining("redoc.standalone")]);
    // ReDoc 3 sends usage telemetry to Redocly unless told not to.
    expect(init).toHaveBeenCalledWith(
      url,
      { disableTelemetry: true },
      element.firstElementChild,
    );
  });
});
