/**
 * The form is a view; the document is the truth.
 *
 * Every form library takes JSON and gives JSON back, and that round trip
 * is not faithful — measured while weighing stage 3 of ADR-0007, it left
 * 35 differences on this very configuration and lost comments and key
 * order along the way. pygeoapi's schema does not describe
 * `store_options` or `engine_options`, and declares no
 * `additionalProperties` on providers, so everything provider-specific is
 * legal and invisible to a form.
 *
 * A form that owned the document would therefore delete that on open and
 * save, with nothing touched. These tests exist to make that impossible:
 * what the form never saw is never written.
 */

import { describe, expect, it } from "vitest";
import { parseDocument } from "yaml";

import { applyDiff, serialise, toJSON } from "./document";

const SOURCE = `# The deployment reads this from a bucket.
server:
    bind:
        host: \${HOST}
        port: \${PORT}   # parameterised on purpose
metadata:
    identification:
        title:
            en: pygeoapi default instance
            fr: instance par défaut
resources:
    overture-places:
        type: collection
        title: Overture places
        providers:
            - type: feature
              name: app.provider.geoparquet.GeoParquetProvider
              data: s3://overturemaps-us-west-2/release/
              # Neither of these is in pygeoapi's schema.
              store_options:
                  region: us-west-2
                  skip_signature: true
              engine_options:
                  memory_limit: 384MB
`;

describe("the bridge between the form and the document", () => {
  it("writes nothing when the form changed nothing", () => {
    // Not asserted by comparing the serialised text: re-emitting a
    // document normalises indentation and escapes, so a no-op round trip
    // rewrites 122 of the demo configuration's 227 lines while losing
    // nothing. That is why the count is the invariant and the caller
    // keeps the original text when it is zero — opening and saving must
    // not produce a diff.
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc);

    const written = applyDiff(doc, before, structuredClone(before));

    expect(written).toBe(0);
  });

  it("counts only the paths it wrote", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    after.metadata.identification.title.en = "fastgeoapi demo";
    after.resources["overture-places"].type = "collection"; // unchanged

    expect(applyDiff(doc, before, after)).toBe(1);
  });

  it("leaves what the form cannot see alone", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    after.metadata.identification.title.en = "fastgeoapi demo";

    applyDiff(doc, before, after);

    const text = doc.toString();
    expect(text).toContain("fastgeoapi demo");
    expect(text).toContain("skip_signature: true");
    expect(text).toContain("memory_limit: 384MB");
    expect(text).toContain("# Neither of these is in pygeoapi's schema.");
  });

  it("keeps a placeholder a placeholder", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    after.metadata.identification.title.fr = "démonstration fastgeoapi";

    applyDiff(doc, before, after);

    expect(doc.toString()).toContain("port: ${PORT}");
    expect(doc.toString()).toContain("# parameterised on purpose");
  });

  it("removes a key the form removed", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    delete after.resources["overture-places"].title;

    applyDiff(doc, before, after);

    expect(doc.toString()).not.toContain("title: Overture places");
    expect(doc.toString()).toContain("skip_signature: true");
  });

  it("adds a list entry without rewriting the ones already there", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    after.resources["overture-places"].providers.push({
      type: "tile",
      name: "another",
    });

    applyDiff(doc, before, after);

    const text = doc.toString();
    expect(text).toContain("name: another");
    expect(text).toContain("skip_signature: true");
    expect(text).toContain("memory_limit: 384MB");
  });
});

describe("what gets sent back to the server", () => {
  it("sends the very text that was opened when nothing changed", () => {
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc);
    const written = applyDiff(doc, before, structuredClone(before));

    expect(serialise(SOURCE, doc, written)).toBe(SOURCE);
  });

  it("keeps the shape of the lines it did not touch", () => {
    // The fixture is indented with four spaces; re-emitting a document
    // normalises that to two. A transplant carries only the changed
    // region across, so everything else keeps the shape the operator
    // gave it — which is what makes the saved diff readable.
    const doc = parseDocument(SOURCE);
    const before = toJSON(doc) as any;
    const after = structuredClone(before);
    after.metadata.identification.title.en = "fastgeoapi demo";
    const written = applyDiff(doc, before, after);

    const text = serialise(SOURCE, doc, written);

    expect(text).toContain("fastgeoapi demo");
    expect(text).toContain("    bind:");
    expect(text).toContain("        host: ${HOST}");
    expect(text).toContain("# parameterised on purpose");
  });

  it("means what the form meant, whatever the merge did", () => {
    // The safety net, asserted rather than assumed: a merge that came
    // out meaning something else would be worse than a reformatted
    // file, so the result is checked and the plain serialisation used
    // instead when it does not match.
    const edits: ((data: any) => void)[] = [
      (d) => (d.metadata.identification.title.en = "changed"),
      (d) => delete d.resources["overture-places"].title,
      (d) => d.resources["overture-places"].providers.push({ type: "tile" }),
      (d) => (d.resources["new-one"] = { type: "collection", title: "New" }),
      (d) => (d.server.bind.port = 8080),
    ];

    for (const edit of edits) {
      const doc = parseDocument(SOURCE);
      const before = toJSON(doc) as any;
      const after = structuredClone(before);
      edit(after);
      const written = applyDiff(doc, before, after);

      const text = serialise(SOURCE, doc, written);

      expect(parseDocument(text).toJS()).toEqual(after);
    }
  });
});
