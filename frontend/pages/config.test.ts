import { readConfig } from "./config";

function island(html: string): HTMLElement {
  const element = document.createElement("fga-test");
  element.innerHTML = html;
  return element;
}

describe("readConfig", () => {
  it("parses the JSON the server wrote inside the element", () => {
    const element = island(
      '<script type="application/json">{"url": "https://example.org/a?f=json"}</script>',
    );

    expect(readConfig<{ url: string }>(element)).toEqual({
      url: "https://example.org/a?f=json",
    });
  });

  it("reads its own child, not the configuration of a nested element", () => {
    const element = island(
      '<div><script type="application/json">{"nested": true}</script></div>' +
        '<script type="application/json">{"own": true}</script>',
    );

    expect(readConfig(element)).toEqual({ own: true });
  });

  it("says which element has no configuration", () => {
    expect(() => readConfig(island("<p>no script</p>"))).toThrow(
      "fga-test has no configuration",
    );
  });
});
