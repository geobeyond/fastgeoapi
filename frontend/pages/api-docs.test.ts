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

  it("opens ReDoc when the page asks for it", async () => {
    const element = document.createElement("fga-api-docs");
    const loaded: string[] = [];
    const init = vi.fn();

    await showDocs(
      element,
      { ui: "redoc", url },
      async (src) => {
        loaded.push(src);
      },
      { Redoc: { init } },
    );

    expect(loaded).toEqual([expect.stringContaining("redoc.standalone")]);
    expect(init).toHaveBeenCalledWith(url, {}, element.firstElementChild);
  });
});
