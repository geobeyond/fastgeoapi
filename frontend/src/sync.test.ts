/**
 * Two views of one document, and what has to be true between them.
 *
 * The form cannot create what pygeoapi's schema does not describe —
 * `store_options`, `engine_options`, anything a provider invented — so
 * without a way to write YAML directly there is no way to add a
 * GeoParquet collection from this page at all. The bridge preserves
 * those keys; only the text view can bring them into being.
 *
 * That makes the YAML editable, and editable in two directions means the
 * two views must never disagree about what will be saved.
 */

import { describe, expect, it } from "vitest";

import { fromForm, fromYaml, toYaml } from "./sync";

const SOURCE = `# Kept by hand.
server:
    bind:
        port: \${PORT}
resources:
    overture-places:
        type: collection
        providers:
            - name: app.provider.geoparquet.GeoParquetProvider
              store_options:
                  skip_signature: true
`;

describe("moving between the two views", () => {
  it("takes text the form could never have produced", () => {
    // The point of the whole tab: `store_options` is not in the schema,
    // so no widget can create it. Typed here, it becomes part of the
    // document the form then edits around.
    const opened = fromYaml(SOURCE);

    expect(opened.error).toBeNull();
    expect(
      (opened.state!.data as any).resources["overture-places"].providers[0]
        .store_options,
    ).toEqual({ skip_signature: true });
  });

  it("saves exactly what was typed, with no transplant in the way", () => {
    // Text typed by hand is already the document, so it goes back
    // untouched. The spacing here is deliberate and re-emitting would
    // tidy it away: without it the assertion would hold whatever the
    // code did, which is how this test first passed for the wrong
    // reason.
    const typed =
      "server:\n    bind:\n        port:     5000\nresources:\n    a:   {}\n";

    const opened = fromYaml(typed);

    expect(toYaml(opened.state!)).toBe(typed);
    expect(opened.state!.doc.toString()).not.toBe(typed);
  });

  it("reports a broken document instead of throwing it away", () => {
    // Half-written YAML is the normal state of someone typing, not an
    // exception. The previous state has to survive it, or a stray
    // keystroke would empty the form.
    const broken = fromYaml("resources:\n  - [unclosed\n");

    expect(broken.state).toBeNull();
    expect(broken.error).toMatch(/./);
  });

  it("shows the form's changes as text", () => {
    const opened = fromYaml(SOURCE);
    const state = opened.state!;
    const after = structuredClone(state.data) as any;
    after.server.bind.port = "${OTHER}";

    const text = toYaml(fromForm(state, after));

    expect(text).toContain("port: ${OTHER}");
    expect(text).toContain("# Kept by hand.");
    expect(text).toContain("skip_signature: true");
  });
});
